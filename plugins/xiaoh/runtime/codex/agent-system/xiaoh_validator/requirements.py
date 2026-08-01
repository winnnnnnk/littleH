"""XiaoH validator requirements boundary."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile

from xiaoh_validator.policy import (
    ALLOWED_ARTIFACT_ROUTES,
    ALLOWED_CURRENT_FACT_KINDS,
    ALLOWED_MEMORY_SOURCE_KINDS,
    ALLOWED_MEMORY_SOURCE_ROLES,
    ALLOWED_RECALL_STATUS,
    ALLOWED_REQUIREMENT_CHECK_STATUS,
    ALLOWED_RETROACTIVE_STATUS,
    ALLOWED_SKILL_CONFIRMATION_STATUS,
    ALLOWED_SKILL_STATUS,
    ALLOWED_SPEC_RFC_STATUS,
    ALLOWED_TASK_RELATIONS,
    MAX_RECALL_AGE_HOURS,
)
from xiaoh_validator.schemas import RECALL_MANIFEST_SCHEMA
from xiaoh_validator.evidence import (
    configured_vault_path,
    configured_xiaoh_path,
    file_identity,
    file_sha256,
    non_empty_or_none,
    parse_timestamp,
    path_is_covered,
    require_keys,
    resolve_configured_workspace,
    validate_string_list,
)


def _valid_enum(value, allowed):
    return isinstance(value, str) and value in allowed


def validate_recall_manifest(
    manifest,
    recall,
    context,
    registered_workspace,
    report,
    check_paths=True,
    check_freshness=True,
):
    required = [
        "schema_version", "created_at", "task_id", "workspace_id", "project", "system",
        "task_relation", "query", "memory_sources", "checked_indexes", "no_relevant_history_reason",
        "current_fact_sources", "current_fact_scope", "material_conflicts",
        "unresolved", "recommended_baseline",
    ]
    if not require_keys(manifest, required, "memory recall manifest", report):
        return
    if manifest["schema_version"] != RECALL_MANIFEST_SCHEMA:
        report.error("memory recall manifest schema_version must be {}".format(RECALL_MANIFEST_SCHEMA))
    for key in ("task_id", "workspace_id", "project", "system", "current_fact_scope", "recommended_baseline"):
        if not isinstance(manifest[key], str) or not manifest[key].strip():
            report.error("memory recall manifest {} must be a non-empty string".format(key))
    if manifest["task_id"] != context.get("task_id"):
        report.error("memory recall manifest task_id does not match task context")
    if manifest["workspace_id"] != recall.get("workspace_id"):
        report.error("memory recall manifest workspace_id does not match task context")
    if registered_workspace:
        for key in ("workspace_id", "project", "system"):
            if manifest.get(key) != registered_workspace.get(key):
                report.error(
                    "memory recall manifest {} does not match configured Workspace".format(key)
                )
    if manifest["task_relation"] != recall.get("task_relation"):
        report.error("memory recall manifest task_relation does not match task context")
    if not _valid_enum(manifest["task_relation"], ALLOWED_TASK_RELATIONS):
        report.error("memory recall manifest task_relation must be one of {}".format(sorted(ALLOWED_TASK_RELATIONS)))
    created_at = parse_timestamp(manifest["created_at"], "memory recall manifest created_at", report)
    if manifest["created_at"] != recall.get("completed_at"):
        report.error("memory recall completed_at must equal manifest created_at")
    if check_freshness and created_at:
        age = (datetime.now(timezone.utc) - created_at).total_seconds()
        if age < -300 or age > MAX_RECALL_AGE_HOURS * 3600:
            report.error("memory recall manifest is stale or from the future")

    query = manifest["query"]
    if require_keys(query, ["summary", "topics", "task_ids", "keywords"], "memory recall query", report):
        if not isinstance(query["summary"], str) or not query["summary"].strip():
            report.error("memory recall query.summary must be a non-empty string")
        for key in ("topics", "task_ids", "keywords"):
            validate_string_list(query[key], "memory recall query.{}".format(key), report)
        if not any(query[key] for key in ("topics", "task_ids", "keywords")):
            report.error("memory recall query requires at least one topic, task_id, or keyword")

    memory_sources = manifest["memory_sources"]
    if not isinstance(memory_sources, list):
        report.error("memory recall manifest memory_sources must be a list")
        memory_sources = []
    vault = None
    if check_paths:
        try:
            vault = configured_vault_path()
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            report.error("cannot resolve configured Vault for memory recall: {}".format(exc))
        if vault is not None and not (vault / ".obsidian").is_dir():
            report.error("configured Vault for memory recall lacks .obsidian marker")
    memory_paths = set()
    authoritative_history = False
    for index, source in enumerate(memory_sources):
        label = "memory recall manifest memory_sources[{}]".format(index)
        if not require_keys(
            source, ["kind", "path", "sha256", "role", "point_ids", "relevance"],
            label, report,
        ):
            continue
        if not _valid_enum(source["kind"], ALLOWED_MEMORY_SOURCE_KINDS):
            report.error("{}.kind must be one of {}".format(label, sorted(ALLOWED_MEMORY_SOURCE_KINDS)))
        if not _valid_enum(source["role"], ALLOWED_MEMORY_SOURCE_ROLES):
            report.error("{}.role must be one of {}".format(label, sorted(ALLOWED_MEMORY_SOURCE_ROLES)))
        if source["kind"] == "daily_digest" and source["role"] != "navigation":
            report.error("daily_digest memory sources must use role=navigation")
        validate_string_list(
            source["point_ids"],
            "{}.point_ids".format(label),
            report,
            non_empty=(
                source["kind"] == "requirement_baseline"
                and isinstance(source["role"], str)
                and source["role"] in {"authority", "evidence"}
            ),
        )
        if not re.fullmatch(r"[0-9a-f]{64}", str(source["sha256"])):
            report.error("{}.sha256 must be a lowercase SHA-256 digest".format(label))
        if not isinstance(source["relevance"], str) or not source["relevance"].strip():
            report.error("{}.relevance must be a non-empty string".format(label))
        raw_path = source["path"]
        if not isinstance(raw_path, str) or not raw_path.strip():
            report.error("{}.path must be a non-empty absolute path".format(label))
        else:
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                report.error("{}.path must be absolute".format(label))
            else:
                resolved = path.resolve(strict=False)
                identity = file_identity(resolved)
                if identity in memory_paths:
                    report.error("memory recall manifest memory_sources contains duplicate file identities")
                memory_paths.add(identity)
                if (
                    source["kind"] != "daily_digest"
                    and isinstance(source["role"], str)
                    and source["role"] in {"authority", "evidence"}
                ):
                    authoritative_history = True
            if path.is_absolute() and check_paths:
                resolved = path.resolve(strict=False)
                if vault is not None and not path_is_covered(str(resolved), [str(vault)]):
                    report.error("{}.path is outside the configured Vault".format(label))
                elif not resolved.is_file():
                    report.error("{}.path does not exist".format(label))
                elif file_sha256(resolved) != source["sha256"]:
                    report.error("{}.sha256 does not match path".format(label))

    checked_indexes = manifest["checked_indexes"]
    if not isinstance(checked_indexes, list):
        report.error("memory recall manifest checked_indexes must be a list")
        checked_indexes = []
    checked_index_paths = set()
    for index, source in enumerate(checked_indexes):
        label = "memory recall manifest checked_indexes[{}]".format(index)
        if not require_keys(source, ["path", "sha256", "relevance"], label, report):
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", str(source["sha256"])):
            report.error("{}.sha256 must be a lowercase SHA-256 digest".format(label))
        if not isinstance(source["relevance"], str) or not source["relevance"].strip():
            report.error("{}.relevance must be a non-empty string".format(label))
        raw_path = source["path"]
        if not isinstance(raw_path, str) or not raw_path.strip():
            report.error("{}.path must be a non-empty absolute path".format(label))
            continue
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            report.error("{}.path must be absolute".format(label))
            continue
        resolved = path.resolve(strict=False)
        identity = file_identity(resolved)
        if identity in checked_index_paths:
            report.error("memory recall manifest checked_indexes contains duplicate file identities")
        if identity in memory_paths:
            report.error("memory recall manifest reuses a file identity across history and checked indexes")
        checked_index_paths.add(identity)
        if check_paths:
            if vault is not None and not path_is_covered(str(resolved), [str(vault)]):
                report.error("{}.path is outside the configured Vault".format(label))
            elif not resolved.is_file():
                report.error("{}.path does not exist".format(label))
            elif file_sha256(resolved) != source["sha256"]:
                report.error("{}.sha256 does not match path".format(label))

    reason = manifest["no_relevant_history_reason"]
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        report.error("no_relevant_history_reason must be null or a non-empty string")
    if not memory_sources and not isinstance(reason, str):
        report.error("empty memory_sources requires no_relevant_history_reason")
    if not memory_sources and not checked_indexes:
        report.error("empty memory_sources requires at least one checked index")
    if memory_sources and reason is not None:
        report.error("no_relevant_history_reason must be null when memory_sources are present")
    if memory_sources and not authoritative_history:
        report.error("recalled project history requires a distinct non-digest authority or evidence source")

    current_sources = manifest["current_fact_sources"]
    if not isinstance(current_sources, list):
        report.error("memory recall manifest current_fact_sources must be a list")
        current_sources = []
    elif not current_sources:
        report.error("memory recall manifest current_fact_sources must not be empty")
    for index, source in enumerate(current_sources):
        label = "memory recall manifest current_fact_sources[{}]".format(index)
        if not require_keys(source, ["kind", "path", "sha256", "relevance"], label, report):
            continue
        if not _valid_enum(source["kind"], ALLOWED_CURRENT_FACT_KINDS):
            report.error("{}.kind must be one of {}".format(label, sorted(ALLOWED_CURRENT_FACT_KINDS)))
        if not isinstance(source["relevance"], str) or not source["relevance"].strip():
            report.error("{}.relevance must be a non-empty string".format(label))
        if not re.fullmatch(r"[0-9a-f]{64}", str(source["sha256"])):
            report.error("{}.sha256 must be a lowercase SHA-256 digest".format(label))
        raw_path = source["path"]
        if not isinstance(raw_path, str) or not raw_path.strip():
            report.error("{}.path must be a non-empty absolute path".format(label))
        else:
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                report.error("{}.path must be absolute".format(label))
            elif check_paths:
                resolved = path.resolve(strict=False)
                allowed_paths = context.get("scope", {}).get("allowed_paths", [])
                if not any(
                    isinstance(allowed, str)
                    and path_is_covered(str(resolved), [allowed])
                    for allowed in allowed_paths
                ):
                    report.error("{}.path is outside task scope.allowed_paths".format(label))
                elif not resolved.is_file():
                    report.error("{}.path does not exist".format(label))
                elif file_sha256(resolved) != source["sha256"]:
                    report.error("{}.sha256 does not match path".format(label))
    validate_string_list(manifest["material_conflicts"], "memory recall manifest material_conflicts", report)
    validate_string_list(manifest["unresolved"], "memory recall manifest unresolved", report)

def validate_memory_recall(
    recall,
    context,
    report,
    check_paths=True,
    check_freshness=True,
    require_completed=False,
):
    required = [
        "status", "workspace_id", "task_relation", "manifest_path",
        "manifest_sha256", "completed_at",
    ]
    if not require_keys(recall, required, "memory_recall", report):
        return
    if not _valid_enum(recall["status"], ALLOWED_RECALL_STATUS):
        report.error("memory_recall.status must be one of {}".format(sorted(ALLOWED_RECALL_STATUS)))
    if require_completed and recall["status"] != "completed":
        report.error("project memory recall must be completed before this action")
    if not _valid_enum(recall["task_relation"], ALLOWED_TASK_RELATIONS):
        report.error("memory_recall.task_relation must be one of {}".format(sorted(ALLOWED_TASK_RELATIONS)))
    if not isinstance(recall["workspace_id"], str) or not recall["workspace_id"].strip():
        report.error("memory_recall.workspace_id must be a non-empty string")
    registered_workspace = None
    if check_paths:
        try:
            registered_workspace = resolve_configured_workspace(
                context.get("scope", {}).get("workspace")
            )
        except (OSError, RuntimeError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            report.error("cannot resolve configured Workspace for memory recall: {}".format(exc))
        else:
            if recall["workspace_id"] != registered_workspace["workspace_id"]:
                report.error("memory_recall.workspace_id does not match configured Workspace")
    playbook = context.get("playbook", {})
    if isinstance(playbook, dict) and playbook.get("managed"):
        xiaoh_workspace_id = playbook.get("xiaoh_workspace_id")
        if isinstance(xiaoh_workspace_id, str) and recall["workspace_id"] != xiaoh_workspace_id:
            report.error("memory_recall.workspace_id does not match playbook.xiaoh_workspace_id")
    completed = recall["status"] == "completed"
    for key in ("manifest_path", "manifest_sha256", "completed_at"):
        value = recall[key]
        if completed and (not isinstance(value, str) or not value.strip()):
            report.error("completed memory_recall requires {}".format(key))
        if not completed and value is not None:
            report.error("non-completed memory_recall must use null {}".format(key))
    if not completed:
        return
    manifest_path = Path(recall["manifest_path"]).expanduser()
    if not manifest_path.is_absolute():
        report.error("memory_recall.manifest_path must be absolute")
        return
    if not re.fullmatch(r"[0-9a-f]{64}", recall["manifest_sha256"]):
        report.error("memory_recall.manifest_sha256 must be a lowercase SHA-256 digest")
        return
    parse_timestamp(recall["completed_at"], "memory_recall.completed_at", report)
    if not check_paths:
        return
    if context.get("playbook", {}).get("managed"):
        manifest_roots = context.get("scope", {}).get("allowed_paths", [])
    else:
        manifest_roots = [str(configured_xiaoh_path().parent / "evidence/recall")]
    if not any(
        isinstance(root, str)
        and path_is_covered(str(manifest_path.resolve(strict=False)), [root])
        for root in manifest_roots
    ):
        report.error("memory_recall.manifest_path is outside the authorized evidence directory")
        return
    if not manifest_path.is_file():
        report.error("memory_recall.manifest_path does not exist: {}".format(manifest_path))
        return
    payload = manifest_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != recall["manifest_sha256"]:
        report.error("memory_recall.manifest_sha256 does not match manifest_path")
        return
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        report.error("memory_recall.manifest_path is not valid UTF-8 JSON: {}".format(exc))
        return
    validate_recall_manifest(
        manifest,
        recall,
        context,
        registered_workspace,
        report,
        check_paths=check_paths,
        check_freshness=check_freshness,
    )

def validate_requirements(requirements, report):
    required = [
        "artifact_route", "route_reason", "risk_signals", "required_gates", "spec_rfc", "openspec",
        "bypass", "retroactive_normalization", "skill_execution",
    ]
    if not require_keys(requirements, required, "requirements", report):
        return
    route = requirements["artifact_route"]
    if not _valid_enum(route, ALLOWED_ARTIFACT_ROUTES):
        report.error("requirements.artifact_route must be one of {}".format(sorted(ALLOWED_ARTIFACT_ROUTES)))
    if not isinstance(requirements["route_reason"], str) or not requirements["route_reason"].strip():
        report.error("requirements.route_reason must be a non-empty string")
    validate_string_list(requirements["risk_signals"], "requirements.risk_signals", report)
    required_gates = validate_string_list(requirements["required_gates"], "requirements.required_gates", report)
    if route == "spec_rfc_then_openspec":
        missing_gates = {"spec_rfc_validation", "user_confirmation", "openspec_traceability"} - set(required_gates)
        if missing_gates:
            report.error("spec_rfc_then_openspec missing required gates: {}".format(", ".join(sorted(missing_gates))))

    spec = requirements["spec_rfc"]
    if require_keys(
        spec,
        [
            "status", "reference", "revision", "validation_status", "confirmed_by_user", "confirmed_at",
        ],
        "requirements.spec_rfc", report,
    ):
        if not _valid_enum(spec["status"], ALLOWED_SPEC_RFC_STATUS):
            report.error("requirements.spec_rfc.status must be one of {}".format(sorted(ALLOWED_SPEC_RFC_STATUS)))
        if not non_empty_or_none(spec["reference"]):
            report.error("requirements.spec_rfc.reference must be null or a non-empty string")
        if not isinstance(spec["revision"], int) or isinstance(spec["revision"], bool) or spec["revision"] < 0:
            report.error("requirements.spec_rfc.revision must be a non-negative integer")
        if not _valid_enum(spec["validation_status"], ALLOWED_REQUIREMENT_CHECK_STATUS):
            report.error("requirements.spec_rfc.validation_status must be one of {}".format(sorted(ALLOWED_REQUIREMENT_CHECK_STATUS)))
        if not isinstance(spec["confirmed_by_user"], bool):
            report.error("requirements.spec_rfc.confirmed_by_user must be a boolean")
        if not non_empty_or_none(spec["confirmed_at"]):
            report.error("requirements.spec_rfc.confirmed_at must be null or an ISO-8601 timestamp")
        elif spec["confirmed_at"] is not None:
            parse_timestamp(spec["confirmed_at"], "requirements.spec_rfc.confirmed_at", report)
        if spec["status"] == "confirmed":
            if not isinstance(spec["reference"], str) or not spec["reference"].strip():
                report.error("confirmed Spec+RFC requires requirements.spec_rfc.reference")
            if (
                not isinstance(spec["revision"], int)
                or isinstance(spec["revision"], bool)
                or spec["revision"] < 1
            ):
                report.error("confirmed Spec+RFC requires a positive revision")
            if spec["validation_status"] != "passed":
                report.error("confirmed Spec+RFC requires validation_status=passed")
            if spec["confirmed_by_user"] is not True or spec["confirmed_at"] is None:
                report.error("confirmed Spec+RFC requires user confirmation evidence")

    openspec = requirements["openspec"]
    if require_keys(
        openspec,
        ["status", "traceability_status", "validated_spec_rfc_revision", "confirmed_by_user", "confirmed_at"],
        "requirements.openspec", report,
    ):
        for key in ("status", "traceability_status"):
            if not _valid_enum(openspec[key], ALLOWED_REQUIREMENT_CHECK_STATUS):
                report.error("requirements.openspec.{} must be one of {}".format(key, sorted(ALLOWED_REQUIREMENT_CHECK_STATUS)))
        validated_revision = openspec["validated_spec_rfc_revision"]
        if validated_revision is not None and (
            not isinstance(validated_revision, int) or isinstance(validated_revision, bool) or validated_revision < 1
        ):
            report.error("requirements.openspec.validated_spec_rfc_revision must be null or a positive integer")
        if (
            isinstance(spec, dict)
            and openspec["status"] == "passed"
            and validated_revision != spec.get("revision")
        ):
            report.error("Spec+RFC revision changed; OpenSpec status must reset to pending")
        if not isinstance(openspec["confirmed_by_user"], bool):
            report.error("requirements.openspec.confirmed_by_user must be a boolean")
        if not non_empty_or_none(openspec["confirmed_at"]):
            report.error("requirements.openspec.confirmed_at must be null or an ISO-8601 timestamp")
        elif openspec["confirmed_at"] is not None:
            parse_timestamp(openspec["confirmed_at"], "requirements.openspec.confirmed_at", report)
        if openspec["status"] == "passed" and openspec["traceability_status"] == "passed":
            if openspec["confirmed_by_user"] is not True or openspec["confirmed_at"] is None:
                report.error("completed OpenSpec requires user confirmation evidence")

    bypass = requirements["bypass"]
    if require_keys(bypass, ["reason"], "requirements.bypass", report):
        if not non_empty_or_none(bypass["reason"]):
            report.error("requirements.bypass.reason must be null or a non-empty string")
        bypass_routes = {"direct_change", "openspec_only"}
        if route in bypass_routes and (not isinstance(bypass["reason"], str) or not bypass["reason"].strip()):
            report.error("{} requires a non-empty requirements.bypass.reason".format(route))
        if route not in bypass_routes and bypass["reason"] is not None:
            report.error("requirements.bypass.reason is only allowed for direct_change or openspec_only")

    retro = requirements["retroactive_normalization"]
    if require_keys(retro, ["required", "status"], "requirements.retroactive_normalization", report):
        if not isinstance(retro["required"], bool):
            report.error("requirements.retroactive_normalization.required must be a boolean")
        if not _valid_enum(retro["status"], ALLOWED_RETROACTIVE_STATUS):
            report.error("requirements.retroactive_normalization.status must be one of {}".format(sorted(ALLOWED_RETROACTIVE_STATUS)))
        if retro["required"] is True and retro["status"] == "not_required":
            report.error("required retroactive normalization cannot use status=not_required")
        if retro["required"] is False and retro["status"] != "not_required":
            report.error("non-required retroactive normalization must use status=not_required")

    execution = requirements["skill_execution"]
    if require_keys(execution, ["explicitly_requested", "records"], "requirements.skill_execution", report):
        requested = validate_string_list(
            execution["explicitly_requested"], "requirements.skill_execution.explicitly_requested", report
        )
        records = execution["records"]
        if not isinstance(records, list):
            report.error("requirements.skill_execution.records must be a list")
            records = []
        names = []
        for index, record in enumerate(records):
            label = "requirements.skill_execution.records[{}]".format(index)
            if not require_keys(
                record,
                ["name", "status", "validation_status", "confirmation_status", "evidence"],
                label, report,
            ):
                continue
            if not isinstance(record["name"], str) or not record["name"].strip():
                report.error("{}.name must be a non-empty string".format(label))
            else:
                names.append(record["name"].lstrip("$"))
            if not _valid_enum(record["status"], ALLOWED_SKILL_STATUS):
                report.error("{}.status must be one of {}".format(label, sorted(ALLOWED_SKILL_STATUS)))
            if not _valid_enum(
                record["validation_status"], ALLOWED_REQUIREMENT_CHECK_STATUS
            ):
                report.error("{}.validation_status must be one of {}".format(label, sorted(ALLOWED_REQUIREMENT_CHECK_STATUS)))
            if not _valid_enum(
                record["confirmation_status"], ALLOWED_SKILL_CONFIRMATION_STATUS
            ):
                report.error("{}.confirmation_status must be one of {}".format(label, sorted(ALLOWED_SKILL_CONFIRMATION_STATUS)))
            if not non_empty_or_none(record["evidence"]):
                report.error("{}.evidence must be null or a non-empty string".format(label))
        normalized_requested = [name.lstrip("$") for name in requested]
        if len(names) != len(set(names)):
            report.error("requirements.skill_execution.records contains duplicate skill names")
        if set(names) != set(normalized_requested):
            report.error("requirements.skill_execution.records must cover every explicitly requested Skill")
        if "spec-rfc" in normalized_requested and route != "spec_rfc_then_openspec":
            report.error("explicit spec-rfc request requires artifact_route=spec_rfc_then_openspec")

    if route in {"direct_change", "openspec_only"} and isinstance(spec, dict) and spec.get("status") != "not_required":
        report.error("{} requires requirements.spec_rfc.status=not_required".format(route))
    if route == "spec_rfc_then_openspec" and isinstance(spec, dict) and spec.get("status") == "not_required":
        report.error("spec_rfc_then_openspec cannot use requirements.spec_rfc.status=not_required")
    if route == "direct_change":
        if requirements.get("risk_signals"):
            report.error("direct_change requires empty requirements.risk_signals")
        if isinstance(openspec, dict) and (
            openspec.get("status") != "not_required"
            or openspec.get("traceability_status") != "not_required"
        ):
            report.error("direct_change requires OpenSpec to be not_required")

def example_memory_recall():
    return {
        "status": "completed",
        "workspace_id": "workspace-1",
        "task_relation": "new",
        "manifest_path": str(
            Path(tempfile.gettempdir()) / "xiaoh-project-recall.json"
        ),
        "manifest_sha256": "0" * 64,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

def example_requirements():
    return {
        "artifact_route": "spec_rfc_then_openspec",
        "route_reason": "总体需求涉及需要稳定基线的跨阶段语义",
        "risk_signals": ["multi_phase"],
        "required_gates": [
            "spec_rfc_validation", "user_confirmation", "openspec_traceability",
        ],
        "spec_rfc": {
            "status": "confirmed",
            "reference": "/tmp/spec-rfc.md",
            "revision": 1,
            "validation_status": "passed",
            "confirmed_by_user": True,
            "confirmed_at": "2026-07-21T00:00:00+08:00",
        },
        "openspec": {
            "status": "passed",
            "traceability_status": "passed",
            "validated_spec_rfc_revision": 1,
            "confirmed_by_user": True,
            "confirmed_at": "2026-07-21T00:00:00+08:00",
        },
        "bypass": {"reason": None},
        "retroactive_normalization": {"required": False, "status": "not_required"},
        "skill_execution": {
            "explicitly_requested": ["spec-rfc"],
            "records": [{
                "name": "spec-rfc",
                "status": "completed",
                "validation_status": "passed",
                "confirmation_status": "confirmed",
                "evidence": "/tmp/spec-rfc-validation.json",
            }],
        },
    }
