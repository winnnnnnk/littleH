#!/usr/bin/env python3
"""Validate XiaoH's global agent configuration and explicitly sync evidence counters."""

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playbook_adapter import (
    ALLOWED_ACTIONS as ALLOWED_DELEGATED_ACTIONS,
    LOCAL_REVIEW_ACTIONS,
    STATUS_REVIEW_ACTIONS,
    AdapterError,
    configured_integration_mode,
    playbook_probe,
    validate_receipt,
    worker_facts,
)


HOME = Path.home()
CODEX = Path(os.environ.get("CODEX_HOME", str(HOME / ".codex"))).expanduser()
OBSIDIAN_VAULT = Path(
    os.environ.get("XIAOH_VAULT", str(HOME / "obsidian/development-vault"))
).expanduser()
AGENTS_DIR = CODEX / "agents"
ROOT_AGENT = "xiaoh"
ROOT_AGENT_EXECUTION_MODES = {"main_agent_direct", "main_agent_sequential"}
ROOT_AGENT_HOOK = CODEX / "hooks/block_reserved_root_agent.py"
VAULT_WRITE_HOOK = CODEX / "hooks/guard_vault_writes.py"
HOOK_RUNTIME_VERIFIER = CODEX / "hooks/verify_agent_hook_runtime.py"
ROLE_CATALOG = OBSIDIAN_VAULT / "90-个人系统/Agent协作角色.md"
EVOLUTION_LEDGER = OBSIDIAN_VAULT / "90-个人系统/Agent进化台账.md"
SYSTEM_DIR = CODEX / "agent-system"
ROUTING_CASES = SYSTEM_DIR / "routing-cases.json"
EVOLUTION_POLICY = SYSTEM_DIR / "evolution-policy.json"
AGENT_STAGES = SYSTEM_DIR / "agent-stages.json"
ALLOWED_SANDBOXES = {"read-only", "workspace-write", "danger-full-access"}
ALLOWED_TASK_TYPES = {"analysis", "design", "implementation", "verification", "review", "operations"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high", "critical"}
ALLOWED_INTENT_DOMAINS = {"global_agent_capability", "playbook_platform", "business_project"}
ALLOWED_USER_ACTS = {"question", "hypothesis", "fact_correction", "business_decision", "execution_instruction"}
ALLOWED_BASELINE_CHANGES = {"none", "proposed", "confirmed"}
ALLOWED_EVIDENCE_STATUSES = {"not_checked", "supported", "conflicted", "insufficient"}
ALLOWED_SCOPE_REDUCTION_BASES = {"not_applicable", "evidence_supported", "explicit_business_decision"}
ALLOWED_ARTIFACT_ROUTES = {"openspec_only", "spec_rfc_then_openspec", "class_skill"}
ALLOWED_SPEC_RFC_STATUS = {
    "not_required", "pending", "drafting", "validating", "review_pending",
    "confirmation_pending", "confirmed",
}
ALLOWED_REQUIREMENT_CHECK_STATUS = {"not_required", "pending", "passed", "failed"}


def root_agent_owns_worker(worker):
    return (
        worker.get("execution_mode") in ROOT_AGENT_EXECUTION_MODES
        and worker.get("recommended_executor") == "main_agent"
    )


ALLOWED_RETROACTIVE_STATUS = {"not_required", "pending", "in_progress", "review_pending", "completed"}
ALLOWED_SKILL_STATUS = {"pending", "in_progress", "completed"}
ALLOWED_SKILL_CONFIRMATION_STATUS = {"not_required", "pending", "confirmed"}
ALLOWED_REQUIREMENT_GATE_ACTIONS = {
    "readonly_analysis", "artifact_routing", "spec_rfc_baseline", "spec_rfc_confirmation", "member_confirmation",
    "task_create", "openspec_authoring", "openspec_consistency_review", "openspec_confirmation",
    "task_start", "implementation",
}
ALLOWED_RECALL_STATUS = {"pending", "completed", "blocked"}
ALLOWED_TASK_RELATIONS = {
    "new", "continuation", "historical_recovery", "similar_reuse",
}
ALLOWED_MEMORY_SOURCE_KINDS = {
    "project_progress", "task_page", "task_closeout", "requirement_baseline",
    "formal_knowledge", "daily_digest",
}
ALLOWED_MEMORY_SOURCE_ROLES = {"navigation", "authority", "evidence"}
ALLOWED_CURRENT_FACT_KINDS = {
    "code", "configuration", "spec_rfc", "openspec", "task_state", "runtime_evidence",
}
RECALL_MANIFEST_SCHEMA = "xiaoh-project-recall/v1"
SPEC_RFC_REVIEW_SKILLS = {"spec-rfc-reviewer", "xiaoh:spec-rfc-reviewer"}
OPENSPEC_REVIEW_SKILLS = {
    "spec-rfc-openspec-consistency-review",
    "xiaoh:spec-rfc-openspec-consistency-review",
}
SPEC_RFC_REVIEW_DECISIONS = {"OPENSPEC_READY", "OPENSPEC_READY_WITH_FIXES", "OPENSPEC_NOT_READY"}
OPENSPEC_REVIEW_DECISIONS = {"PASS", "PASS_WITH_FINDINGS", "BLOCKED"}
LOCAL_REVIEW_SCHEMA = "xiaoh-local-review/v1"
LOCAL_REVIEW_EVIDENCE_SCHEMA = "xiaoh-local-review-evidence/v1"
LOCAL_REVIEW_REPOSITORY_SET_SCHEMA = "xiaoh-repository-set/v1"
DELEGATION_BINDING_SCHEMA = "xiaoh-delegation-binding/v1"
ALLOWED_LOCAL_REVIEW_MODES = {"standalone", "playbook_managed"}
ALLOWED_LOCAL_REVIEW_SUBJECTS = {"git_commit", "artifact_digest"}
ALLOWED_LOCAL_REVIEW_VERDICTS = {"changes_requested", "passed"}
ALLOWED_RUN_STATUS = {"completed", "blocked", "failed", "cancelled"}
ALLOWED_GATE_STATUS = {"passed", "failed", "blocked", "not-run", "blocked-as-required", "blocked-as-designed"}
ALLOWED_VERIFICATION_STATUS = {"passed", "failed", "blocked", "not-run", "blocked-as-required", "blocked-as-designed"}
SENSITIVE_KEYS = re.compile(r"(^|_)(password|token|secret|private_key|credential)s?($|_)", re.I)
ABSOLUTE_PATH = re.compile(r"/(?:Users|home|opt|var|srv|workspace)/[^\s'\"`]+")
RESERVED_AGENT_ALIASES = {"xiaoh", "小h"}
IMPLEMENTATION_AGENTS = {"java_implementer", "frontend_implementer"}
MAX_CONTEXT_AGE_HOURS = 24
PLAYBOOK_BINDING_MAX_AGE_SECONDS = 900
MAX_RECALL_AGE_HOURS = 24
DELEGATION_BINDING_MAX_AGE_SECONDS = 900


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.details = {}

    def error(self, message):
        self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def emit(self, as_json=False):
        payload = {
            "status": "failed" if self.errors else "passed",
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if self.details:
            payload["details"] = self.details
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("agent-system validation:", payload["status"])
            for message in self.errors:
                print("ERROR:", message)
            for message in self.warnings:
                print("WARN:", message)
            if self.details:
                print(json.dumps(self.details, ensure_ascii=False, indent=2))
        return 1 if self.errors else 0


def load_json(path, report):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.error("{}: {}".format(path, exc))
        return None


def configured_xiaoh_path():
    return Path(
        os.environ.get("XIAOH_CONFIG", str(HOME / ".xiaoh/config.json"))
    ).expanduser().resolve(strict=False)


def configured_xiaoh_data():
    config_path = configured_xiaoh_path()
    value = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("XiaoH config must be a JSON object")
    return value


def configured_vault_path():
    value = configured_xiaoh_data()
    vault = value.get("obsidian_vault")
    if not isinstance(vault, str) or not vault.strip():
        raise ValueError("XiaoH config lacks obsidian_vault")
    return Path(vault).expanduser().resolve(strict=False)


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_hash(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def task_authority_hash(context):
    if not isinstance(context, dict) or context.get("schema_version") != "1.6":
        raise ValueError("authority hash requires task context schema 1.6")
    return canonical_json_hash(context)


def migrate_task_context_15_to_16(source, source_path):
    if source.get("schema_version") != "1.5":
        raise ValueError("only task context schema 1.5 can migrate to 1.6")
    migrated = copy.deepcopy(source)
    migrated["schema_version"] = "1.6"
    migrated["revision"] = source["revision"] + 1
    migrated["previous_context"] = {
        "path": str(source_path.expanduser().resolve()),
        "hash": file_sha256(source_path),
    }
    routing = migrated["routing"]
    names = routing.pop("delegation_names", {})
    actions = routing.pop("delegated_actions", {})
    routing["delegation_policies"] = {
        agent: {
            "agent_type": agent,
            "action": actions[agent],
            "task_name_prefix": names[agent],
        }
        for agent in routing.get("delegated_agents", [])
    }
    playbook = migrated["playbook"]
    for key in (
        "binding_kind", "stage", "review_artifacts", "worker_contract_source",
        "adapter_receipt", "adapter_receipt_sha256",
    ):
        playbook.pop(key, None)
    migrated["freshness"] = {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "checked_by": ROOT_AGENT,
    }
    return migrated


def file_identity(path):
    resolved = Path(path).resolve(strict=False)
    try:
        metadata = resolved.stat()
    except OSError:
        return ("path", os.path.normcase(str(resolved)))
    return ("file", metadata.st_dev, metadata.st_ino)


def resolve_configured_workspace(workspace_path):
    value = configured_xiaoh_data()
    registry = value.get("workspaces")
    if not isinstance(registry, dict):
        raise ValueError("XiaoH config workspaces must be a JSON object")
    target = Path(workspace_path).expanduser().resolve(strict=False)
    current_platform = platform.system().lower()
    matches = []
    for workspace_id, entry in registry.items():
        if not isinstance(workspace_id, str) or not isinstance(entry, dict):
            continue
        candidates = []
        bindings = entry.get("bindings")
        if isinstance(bindings, list):
            candidates.extend(
                binding.get("root")
                for binding in bindings
                if isinstance(binding, dict)
                and isinstance(binding.get("platform"), str)
                and binding["platform"].lower() == current_platform
            )
        else:
            roots = entry.get("roots")
            legacy_platform = entry.get("platform", "unknown")
            if (
                isinstance(roots, list)
                and isinstance(legacy_platform, str)
                and legacy_platform.lower() == current_platform
            ):
                candidates.extend(roots)
        for raw_root in candidates:
            if not isinstance(raw_root, str) or not raw_root.strip():
                continue
            root = Path(raw_root).expanduser().resolve(strict=False)
            if target == root or path_is_covered(str(target), [str(root)]):
                matches.append((len(root.parts), workspace_id, entry, root))
    if not matches:
        raise ValueError("scope.workspace is not registered in XiaoH config")
    strongest_length = max(match[0] for match in matches)
    strongest = [match for match in matches if match[0] == strongest_length]
    workspace_ids = {match[1] for match in strongest}
    if len(workspace_ids) != 1:
        raise ValueError("scope.workspace matches conflicting XiaoH workspace registrations")
    _, workspace_id, entry, root = strongest[0]
    project = entry.get("project")
    system = entry.get("system")
    if not isinstance(project, str) or not project.strip():
        raise ValueError("registered XiaoH workspace lacks project")
    if not isinstance(system, str) or not system.strip():
        raise ValueError("registered XiaoH workspace lacks system")
    return {
        "workspace_id": workspace_id,
        "project": project,
        "system": system,
        "matched_root": str(root),
    }


def require_keys(data, keys, label, report):
    if not isinstance(data, dict):
        report.error("{} must be a JSON object".format(label))
        return False
    missing = [key for key in keys if key not in data]
    if missing:
        report.error("{} missing keys: {}".format(label, ", ".join(missing)))
        return False
    return True


def find_sensitive_keys(value, prefix=""):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            location = "{}.{}".format(prefix, key).strip(".")
            if SENSITIVE_KEYS.search(key):
                found.append(location)
            found.extend(find_sensitive_keys(child, location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_sensitive_keys(child, "{}[{}]".format(prefix, index)))
    return found


def normalize_agent_name(value):
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


def parse_timestamp(value, label, report):
    if not isinstance(value, str) or not value.strip():
        report.error("{} must be an ISO-8601 timestamp".format(label))
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        report.error("{} must be an ISO-8601 timestamp".format(label))
        return None
    if parsed.tzinfo is None:
        report.error("{} must include a timezone".format(label))
        return None
    return parsed


def validate_string_list(value, label, report, non_empty=False):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        report.error("{} must be a list of non-empty strings".format(label))
        return []
    if non_empty and not value:
        report.error("{} must be a non-empty list".format(label))
    if len(value) != len(set(value)):
        report.error("{} contains duplicates".format(label))
    return value


def path_is_covered(path, allowed_paths):
    candidate = Path(path).resolve(strict=False)
    for allowed in allowed_paths:
        root = Path(allowed).resolve(strict=False)
        if candidate == root or root in candidate.parents:
            return True
    return False


def validate_result_entries(entries, label, required_keys, allowed_statuses, report):
    if not isinstance(entries, list):
        report.error("{} must be a list".format(label))
        return
    for index, entry in enumerate(entries):
        item_label = "{}[{}]".format(label, index)
        if not require_keys(entry, required_keys, item_label, report):
            continue
        for key in required_keys:
            if not isinstance(entry[key], str) or not entry[key].strip():
                report.error("{}.{} must be a non-empty string".format(item_label, key))
        if entry.get("status") not in allowed_statuses:
            report.error("{}.status must be one of {}".format(item_label, sorted(allowed_statuses)))


def non_empty_or_none(value):
    return value is None or (isinstance(value, str) and bool(value.strip()))


def validate_artifact_review(
    review, label, allowed_skills, allowed_decisions, passing_decision, revision, required, report,
):
    if not isinstance(review, dict):
        if required:
            report.error("{} review evidence is required".format(label))
        return
    if not require_keys(review, ["skill", "status", "decision", "reviewed_revision", "evidence"], label, report):
        return
    if review["skill"] not in allowed_skills:
        report.error("{}.skill must be one of {}".format(label, sorted(allowed_skills)))
    if review["status"] not in ALLOWED_REQUIREMENT_CHECK_STATUS:
        report.error("{}.status must be one of {}".format(label, sorted(ALLOWED_REQUIREMENT_CHECK_STATUS)))
    if review["decision"] not in allowed_decisions:
        report.error("{}.decision must be one of {}".format(label, sorted(allowed_decisions)))
    reviewed_revision = review["reviewed_revision"]
    if reviewed_revision is not None and (
        not isinstance(reviewed_revision, int) or isinstance(reviewed_revision, bool) or reviewed_revision < 1
    ):
        report.error("{}.reviewed_revision must be null or a positive integer".format(label))
    if not non_empty_or_none(review["evidence"]):
        report.error("{}.evidence must be null or a non-empty string".format(label))
    if required:
        if review["status"] != "passed":
            report.error("{}.status must be passed".format(label))
        if review["decision"] != passing_decision:
            report.error("{}.decision must be {}".format(label, passing_decision))
        if reviewed_revision != revision:
            report.error("{}.reviewed_revision must match the current artifact revision".format(label))
        if not isinstance(review["evidence"], str) or not review["evidence"].strip():
            report.error("{}.evidence is required when the review passes".format(label))


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
    if manifest["task_relation"] not in ALLOWED_TASK_RELATIONS:
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
        if source["kind"] not in ALLOWED_MEMORY_SOURCE_KINDS:
            report.error("{}.kind must be one of {}".format(label, sorted(ALLOWED_MEMORY_SOURCE_KINDS)))
        if source["role"] not in ALLOWED_MEMORY_SOURCE_ROLES:
            report.error("{}.role must be one of {}".format(label, sorted(ALLOWED_MEMORY_SOURCE_ROLES)))
        if source["kind"] == "daily_digest" and source["role"] != "navigation":
            report.error("daily_digest memory sources must use role=navigation")
        validate_string_list(
            source["point_ids"],
            "{}.point_ids".format(label),
            report,
            non_empty=(
                source["kind"] == "requirement_baseline"
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
        if source["kind"] not in ALLOWED_CURRENT_FACT_KINDS:
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
    if recall["status"] not in ALLOWED_RECALL_STATUS:
        report.error("memory_recall.status must be one of {}".format(sorted(ALLOWED_RECALL_STATUS)))
    if require_completed and recall["status"] != "completed":
        report.error("project memory recall must be completed before this action")
    if recall["task_relation"] not in ALLOWED_TASK_RELATIONS:
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
    if route not in ALLOWED_ARTIFACT_ROUTES:
        report.error("requirements.artifact_route must be one of {}".format(sorted(ALLOWED_ARTIFACT_ROUTES)))
    if not isinstance(requirements["route_reason"], str) or not requirements["route_reason"].strip():
        report.error("requirements.route_reason must be a non-empty string")
    validate_string_list(requirements["risk_signals"], "requirements.risk_signals", report)
    required_gates = validate_string_list(requirements["required_gates"], "requirements.required_gates", report)
    if route == "spec_rfc_then_openspec":
        missing_gates = {
            "spec_rfc_validation", "spec_rfc_quality_review", "user_confirmation",
            "openspec_consistency_review",
        } - set(required_gates)
        if missing_gates:
            report.error("spec_rfc_then_openspec missing required gates: {}".format(", ".join(sorted(missing_gates))))

    spec = requirements["spec_rfc"]
    if require_keys(
        spec,
        [
            "status", "reference", "revision", "validation_status", "independent_review_status",
            "confirmed_by_user", "confirmed_at",
        ],
        "requirements.spec_rfc", report,
    ):
        if spec["status"] not in ALLOWED_SPEC_RFC_STATUS:
            report.error("requirements.spec_rfc.status must be one of {}".format(sorted(ALLOWED_SPEC_RFC_STATUS)))
        if not non_empty_or_none(spec["reference"]):
            report.error("requirements.spec_rfc.reference must be null or a non-empty string")
        if not isinstance(spec["revision"], int) or isinstance(spec["revision"], bool) or spec["revision"] < 0:
            report.error("requirements.spec_rfc.revision must be a non-negative integer")
        for key in ("validation_status", "independent_review_status"):
            if spec[key] not in ALLOWED_REQUIREMENT_CHECK_STATUS:
                report.error("requirements.spec_rfc.{} must be one of {}".format(key, sorted(ALLOWED_REQUIREMENT_CHECK_STATUS)))
        if not isinstance(spec["confirmed_by_user"], bool):
            report.error("requirements.spec_rfc.confirmed_by_user must be a boolean")
        if not non_empty_or_none(spec["confirmed_at"]):
            report.error("requirements.spec_rfc.confirmed_at must be null or an ISO-8601 timestamp")
        elif spec["confirmed_at"] is not None:
            parse_timestamp(spec["confirmed_at"], "requirements.spec_rfc.confirmed_at", report)
        if spec["status"] == "confirmed":
            if not isinstance(spec["reference"], str) or not spec["reference"].strip():
                report.error("confirmed Spec+RFC requires requirements.spec_rfc.reference")
            if spec["revision"] < 1:
                report.error("confirmed Spec+RFC requires a positive revision")
            if spec["validation_status"] != "passed":
                report.error("confirmed Spec+RFC requires validation_status=passed")
            if spec["independent_review_status"] != "passed":
                report.error("confirmed Spec+RFC requires independent_review_status=passed")
            validate_artifact_review(
                spec.get("quality_review"), "requirements.spec_rfc.quality_review",
                SPEC_RFC_REVIEW_SKILLS, SPEC_RFC_REVIEW_DECISIONS, "OPENSPEC_READY",
                spec["revision"], True, report,
            )
            if spec["confirmed_by_user"] is not True or spec["confirmed_at"] is None:
                report.error("confirmed Spec+RFC requires user confirmation evidence")

    openspec = requirements["openspec"]
    if require_keys(
        openspec,
        ["consistency_status", "traceability_status", "validated_spec_rfc_revision"],
        "requirements.openspec", report,
    ):
        for key in ("consistency_status", "traceability_status"):
            if openspec[key] not in ALLOWED_REQUIREMENT_CHECK_STATUS:
                report.error("requirements.openspec.{} must be one of {}".format(key, sorted(ALLOWED_REQUIREMENT_CHECK_STATUS)))
        validated_revision = openspec["validated_spec_rfc_revision"]
        if validated_revision is not None and (
            not isinstance(validated_revision, int) or isinstance(validated_revision, bool) or validated_revision < 1
        ):
            report.error("requirements.openspec.validated_spec_rfc_revision must be null or a positive integer")
        if (
            isinstance(spec, dict)
            and openspec["consistency_status"] == "passed"
            and validated_revision != spec.get("revision")
        ):
            report.error("Spec+RFC revision changed; OpenSpec consistency_status must reset to pending")
        validate_artifact_review(
            openspec.get("consistency_review"), "requirements.openspec.consistency_review",
            OPENSPEC_REVIEW_SKILLS, OPENSPEC_REVIEW_DECISIONS, "PASS", validated_revision,
            openspec["consistency_status"] == "passed", report,
        )

    bypass = requirements["bypass"]
    if require_keys(bypass, ["reason"], "requirements.bypass", report):
        if not non_empty_or_none(bypass["reason"]):
            report.error("requirements.bypass.reason must be null or a non-empty string")
        if route == "openspec_only" and (not isinstance(bypass["reason"], str) or not bypass["reason"].strip()):
            report.error("openspec_only requires a non-empty requirements.bypass.reason")
        if route != "openspec_only" and bypass["reason"] is not None:
            report.error("requirements.bypass.reason is only allowed for openspec_only")

    retro = requirements["retroactive_normalization"]
    if require_keys(retro, ["required", "status"], "requirements.retroactive_normalization", report):
        if not isinstance(retro["required"], bool):
            report.error("requirements.retroactive_normalization.required must be a boolean")
        if retro["status"] not in ALLOWED_RETROACTIVE_STATUS:
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
                names.append(record["name"].removeprefix("$"))
            if record["status"] not in ALLOWED_SKILL_STATUS:
                report.error("{}.status must be one of {}".format(label, sorted(ALLOWED_SKILL_STATUS)))
            if record["validation_status"] not in ALLOWED_REQUIREMENT_CHECK_STATUS:
                report.error("{}.validation_status must be one of {}".format(label, sorted(ALLOWED_REQUIREMENT_CHECK_STATUS)))
            if record["confirmation_status"] not in ALLOWED_SKILL_CONFIRMATION_STATUS:
                report.error("{}.confirmation_status must be one of {}".format(label, sorted(ALLOWED_SKILL_CONFIRMATION_STATUS)))
            if not non_empty_or_none(record["evidence"]):
                report.error("{}.evidence must be null or a non-empty string".format(label))
        normalized_requested = [name.removeprefix("$") for name in requested]
        if len(names) != len(set(names)):
            report.error("requirements.skill_execution.records contains duplicate skill names")
        if set(names) != set(normalized_requested):
            report.error("requirements.skill_execution.records must cover every explicitly requested Skill")
        if "spec-rfc" in normalized_requested and route != "spec_rfc_then_openspec":
            report.error("explicit spec-rfc request requires artifact_route=spec_rfc_then_openspec")

    if route == "openspec_only" and isinstance(spec, dict) and spec.get("status") != "not_required":
        report.error("openspec_only requires requirements.spec_rfc.status=not_required")
    if route == "spec_rfc_then_openspec" and isinstance(spec, dict) and spec.get("status") == "not_required":
        report.error("spec_rfc_then_openspec cannot use requirements.spec_rfc.status=not_required")


def validate_requirement_gate(
    context,
    action,
    report,
    check_paths=True,
    *,
    root_playbook_receipt=None,
    root_playbook_receipt_sha256=None,
    delegated_execution_binding=None,
    delegated_execution_binding_context_path=None,
    check_playbook_live_status=True,
):
    if action not in ALLOWED_REQUIREMENT_GATE_ACTIONS:
        report.error("requirement gate action must be one of {}".format(sorted(ALLOWED_REQUIREMENT_GATE_ACTIONS)))
        return
    if action != "readonly_analysis" and context.get("schema_version") != "1.6":
        report.error("new requirement lifecycle actions require schema 1.6 stable task authority")
    validate_interaction_gate(context, action, report)
    intent = context.get("intent", {})
    if intent.get("domain") != "business_project":
        report.error("requirement lifecycle gates apply only to business_project contexts")
        return
    if context.get("schema_version") in {"1.5", "1.6"}:
        validate_memory_recall(
            context.get("memory_recall"),
            context,
            report,
            check_paths=check_paths,
            require_completed=action != "readonly_analysis",
        )
    if action == "implementation" and context.get("playbook", {}).get("managed"):
        if context.get("schema_version") == "1.6":
            if delegated_execution_binding is not None:
                if delegated_execution_binding_context_path is None:
                    report.error(
                        "managed delegated implementation requires its task context path"
                    )
                else:
                    validate_execution_binding(
                        delegated_execution_binding,
                        context,
                        delegated_execution_binding_context_path,
                        report,
                        check_paths=True,
                        check_freshness=True,
                        check_live_status=check_playbook_live_status,
                    )
                    if delegated_execution_binding.get("action") != action:
                        report.error(
                            "delegated execution binding action does not match requirement gate"
                        )
            elif not root_playbook_receipt or not root_playbook_receipt_sha256:
                report.error(
                    "managed root implementation requires an explicit fresh Playbook receipt"
                )
            else:
                validate_root_playbook_receipt(
                    context,
                    root_playbook_receipt,
                    root_playbook_receipt_sha256,
                    action,
                    report,
                    check_live_status=check_playbook_live_status,
                )
        else:
            validate_playbook_binding(
                context,
                report,
                check_paths=True,
                require_binding=True,
                expected_action=action,
            )
    requirements = context.get("requirements")
    if not isinstance(requirements, dict):
        report.error("business_project requirement gate requires requirements state")
        return
    route = requirements.get("artifact_route")
    spec = requirements.get("spec_rfc", {})
    openspec = requirements.get("openspec", {})
    retro = requirements.get("retroactive_normalization", {})
    execution = requirements.get("skill_execution", {})
    gated_actions = {
        "member_confirmation", "task_create", "openspec_authoring", "openspec_confirmation",
        "task_start", "implementation",
    }
    if action == "spec_rfc_confirmation" and route == "spec_rfc_then_openspec":
        if spec.get("validation_status") != "passed":
            report.error("Spec+RFC validation must pass before user confirmation")
        validate_artifact_review(
            spec.get("quality_review"), "requirements.spec_rfc.quality_review",
            SPEC_RFC_REVIEW_SKILLS, SPEC_RFC_REVIEW_DECISIONS, "OPENSPEC_READY",
            spec.get("revision"), True, report,
        )
    if action in gated_actions and retro.get("required") is True and retro.get("status") != "completed":
        report.error("retroactive_normalization must be completed before {}".format(action))
    if action in gated_actions and route == "spec_rfc_then_openspec" and spec.get("status") != "confirmed":
        report.error("confirmed Spec+RFC is required before {}".format(action))
    if action in {"openspec_confirmation", "task_start", "implementation"} and route == "spec_rfc_then_openspec":
        if openspec.get("consistency_status") != "passed":
            report.error("OpenSpec consistency review must pass before {}".format(action))
        if openspec.get("traceability_status") != "passed":
            report.error("OpenSpec traceability must pass before {}".format(action))
    if action in gated_actions:
        records = {
            str(record.get("name", "")).removeprefix("$"): record
            for record in execution.get("records", [])
            if isinstance(record, dict)
        }
        for requested in execution.get("explicitly_requested", []):
            name = str(requested).removeprefix("$")
            record = records.get(name, {})
            if record.get("status") != "completed" or record.get("validation_status") != "passed" or not record.get("evidence"):
                report.error("explicitly requested Skill {} lacks completed and validated execution evidence".format(name))


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
            "spec_rfc_validation", "spec_rfc_quality_review", "user_confirmation",
            "openspec_consistency_review", "traceability",
        ],
        "spec_rfc": {
            "status": "confirmed",
            "reference": "/tmp/spec-rfc.md",
            "revision": 1,
            "validation_status": "passed",
            "independent_review_status": "passed",
            "quality_review": {
                "skill": "spec-rfc-reviewer", "status": "passed", "decision": "OPENSPEC_READY",
                "reviewed_revision": 1,
                "evidence": "/tmp/spec-rfc-review.md",
            },
            "confirmed_by_user": True,
            "confirmed_at": "2026-07-21T00:00:00+08:00",
        },
        "openspec": {
            "consistency_status": "passed",
            "traceability_status": "passed",
            "validated_spec_rfc_revision": 1,
            "consistency_review": {
                "skill": "xiaoh:spec-rfc-openspec-consistency-review", "status": "passed",
                "decision": "PASS", "reviewed_revision": 1,
                "evidence": "/tmp/openspec-consistency-review.md",
            },
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


def closure_rejection_reasons(record, reviewer_agents=None):
    reasons = []
    if record.get("schema_version") != "1.2":
        reasons.append("legacy schema is not eligible for v1.2 closure")
    gates = record.get("gates")
    if not isinstance(gates, list) or not gates or any(item.get("status") != "passed" for item in gates if isinstance(item, dict)) or any(not isinstance(item, dict) for item in gates or []):
        reasons.append("all gates must be present and passed")
    verification = record.get("verification")
    if not isinstance(verification, list) or not verification or any(item.get("status") != "passed" for item in verification if isinstance(item, dict)) or any(not isinstance(item, dict) for item in verification or []):
        reasons.append("all verification results must be present and passed")
    if record.get("metrics", {}).get("result_accepted") is not True:
        reasons.append("metrics.result_accepted must be true")
    if record.get("agent") in set(reviewer_agents or []):
        if not any(item.get("name") == "independent_review" and item.get("status") == "passed" for item in gates or [] if isinstance(item, dict)):
            reasons.append("independent reviewer must pass the independent_review gate")
    return reasons


def expected_effective_brief(
    context, task_context, context_hash, agent, agent_type, task_name, proof=None
):
    if context.get("schema_version") == "1.6":
        proof = proof or {}
        effective = proof.get("effective_brief", {})
        brief = {
            "schema_version": "1.2",
            "task_id": context.get("task_id"),
            "task_context": str(task_context),
            "authority_hash": context_hash,
            "delegated_agent": agent,
            "agent_type": agent_type,
            "task_name": task_name,
            "action": context.get("routing", {}).get(
                "delegation_policies", {}
            ).get(agent, {}).get("action"),
            "execution_binding": effective.get("execution_binding"),
            "binding_hash": effective.get("binding_hash"),
            "authority": (
                "task_context_execution_binding_and_playbook_receipt"
                if context.get("playbook", {}).get("managed")
                else "task_context_and_one_time_execution_binding"
            ),
        }
        if context.get("playbook", {}).get("managed"):
            brief["playbook_adapter_receipt"] = effective.get(
                "playbook_adapter_receipt"
            )
            brief["playbook_adapter_receipt_sha256"] = effective.get(
                "playbook_adapter_receipt_sha256"
            )
        return brief
    brief = {
        "schema_version": "1.0",
        "task_id": context.get("task_id"),
        "task_context": str(task_context),
        "context_hash": context_hash,
        "delegated_agent": agent,
        "agent_type": agent_type,
        "task_name": task_name,
        "authority": "task_context_is_authoritative",
    }
    playbook = context.get("playbook", {})
    routing = context.get("routing", {})
    if (
        context.get("intent", {}).get("domain") == "business_project"
        and isinstance(playbook, dict)
        and playbook.get("managed")
        and playbook.get("adapter_receipt")
    ):
        brief.update({
            "schema_version": "1.1",
            "authority": "task_context_and_playbook_adapter_receipt",
            "delegated_action": routing.get("delegated_actions", {}).get(agent),
            "playbook_adapter_receipt": playbook.get("adapter_receipt"),
            "playbook_adapter_receipt_sha256": playbook.get("adapter_receipt_sha256"),
            "playbook_binding_kind": playbook.get("binding_kind") or "worker",
            "playbook_task_workspace_id": playbook.get("task_workspace_id"),
            "playbook_member": playbook.get("member"),
            "playbook_member_worktree": playbook.get("member_worktree"),
            "playbook_workspace_root": playbook.get("workspace_root"),
            "playbook_allowed_scope": playbook.get("allowed_scope"),
        })
    return brief


def validate_playbook_receipt_at_agent_start(context, proof, report):
    playbook = context.get("playbook", {})
    if (
        context.get("intent", {}).get("domain") != "business_project"
        or not isinstance(playbook, dict)
        or not playbook.get("managed")
    ):
        return
    effective_brief = proof.get("effective_brief", {})
    if context.get("schema_version") == "1.6":
        receipt_path = effective_brief.get("playbook_adapter_receipt")
        receipt_sha256 = effective_brief.get("playbook_adapter_receipt_sha256")
        delegated_action = effective_brief.get("action")
    else:
        receipt_path = playbook.get("adapter_receipt")
        receipt_sha256 = playbook.get("adapter_receipt_sha256")
        delegated_action = effective_brief.get("delegated_action")
    try:
        receipt = validate_receipt(
            Path(receipt_path),
            expected_sha256=receipt_sha256,
            expected_action=delegated_action,
            max_age_seconds=None,
            check_sources=False,
            check_live_status=False,
        )
    except (AdapterError, OSError, KeyError) as exc:
        report.error("historical Playbook adapter receipt is invalid: {}".format(exc))
        return
    captured_at = parse_timestamp(
        receipt.get("captured_at"), "Playbook receipt captured_at", report
    )
    started_at = parse_timestamp(
        proof.get("started_at"), "delegation proof started_at", report
    )
    if captured_at and started_at:
        age_at_start = (started_at - captured_at).total_seconds()
        if age_at_start < -300 or age_at_start > PLAYBOOK_BINDING_MAX_AGE_SECONDS:
            report.error(
                "Playbook adapter receipt was not fresh when the Agent started"
            )


def validate_attested_binding(proof, expected_brief, transcript_path, report):
    if proof.get("state") != "attested":
        report.error("delegation proof state must be attested")
    if proof.get("source") != "subagent-start-stop":
        report.error("delegation proof source must be subagent-start-stop")
    if proof.get("effective_brief") != expected_brief:
        report.error("delegation proof effective_brief does not match the run/context binding")
    encoded_brief = json.dumps(
        expected_brief, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if proof.get("effective_brief_hash") != hashlib.sha256(encoded_brief).hexdigest():
        report.error("delegation proof effective_brief_hash does not match effective_brief")
    proof_transcript = Path(str(proof.get("agent_transcript_path"))).resolve(strict=False)
    if proof_transcript != Path(str(transcript_path)).resolve(strict=False):
        report.error("delegation proof agent_transcript_path does not match runtime evidence")
    for key in (
        "effective_brief_hash", "transport_message_hash", "receipt_hash", "last_message_hash", "hook_hash",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(proof.get(key))):
            report.error("delegation proof {} must be a lowercase SHA-256 digest".format(key))


def validate_delegation_proof(runtime_evidence, data, context, context_path, report, check_paths):
    proof_path = Path(str(runtime_evidence["delegation_proof_path"]))
    proof_hash = runtime_evidence["delegation_proof_hash"]
    if not proof_path.is_absolute():
        report.error("runtime_evidence.delegation_proof_path must be absolute")
    elif not path_is_covered(str(proof_path), [str(SYSTEM_DIR / "delegation-proofs")]):
        report.error("runtime delegation proof must be under CODEX_HOME/agent-system/delegation-proofs")
    elif check_paths and not proof_path.is_file():
        report.error("runtime delegation proof does not exist: {}".format(proof_path))
    if not re.fullmatch(r"[0-9a-f]{64}", str(proof_hash)):
        report.error("runtime_evidence.delegation_proof_hash must be a lowercase SHA-256 digest")
        return
    if not check_paths or not proof_path.is_file():
        return
    proof_bytes = proof_path.read_bytes()
    if hashlib.sha256(proof_bytes).hexdigest() != proof_hash:
        report.error("runtime_evidence.delegation_proof_hash does not match proof")
        return
    try:
        proof = json.loads(proof_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        report.error("runtime delegation proof must be valid UTF-8 JSON")
        return
    schema_version = proof.get("schema_version")
    if (
        isinstance(context, dict)
        and context.get("schema_version") == "1.6"
        and schema_version != "1.3"
    ):
        report.error("task context schema 1.6 requires an attested delegation proof schema 1.3")
        return
    if schema_version not in {"1.0", "1.1", "1.2", "1.3"}:
        report.error("delegation proof schema_version must be 1.0, 1.1, 1.2, or 1.3")
        return
    expected = {
        "session_id": runtime_evidence["parent_agent_id"],
        "task_id": data.get("task_id"),
        "task_context": str(context_path.resolve(strict=False)),
        "context_hash": data.get("context_hash"),
        "delegated_agent": data.get("agent"),
        "agent_type": runtime_evidence["agent_type"],
        "task_name": runtime_evidence["task_name"],
    }
    if schema_version in {"1.0", "1.1"}:
        required = [
            "schema_version", "issued_at", "session_id", "turn_id", "task_id",
            "task_context", "context_hash", "delegated_agent", "agent_type", "task_name",
            "message_hash", "hook_path", "hook_hash",
        ]
        if schema_version == "1.0":
            required.append("tool_use_id")
        else:
            required.extend(["source", "prepared_at", "agent_id"])
        if not require_keys(proof, required, "delegation proof", report):
            return
        issued_at = parse_timestamp(proof["issued_at"], "delegation proof issued_at", report)
        id_keys = ["session_id", "turn_id"]
        if schema_version == "1.0":
            id_keys.append("tool_use_id")
        else:
            id_keys.append("agent_id")
            expected["agent_id"] = runtime_evidence["agent_id"]
            prepared_at = parse_timestamp(proof["prepared_at"], "delegation proof prepared_at", report)
            if proof["source"] != "subagent-start":
                report.error("delegation proof source must be subagent-start")
            if prepared_at and issued_at and issued_at < prepared_at:
                report.error("delegation proof issued_at must not be earlier than prepared_at")
        for key in id_keys:
            if not isinstance(proof[key], str) or not proof[key].strip():
                report.error("delegation proof {} must be a non-empty string".format(key))
        for key in ("message_hash", "hook_hash"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(proof.get(key))):
                report.error("delegation proof {} must be a lowercase SHA-256 digest".format(key))
    else:
        required = [
            "schema_version", "state", "source", "prepared_at", "started_at", "attested_at",
            "session_id", "turn_id", "stop_turn_id", "agent_id", "task_id", "task_context",
            "context_hash", "delegated_agent", "agent_type", "task_name", "effective_brief",
            "effective_brief_hash", "transport_message_hash", "receipt_hash", "agent_transcript_path",
            "last_message_hash", "hook_path", "hook_hash",
        ]
        if not require_keys(proof, required, "delegation proof", report):
            return
        if schema_version == "1.3":
            if not require_keys(
                proof,
                ["authority_hash", "execution_binding_hash", "execution_binding_claimed_path"],
                "delegation proof 1.3",
                report,
            ):
                return
            if proof.get("authority_hash") != data.get("context_hash"):
                report.error("delegation proof authority_hash does not match run record")
            claimed_binding = Path(
                str(proof.get("execution_binding_claimed_path"))
            ).expanduser()
            if not claimed_binding.is_absolute():
                report.error("delegation proof execution_binding_claimed_path must be absolute")
            elif check_paths and not claimed_binding.is_file():
                report.error("delegation proof claimed execution binding does not exist")
            elif check_paths and file_sha256(claimed_binding) != proof.get(
                "execution_binding_hash"
            ):
                report.error("delegation proof execution binding hash does not match")
            elif check_paths:
                binding = load_json(claimed_binding, report)
                if isinstance(binding, dict):
                    binding_report = Report()
                    validate_execution_binding(
                        binding,
                        context,
                        context_path,
                        binding_report,
                        check_paths=True,
                        check_freshness=False,
                        check_live_status=False,
                        check_receipt_sources=False,
                        check_hook_source=False,
                    )
                    for error in binding_report.errors:
                        report.error(
                            "historical execution binding is invalid: {}".format(error)
                        )
                    if binding.get("hook_path") != proof.get("hook_path"):
                        report.error(
                            "historical execution binding hook_path does not match delegation proof"
                        )
                    if binding.get("hook_hash") != proof.get("hook_hash"):
                        report.error(
                            "historical execution binding hook_hash does not match delegation proof"
                        )
                    binding_expected = {
                        "task_id": data.get("task_id"),
                        "authority_hash": data.get("context_hash"),
                        "delegated_agent": data.get("agent"),
                        "agent_type": runtime_evidence.get("agent_type"),
                        "task_name": runtime_evidence.get("task_name"),
                    }
                    for key, value in binding_expected.items():
                        if binding.get(key) != value:
                            report.error(
                                "historical execution binding {} does not match run record".format(
                                    key
                                )
                            )
                    local_review = data.get("outputs", {}).get("local_review")
                    if isinstance(local_review, dict):
                        review_expected = {
                            "purpose": "local_review",
                            "review_round": local_review.get("round"),
                            "subject_digest": local_review.get("subject_value"),
                        }
                        for key, value in review_expected.items():
                            if binding.get(key) != value:
                                report.error(
                                    "historical execution binding {} does not match local review output".format(
                                        key
                                    )
                                )
        prepared_at = parse_timestamp(proof["prepared_at"], "delegation proof prepared_at", report)
        started_at = parse_timestamp(proof["started_at"], "delegation proof started_at", report)
        attested_at = parse_timestamp(proof["attested_at"], "delegation proof attested_at", report)
        if prepared_at and started_at and started_at < prepared_at:
            report.error("delegation proof started_at must not be earlier than prepared_at")
        if started_at and attested_at and attested_at < started_at:
            report.error("delegation proof attested_at must not be earlier than started_at")
        for key in ("session_id", "turn_id", "stop_turn_id", "agent_id"):
            if not isinstance(proof[key], str) or not proof[key].strip():
                report.error("delegation proof {} must be a non-empty string".format(key))
        expected["agent_id"] = runtime_evidence["agent_id"]
        expected_brief = expected_effective_brief(
            context,
            context_path.resolve(strict=False),
            data.get("context_hash"),
            data.get("agent"),
            runtime_evidence["agent_type"],
            runtime_evidence["task_name"],
            proof,
        )
        validate_attested_binding(proof, expected_brief, runtime_evidence["transcript_path"], report)
        validate_playbook_receipt_at_agent_start(context, proof, report)
    for key, value in expected.items():
        if proof.get(key) != value:
            report.error("delegation proof {} does not match the run/context binding".format(key))
    hook_path = Path(str(proof["hook_path"])).resolve(strict=False)
    allowed_hooks = {ROOT_AGENT_HOOK.resolve(strict=False)}
    if hook_path not in allowed_hooks:
        report.error("delegation proof hook_path is not an installed delegation Hook")
    elif not hook_path.is_file():
        report.error("delegation proof Hook does not exist: {}".format(hook_path))
    elif (
        isinstance(context, dict)
        and schema_version != "1.3"
        and (
            context.get("schema_version") == "1.6"
            or context.get("revision", 0) >= 6
        )
        and re.fullmatch(r"[0-9a-f]{64}", str(proof.get("hook_hash")))
        and hashlib.sha256(hook_path.read_bytes()).hexdigest() != proof["hook_hash"]
    ):
        report.error("delegation proof hook_hash does not match the installed Hook")


def active_global_instructions():
    override = CODEX / "AGENTS.override.md"
    if override.exists() and override.read_text(encoding="utf-8").strip():
        return override
    return CODEX / "AGENTS.md"


def validate_evidence_backed_change(change, label, interaction, report, require_value=False):
    required = ["present", "basis", "evidence", "independent_review_status"]
    if require_value:
        required += ["target", "value"]
    if not require_keys(change, required, label, report):
        return
    evidence = validate_string_list(change["evidence"], "{}.evidence".format(label), report)
    if not isinstance(change["present"], bool):
        report.error("{}.present must be a boolean".format(label))
        return
    if not isinstance(change["basis"], str) or change["basis"] not in ALLOWED_SCOPE_REDUCTION_BASES:
        report.error("{}.basis must be one of {}".format(label, sorted(ALLOWED_SCOPE_REDUCTION_BASES)))
    review_status = change["independent_review_status"]
    if not isinstance(review_status, str) or review_status not in ALLOWED_REQUIREMENT_CHECK_STATUS:
        report.error("{}.independent_review_status must be one of {}".format(
            label, sorted(ALLOWED_REQUIREMENT_CHECK_STATUS)
        ))
    if not change["present"]:
        if change["basis"] != "not_applicable" or evidence or review_status != "not_required":
            report.error("absent {} must use not_applicable, empty evidence, and not_required review".format(label))
        if require_value and (change["target"] is not None or change["value"] is not None):
            report.error("absent {} must not define target or value".format(label))
        return
    if require_value:
        for key in ("target", "value"):
            if not isinstance(change[key], str) or not change[key].strip():
                report.error("{}.{} must be a non-empty string when present".format(label, key))
    if change["basis"] == "not_applicable":
        report.error("present {} requires evidence or an explicit business decision".format(label))
    if interaction["impact_explained"] is not True:
        report.error("{} requires explained impact".format(label))
    if change["basis"] == "evidence_supported" and not evidence:
        report.error("evidence-supported {} requires evidence".format(label))
    if change["basis"] == "explicit_business_decision" and not (
        interaction["baseline_change"] == "confirmed"
        and isinstance(interaction["user_act"], str)
        and interaction["user_act"] in {"business_decision", "execution_instruction"}
    ):
        report.error("decision-based {} requires a confirmed explicit decision".format(label))


def validate_interaction(interaction, report):
    required = [
        "user_act", "baseline_change", "evidence_status", "material_conflicts",
        "impact_explained", "scope_reduction", "compatibility_default",
    ]
    if not require_keys(interaction, required, "interaction", report):
        return
    user_act = interaction["user_act"]
    baseline_change = interaction["baseline_change"]
    evidence_status = interaction["evidence_status"]
    conflicts = validate_string_list(interaction["material_conflicts"], "interaction.material_conflicts", report)
    if not isinstance(user_act, str) or user_act not in ALLOWED_USER_ACTS:
        report.error("interaction.user_act must be one of {}".format(sorted(ALLOWED_USER_ACTS)))
    if not isinstance(baseline_change, str) or baseline_change not in ALLOWED_BASELINE_CHANGES:
        report.error("interaction.baseline_change must be one of {}".format(sorted(ALLOWED_BASELINE_CHANGES)))
    if not isinstance(evidence_status, str) or evidence_status not in ALLOWED_EVIDENCE_STATUSES:
        report.error("interaction.evidence_status must be one of {}".format(sorted(ALLOWED_EVIDENCE_STATUSES)))
    if not isinstance(interaction["impact_explained"], bool):
        report.error("interaction.impact_explained must be a boolean")
    if isinstance(user_act, str) and user_act in {"question", "hypothesis"} and baseline_change != "none":
        report.error("questions and hypotheses cannot change the confirmed baseline")
    if baseline_change == "confirmed":
        if not isinstance(user_act, str) or user_act not in {"business_decision", "execution_instruction"}:
            report.error("confirmed baseline change requires a business decision or execution instruction")
        if interaction["impact_explained"] is not True:
            report.error("confirmed baseline change requires explained impact")
    if evidence_status == "conflicted" and not conflicts:
        report.error("conflicted evidence requires material_conflicts")
    if conflicts and evidence_status != "conflicted":
        report.error("material_conflicts require evidence_status=conflicted")
    if conflicts and interaction["impact_explained"] is not True:
        report.error("material conflicts require explained impact")
    validate_evidence_backed_change(
        interaction["scope_reduction"], "interaction.scope_reduction",
        interaction, report,
    )
    validate_evidence_backed_change(
        interaction["compatibility_default"], "interaction.compatibility_default",
        interaction, report, require_value=True,
    )


def validate_interaction_gate(context, action, report):
    protected_actions = {
        "spec_rfc_confirmation", "member_confirmation", "task_create",
        "openspec_confirmation", "task_start", "implementation",
    }
    if action not in protected_actions or context.get("risk_level") not in {"high", "critical"}:
        return
    interaction = context.get("interaction")
    if not isinstance(interaction, dict):
        return
    for key in ("scope_reduction", "compatibility_default"):
        change = interaction.get(key)
        if (
            isinstance(change, dict)
            and change.get("present") is True
            and change.get("independent_review_status") != "passed"
        ):
            report.error("high-risk {} requires passed independent review before {}".format(key, action))


def playbook_binding_required_fields(playbook):
    return (
        "xiaoh_workspace_id",
        "task_workspace_id",
        "member",
        "member_worktree",
        "workspace_root",
        "adapter_receipt",
        "adapter_receipt_sha256",
    )


def validate_playbook_binding(
    context,
    report,
    check_paths=True,
    require_binding=False,
    check_freshness=True,
    check_live_status=True,
    expected_action=None,
):
    playbook = context.get("playbook")
    routing = context.get("routing")
    if not isinstance(playbook, dict) or not playbook.get("managed"):
        return None
    if check_freshness:
        try:
            mode = configured_integration_mode()
        except AdapterError as exc:
            report.error("invalid XiaoH integration configuration: {}".format(exc))
            return None
        if mode == "disabled":
            report.error(
                "managed Playbook context is forbidden because integrations.playbook is disabled"
            )
            return None
    missing = [
        key for key in playbook_binding_required_fields(playbook)
        if not isinstance(playbook.get(key), str) or not playbook[key].strip()
    ]
    delegated_actions = routing.get("delegated_actions") if isinstance(routing, dict) else None
    if not isinstance(delegated_actions, dict):
        missing.append("routing.delegated_actions")
    if missing:
        message = (
            "managed Playbook context lacks XiaoH adapter binding: "
            + ", ".join(sorted(set(missing)))
        )
        if require_binding:
            report.error(message)
        else:
            report.warn(message + "; legacy context is read-only")
        return None
    delegated_agents = routing.get("delegated_agents", [])
    invalid_actions = {
        value for value in delegated_actions.values()
        if not isinstance(value, str) or value not in ALLOWED_DELEGATED_ACTIONS
    }
    if invalid_actions:
        report.error(
            "routing.delegated_actions contains unsupported actions: "
            + ", ".join(sorted(str(value) for value in invalid_actions))
        )
    actions = set(delegated_actions.values())
    has_delegation = bool(delegated_agents or delegated_actions)
    if has_delegation:
        if set(delegated_actions) != set(delegated_agents):
            report.error("routing.delegated_actions keys must equal delegated_agents")
        if len(actions) != 1:
            report.error("one Playbook adapter receipt can bind exactly one delegated action")
        if expected_action and actions != {expected_action}:
            report.error("routing.delegated_actions does not match the required action")
    if playbook.get("workspace_id") != playbook.get("task_workspace_id"):
        report.error("playbook.workspace_id legacy alias must equal playbook.task_workspace_id")
    receipt_path = Path(playbook["adapter_receipt"]).expanduser()
    if not receipt_path.is_absolute():
        report.error("playbook.adapter_receipt must be an absolute path")
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", playbook["adapter_receipt_sha256"]):
        report.error("playbook.adapter_receipt_sha256 must be a lowercase SHA-256 digest")
        return None
    if not check_paths:
        if require_binding and not has_delegation:
            report.error(
                "root-owned Playbook execution requires worker identity and receipt path validation"
            )
        return None
    try:
        receipt = validate_receipt(
            receipt_path,
            expected_sha256=playbook["adapter_receipt_sha256"],
            expected_action=expected_action or (
                next(iter(actions)) if len(actions) == 1 else None
            ),
            max_age_seconds=PLAYBOOK_BINDING_MAX_AGE_SECONDS if check_freshness else None,
            check_live_status=check_live_status,
        )
    except (AdapterError, OSError) as exc:
        report.error("invalid XiaoH Playbook adapter receipt: {}".format(exc))
        return None
    if check_freshness:
        binding_kind = receipt.get("binding_kind", "worker")
        if binding_kind == "worker":
            probe = playbook_probe(
                receipt["playbook"]["command"],
                mode,
                Path(receipt["playbook"]["worker_contract_source"]),
                Path(receipt["playbook"]["status_source"]),
                check_source_freshness=False,
            )
            probe_ready = probe.get("status") == "compatible"
        else:
            probe = playbook_probe(
                receipt["playbook"]["command"], mode, require_worker=False
            )
            probe_ready = (
                probe.get("status") in {"available", "compatible"}
                and probe.get("checks", {}).get("task_status", {}).get("supported")
            )
        if not probe_ready:
            report.error(
                "managed Playbook delegation requires a compatible adapter probe: "
                + "; ".join(probe.get("errors") or [str(probe.get("status"))])
            )
            return None
    receipt_playbook = receipt["playbook"]
    binding_kind = receipt.get("binding_kind", "worker")
    if binding_kind == "worker":
        try:
            current_worker = worker_facts(
                Path(receipt_playbook["worker_contract_source"])
            )
        except (AdapterError, OSError) as exc:
            report.error("invalid XiaoH Playbook worker identity: {}".format(exc))
            return None
    else:
        current_worker = receipt_playbook
        allowed_review_actions = (
            STATUS_REVIEW_ACTIONS
            if binding_kind == "status_review"
            else LOCAL_REVIEW_ACTIONS
        )
        if actions and not actions.issubset(allowed_review_actions):
            report.error(
                "{} binding cannot authorize the requested action".format(binding_kind)
            )
    root_owned_execution = (
        binding_kind == "worker"
        and root_agent_owns_worker(current_worker)
    )
    if root_owned_execution:
        if routing.get("root_agent") != ROOT_AGENT:
            report.error("root-owned Playbook execution requires the current XiaoH root agent")
        if delegated_agents or delegated_actions:
            report.error("root-owned Playbook execution cannot declare delegated agents or actions")
    else:
        if not has_delegation:
            report.error("one Playbook adapter receipt can bind exactly one delegated action")
    comparisons = {
        "xiaoh_workspace_id": receipt["xiaoh_workspace_id"],
        "task_workspace_id": receipt_playbook["task_workspace_id"],
        "change_id": receipt_playbook["change_id"],
        "member": receipt_playbook["member"],
        "member_worktree": receipt_playbook["member_worktree"],
        "workspace_root": receipt_playbook["workspace_root"],
    }
    if binding_kind == "worker":
        comparisons["worker_contract_source"] = receipt_playbook[
            "worker_contract_source"
        ]
    for key, expected in comparisons.items():
        if playbook.get(key) != expected:
            report.error("playbook.{} does not match adapter receipt".format(key))
    if (playbook.get("binding_kind") or "worker") != binding_kind:
        report.error("playbook.binding_kind does not match adapter receipt")
    if playbook.get("allowed_scope") != receipt_playbook["allowed_scope"]:
        report.error("playbook.allowed_scope does not match adapter receipt")
    allowed_paths = context.get("scope", {}).get("allowed_paths", [])
    member_worktree = receipt_playbook["member_worktree"]
    if binding_kind == "worker" and isinstance(allowed_paths, list) and not any(
        isinstance(path, str) and path_is_covered(member_worktree, [path])
        for path in allowed_paths
    ):
        report.error("Playbook member_worktree is not covered by scope.allowed_paths")
    for delegated_path in receipt_playbook["allowed_scope"]:
        if not any(
            isinstance(path, str) and path_is_covered(delegated_path, [path])
            for path in allowed_paths
        ):
            report.error(
                "Playbook allowed_scope is not covered by scope.allowed_paths: {}".format(
                    delegated_path
                )
            )
    return receipt


def validate_execution_binding(
    binding,
    context,
    context_path,
    report,
    *,
    check_paths=True,
    check_freshness=True,
    check_live_status=True,
    check_receipt_sources=True,
    check_hook_source=True,
):
    required = [
        "schema_version", "prepared_at", "expires_at", "session_id", "task_id",
        "task_context", "authority_hash", "delegated_agent", "agent_type",
        "task_name", "action", "review_round", "purpose", "subject_digest",
        "playbook_adapter_receipt", "playbook_adapter_receipt_sha256",
        "nonce", "hook_path", "hook_hash",
    ]
    if not require_keys(binding, required, "execution binding", report):
        return
    if binding["schema_version"] != DELEGATION_BINDING_SCHEMA:
        report.error("execution binding schema_version must be {}".format(DELEGATION_BINDING_SCHEMA))
    if context.get("schema_version") != "1.6":
        report.error("execution binding requires task context schema 1.6")
        return
    expected_path = context_path.expanduser().resolve(strict=False)
    bound_path = Path(str(binding["task_context"])).expanduser()
    if not bound_path.is_absolute() or bound_path.resolve(strict=False) != expected_path:
        report.error("execution binding task_context must bind the current context")
    try:
        expected_authority = task_authority_hash(context)
    except ValueError as exc:
        report.error(str(exc))
        return
    if binding["authority_hash"] != expected_authority:
        report.error("execution binding authority_hash does not match task context")
    if binding["task_id"] != context.get("task_id"):
        report.error("execution binding task_id does not match task context")
    prepared_at = parse_timestamp(binding["prepared_at"], "execution binding prepared_at", report)
    expires_at = parse_timestamp(binding["expires_at"], "execution binding expires_at", report)
    if prepared_at and expires_at:
        if expires_at <= prepared_at:
            report.error("execution binding expires_at must be after prepared_at")
        lifetime = (expires_at - prepared_at).total_seconds()
        if lifetime > DELEGATION_BINDING_MAX_AGE_SECONDS:
            report.error(
                "execution binding lifetime exceeds {} seconds".format(
                    DELEGATION_BINDING_MAX_AGE_SECONDS
                )
            )
        if check_freshness:
            now = datetime.now(timezone.utc)
            if prepared_at.astimezone(timezone.utc) - now > timedelta(seconds=300):
                report.error("execution binding prepared_at is in the future")
            if now > expires_at.astimezone(timezone.utc):
                report.error("execution binding is expired")
    for key in ("session_id", "delegated_agent", "agent_type", "task_name", "action"):
        if not isinstance(binding[key], str) or not binding[key].strip():
            report.error("execution binding {} must be a non-empty string".format(key))
    if not re.fullmatch(r"[0-9a-f]{64}", str(binding["nonce"])):
        report.error("execution binding nonce must be a lowercase 256-bit hex value")
    review_round = binding["review_round"]
    if review_round is not None and (
        not isinstance(review_round, int)
        or isinstance(review_round, bool)
        or review_round < 1
    ):
        report.error("execution binding review_round must be null or a positive integer")
    purpose = binding["purpose"]
    if purpose is not None and (not isinstance(purpose, str) or not purpose.strip()):
        report.error("execution binding purpose must be null or a non-empty string")
    subject_digest = binding["subject_digest"]
    if subject_digest is not None and not re.fullmatch(r"[0-9a-f]{64}", str(subject_digest)):
        report.error("execution binding subject_digest must be null or a lowercase SHA-256 digest")
    routing = context.get("routing", {})
    agent = binding["delegated_agent"]
    policies = routing.get("delegation_policies", {})
    policy = policies.get(agent) if isinstance(policies, dict) else None
    if agent not in routing.get("delegated_agents", []) or not isinstance(policy, dict):
        report.error("execution binding delegated_agent is not authorized")
        policy = {}
    if binding["agent_type"] != policy.get("agent_type"):
        report.error("execution binding agent_type does not match delegation policy")
    if binding["action"] != policy.get("action"):
        report.error("execution binding action does not match delegation policy")
    prefix = policy.get("task_name_prefix")
    if (
        not isinstance(prefix, str)
        or not re.fullmatch(
            re.escape(prefix) + r"__r[1-9][0-9]*__[0-9a-f]{8,64}",
            str(binding["task_name"]),
        )
    ):
        report.error("execution binding task_name is outside its authorized namespace")
    elif binding["task_name"].rsplit("__", 1)[-1] != str(binding["nonce"])[:16]:
        report.error("execution binding task_name suffix must be derived from its nonce")
    hook_path = Path(str(binding["hook_path"])).expanduser()
    if not hook_path.is_absolute():
        report.error("execution binding hook_path must be absolute")
    if not re.fullmatch(r"[0-9a-f]{64}", str(binding["hook_hash"])):
        report.error("execution binding hook_hash must be a lowercase SHA-256 digest")
    elif check_paths and check_hook_source:
        if not hook_path.is_file():
            report.error("execution binding hook_path does not exist")
        elif file_sha256(hook_path) != binding["hook_hash"]:
            report.error("execution binding hook_hash does not match hook_path")
    playbook = context.get("playbook", {})
    receipt_value = binding["playbook_adapter_receipt"]
    receipt_hash = binding["playbook_adapter_receipt_sha256"]
    if playbook.get("managed"):
        receipt_path = Path(str(receipt_value)).expanduser()
        if not receipt_path.is_absolute():
            report.error("managed execution binding requires an absolute Playbook receipt")
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt_hash)):
            report.error("managed execution binding requires a Playbook receipt SHA-256")
        elif check_paths and receipt_path.is_file():
            try:
                receipt = validate_receipt(
                    receipt_path,
                    expected_sha256=receipt_hash,
                    expected_action=binding["action"],
                    max_age_seconds=(
                        PLAYBOOK_BINDING_MAX_AGE_SECONDS if check_freshness else None
                    ),
                    check_sources=check_receipt_sources,
                    check_live_status=check_live_status,
                )
            except (AdapterError, OSError) as exc:
                report.error("invalid execution binding Playbook receipt: {}".format(exc))
            else:
                facts = receipt.get("playbook", {})
                binding_kind = receipt.get("binding_kind", "worker")
                if binding_kind in {"status_review", "local_review"}:
                    artifact_digest = (
                        facts.get("local_review_subject_sha256")
                        if binding_kind == "local_review"
                        else facts.get("artifact_manifest_sha256")
                    )
                    if subject_digest is None:
                        report.error(
                            "review execution binding requires subject_digest"
                        )
                    elif subject_digest != artifact_digest:
                        report.error(
                            "review subject_digest does not match artifact manifest"
                        )
                if binding_kind == "local_review":
                    if purpose != "local_review":
                        report.error(
                            "local_review execution binding requires local_review purpose"
                        )
                    if review_round is None:
                        report.error(
                            "local_review execution binding requires review_round"
                        )
                if (
                    binding_kind == "worker"
                    and facts.get("recommended_executor") == "main_agent"
                ):
                    report.error(
                        "professional execution binding cannot use a "
                        "main-agent Playbook receipt"
                    )
                comparisons = {
                    "xiaoh_workspace_id": receipt.get("xiaoh_workspace_id"),
                    "task_workspace_id": facts.get("task_workspace_id"),
                    "change_id": facts.get("change_id"),
                    "member": facts.get("member"),
                    "member_worktree": facts.get("member_worktree"),
                    "workspace_root": facts.get("workspace_root"),
                    "allowed_scope": facts.get("allowed_scope"),
                }
                for key, expected in comparisons.items():
                    if playbook.get(key) != expected:
                        report.error(
                            "execution binding Playbook {} does not match task authority".format(
                                key
                            )
                        )
        elif check_paths:
            report.error("managed execution binding Playbook receipt does not exist")
    elif receipt_value is not None or receipt_hash is not None:
        report.error("standalone execution binding must not carry a Playbook receipt")
    sensitive = find_sensitive_keys(binding)
    if sensitive:
        report.error(
            "execution binding contains forbidden sensitive fields: {}".format(
                ", ".join(sensitive)
            )
        )


def validate_root_playbook_receipt(
    context,
    receipt_path,
    receipt_sha256,
    action,
    report,
    *,
    check_live_status=True,
):
    if context.get("schema_version") != "1.6":
        report.error("root Playbook receipt requires task context schema 1.6")
        return
    try:
        receipt = validate_receipt(
            Path(receipt_path),
            expected_sha256=receipt_sha256,
            expected_action=action,
            max_age_seconds=PLAYBOOK_BINDING_MAX_AGE_SECONDS,
            check_live_status=check_live_status,
        )
    except (AdapterError, OSError, TypeError) as exc:
        report.error("invalid root Playbook receipt: {}".format(exc))
        return
    facts = receipt.get("playbook", {})
    try:
        worker = worker_facts(Path(facts["worker_contract_source"]))
    except (AdapterError, OSError, KeyError) as exc:
        report.error("invalid root Playbook worker identity: {}".format(exc))
        return
    if not root_agent_owns_worker(worker):
        report.error("root Playbook receipt is not authorized for root-owned execution")
    playbook = context.get("playbook", {})
    comparisons = {
        "xiaoh_workspace_id": receipt.get("xiaoh_workspace_id"),
        "task_workspace_id": facts.get("task_workspace_id"),
        "change_id": facts.get("change_id"),
        "member": facts.get("member"),
        "member_worktree": facts.get("member_worktree"),
        "workspace_root": facts.get("workspace_root"),
        "allowed_scope": facts.get("allowed_scope"),
    }
    for key, expected in comparisons.items():
        if playbook.get(key) != expected:
            report.error("root Playbook receipt {} does not match task authority".format(key))


def validate_task_context(
    data,
    report,
    check_paths=True,
    check_freshness=True,
    check_playbook_freshness=True,
    check_playbook_live_status=True,
):
    required = [
        "schema_version", "task_id", "task_type", "risk_level", "goal", "behavior",
        "scope", "sources", "confirmed_decisions", "routing", "playbook", "acceptance",
        "verification", "output_contract", "stop_conditions", "freshness", "revision", "previous_context",
    ]
    if not require_keys(data, required, "task context", report):
        return
    if data["schema_version"] not in {"1.2", "1.3", "1.4", "1.5", "1.6"}:
        report.error("task context schema_version must be 1.2, 1.3, 1.4, 1.5, or 1.6")
    if data["schema_version"] in {"1.3", "1.4", "1.5", "1.6"}:
        validate_intent(data.get("intent"), data, report)
        domain = data.get("intent", {}).get("domain") if isinstance(data.get("intent"), dict) else None
        if domain == "business_project":
            validate_requirements(data.get("requirements"), report)
        elif data.get("requirements") is not None:
            report.error("requirements must be null outside business_project contexts")
    if data["schema_version"] in {"1.4", "1.5", "1.6"}:
        validate_interaction(data.get("interaction"), report)
    if data["schema_version"] in {"1.5", "1.6"}:
        domain = data.get("intent", {}).get("domain") if isinstance(data.get("intent"), dict) else None
        if domain == "business_project":
            delegated = data.get("routing", {}).get("delegated_agents", [])
            validate_memory_recall(
                data.get("memory_recall"),
                data,
                report,
                check_paths=check_paths,
                check_freshness=check_freshness,
                require_completed=bool(delegated),
            )
        elif data.get("memory_recall") is not None:
            report.error("memory_recall must be null outside business_project contexts")
    revision = data["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        report.error("revision must be a positive integer")
    previous = data["previous_context"]
    if revision == 1 and previous is not None:
        report.error("revision 1 must not declare previous_context")
    elif isinstance(revision, int) and revision > 1:
        if require_keys(previous, ["path", "hash"], "previous_context", report):
            previous_path = Path(str(previous["path"]))
            if not previous_path.is_absolute():
                report.error("previous_context.path must be absolute")
            elif check_paths and not previous_path.is_file():
                report.error("previous_context.path does not exist: {}".format(previous_path))
            if not re.fullmatch(r"[0-9a-f]{64}", str(previous["hash"])):
                report.error("previous_context.hash must be a lowercase SHA-256 digest")
            elif check_paths and previous_path.is_file():
                previous_bytes = previous_path.read_bytes()
                if hashlib.sha256(previous_bytes).hexdigest() != previous["hash"]:
                    report.error("previous_context.hash does not match previous_context.path")
                else:
                    try:
                        previous_data = json.loads(previous_bytes.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError):
                        report.error("previous_context.path is not valid UTF-8 JSON")
                    else:
                        if previous_data.get("task_id") != data.get("task_id"):
                            report.error("previous_context task_id does not match")
                        if previous_data.get("revision") != revision - 1:
                            report.error("previous_context revision must be current revision minus one")
        elif previous is None:
            report.error("revision greater than 1 requires previous_context")
    if not isinstance(data["task_type"], str) or data["task_type"] not in ALLOWED_TASK_TYPES:
        report.error("task_type must be one of {}".format(sorted(ALLOWED_TASK_TYPES)))
    if not isinstance(data["risk_level"], str) or data["risk_level"] not in ALLOWED_RISK_LEVELS:
        report.error("risk_level must be one of {}".format(sorted(ALLOWED_RISK_LEVELS)))
    for key in ("task_id", "goal"):
        if not isinstance(data[key], str) or not data[key].strip():
            report.error("{} must be a non-empty string".format(key))
    if require_keys(data["behavior"], ["current", "target"], "behavior", report):
        for key in ("current", "target"):
            if not isinstance(data["behavior"][key], str) or not data["behavior"][key].strip():
                report.error("behavior.{} must be a non-empty string".format(key))
    allowed_paths = []
    if require_keys(data["scope"], ["workspace", "repositories", "allowed_paths", "prohibited_actions"], "scope", report):
        workspace = data["scope"]["workspace"]
        if not isinstance(workspace, str) or not Path(workspace).is_absolute():
            report.error("scope.workspace must be an absolute path")
        elif check_paths and not Path(workspace).exists():
            report.error("scope.workspace does not exist: {}".format(workspace))
        repositories = validate_string_list(data["scope"]["repositories"], "scope.repositories", report)
        allowed_paths = validate_string_list(data["scope"]["allowed_paths"], "scope.allowed_paths", report, non_empty=True)
        validate_string_list(data["scope"]["prohibited_actions"], "scope.prohibited_actions", report, non_empty=True)
        for label, paths in (("scope.repositories", repositories), ("scope.allowed_paths", allowed_paths)):
            for path in paths:
                if not Path(path).is_absolute():
                    report.error("{} contains non-absolute path: {}".format(label, path))
                elif check_paths and not Path(path).exists():
                    report.error("{} path does not exist: {}".format(label, path))
    routing_keys = [
        "root_agent", "delegated_agents", "selection_reason",
        "independent_review_required", "independent_review_agents",
    ]
    routing_keys.append(
        "delegation_policies"
        if data.get("schema_version") == "1.6"
        else "delegation_names"
    )
    if require_keys(data["routing"], routing_keys, "routing", report):
        root_agent = data["routing"]["root_agent"]
        selected = data["routing"]["delegated_agents"]
        reviewers = data["routing"]["independent_review_agents"]
        if root_agent != ROOT_AGENT:
            report.error("routing.root_agent must be {}".format(ROOT_AGENT))
        selected = validate_string_list(selected, "routing.delegated_agents", report)
        if data.get("schema_version") not in {"1.5", "1.6"} and selected:
            report.error("formal delegation requires schema 1.5 or 1.6")
        if data.get("schema_version") == "1.6":
            policies = data["routing"].get("delegation_policies")
            if not isinstance(policies, dict):
                report.error("routing.delegation_policies must be an object")
                policies = {}
            if set(policies) != set(selected):
                report.error("routing.delegation_policies keys must equal delegated_agents")
            prefixes = []
            for agent, policy in policies.items():
                label = "routing.delegation_policies.{}".format(agent)
                if not require_keys(
                    policy,
                    ["agent_type", "action", "task_name_prefix"],
                    label,
                    report,
                ):
                    continue
                if policy["agent_type"] != agent:
                    report.error("{}.agent_type must equal its registered role".format(label))
                if policy["action"] not in ALLOWED_DELEGATED_ACTIONS:
                    report.error("{}.action is unsupported".format(label))
                prefix = policy["task_name_prefix"]
                if not isinstance(prefix, str) or not re.fullmatch(r"[a-z0-9_]+", prefix):
                    report.error("{}.task_name_prefix must match [a-z0-9_]+".format(label))
                else:
                    prefixes.append(prefix)
                    if normalize_agent_name(prefix) in RESERVED_AGENT_ALIASES:
                        report.error("{}.task_name_prefix cannot use the reserved root identity".format(label))
            if len(prefixes) != len(set(prefixes)):
                report.error("routing.delegation_policies task_name_prefix values must be unique")
            if "delegation_names" in data["routing"]:
                report.error("schema 1.6 routing must not declare concrete delegation_names")
            if "delegated_actions" in data["routing"]:
                report.error("schema 1.6 routing must not declare delegated_actions outside delegation_policies")
        else:
            delegation_names = data["routing"].get("delegation_names")
            if not isinstance(delegation_names, dict):
                report.error("routing.delegation_names must be an object")
                delegation_names = {}
            if set(delegation_names) != set(selected):
                report.error("routing.delegation_names keys must equal delegated_agents")
            names = list(delegation_names.values())
            valid_names = [name for name in names if isinstance(name, str)]
            if len(valid_names) != len(names) or any(not re.fullmatch(r"[a-z0-9_]+", name) for name in valid_names):
                report.error("routing.delegation_names values must match [a-z0-9_]+")
            if len(valid_names) != len(set(valid_names)):
                report.error("routing.delegation_names values must be unique")
            if any(normalize_agent_name(name) in RESERVED_AGENT_ALIASES for name in valid_names):
                report.error("routing.delegation_names cannot use the reserved root identity")
        if ROOT_AGENT in selected:
            report.error("routing.delegated_agents cannot contain reserved root agent {}".format(ROOT_AGENT))
        reviewers = validate_string_list(reviewers, "routing.independent_review_agents", report)
        unknown = {name for name in selected + reviewers if not (AGENTS_DIR / "{}.toml".format(name)).exists()}
        if unknown:
            report.error("routing references unregistered agents: {}".format(", ".join(sorted(unknown))))
        if not set(reviewers) <= set(selected):
            report.error("routing independent reviewers must be selected agents")
        if set(reviewers) & ({ROOT_AGENT} | IMPLEMENTATION_AGENTS):
            report.error("routing independent reviewers cannot be the coordinator or implementers")
        required_review = (
            data["task_type"] == "implementation"
            or data["risk_level"] in {"high", "critical"}
        )
        if required_review and not data["routing"]["independent_review_required"]:
            report.error(
                "implementation and high-risk task contexts must require independent review"
            )
        if data["routing"]["independent_review_required"] and not reviewers:
            report.error("independent review requires at least one reviewer")
        if data["task_type"] == "implementation" and len(set(reviewers)) < 2:
            report.error(
                "implementation task context requires at least two independent review roles"
            )
    playbook_keys = [
        "managed", "workspace_id", "xiaoh_workspace_id", "task_workspace_id",
        "change_id", "member", "member_worktree", "workspace_root",
        "allowed_scope",
    ]
    if data.get("schema_version") != "1.6":
        playbook_keys.extend(["stage", "worker_contract_source"])
    require_keys(data["playbook"], playbook_keys, "playbook", report)
    if data.get("schema_version") == "1.6":
        playbook = data["playbook"]
        volatile_fields = {
            "binding_kind", "stage", "worker_contract_source", "adapter_receipt",
            "adapter_receipt_sha256", "review_artifacts",
        }
        declared_volatile = volatile_fields & set(playbook)
        if declared_volatile:
            report.error(
                "schema 1.6 playbook must not contain runtime binding fields: {}".format(
                    ", ".join(sorted(declared_volatile))
                )
            )
        if playbook.get("managed"):
            for key in (
                "xiaoh_workspace_id", "task_workspace_id", "change_id", "member",
                "member_worktree", "workspace_root", "allowed_scope",
            ):
                if playbook.get(key) in (None, "", []):
                    report.error("managed schema 1.6 context requires playbook.{}".format(key))
            if playbook.get("workspace_id") != playbook.get("task_workspace_id"):
                report.error("playbook.workspace_id legacy alias must equal playbook.task_workspace_id")
            task_allowed_paths = data.get("scope", {}).get("allowed_paths", [])
            member_worktree = playbook.get("member_worktree")
            if (
                isinstance(member_worktree, str)
                and member_worktree
                and not path_is_covered(member_worktree, task_allowed_paths)
            ):
                report.error(
                    "playbook.member_worktree is outside task scope.allowed_paths"
                )
            allowed_scope = playbook.get("allowed_scope")
            if not isinstance(allowed_scope, list) or not allowed_scope:
                report.error(
                    "managed schema 1.6 context requires non-empty playbook.allowed_scope"
                )
            else:
                for index, path_value in enumerate(allowed_scope):
                    if not isinstance(path_value, str) or not Path(
                        path_value
                    ).expanduser().is_absolute():
                        report.error(
                            "playbook.allowed_scope[{}] must be an absolute path".format(
                                index
                            )
                        )
                    elif not path_is_covered(path_value, task_allowed_paths):
                        report.error(
                            "playbook.allowed_scope[{}] is outside task scope.allowed_paths".format(
                                index
                            )
                        )
                    elif (
                        isinstance(member_worktree, str)
                        and member_worktree
                        and not path_is_covered(path_value, [member_worktree])
                    ):
                        report.error(
                            "playbook.allowed_scope[{}] is outside playbook.member_worktree".format(
                                index
                            )
                        )
    else:
        validate_playbook_binding(
            data,
            report,
            check_paths=check_paths,
            require_binding=False,
            check_freshness=check_playbook_freshness,
            check_live_status=check_playbook_live_status,
        )
    if require_keys(data["output_contract"], ["format", "required_fields"], "output_contract", report):
        if not isinstance(data["output_contract"]["format"], str) or not data["output_contract"]["format"].strip():
            report.error("output_contract.format must be a non-empty string")
        validate_string_list(data["output_contract"]["required_fields"], "output_contract.required_fields", report, non_empty=True)
    if require_keys(data["freshness"], ["checked_at", "checked_by"], "freshness", report):
        checked_at = parse_timestamp(data["freshness"]["checked_at"], "freshness.checked_at", report)
        if data["freshness"]["checked_by"] != ROOT_AGENT:
            report.error("freshness.checked_by must be {}".format(ROOT_AGENT))
        if check_freshness and checked_at and data.get("task_id") != "example-task":
            age = datetime.now(timezone.utc) - checked_at.astimezone(timezone.utc)
            if age.total_seconds() < -300 or age.total_seconds() > MAX_CONTEXT_AGE_HOURS * 3600:
                report.error("task context freshness exceeds {} hours".format(MAX_CONTEXT_AGE_HOURS))
    for key in ("confirmed_decisions", "acceptance", "stop_conditions"):
        validate_string_list(data[key], key, report, non_empty=True)
    if not isinstance(data["verification"], list) or not data["verification"]:
        report.error("verification must be a non-empty list")
    else:
        for index, item in enumerate(data["verification"]):
            label = "verification[{}]".format(index)
            if require_keys(item, ["command", "expected"], label, report):
                for key in ("command", "expected"):
                    if not isinstance(item[key], str) or not item[key].strip():
                        report.error("{}.{} must be a non-empty string".format(label, key))
    if not isinstance(data["sources"], list) or not data["sources"]:
        report.error("sources must be a non-empty list")
    if isinstance(data["sources"], list):
        for index, source in enumerate(data["sources"]):
            label = "sources[{}]".format(index)
            if not require_keys(source, ["path", "purpose", "required"], label, report):
                continue
            if not isinstance(source["path"], str) or not Path(source["path"]).is_absolute():
                report.error("{}.path must be an absolute path".format(label))
                continue
            if not isinstance(source["purpose"], str) or not source["purpose"].strip():
                report.error("{}.purpose must be a non-empty string".format(label))
            if not isinstance(source["required"], bool):
                report.error("{}.required must be a boolean".format(label))
                continue
            if allowed_paths and not path_is_covered(source["path"], allowed_paths):
                report.error("{}.path is outside scope.allowed_paths: {}".format(label, source["path"]))
            if check_paths and source["required"] and not Path(source["path"]).exists():
                report.error("{} required path does not exist: {}".format(label, source["path"]))
    if (
        data.get("schema_version") != "1.6"
        and isinstance(data["playbook"], dict)
        and data["playbook"].get("managed")
    ):
        binding_kind = data["playbook"].get("binding_kind") or "worker"
        if binding_kind not in {"worker", "status_review"}:
            report.error("managed Playbook context has invalid playbook.binding_kind")
        for key in ("workspace_id", "stage"):
            if not data["playbook"].get(key):
                report.error("managed Playbook context requires playbook.{}".format(key))
        if (
            binding_kind == "worker"
            and not data["playbook"].get("worker_contract_source")
        ):
            report.error(
                "worker Playbook context requires playbook.worker_contract_source"
            )
        if (
            binding_kind == "status_review"
            and data["playbook"].get("worker_contract_source")
        ):
            report.error(
                "status_review Playbook context must not declare worker_contract_source"
            )
    sensitive = find_sensitive_keys(data)
    if sensitive:
        report.error("task context contains forbidden sensitive fields: {}".format(", ".join(sensitive)))


def validate_local_review_evidence(
    entries,
    reviewers,
    allowed_paths,
    label,
    report,
    check_paths,
    *,
    context,
    context_path,
    round_number,
    subject_value,
    seen_evidence,
    seen_run_ids,
    seen_run_digests,
    seen_agent_ids,
    seen_transcript_hashes,
    seen_proof_hashes,
    seen_binding_hashes,
    seen_task_names,
):
    outcomes = []
    if not isinstance(entries, list) or not entries:
        report.error("{}.evidence must be a non-empty list".format(label))
        return outcomes
    evidence_reviewers = []
    for index, entry in enumerate(entries):
        entry_label = "{}.evidence[{}]".format(label, index)
        if not require_keys(entry, ["reviewer", "path", "sha256"], entry_label, report):
            continue
        reviewer = entry["reviewer"]
        path_value = entry["path"]
        digest = entry["sha256"]
        if reviewer not in reviewers:
            report.error("{}.reviewer must be listed in round reviewers".format(entry_label))
        else:
            evidence_reviewers.append(reviewer)
        path = Path(str(path_value)).expanduser()
        if not path.is_absolute():
            report.error("{}.path must be absolute".format(entry_label))
        elif allowed_paths and not path_is_covered(str(path), allowed_paths):
            report.error("{}.path is outside scope.allowed_paths".format(entry_label))
        elif check_paths and not path.is_file():
            report.error("{}.path does not exist: {}".format(entry_label, path))
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
            report.error("{}.sha256 must be a lowercase SHA-256 digest".format(entry_label))
        elif check_paths and path.is_file():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                report.error("{}.sha256 does not match evidence file".format(entry_label))
        evidence_identity = (str(path.resolve(strict=False)), str(digest))
        if evidence_identity in seen_evidence:
            report.error("{}.path and sha256 cannot be reused across review rounds".format(entry_label))
        else:
            seen_evidence.add(evidence_identity)
        if not check_paths or not path.is_file():
            continue
        evidence_report = load_json(path, report)
        if not isinstance(evidence_report, dict):
            continue
        evidence_required = [
            "schema_version", "task_id", "context_hash", "reviewer", "round",
            "subject_value", "verdict", "blocking_findings", "attested_message",
            "run_record",
        ]
        if context.get("schema_version") == "1.6":
            evidence_required.append("execution_binding_hash")
        if not require_keys(
            evidence_report, evidence_required, "{} report".format(entry_label), report
        ):
            continue
        if evidence_report["schema_version"] != LOCAL_REVIEW_EVIDENCE_SCHEMA:
            report.error(
                "{} report schema_version must be {}".format(
                    entry_label, LOCAL_REVIEW_EVIDENCE_SCHEMA
                )
            )
        expected_context_hash = (
            task_authority_hash(context)
            if context.get("schema_version") == "1.6"
            else hashlib.sha256(context_path.read_bytes()).hexdigest()
        )
        expected_values = {
            "task_id": context.get("task_id"),
            "context_hash": expected_context_hash,
            "reviewer": reviewer,
            "round": round_number,
            "subject_value": subject_value,
        }
        for key, expected in expected_values.items():
            if evidence_report.get(key) != expected:
                report.error(
                    "{} report {} does not match its review round".format(
                        entry_label, key
                    )
                )
        evidence_verdict = evidence_report.get("verdict")
        evidence_findings = evidence_report.get("blocking_findings")
        if evidence_verdict not in ALLOWED_LOCAL_REVIEW_VERDICTS:
            report.error(
                "{} report verdict must be one of {}".format(
                    entry_label,
                    sorted(ALLOWED_LOCAL_REVIEW_VERDICTS),
                )
            )
        if (
            not isinstance(evidence_findings, int)
            or isinstance(evidence_findings, bool)
            or evidence_findings < 0
        ):
            report.error(
                "{} report blocking_findings must be a non-negative integer".format(
                    entry_label
                )
            )
        elif evidence_verdict == "passed" and evidence_findings != 0:
            report.error(
                "{} passed report requires zero blocking findings".format(
                    entry_label
                )
            )
        elif evidence_verdict == "changes_requested" and evidence_findings == 0:
            report.error(
                "{} changes_requested report requires at least one blocking finding".format(
                    entry_label
                )
            )
        if (
            evidence_verdict in ALLOWED_LOCAL_REVIEW_VERDICTS
            and isinstance(evidence_findings, int)
            and not isinstance(evidence_findings, bool)
            and evidence_findings >= 0
        ):
            outcomes.append(
                {
                    "reviewer": reviewer,
                    "verdict": evidence_verdict,
                    "blocking_findings": evidence_findings,
                }
            )
        expected_claim = {
            "schema_version": "xiaoh-local-review-claim/v1",
            **expected_values,
            "verdict": evidence_verdict,
            "blocking_findings": evidence_findings,
        }
        attested_message = evidence_report.get("attested_message")
        if not isinstance(attested_message, str) or not attested_message.strip():
            report.error("{} report attested_message must be non-empty".format(entry_label))
            attested_message = ""
        claim_matches = re.findall(
            r"(?m)^xiaoh-local-review-claim: (\{.*\})$",
            attested_message,
        )
        if len(claim_matches) != 1:
            report.error(
                "{} report attested_message must contain exactly one local review claim".format(
                    entry_label
                )
            )
            attested_claim = {}
        else:
            try:
                attested_claim = json.loads(claim_matches[0])
            except json.JSONDecodeError:
                report.error("{} report attested claim must be valid JSON".format(entry_label))
                attested_claim = {}
        if attested_claim != expected_claim:
            report.error("{} report attested claim does not match its review round".format(entry_label))
        canonical_claim = json.dumps(
            expected_claim, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        expected_claim_hash = hashlib.sha256(canonical_claim).hexdigest()
        run_binding = evidence_report["run_record"]
        if not require_keys(
            run_binding, ["path", "sha256"], "{} report run_record".format(entry_label), report
        ):
            continue
        run_path = Path(str(run_binding["path"])).expanduser()
        run_digest = run_binding["sha256"]
        if not run_path.is_absolute():
            report.error("{} report run_record.path must be absolute".format(entry_label))
            continue
        if allowed_paths and not path_is_covered(str(run_path), allowed_paths):
            report.error("{} report run_record.path is outside scope.allowed_paths".format(entry_label))
        if not re.fullmatch(r"[0-9a-f]{64}", str(run_digest)):
            report.error(
                "{} report run_record.sha256 must be a lowercase SHA-256 digest".format(
                    entry_label
                )
            )
            continue
        if not run_path.is_file():
            report.error("{} report run_record.path does not exist".format(entry_label))
            continue
        if hashlib.sha256(run_path.read_bytes()).hexdigest() != run_digest:
            report.error("{} report run_record.sha256 does not match".format(entry_label))
            continue
        run_record = load_json(run_path, report)
        if not isinstance(run_record, dict):
            continue
        run_report = Report()
        validate_run_record(run_record, run_report, check_paths=True)
        for error in run_report.errors:
            report.error("{} authenticated run record: {}".format(entry_label, error))
        if run_record.get("task_id") != context.get("task_id"):
            report.error("{} run record task_id does not match".format(entry_label))
        if run_record.get("context_hash") != expected_context_hash:
            report.error("{} run record context_hash does not match".format(entry_label))
        if run_record.get("agent") != reviewer:
            report.error("{} run record agent does not match reviewer".format(entry_label))
        if run_record.get("status") != "completed":
            report.error("{} run record must be completed".format(entry_label))
        if run_record.get("schema_version") != "1.2":
            report.error("{} run record must use schema 1.2".format(entry_label))
        run_id = run_record.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            report.error("{} run record must have a stable run_id".format(entry_label))
        elif run_id in seen_run_ids:
            report.error("{} run record cannot be reused across review rounds".format(entry_label))
        else:
            seen_run_ids.add(run_id)
        if run_digest in seen_run_digests:
            report.error("{} run record content cannot be reused across review rounds".format(entry_label))
        else:
            seen_run_digests.add(run_digest)
        runtime_evidence = run_record.get("runtime_evidence", {})
        runtime_identities = (
            (
                "agent_id",
                runtime_evidence.get("agent_id"),
                seen_agent_ids,
            ),
            (
                "transcript_hash",
                runtime_evidence.get("transcript_hash"),
                seen_transcript_hashes,
            ),
            (
                "delegation_proof_hash",
                runtime_evidence.get("delegation_proof_hash"),
                seen_proof_hashes,
            ),
        )
        for identity_name, identity_value, seen_values in runtime_identities:
            if not isinstance(identity_value, str) or not identity_value.strip():
                report.error(
                    "{} run record lacks runtime_evidence.{}".format(
                        entry_label, identity_name
                    )
                )
            elif identity_value in seen_values:
                report.error(
                    "{} runtime_evidence.{} cannot be reused across review rounds".format(
                        entry_label, identity_name
                    )
                )
            else:
                seen_values.add(identity_value)
        proof_path = Path(str(runtime_evidence.get("delegation_proof_path", "")))
        proof = load_json(proof_path, report) if proof_path.is_file() else None
        required_proof_schema = (
            "1.3" if context.get("schema_version") == "1.6" else "1.2"
        )
        if not isinstance(proof, dict) or proof.get("schema_version") != required_proof_schema:
            report.error(
                "{} local review requires an attested schema {} proof".format(
                    entry_label, required_proof_schema
                )
            )
        elif hashlib.sha256(attested_message.encode("utf-8")).hexdigest() != proof.get(
            "last_message_hash"
        ):
            report.error(
                "{} attested_message does not match delegation proof".format(entry_label)
            )
        if isinstance(proof, dict) and required_proof_schema == "1.3":
            binding_hash = proof.get("execution_binding_hash")
            task_name = proof.get("task_name")
            if evidence_report.get("execution_binding_hash") != binding_hash:
                report.error(
                    "{} execution_binding_hash does not match delegation proof".format(
                        entry_label
                    )
                )
            if binding_hash in seen_binding_hashes:
                report.error(
                    "{} execution binding cannot be reused across review rounds".format(
                        entry_label
                    )
                )
            elif isinstance(binding_hash, str) and binding_hash:
                seen_binding_hashes.add(binding_hash)
            if task_name in seen_task_names:
                report.error(
                    "{} concrete task_name cannot be reused across review rounds".format(
                        entry_label
                    )
                )
            elif isinstance(task_name, str) and task_name:
                seen_task_names.add(task_name)
            if proof.get("review_round") != round_number:
                report.error(
                    "{} proof review_round does not match review round".format(entry_label)
                )
            if proof.get("purpose") != "local_review":
                report.error(
                    "{} proof purpose must be local_review".format(entry_label)
                )
            if proof.get("subject_digest") != subject_value:
                report.error(
                    "{} proof subject_digest does not match review subject".format(
                        entry_label
                    )
                )
        review_output = run_record.get("outputs", {}).get("local_review")
        if not require_keys(
            review_output,
            [
                "round", "subject_value", "verdict", "blocking_findings",
                "claim_hash",
            ],
            "{} run record outputs.local_review".format(entry_label),
            report,
        ):
            review_output = {}
        output_expected = {
            "round": round_number,
            "subject_value": subject_value,
            "verdict": evidence_verdict,
            "blocking_findings": evidence_findings,
            "claim_hash": expected_claim_hash,
        }
        for key, expected in output_expected.items():
            if review_output.get(key) != expected:
                report.error(
                    "{} run record local_review.{} does not match".format(
                        entry_label, key
                    )
                )
        gates = run_record.get("gates")
        verification = run_record.get("verification")
        if (
            not isinstance(gates, list)
            or not gates
            or any(item.get("status") != "passed" for item in gates if isinstance(item, dict))
            or any(not isinstance(item, dict) for item in gates)
        ):
            report.error("{} run record gates must all pass".format(entry_label))
        if not any(
            isinstance(item, dict)
            and item.get("name") == "independent_review"
            and item.get("status") == "passed"
            for item in gates or []
        ):
            report.error("{} run record lacks a passed independent_review gate".format(entry_label))
        if (
            not isinstance(verification, list)
            or not verification
            or any(
                item.get("status") != "passed"
                for item in verification
                if isinstance(item, dict)
            )
            or any(not isinstance(item, dict) for item in verification)
        ):
            report.error("{} run record verification must all pass".format(entry_label))
        accepted = run_record.get("metrics", {}).get("result_accepted")
        if evidence_verdict == "passed" and accepted is not True:
            report.error("{} passed review requires an accepted run record".format(entry_label))
        if evidence_verdict == "changes_requested" and accepted is not False:
            report.error(
                "{} changes_requested review requires a non-accepted run record".format(
                    entry_label
                )
            )
    missing = set(reviewers) - set(evidence_reviewers)
    if missing:
        report.error(
            "{}.evidence is missing reviewer reports for: {}".format(
                label, ", ".join(sorted(missing))
            )
        )
    duplicates = {
        reviewer
        for reviewer, count in Counter(evidence_reviewers).items()
        if count > 1
    }
    if duplicates:
        report.error(
            "{}.evidence contains duplicate reviewer reports for: {}".format(
                label, ", ".join(sorted(duplicates))
            )
        )
    return outcomes


def validate_local_review_manifest(
    manifest,
    context,
    context_path,
    report,
    check_paths=True,
):
    required = [
        "schema_version", "task_id", "task_context", "mode", "subject",
        "implementers", "rounds", "final_status", "completed_at",
    ]
    if not require_keys(manifest, required, "local review manifest", report):
        return
    if manifest["schema_version"] != LOCAL_REVIEW_SCHEMA:
        report.error("local review manifest schema_version must be {}".format(LOCAL_REVIEW_SCHEMA))
    if manifest["task_id"] != context.get("task_id"):
        report.error("local review manifest task_id does not match task context")
    if context.get("task_type") != "implementation":
        report.error("local review manifest requires an implementation task context")
    context_binding = manifest["task_context"]
    context_hash_key = (
        "authority_hash"
        if context.get("schema_version") == "1.6"
        else "sha256"
    )
    if require_keys(
        context_binding,
        ["path", context_hash_key],
        "local review task_context",
        report,
    ):
        expected_path = context_path.resolve(strict=False)
        bound_path = Path(str(context_binding["path"])).expanduser()
        if not bound_path.is_absolute() or bound_path.resolve(strict=False) != expected_path:
            report.error("local review task_context.path must bind the current context")
        digest = context_binding[context_hash_key]
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
            report.error(
                "local review task_context.{} must be a lowercase SHA-256 digest".format(
                    context_hash_key
                )
            )
        elif check_paths and expected_path.is_file():
            expected_digest = (
                task_authority_hash(context)
                if context.get("schema_version") == "1.6"
                else hashlib.sha256(expected_path.read_bytes()).hexdigest()
            )
            if expected_digest != digest:
                report.error(
                    "local review task_context.{} does not match current context".format(
                        context_hash_key
                    )
                )
    expected_mode = (
        "playbook_managed"
        if context.get("playbook", {}).get("managed") is True
        else "standalone"
    )
    if manifest["mode"] not in ALLOWED_LOCAL_REVIEW_MODES:
        report.error(
            "local review mode must be one of {}".format(
                sorted(ALLOWED_LOCAL_REVIEW_MODES)
            )
        )
    elif manifest["mode"] != expected_mode:
        report.error("local review mode does not match playbook.managed")
    selected_reviewers = set(
        context.get("routing", {}).get("independent_review_agents", [])
    )
    implementers = validate_string_list(
        manifest["implementers"], "local review implementers", report, non_empty=True
    )
    allowed_implementers = (
        set(context.get("routing", {}).get("delegated_agents", [])) | {ROOT_AGENT}
    )
    unknown_implementers = set(implementers) - allowed_implementers
    if unknown_implementers:
        report.error(
            "local review implementers were not selected by task context: {}".format(
                ", ".join(sorted(unknown_implementers))
            )
        )
    allowed_paths = context.get("scope", {}).get("allowed_paths", [])
    subject = manifest["subject"]
    subject_value = ""
    subject_pattern = r"(?:[0-9a-f]{40}|[0-9a-f]{64})"
    if require_keys(
        subject,
        ["kind", "repository", "artifact_path", "value"],
        "local review subject",
        report,
    ):
        kind = subject["kind"]
        subject_value = str(subject["value"])
        if kind not in ALLOWED_LOCAL_REVIEW_SUBJECTS:
            report.error(
                "local review subject.kind must be one of {}".format(
                    sorted(ALLOWED_LOCAL_REVIEW_SUBJECTS)
                )
            )
        if kind == "artifact_digest":
            subject_pattern = r"[0-9a-f]{64}"
        if not re.fullmatch(subject_pattern, subject_value):
            report.error(
                "local review subject.value must be a valid lowercase immutable digest"
            )
        repository_value = subject["repository"]
        artifact_path_value = subject["artifact_path"]
        if kind == "git_commit":
            if artifact_path_value is not None:
                report.error("git review subject.artifact_path must be null")
            repository = Path(str(repository_value)).expanduser()
            repositories = {
                str(Path(value).expanduser().resolve(strict=False))
                for value in context.get("scope", {}).get("repositories", [])
            }
            if len(repositories) != 1:
                report.error(
                    "git review subject requires exactly one scoped repository; "
                    "use an artifact_digest manifest for multi-repository work"
                )
            if (
                not repository.is_absolute()
                or str(repository.resolve(strict=False)) not in repositories
            ):
                report.error("git review subject.repository must be a scoped repository")
            elif check_paths:
                try:
                    completed = subprocess.run(
                        ["git", "-C", str(repository), "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    worktree = subprocess.run(
                        ["git", "-C", str(repository), "status", "--porcelain"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except OSError as exc:
                    report.error(
                        "cannot inspect Git subject for local review: {}".format(exc)
                    )
                else:
                    if completed.returncode != 0:
                        report.error("cannot resolve current Git HEAD for local review subject")
                    elif completed.stdout.strip() != subject_value:
                        report.error("local review subject is stale because Git HEAD changed")
                    if worktree.returncode != 0:
                        report.error("cannot inspect current Git worktree for local review subject")
                    elif worktree.stdout.strip():
                        report.error(
                            "git review subject requires a clean worktree with no unreviewed changes"
                        )
        elif repository_value is not None:
            report.error("artifact_digest review subject.repository must be null")
        if kind == "artifact_digest":
            artifact_path = Path(str(artifact_path_value)).expanduser()
            if not artifact_path.is_absolute():
                report.error("artifact_digest subject.artifact_path must be absolute")
            elif allowed_paths and not path_is_covered(str(artifact_path), allowed_paths):
                report.error("artifact_digest subject.artifact_path is outside scope.allowed_paths")
            elif check_paths and not artifact_path.is_file():
                report.error("artifact_digest subject.artifact_path does not exist")
            elif check_paths and hashlib.sha256(artifact_path.read_bytes()).hexdigest() != subject_value:
                report.error(
                    "artifact_digest subject.value does not match artifact_path content"
                )
            elif (
                check_paths
                and artifact_path.is_file()
                and len(context.get("scope", {}).get("repositories", [])) > 1
            ):
                repository_manifest = load_json(artifact_path, report)
                if not isinstance(repository_manifest, dict):
                    report.error(
                        "multi-repository artifact must be a JSON object"
                    )
                else:
                    if not require_keys(
                        repository_manifest,
                        ["schema_version", "repositories"],
                        "repository-set artifact",
                        report,
                    ):
                        repository_manifest = {}
                    if (
                        repository_manifest.get("schema_version")
                        != LOCAL_REVIEW_REPOSITORY_SET_SCHEMA
                    ):
                        report.error(
                            "multi-repository artifact must use {}".format(
                                LOCAL_REVIEW_REPOSITORY_SET_SCHEMA
                            )
                        )
                    entries = repository_manifest.get("repositories")
                    if not isinstance(entries, list) or not entries:
                        report.error(
                            "repository-set artifact.repositories must be a non-empty list"
                        )
                    else:
                        declared = {}
                        for index, entry in enumerate(entries):
                            entry_label = "repository-set artifact.repositories[{}]".format(index)
                            if not require_keys(
                                entry, ["path", "commit"], entry_label, report
                            ):
                                continue
                            repo_path = Path(str(entry["path"])).expanduser()
                            commit = str(entry["commit"])
                            resolved = str(repo_path.resolve(strict=False))
                            if not repo_path.is_absolute():
                                report.error("{}.path must be absolute".format(entry_label))
                            if resolved in declared:
                                report.error("repository-set artifact contains duplicate repository")
                            declared[resolved] = commit
                            if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
                                report.error(
                                    "{}.commit must be a Git object ID".format(entry_label)
                                )
                                continue
                            try:
                                head = subprocess.run(
                                    ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                                    capture_output=True,
                                    text=True,
                                    check=False,
                                )
                                dirty = subprocess.run(
                                    ["git", "-C", str(repo_path), "status", "--porcelain"],
                                    capture_output=True,
                                    text=True,
                                    check=False,
                                )
                            except OSError as exc:
                                report.error(
                                    "{} cannot inspect repository: {}".format(
                                        entry_label, exc
                                    )
                                )
                                continue
                            if head.returncode != 0 or head.stdout.strip() != commit:
                                report.error(
                                    "{} commit does not match current HEAD".format(entry_label)
                                )
                            if dirty.returncode != 0 or dirty.stdout.strip():
                                report.error(
                                    "{} repository must have a clean worktree".format(entry_label)
                                )
                        expected_repositories = {
                            str(Path(value).expanduser().resolve(strict=False))
                            for value in context.get("scope", {}).get("repositories", [])
                        }
                        if set(declared) != expected_repositories:
                            report.error(
                                "repository-set artifact must cover every scoped repository exactly once"
                            )
    rounds = manifest["rounds"]
    if not isinstance(rounds, list) or len(rounds) < 2:
        report.error("local review requires at least two review rounds")
        rounds = []
    final_round_reviewers = set()
    seen_evidence = set()
    seen_run_ids = set()
    seen_run_digests = set()
    seen_agent_ids = set()
    seen_transcript_hashes = set()
    seen_proof_hashes = set()
    seen_binding_hashes = set()
    seen_task_names = set()
    for index, item in enumerate(rounds):
        label = "local review rounds[{}]".format(index)
        if not require_keys(
            item,
            [
                "number", "subject_value", "reviewers", "verdict",
                "blocking_findings", "evidence",
            ],
            label,
            report,
        ):
            continue
        if item["number"] != index + 1:
            report.error("{}.number must be sequential starting at 1".format(label))
        if not re.fullmatch(
            subject_pattern, str(item["subject_value"])
        ):
            report.error("{}.subject_value must be a valid immutable digest".format(label))
        reviewers = set(
            validate_string_list(
                item["reviewers"], "{}.reviewers".format(label), report, non_empty=True
            )
        )
        if len(reviewers) < 2:
            report.error("{} requires at least two distinct reviewers".format(label))
        if (
            subject.get("kind") == "git_commit"
            and not {"code_quality_reviewer", "test_integration_verifier"} <= reviewers
        ):
            report.error(
                "{} Git review requires code_quality_reviewer and test_integration_verifier".format(
                    label
                )
            )
        if not reviewers <= selected_reviewers:
            report.error("{} contains reviewers outside task context routing".format(label))
        if reviewers & set(implementers):
            report.error("{} reviewers must be independent from implementers".format(label))
        if reviewers & ({ROOT_AGENT} | IMPLEMENTATION_AGENTS):
            report.error("{} contains a coordinator or implementation role".format(label))
        if item["verdict"] not in ALLOWED_LOCAL_REVIEW_VERDICTS:
            report.error(
                "{}.verdict must be one of {}".format(
                    label, sorted(ALLOWED_LOCAL_REVIEW_VERDICTS)
                )
            )
        findings = item["blocking_findings"]
        if not isinstance(findings, int) or isinstance(findings, bool) or findings < 0:
            report.error("{}.blocking_findings must be a non-negative integer".format(label))
        if item["verdict"] == "passed" and findings != 0:
            report.error("{} passed verdict requires zero blocking findings".format(label))
        outcomes = validate_local_review_evidence(
            item["evidence"],
            reviewers,
            allowed_paths,
            label,
            report,
            check_paths,
            context=context,
            context_path=context_path,
            round_number=item["number"],
            subject_value=str(item["subject_value"]),
            seen_evidence=seen_evidence,
            seen_run_ids=seen_run_ids,
            seen_run_digests=seen_run_digests,
            seen_agent_ids=seen_agent_ids,
            seen_transcript_hashes=seen_transcript_hashes,
            seen_proof_hashes=seen_proof_hashes,
            seen_binding_hashes=seen_binding_hashes,
            seen_task_names=seen_task_names,
        )
        expected_verdict = (
            "changes_requested"
            if any(
                outcome.get("verdict") == "changes_requested"
                for outcome in outcomes
            )
            else "passed"
        )
        expected_findings = sum(
            outcome.get("blocking_findings", 0)
            for outcome in outcomes
        )
        if item["verdict"] != expected_verdict:
            report.error(
                "{}.verdict does not aggregate reviewer evidence".format(label)
            )
        if findings != expected_findings:
            report.error(
                "{}.blocking_findings must equal the sum of reviewer findings".format(
                    label
                )
            )
        if index == len(rounds) - 1:
            final_round_reviewers = reviewers
            if item["subject_value"] != subject_value:
                report.error("final review round does not bind the current subject")
            if item["verdict"] != "passed":
                report.error("final review round must pass")
    missing_final_reviewers = selected_reviewers - final_round_reviewers
    if missing_final_reviewers:
        report.error(
            "final review round is missing configured independent reviewers: {}".format(
                ", ".join(sorted(missing_final_reviewers))
            )
        )
    if manifest["final_status"] != "passed":
        report.error("local review final_status must be passed")
    parse_timestamp(manifest["completed_at"], "local review completed_at", report)
    sensitive = find_sensitive_keys(manifest)
    if sensitive:
        report.error(
            "local review manifest contains forbidden sensitive fields: {}".format(
                ", ".join(sensitive)
            )
        )


def validate_intent(intent, context, report):
    required = ["domain", "previous_domain", "scope_change_confirmed", "confirmation_evidence"]
    if not require_keys(intent, required, "intent", report):
        return
    domain = intent["domain"]
    previous = intent["previous_domain"]
    if domain not in ALLOWED_INTENT_DOMAINS:
        report.error("intent.domain must be one of {}".format(sorted(ALLOWED_INTENT_DOMAINS)))
        return
    if previous is not None and previous not in ALLOWED_INTENT_DOMAINS:
        report.error("intent.previous_domain must be null or one of {}".format(sorted(ALLOWED_INTENT_DOMAINS)))
    confirmed = intent["scope_change_confirmed"]
    evidence = intent["confirmation_evidence"]
    if not isinstance(confirmed, bool):
        report.error("intent.scope_change_confirmed must be a boolean")
    if evidence is not None and (not isinstance(evidence, str) or not evidence.strip()):
        report.error("intent.confirmation_evidence must be null or a non-empty string")
    changed = previous is not None and previous != domain
    if changed and (confirmed is not True or not isinstance(evidence, str) or not evidence.strip()):
        report.error("intent domain change requires explicit user confirmation evidence")
    scope = context.get("scope", {})
    playbook = context.get("playbook", {})
    if domain == "global_agent_capability":
        if scope.get("repositories"):
            report.error("global_agent_capability context cannot include business repositories")
        if playbook.get("managed"):
            report.error("global_agent_capability context cannot create or manage a Playbook business task")
    if domain == "playbook_platform" and playbook.get("managed"):
        report.error("playbook_platform context cannot use a business Playbook task as its authority")


def validate_run_record(data, report, check_paths=True):
    required = [
        "schema_version", "run_id", "task_id", "agent", "role", "selection_reason",
        "context_pack", "context_hash", "started_at", "ended_at", "status", "gates",
        "verification", "outputs", "runtime_evidence", "rework", "metrics", "agent_improvement_candidates",
    ]
    if not require_keys(data, required, "run record", report):
        return
    if data["schema_version"] not in {"1.1", "1.2"}:
        report.error("run record schema_version must be 1.1 or 1.2")
    for key in ("run_id", "task_id", "agent", "role", "selection_reason", "context_pack"):
        if not isinstance(data[key], str) or not data[key].strip():
            report.error("run record {} must be a non-empty string".format(key))
    if not isinstance(data["status"], str) or data["status"] not in ALLOWED_RUN_STATUS:
        report.error("run record status must be one of {}".format(sorted(ALLOWED_RUN_STATUS)))
    if not re.fullmatch(r"[0-9a-f]{64}", str(data["context_hash"])):
        report.error("context_hash must be a lowercase SHA-256 hex digest")
    started = parse_timestamp(data["started_at"], "started_at", report)
    ended = parse_timestamp(data["ended_at"], "ended_at", report)
    if started and ended and ended < started:
        report.error("ended_at must not be earlier than started_at")
    context_path = Path(str(data["context_pack"]))
    context = None
    if not context_path.exists():
        if check_paths:
            report.error("context_pack does not exist: {}".format(context_path))
    else:
        try:
            context = json.loads(context_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report.error("cannot load context_pack {}: {}".format(context_path, exc))
        else:
            actual_hash = (
                task_authority_hash(context)
                if context.get("schema_version") == "1.6"
                else hashlib.sha256(context_path.read_bytes()).hexdigest()
            )
            if actual_hash != data["context_hash"]:
                report.error("context_hash does not match {}".format(context_path))
    if isinstance(context, dict):
        if data["task_id"] != context.get("task_id"):
            report.error("run record task_id does not match context_pack")
        routing = context.get("routing", {})
        allowed_agents = set(routing.get("delegated_agents", [])) | {routing.get("root_agent")}
        if data["agent"] not in allowed_agents:
            report.error("run record agent {} was not delegated by context_pack".format(data["agent"]))
    if data["agent"] != ROOT_AGENT and not (AGENTS_DIR / "{}.toml".format(data["agent"])).exists():
        report.error("run record references an unregistered agent: {}".format(data["agent"]))
    validate_result_entries(data["gates"], "gates", ["name", "status", "evidence"], ALLOWED_GATE_STATUS, report)
    validate_result_entries(
        data["verification"], "verification", ["command", "status", "summary"],
        ALLOWED_VERIFICATION_STATUS, report,
    )
    if not isinstance(data["agent_improvement_candidates"], list):
        report.error("agent_improvement_candidates must be a list")
    if data.get("status") == "completed":
        for key in ("gates", "verification"):
            if not isinstance(data.get(key), list) or not data[key]:
                report.error("completed run record requires non-empty {}".format(key))
    if not isinstance(data.get("outputs"), dict):
        report.error("outputs must be a JSON object")
    runtime_evidence = data.get("runtime_evidence")
    if data.get("status") == "completed" and data.get("agent") != ROOT_AGENT:
        evidence_keys = [
            "source", "agent_type", "task_name", "agent_id", "parent_agent_id",
            "transcript_path", "transcript_hash", "terminal_event",
        ]
        if data.get("schema_version") == "1.2":
            evidence_keys.extend(["delegation_proof_path", "delegation_proof_hash"])
        if require_keys(runtime_evidence, evidence_keys, "runtime_evidence", report):
            if runtime_evidence["source"] != "codex-runtime":
                report.error("runtime_evidence.source must be codex-runtime")
            if runtime_evidence["agent_type"] != data.get("agent"):
                report.error("runtime_evidence.agent_type must match run record agent")
            if isinstance(context, dict) and context.get("schema_version") == "1.6":
                prefix = context.get("routing", {}).get(
                    "delegation_policies", {}
                ).get(data.get("agent"), {}).get("task_name_prefix")
                if (
                    not isinstance(prefix, str)
                    or not re.fullmatch(
                        re.escape(prefix) + r"__r[1-9][0-9]*__[0-9a-f]{8,64}",
                        runtime_evidence["task_name"],
                    )
                ):
                    report.error("runtime_evidence.task_name is outside its authorized namespace")
            else:
                expected_task_name = context.get("routing", {}).get("delegation_names", {}).get(data.get("agent")) if isinstance(context, dict) else None
                if runtime_evidence["task_name"] != expected_task_name:
                    report.error("runtime_evidence.task_name must match context routing.delegation_names")
            for key in ("agent_id", "parent_agent_id"):
                if not isinstance(runtime_evidence[key], str) or not runtime_evidence[key].strip():
                    report.error("runtime_evidence.{} must be a non-empty string".format(key))
            transcript = Path(str(runtime_evidence["transcript_path"]))
            if not transcript.is_absolute():
                report.error("runtime_evidence.transcript_path must be absolute")
            elif check_paths and not transcript.is_file():
                report.error("runtime evidence transcript does not exist: {}".format(transcript))
            elif check_paths and not path_is_covered(str(transcript), [str(CODEX / "sessions")]):
                report.error("runtime evidence transcript must be a Codex rollout under CODEX_HOME/sessions")
            transcript_hash = runtime_evidence["transcript_hash"]
            if not re.fullmatch(r"[0-9a-f]{64}", str(transcript_hash)):
                report.error("runtime_evidence.transcript_hash must be a lowercase SHA-256 digest")
            elif check_paths and transcript.is_file() and hashlib.sha256(transcript.read_bytes()).hexdigest() != transcript_hash:
                report.error("runtime_evidence.transcript_hash does not match transcript")
            if runtime_evidence["terminal_event"] != "task_complete":
                report.error("runtime_evidence.terminal_event must be task_complete")
            if data.get("schema_version") == "1.2":
                validate_delegation_proof(runtime_evidence, data, context, context_path, report, check_paths)
            if (
                check_paths
                and transcript.is_file()
                and re.fullmatch(r"[0-9a-f]{64}", str(transcript_hash))
                and (not isinstance(context, dict) or context.get("revision", 0) < 6)
            ):
                try:
                    transcript_lines = transcript.read_text(encoding="utf-8").splitlines()
                    events = [json.loads(line) for line in transcript_lines]
                except (OSError, UnicodeError, json.JSONDecodeError):
                    report.error("runtime evidence transcript must be valid Codex JSONL")
                else:
                    session_meta = next((item.get("payload", {}) for item in events if item.get("type") == "session_meta"), None)
                    if not isinstance(session_meta, dict):
                        report.error("runtime transcript missing session_meta")
                    else:
                        spawn = session_meta.get("source", {}).get("subagent", {}).get("thread_spawn", {})
                        if session_meta.get("id") != runtime_evidence["agent_id"]:
                            report.error("runtime transcript agent id does not match")
                        if session_meta.get("parent_thread_id") != runtime_evidence["parent_agent_id"]:
                            report.error("runtime transcript parent agent id does not match")
                        if spawn.get("agent_role") != runtime_evidence["agent_type"]:
                            report.error("runtime transcript does not prove the configured agent_type")
                        agent_path = spawn.get("agent_path")
                        if not isinstance(agent_path, str) or agent_path.rsplit("/", 1)[-1] != runtime_evidence["task_name"]:
                            report.error("runtime transcript task name does not match the bound delegation name")
                        new_task_indexes = []
                        for index, item in enumerate(events):
                            payload = item.get("payload", {})
                            if (
                                item.get("type") != "response_item"
                                or payload.get("type") != "agent_message"
                                or payload.get("author") != "/root"
                                or payload.get("recipient") != agent_path
                            ):
                                continue
                            input_texts = [part.get("text", "") for part in payload.get("content", []) if part.get("type") == "input_text"]
                            envelope = "\n".join(input_texts)
                            if "Message Type: NEW_TASK" in envelope and "Task name: {}".format(agent_path) in envelope:
                                new_task_indexes.append(index)
                        brief_index = new_task_indexes[0] if new_task_indexes else None
                        if brief_index is None:
                            report.error("runtime transcript does not contain the trusted inbound NEW_TASK envelope")
                        elif not any(
                            item.get("type") == "event_msg" and item.get("payload", {}).get("type") == "task_complete"
                            for item in events[brief_index + 1:]
                        ):
                            report.error("runtime transcript has no task_complete after the bound delegation brief")
    elif runtime_evidence is not None and not isinstance(runtime_evidence, dict):
        report.error("runtime_evidence must be an object or null")
    if not require_keys(data["rework"], ["count", "reasons"], "rework", report):
        return
    if not isinstance(data["rework"]["count"], int) or data["rework"]["count"] < 0:
        report.error("rework.count must be a non-negative integer")
    metric_keys = [
        "context_supplements", "boundary_violations", "verification_failures",
        "escaped_defects", "result_accepted",
    ]
    if require_keys(data["metrics"], metric_keys, "metrics", report):
        for key in metric_keys[:-1]:
            if not isinstance(data["metrics"][key], int) or data["metrics"][key] < 0:
                report.error("metrics.{} must be a non-negative integer".format(key))
        if data["metrics"]["result_accepted"] not in (True, False, None):
            report.error("metrics.result_accepted must be true, false, or null")
    if isinstance(data["agent_improvement_candidates"], list):
        for index, candidate in enumerate(data["agent_improvement_candidates"]):
            if not isinstance(candidate, dict) or not isinstance(candidate.get("category"), str):
                report.error("agent_improvement_candidates[{}] must contain string category".format(index))


def validate_routing_cases(data, report, registered_names):
    if not require_keys(data, ["schema_version", "policy", "cases", "interaction_cases"], "routing cases", report):
        return
    if data["schema_version"] != "1.4":
        report.error("routing cases schema_version must be 1.4")
    require_keys(data["policy"], ["root_agent", "selection_rule", "independent_review_rule"], "routing policy", report)
    if isinstance(data.get("policy"), dict) and data["policy"].get("root_agent") != ROOT_AGENT:
        report.error("routing policy root_agent must be {}".format(ROOT_AGENT))
    cases = data["cases"]
    if not isinstance(cases, list) or len(cases) < 10:
        report.error("routing cases must contain at least 10 representative cases")
        return
    seen = set()
    implementation_agents = {"java_implementer", "frontend_implementer"}
    for index, case in enumerate(cases):
        label = "routing cases[{}]".format(index)
        required = [
            "id", "title", "prompt", "intent_domain", "risk_level", "required_agents", "optional_agents",
            "independent_review_agents", "rationale",
        ]
        if not require_keys(case, required, label, report):
            continue
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id.strip():
            report.error("{}.id must be a non-empty string".format(label))
            case_id = "invalid-{}".format(index)
        if case_id in seen:
            report.error("duplicate routing case id: {}".format(case_id))
        seen.add(case_id)
        if case["risk_level"] not in ALLOWED_RISK_LEVELS:
            report.error("{} has unsupported risk_level {}".format(label, case["risk_level"]))
        if case["intent_domain"] not in ALLOWED_INTENT_DOMAINS:
            report.error("{} has unsupported intent_domain {}".format(label, case["intent_domain"]))
        for key in ("title", "prompt", "rationale"):
            if not isinstance(case[key], str) or not case[key].strip():
                report.error("{}.{} must be a non-empty string".format(label, key))
        agent_sets = {}
        for key in ("required_agents", "optional_agents", "independent_review_agents"):
            value = case[key]
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                report.error("{}.{} must be a list of agent names".format(label, key))
                value = []
            if len(value) != len(set(value)):
                report.error("{}.{} contains duplicates".format(label, key))
            agent_sets[key] = set(value)
        required_agents = agent_sets["required_agents"]
        optional_agents = agent_sets["optional_agents"]
        review_agents = agent_sets["independent_review_agents"]
        reserved = (required_agents | optional_agents | review_agents) & {ROOT_AGENT}
        if reserved:
            report.error("{} delegates reserved root agent {}".format(label, ROOT_AGENT))
        overlap = required_agents & optional_agents
        if overlap:
            report.error("{} required/optional overlap: {}".format(label, ", ".join(sorted(overlap))))
        unknown = (required_agents | optional_agents | review_agents) - registered_names
        if unknown:
            report.error("{} references unregistered agents: {}".format(label, ", ".join(sorted(unknown))))
        if not review_agents <= (required_agents | optional_agents):
            report.error("{} independent reviewers must be required or optional agents".format(label))
        invalid_reviewers = review_agents & (implementation_agents | {ROOT_AGENT})
        if invalid_reviewers:
            report.error("{} uses non-independent reviewers: {}".format(label, ", ".join(sorted(invalid_reviewers))))
        if case["risk_level"] in {"high", "critical"} and not review_agents:
            report.error("{} high-risk case requires independent_review_agents".format(label))
    validate_artifact_routing_cases(data.get("artifact_routing_cases"), report)
    validate_interaction_cases(data.get("interaction_cases"), report)


def validate_artifact_routing_cases(cases, report):
    expected = {
        "single_repo_local": ("openspec_only", False, False),
        "small_interface_local": ("openspec_only", False, False),
        "data_migration": ("spec_rfc_then_openspec", False, False),
        "transaction_failure": ("spec_rfc_then_openspec", False, False),
        "sensitive_pki": ("spec_rfc_then_openspec", False, False),
        "multi_phase": ("spec_rfc_then_openspec", False, False),
        "explicit_spec_rfc": ("spec_rfc_then_openspec", False, False),
        "class_document": ("class_skill", False, False),
        "retroactive_missing_baseline": ("spec_rfc_then_openspec", True, False),
        "spec_rfc_substantive_change": ("spec_rfc_then_openspec", False, True),
        "tasks_status_only": ("spec_rfc_then_openspec", False, False),
    }
    if not isinstance(cases, list):
        report.error("artifact_routing_cases must be a list")
        return
    seen = set()
    for index, case in enumerate(cases):
        label = "artifact_routing_cases[{}]".format(index)
        if not require_keys(
            case,
            [
                "id", "signal", "prompt", "expected_route", "risk_signals", "required_gates",
                "retroactive_normalization", "consistency_reset", "rationale",
            ],
            label, report,
        ):
            continue
        signal = case["signal"]
        if signal in seen:
            report.error("duplicate artifact routing signal: {}".format(signal))
        seen.add(signal)
        if signal not in expected:
            report.error("{} has unsupported signal {}".format(label, signal))
            continue
        route, retroactive, reset = expected[signal]
        if case["expected_route"] != route:
            report.error("{} expected_route must be {}".format(label, route))
        if case["retroactive_normalization"] is not retroactive:
            report.error("{} retroactive_normalization must be {}".format(label, retroactive))
        if case["consistency_reset"] is not reset:
            report.error("{} consistency_reset must be {}".format(label, reset))
        for key in ("id", "prompt", "rationale"):
            if not isinstance(case[key], str) or not case[key].strip():
                report.error("{}.{} must be a non-empty string".format(label, key))
        validate_string_list(case["risk_signals"], "{}.risk_signals".format(label), report)
        validate_string_list(case["required_gates"], "{}.required_gates".format(label), report)
    missing = set(expected) - seen
    if missing:
        report.error("artifact routing regression cases missing signals: {}".format(", ".join(sorted(missing))))


def validate_interaction_cases(cases, report):
    expected = {
        "question_not_decision": ("question", "none", "conflicted", False, "not_applicable"),
        "hypothesis_not_decision": ("hypothesis", "none", "insufficient", False, "not_applicable"),
        "supported_fact_correction": ("fact_correction", "none", "supported", False, "not_applicable"),
        "conflicting_fact_correction": ("fact_correction", "none", "conflicted", False, "not_applicable"),
        "evidence_scope_reduction": ("execution_instruction", "confirmed", "supported", True, "evidence_supported"),
        "decision_scope_reduction": ("business_decision", "confirmed", "conflicted", True, "explicit_business_decision"),
    }
    if not isinstance(cases, list):
        report.error("interaction_cases must be a list")
        return
    seen = set()
    for index, case in enumerate(cases):
        label = "interaction_cases[{}]".format(index)
        required = [
            "id", "signal", "prompt", "user_act", "baseline_change", "evidence_status",
            "scope_reduction_present", "scope_reduction_basis", "expected_outcome", "rationale",
        ]
        if not require_keys(case, required, label, report):
            continue
        signal = case["signal"]
        if signal in seen:
            report.error("duplicate interaction signal: {}".format(signal))
        seen.add(signal)
        if signal not in expected:
            report.error("{} has unsupported signal {}".format(label, signal))
            continue
        actual = (
            case["user_act"], case["baseline_change"], case["evidence_status"],
            case["scope_reduction_present"], case["scope_reduction_basis"],
        )
        if actual != expected[signal]:
            report.error("{} classification does not match {} policy".format(label, signal))
        for key in ("id", "prompt", "expected_outcome", "rationale"):
            if not isinstance(case[key], str) or not case[key].strip():
                report.error("{}.{} must be a non-empty string".format(label, key))
    missing = set(expected) - seen
    if missing:
        report.error("interaction regression cases missing signals: {}".format(", ".join(sorted(missing))))


def evaluate_routing_case(data, case_id, selected, intent_domain, report):
    cases = {case.get("id"): case for case in data.get("cases", []) if isinstance(case, dict)}
    case = cases.get(case_id)
    if not case:
        report.error("unknown routing case: {}".format(case_id))
        return
    if intent_domain != case["intent_domain"]:
        report.error(
            "{} intent domain mismatch: expected {}, got {}".format(
                case_id, case["intent_domain"], intent_domain or "<missing>"
            )
        )
    selected_agents = set(selected)
    required_agents = set(case["required_agents"])
    optional_agents = set(case["optional_agents"])
    review_agents = set(case["independent_review_agents"])
    missing = required_agents - selected_agents
    unexpected = selected_agents - required_agents - optional_agents
    if missing:
        report.error("{} missing required agents: {}".format(case_id, ", ".join(sorted(missing))))
    if unexpected:
        report.error("{} over-routed agents: {}".format(case_id, ", ".join(sorted(unexpected))))
    if review_agents and not (review_agents & selected_agents):
        report.error("{} missing an independent reviewer from: {}".format(case_id, ", ".join(sorted(review_agents))))
    used_optional = selected_agents & optional_agents
    if used_optional:
        report.warn("{} optional agents require task-specific evidence: {}".format(case_id, ", ".join(sorted(used_optional))))


def validate_evolution_policy(data, report):
    required = ["schema_version", "allowed_stages", "trial_to_stable", "optimization_triggers", "decision_rule"]
    if not require_keys(data, required, "evolution policy", report):
        return
    if data["schema_version"] != "1.0":
        report.error("evolution policy schema_version must be 1.0")
    if not isinstance(data["allowed_stages"], list) or not data["allowed_stages"]:
        report.error("evolution policy allowed_stages must be a non-empty list")
    stable_keys = [
        "min_valid_runs", "min_task_types", "min_acceptance_observations", "min_acceptance_rate",
        "max_rework_run_rate", "max_context_supplement_run_rate",
        "max_verification_failure_run_rate", "max_boundary_violations", "max_escaped_defects",
    ]
    if require_keys(data["trial_to_stable"], stable_keys, "trial_to_stable", report):
        for key in stable_keys:
            value = data["trial_to_stable"][key]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                report.error("trial_to_stable.{} must be a non-negative number".format(key))
    trigger_keys = ["repeated_candidate_category", "boundary_violations", "escaped_defects"]
    if require_keys(data["optimization_triggers"], trigger_keys, "optimization_triggers", report):
        for key in trigger_keys:
            value = data["optimization_triggers"][key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                report.error("optimization_triggers.{} must be a positive integer".format(key))


def validate_agent_stages(data, report, registered_names, allowed_stages):
    if not require_keys(data, ["schema_version", "agents"], "agent stages", report):
        return
    if data["schema_version"] != "1.0":
        report.error("agent stages schema_version must be 1.0")
    if not isinstance(data["agents"], list):
        report.error("agent stages agents must be a list")
        return
    stage_names = set()
    for index, item in enumerate(data["agents"]):
        label = "agent stages[{}]".format(index)
        if not require_keys(item, ["name", "stage", "since", "evidence_runs", "last_evaluated_at"], label, report):
            continue
        name = item["name"]
        if not isinstance(name, str):
            report.error("{}.name must be a string".format(label))
            continue
        if name in stage_names:
            report.error("duplicate agent stage entry: {}".format(name))
        stage_names.add(name)
        if item["stage"] not in allowed_stages:
            report.error("{} has unsupported stage {}".format(label, item["stage"]))
        if not isinstance(item["evidence_runs"], int) or item["evidence_runs"] < 0:
            report.error("{}.evidence_runs must be a non-negative integer".format(label))
    missing_configs = stage_names - (registered_names | {ROOT_AGENT})
    if missing_configs:
        report.error("agent stages references missing agents: {}".format(", ".join(sorted(missing_configs))))
    unmanaged_configs = registered_names - stage_names
    if unmanaged_configs:
        report.error("agent configs missing stage registration: {}".format(", ".join(sorted(unmanaged_configs))))


def evaluate_stage(metrics, candidate_categories, current_stage, policy):
    thresholds = policy["trial_to_stable"]
    unmet = []
    minimums = {
        "valid_runs": "min_valid_runs",
        "acceptance_observations": "min_acceptance_observations",
        "acceptance_rate": "min_acceptance_rate",
    }
    for metric, threshold in minimums.items():
        if metrics[metric] < thresholds[threshold]:
            unmet.append("{} < {}".format(metric, thresholds[threshold]))
    if len(metrics["task_types"]) < thresholds["min_task_types"]:
        unmet.append("task_types < {}".format(thresholds["min_task_types"]))
    maximums = {
        "rework_run_rate": "max_rework_run_rate",
        "context_supplement_run_rate": "max_context_supplement_run_rate",
        "verification_failure_run_rate": "max_verification_failure_run_rate",
        "boundary_violations": "max_boundary_violations",
        "escaped_defects": "max_escaped_defects",
    }
    for metric, threshold in maximums.items():
        if metrics[metric] > thresholds[threshold]:
            unmet.append("{} > {}".format(metric, thresholds[threshold]))
    repeated = {
        category: count for category, count in candidate_categories.items()
        if count >= policy["optimization_triggers"]["repeated_candidate_category"]
    }
    if current_stage == "trial":
        recommendation = "eligible_for_stable_review" if not unmet else "remain_trial"
    elif current_stage == "stable" and (
        repeated
        or metrics["boundary_violations"] >= policy["optimization_triggers"]["boundary_violations"]
        or metrics["escaped_defects"] >= policy["optimization_triggers"]["escaped_defects"]
    ):
        recommendation = "enter_optimization_review"
    else:
        recommendation = "no_stage_change"
    return unmet, repeated, recommendation


def sync_stage_evidence(stages, agent, valid_runs, evaluated_at=None):
    entry = next((item for item in stages["agents"] if item.get("name") == agent), None)
    if entry is None:
        raise ValueError("agent is not registered in managed stages: {}".format(agent))
    entry["evidence_runs"] = valid_runs
    entry["last_evaluated_at"] = evaluated_at or datetime.now(timezone.utc).isoformat()
    return entry


def evaluate_runs(directories, agent, policy, stages, report, sync_evidence=False):
    if agent != ROOT_AGENT and not (AGENTS_DIR / "{}.toml".format(agent)).exists():
        report.error("cannot evaluate unregistered agent: {}".format(agent))
        return
    runs = []
    task_types = set()
    candidate_categories = Counter()
    seen_run_ids = set()
    paths = sorted(path for directory in directories for path in directory.rglob("*.json"))
    for path in paths:
        if ".template." in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "run_id" not in data or data.get("agent") != agent:
            continue
        item_report = Report()
        validate_run_record(data, item_report, check_paths=False)
        if item_report.errors:
            for error in item_report.errors:
                report.error("{}: {}".format(path, error))
            continue
        if data["run_id"] in seen_run_ids:
            report.error("duplicate run_id {}: {}".format(data["run_id"], path))
            continue
        seen_run_ids.add(data["run_id"])
        runs.append(data)
        context_path = Path(str(data["context_pack"]))
        if context_path.exists():
            try:
                context = json.loads(context_path.read_text(encoding="utf-8"))
                if context.get("task_type") in ALLOWED_TASK_TYPES:
                    task_types.add(context["task_type"])
            except (OSError, json.JSONDecodeError, AttributeError):
                pass
        for candidate in data["agent_improvement_candidates"]:
            candidate_categories[candidate["category"]] += 1

    total = len(runs)
    completed = sum(run["status"] == "completed" for run in runs)
    acceptance = [run["metrics"]["result_accepted"] for run in runs if run["metrics"]["result_accepted"] is not None]
    accepted = sum(value is True for value in acceptance)
    rework_runs = sum(run["rework"]["count"] > 0 for run in runs)
    context_runs = sum(run["metrics"]["context_supplements"] > 0 for run in runs)
    verification_failure_runs = sum(run["metrics"]["verification_failures"] > 0 for run in runs)
    boundary_violations = sum(run["metrics"]["boundary_violations"] for run in runs)
    escaped_defects = sum(run["metrics"]["escaped_defects"] for run in runs)

    def rate(count, denominator):
        return round(count / denominator, 4) if denominator else 0.0

    metrics = {
        "valid_runs": total,
        "completed_runs": completed,
        "task_types": sorted(task_types),
        "acceptance_observations": len(acceptance),
        "acceptance_rate": rate(accepted, len(acceptance)),
        "rework_run_rate": rate(rework_runs, total),
        "context_supplement_run_rate": rate(context_runs, total),
        "verification_failure_run_rate": rate(verification_failure_runs, total),
        "boundary_violations": boundary_violations,
        "escaped_defects": escaped_defects,
        "candidate_categories": dict(candidate_categories),
    }
    stage_map = {item["name"]: item["stage"] for item in stages["agents"]}
    if agent not in stage_map:
        report.error("cannot evaluate agent outside XiaoH managed stages: {}".format(agent))
        return
    current_stage = stage_map[agent]
    unmet, repeated, recommendation = evaluate_stage(metrics, candidate_categories, current_stage, policy)
    report.details["evolution_evaluation"] = {
        "agent": agent,
        "current_stage": current_stage,
        "evidence_directories": [str(directory) for directory in directories],
        "metrics": metrics,
        "unmet_stable_thresholds": unmet,
        "repeated_improvement_categories": repeated,
        "recommendation": recommendation,
        "automatic_change": False,
    }
    if sync_evidence:
        entry = sync_stage_evidence(stages, agent, metrics["valid_runs"])
        AGENT_STAGES.write_text(json.dumps(stages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.details["evolution_evaluation"]["stage_evidence_sync"] = {
            "evidence_runs": entry["evidence_runs"],
            "last_evaluated_at": entry["last_evaluated_at"],
            "stage_changed": False,
        }


def read_flat_agent(path, report):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.error("{}: {}".format(path, exc))
        return None, ""
    if text.count('"""') != 2:
        report.error("{}: expected one triple-quoted developer_instructions value".format(path))
    values = {}
    for key in ("name", "description", "model_reasoning_effort", "sandbox_mode"):
        matches = re.findall(r'^{}\s*=\s*"([^"]*)"\s*$'.format(key), text, re.M)
        if len(matches) > 1:
            report.error("{}: duplicate {}".format(path, key))
        if matches:
            values[key] = matches[0]
    nickname_match = re.search(r'^nickname_candidates\s*=\s*(\[[^\n]*\])\s*$', text, re.M)
    if nickname_match:
        try:
            nicknames = ast.literal_eval(nickname_match.group(1))
        except (SyntaxError, ValueError):
            nicknames = None
        if not isinstance(nicknames, list) or any(not isinstance(item, str) or not item.strip() for item in nicknames):
            report.error("{}: nickname_candidates must be a list of non-empty strings".format(path))
        else:
            values["nickname_candidates"] = nicknames
    if not re.search(r'^developer_instructions\s*=\s*"""[\s\S]*?"""\s*$', text, re.M):
        report.error("{}: missing or malformed developer_instructions".format(path))
    return values, text


def declares_reserved_root(path, text):
    name = re.search(r'^name\s*=\s*"([^"]+)"\s*$', text, re.M)
    return path.stem == ROOT_AGENT or bool(name and name.group(1) == ROOT_AGENT)


def validate_global(report):
    instructions = active_global_instructions()
    required_paths = [
        instructions, CODEX / "config.toml", CODEX / "contexts/INDEX.md",
        ROLE_CATALOG, EVOLUTION_LEDGER, SYSTEM_DIR / "task-context.template.json",
        SYSTEM_DIR / "run-record.template.json", ROUTING_CASES, EVOLUTION_POLICY, AGENT_STAGES,
        ROOT_AGENT_HOOK, SYSTEM_DIR / "playbook_adapter.py", VAULT_WRITE_HOOK, HOOK_RUNTIME_VERIFIER,
    ]
    for path in required_paths:
        if not path.exists():
            report.error("required file missing: {}".format(path))

    stage_preview = load_json(AGENT_STAGES, report) if AGENT_STAGES.exists() else None
    names = {}
    manifests = {}
    nickname_owners = {}
    for path in sorted(AGENTS_DIR.glob("*.toml")):
        values, text = read_flat_agent(path, report)
        if values is None:
            continue
        for key in ("name", "description"):
            if not values.get(key):
                report.error("{}: missing {}".format(path, key))
        name = values.get("name")
        if not name:
            continue
        if path.stem != name:
            report.error("{}: filename must match agent name {}".format(path, name))
        if name in names:
            report.error("duplicate agent name {} in {} and {}".format(name, names[name], path))
        names[name] = path
        manifests[name] = values
        if declares_reserved_root(path, text):
            report.error("{}: reserved root agent {} cannot be registered as a custom agent".format(path, ROOT_AGENT))
        for nickname in values.get("nickname_candidates", []):
            normalized = normalize_agent_name(nickname)
            if normalized in RESERVED_AGENT_ALIASES:
                report.error("{}: reserved root alias cannot be used as nickname: {}".format(path, nickname))
            if normalized in nickname_owners:
                report.error("duplicate agent nickname {} in {} and {}".format(nickname, nickname_owners[normalized], path))
            nickname_owners[normalized] = path
        if "sandbox_mode" not in values:
            report.error("{}: custom agent must declare sandbox_mode".format(path))
        if values.get("sandbox_mode") and values["sandbox_mode"] not in ALLOWED_SANDBOXES:
            report.error("{}: unsupported sandbox_mode {}".format(path, values["sandbox_mode"]))
        paths = ABSOLUTE_PATH.findall(text)
        if paths:
            report.error("{}: specialist agent contains absolute path(s): {}".format(path, ", ".join(paths)))

    if instructions.exists():
        instruction_text = instructions.read_text(encoding="utf-8")
        if "<!-- global-agent-common-contract:start -->" not in instruction_text:
            report.error("active global instructions missing common contract: {}".format(instructions))

    if ROLE_CATALOG.exists():
        catalog = ROLE_CATALOG.read_text(encoding="utf-8")
        catalog_names = set(re.findall(r'^\|\s*`([a-z0-9_]+)`\s*\|', catalog, re.M))
        expected_catalog_names = set(names) | {ROOT_AGENT}
        missing = expected_catalog_names - catalog_names
        stale = catalog_names - expected_catalog_names
        if missing:
            report.error("role catalog missing agents: {}".format(", ".join(sorted(missing))))
        if stale:
            report.error("role catalog references missing agents: {}".format(", ".join(sorted(stale))))
        sandbox_rows = dict(re.findall(
            r'^\|\s*`([a-z0-9_]+)`\s*\|[^|]*\|[^|]*\|\s*`([^`]+)`\s*\|',
            catalog, re.M,
        ))
        if sandbox_rows.get(ROOT_AGENT) != "inherit-current-task":
            report.error("role catalog root agent {} must use inherit-current-task".format(ROOT_AGENT))
        for name, values in manifests.items():
            expected = values.get("sandbox_mode", "inherit-current-task")
            actual = sandbox_rows.get(name)
            if actual != expected:
                report.error("role catalog sandbox drift for {}: expected {}, found {}".format(name, expected, actual))

    config = CODEX / "config.toml"
    if config.exists():
        text = config.read_text(encoding="utf-8")
        features = re.search(r'^\[features\]\s*$([\s\S]*?)(?=^\[|\Z)', text, re.M)
        if features and re.search(r'^hooks\s*=\s*false\s*$', features.group(1), re.M):
            report.error("[features].hooks must not be false")
        if re.search(r'^allow_managed_hooks_only\s*=\s*true\s*$', text, re.M):
            report.error("allow_managed_hooks_only=true disables the user-level xiaoh hook")
        agents_section = re.search(r'^\[agents\]\s*$([\s\S]*?)(?=^\[|\Z)', text, re.M)
        if not agents_section:
            report.error("config.toml missing [agents] section")
        else:
            section = agents_section.group(1)
            depth = re.search(r'^max_depth\s*=\s*(\d+)\s*$', section, re.M)
            threads = re.search(r'^max_threads\s*=\s*(\d+)\s*$', section, re.M)
            if not depth or int(depth.group(1)) != 1:
                report.error("[agents].max_depth must remain 1")
            if not threads or int(threads.group(1)) < 1:
                report.error("[agents].max_threads must be at least 1")
        hook_block = re.search(
            r'^# xiaoh-root-agent-hook:start\s*$[\s\S]*?^# xiaoh-root-agent-hook:end\s*$',
            text,
            re.M,
        )
        if not hook_block:
            report.error("config.toml missing xiaoh root-agent PreToolUse hook")
        elif not re.search(r'^matcher\s*=\s*[\"\']\^\(Agent\|spawn_agent\)\$[\"\']\s*$', hook_block.group(0), re.M):
            report.error("xiaoh root-agent hook must match Agent and spawn_agent tool calls")
        else:
            configured_paths = re.findall(
                r'--config\s+"([^"]+)"', hook_block.group(0)
            )
            unique_config_paths = set(configured_paths)
            if len(configured_paths) != 8 or len(unique_config_paths) != 1:
                report.error(
                    "xiaoh hooks must bind one identical local config path in all POSIX and Windows commands"
                )
                runtime_config = Path("__invalid_xiaoh_config__")
            else:
                runtime_config = Path(next(iter(unique_config_paths))).expanduser()
                if not runtime_config.is_absolute():
                    report.error("xiaoh hook config path must be absolute")
            config_argument = ' --config "{}"'.format(runtime_config.as_posix())
            expected_commands = [
                'command = \'python3 "{}"{}\''.format(
                    ROOT_AGENT_HOOK.as_posix(), config_argument
                ),
                'command_windows = \'"{}" "{}"{}\''.format(
                    Path(sys.executable).resolve().as_posix(),
                    ROOT_AGENT_HOOK.as_posix(),
                    config_argument,
                ),
                'command = \'python3 "{}"{} --subagent-start\''.format(
                    ROOT_AGENT_HOOK.as_posix(), config_argument
                ),
                'command_windows = \'"{}" "{}"{} --subagent-start\''.format(
                    Path(sys.executable).resolve().as_posix(),
                    ROOT_AGENT_HOOK.as_posix(),
                    config_argument,
                ),
                'command = \'python3 "{}"{} --subagent-stop\''.format(
                    ROOT_AGENT_HOOK.as_posix(), config_argument
                ),
                'command_windows = \'"{}" "{}"{} --subagent-stop\''.format(
                    Path(sys.executable).resolve().as_posix(),
                    ROOT_AGENT_HOOK.as_posix(),
                    config_argument,
                ),
                'command = \'python3 "{}"{}\''.format(
                    VAULT_WRITE_HOOK.as_posix(), config_argument
                ),
                'command_windows = \'py -3 "{}"{}\''.format(
                    VAULT_WRITE_HOOK.as_posix(), config_argument
                ),
            ]
            for expected in expected_commands:
                if expected not in hook_block.group(0):
                    report.error("xiaoh root-agent hook command drift: {}".format(expected))
            if not re.search(r'^\[\[hooks\.SubagentStart\]\]\s*$[\s\S]*?^matcher\s*=\s*["\']\.\*["\']\s*$', hook_block.group(0), re.M):
                report.error("xiaoh root-agent hook must include the SubagentStart proof binder")
            if not re.search(r'^\[\[hooks\.SubagentStop\]\]\s*$[\s\S]*?^matcher\s*=\s*["\']\.\*["\']\s*$', hook_block.group(0), re.M):
                report.error("xiaoh root-agent hook must include the SubagentStop proof attestor")
            if not re.search(r'^matcher\s*=\s*["\']\^\(apply_patch\|exec_command\)\$["\']\s*$', hook_block.group(0), re.M):
                report.error("xiaoh root-agent hook must include the Obsidian Vault write gate")

    for template, validator in (
        (SYSTEM_DIR / "task-context.template.json", validate_task_context),
        (SYSTEM_DIR / "run-record.template.json", validate_run_record),
    ):
        if template.exists():
            data = load_json(template, report)
            if data is not None:
                validator(data, report, check_paths=True)
    if ROUTING_CASES.exists():
        data = load_json(ROUTING_CASES, report)
        if data is not None:
            validate_routing_cases(data, report, set(names))
    policy = load_json(EVOLUTION_POLICY, report) if EVOLUTION_POLICY.exists() else None
    stages = stage_preview
    if policy is not None:
        validate_evolution_policy(policy, report)
    if stages is not None:
        allowed_stages = set(policy.get("allowed_stages", [])) if isinstance(policy, dict) else set()
        validate_agent_stages(stages, report, set(names), allowed_stages)


def load_context_chain(context_path, report):
    chain = []
    seen = set()
    current_path = context_path.resolve(strict=False)
    while True:
        if current_path in seen:
            report.error("task context revision chain contains a cycle: {}".format(current_path))
            return []
        seen.add(current_path)
        context = load_json(current_path, report)
        if context is None:
            return []
        validate_task_context(
            context,
            report,
            check_freshness=not chain,
            check_playbook_freshness=False,
            check_playbook_live_status=False,
        )
        digest = (
            task_authority_hash(context)
            if context.get("schema_version") == "1.6"
            else hashlib.sha256(current_path.read_bytes()).hexdigest()
        )
        chain.append((current_path, digest, context))
        previous = context.get("previous_context")
        if previous is None:
            break
        if not isinstance(previous, dict) or not isinstance(previous.get("path"), str):
            break
        current_path = Path(previous["path"]).resolve(strict=False)
        if len(chain) >= 100:
            report.error("task context revision chain exceeds 100 revisions")
            return []
    return chain


def validate_task_closure(context_path, run_directory, report):
    chain = load_context_chain(context_path, report)
    if not chain:
        return
    context = chain[0][2]
    if context.get("task_type") == "implementation":
        manifests = []
        for path in sorted(run_directory.glob("*.json")):
            candidate = load_json(path, Report())
            if (
                isinstance(candidate, dict)
                and candidate.get("schema_version") == LOCAL_REVIEW_SCHEMA
            ):
                manifests.append((path, candidate))
        if len(manifests) != 1:
            report.error(
                "implementation task closure requires exactly one current local review manifest"
            )
        else:
            validate_local_review_manifest(
                manifests[0][1], context, context_path, report, check_paths=True
            )
    accepted_contexts = {(str(chain[0][0]), chain[0][1])}
    records = []
    for path in sorted(run_directory.glob("*.json")):
        data = load_json(path, Report())
        if not isinstance(data, dict) or "run_id" not in data:
            continue
        record_context = Path(str(data.get("context_pack", ""))).resolve(strict=False)
        if (
            data.get("task_id") != context.get("task_id")
            or (str(record_context), data.get("context_hash")) not in accepted_contexts
        ):
            continue
        item_report = Report()
        validate_run_record(data, item_report)
        for error in item_report.errors:
            report.error("{}: {}".format(path, error))
        if not item_report.errors:
            records.append(data)
    run_ids = [record["run_id"] for record in records]
    duplicate_run_ids = {run_id for run_id, count in Counter(run_ids).items() if count > 1}
    if duplicate_run_ids:
        report.error("task closure contains duplicate run ids: {}".format(", ".join(sorted(duplicate_run_ids))))
    finished_records = [record for record in records if record.get("status") == "completed"]
    reviewers = set(context["routing"]["independent_review_agents"])
    completed_records = []
    for record in finished_records:
        reasons = closure_rejection_reasons(record, reviewers)
        if reasons:
            report.error("task closure run {} is not successful: {}".format(record["run_id"], "; ".join(reasons)))
        else:
            completed_records.append(record)
    completed_agents = {record["agent"] for record in completed_records}
    delegated = set(context["routing"]["delegated_agents"])
    required_agents = delegated | {context["routing"]["root_agent"]}
    missing = required_agents - completed_agents
    if missing:
        report.error("task closure missing completed required agents: {}".format(", ".join(sorted(missing))))
    duplicate_agents = {
        agent for agent, count in Counter(record["agent"] for record in completed_records).items()
        if count > 1 and agent not in reviewers
    }
    if duplicate_agents:
        report.error("task closure contains conflicting completed records for: {}".format(", ".join(sorted(duplicate_agents))))
    proof_hashes = [
        record.get("runtime_evidence", {}).get("delegation_proof_hash")
        for record in finished_records
        if record.get("agent") != ROOT_AGENT and isinstance(record.get("runtime_evidence"), dict)
    ]
    duplicate_proofs = {digest for digest, count in Counter(proof_hashes).items() if digest and count > 1}
    if duplicate_proofs:
        report.error("task closure reuses delegation proofs: {}".format(", ".join(sorted(duplicate_proofs))))
    required_fields = set(context["output_contract"]["required_fields"])
    for record in completed_records:
        missing_fields = required_fields - set(record.get("outputs", {}))
        if missing_fields:
            report.error(
                "task closure run {} missing output fields: {}".format(
                    record["run_id"], ", ".join(sorted(missing_fields))
                )
            )
    if context["risk_level"] in {"high", "critical"}:
        missing_reviewers = reviewers - completed_agents
        if missing_reviewers:
            report.error("task closure missing completed independent reviewers: {}".format(", ".join(sorted(missing_reviewers))))


def self_test(report):
    digest = hashlib.sha256(b"context").hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        report.error("SHA-256 self-test failed")
    probe = {"nested": {"private_key": "forbidden"}}
    if find_sensitive_keys(probe) != ["nested.private_key"]:
        report.error("sensitive-field self-test failed")
    if not declares_reserved_root(Path("other.toml"), 'name = "xiaoh"'):
        report.error("reserved root declaration self-test failed")
    if declares_reserved_root(Path("other.toml"), 'name = "explorer"'):
        report.error("non-root declaration self-test failed")
    if normalize_agent_name("xiao_h") != "xiaoh" or normalize_agent_name("小H") != "小h":
        report.error("reserved agent name normalization self-test failed")
    if path_is_covered(str(SYSTEM_DIR / "../config.toml"), [str(SYSTEM_DIR)]):
        report.error("allowed-path traversal self-test failed")
    invalid_report = Report()
    validate_task_context({}, invalid_report, check_paths=False)
    if not invalid_report.errors:
        report.error("invalid task-context self-test failed")
    if (SYSTEM_DIR / "task-context.template.json").exists():
        weak_context = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        weak_context["scope"]["allowed_paths"] = []
        weak_context["scope"]["prohibited_actions"] = []
        weak_context["verification"] = []
        weak_report = Report()
        validate_task_context(weak_context, weak_report, check_paths=False)
        if not weak_report.errors:
            report.error("weak task-context self-test failed")
        malformed_routing = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        malformed_routing["routing"]["delegated_agents"] = ["bad"]
        malformed_routing["routing"]["delegation_names"] = {"bad": []}
        malformed_report = Report()
        validate_task_context(malformed_routing, malformed_report, check_paths=False)
        if not malformed_report.errors:
            report.error("malformed delegation-names self-test failed")
        global_with_repo = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        global_with_repo["scope"]["repositories"] = ["/tmp/business-repo"]
        global_repo_report = Report()
        validate_task_context(global_with_repo, global_repo_report, check_paths=False)
        if not any("cannot include business repositories" in error for error in global_repo_report.errors):
            report.error("global capability repository denial self-test failed")
        unconfirmed_transition = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        unconfirmed_transition["intent"]["previous_domain"] = "business_project"
        transition_report = Report()
        validate_task_context(unconfirmed_transition, transition_report, check_paths=False)
        if not any("requires explicit user confirmation" in error for error in transition_report.errors):
            report.error("unconfirmed intent transition denial self-test failed")
        question_as_decision = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        question_as_decision["interaction"].update({
            "user_act": "question", "baseline_change": "confirmed", "impact_explained": True,
        })
        question_report = Report()
        validate_task_context(question_as_decision, question_report, check_paths=False)
        if not any("questions and hypotheses cannot change" in error for error in question_report.errors):
            report.error("question-as-decision denial self-test failed")
        evidence_question = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        evidence_question["interaction"].update({
            "user_act": "question", "baseline_change": "none", "evidence_status": "conflicted",
            "material_conflicts": ["The question conflicts with current implementation evidence."],
            "impact_explained": True,
        })
        evidence_question_report = Report()
        validate_task_context(evidence_question, evidence_question_report, check_paths=False)
        if evidence_question_report.errors:
            report.error("evidence-backed question self-test failed")
        unsupported_reduction = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        unsupported_reduction["interaction"].update({
            "user_act": "execution_instruction", "baseline_change": "confirmed", "impact_explained": True,
        })
        unsupported_reduction["interaction"]["scope_reduction"].update({
            "present": True, "basis": "evidence_supported", "evidence": [],
        })
        reduction_report = Report()
        validate_task_context(unsupported_reduction, reduction_report, check_paths=False)
        if not any("requires evidence" in error for error in reduction_report.errors):
            report.error("unsupported scope-reduction denial self-test failed")
        unsupported_default = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        unsupported_default["interaction"].update({
            "user_act": "execution_instruction", "baseline_change": "confirmed", "impact_explained": True,
        })
        unsupported_default["interaction"]["compatibility_default"].update({
            "present": True, "target": "required target field", "value": "fixed-value",
            "basis": "evidence_supported", "evidence": [],
        })
        default_report = Report()
        validate_task_context(unsupported_default, default_report, check_paths=False)
        if not any("compatibility_default requires evidence" in error for error in default_report.errors):
            report.error("unsupported compatibility-default denial self-test failed")
        unreviewed_reduction = json.loads(json.dumps(unsupported_reduction))
        unreviewed_reduction["risk_level"] = "high"
        unreviewed_reduction["interaction"]["scope_reduction"].update({
            "evidence": ["Validated source-to-target field mapping."],
            "independent_review_status": "pending",
        })
        unreviewed_report = Report()
        validate_task_context(unreviewed_reduction, unreviewed_report, check_paths=False)
        validate_interaction_gate(unreviewed_reduction, "implementation", unreviewed_report)
        if not any("requires passed independent review" in error for error in unreviewed_report.errors):
            report.error("high-risk scope-reduction review denial self-test failed")
        business_context = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        business_context["intent"]["domain"] = "business_project"
        business_context["scope"].update({
            "workspace": str(Path(tempfile.gettempdir())),
            "allowed_paths": [str(Path(tempfile.gettempdir()))],
        })
        for source in business_context["sources"]:
            source["path"] = str(Path(tempfile.gettempdir()) / Path(source["path"]).name)
        business_context["memory_recall"] = example_memory_recall()
        business_context["requirements"] = example_requirements()
        business_report = Report()
        validate_task_context(business_context, business_report, check_paths=False)
        validate_requirement_gate(business_context, "implementation", business_report, check_paths=False)
        if business_report.errors:
            report.error("valid business requirement gate self-test failed")
        legacy_business = json.loads(json.dumps(business_context))
        legacy_business["schema_version"] = "1.4"
        legacy_business.pop("memory_recall")
        legacy_gate_report = Report()
        validate_task_context(legacy_business, legacy_gate_report, check_paths=False)
        validate_requirement_gate(legacy_business, "task_create", legacy_gate_report, check_paths=False)
        if not any("require schema 1.6" in error for error in legacy_gate_report.errors):
            report.error("legacy lifecycle gate denial self-test failed")
        pending_recall = json.loads(json.dumps(business_context))
        pending_recall["memory_recall"] = {
            "status": "pending",
            "workspace_id": "workspace-1",
            "task_relation": "continuation",
            "manifest_path": None,
            "manifest_sha256": None,
            "completed_at": None,
        }
        pending_recall_report = Report()
        validate_task_context(pending_recall, pending_recall_report, check_paths=False)
        validate_requirement_gate(
            pending_recall, "artifact_routing", pending_recall_report, check_paths=False
        )
        if not any("project memory recall must be completed" in error for error in pending_recall_report.errors):
            report.error("pending project-memory-recall denial self-test failed")

        pending_spec = json.loads(json.dumps(business_context))
        pending_spec["requirements"]["spec_rfc"].update({
            "status": "drafting", "reference": None, "revision": 0,
            "validation_status": "pending", "independent_review_status": "pending",
            "confirmed_by_user": False, "confirmed_at": None,
        })
        pending_spec["requirements"]["openspec"].update({
            "consistency_status": "pending", "traceability_status": "pending",
            "validated_spec_rfc_revision": None,
        })
        pending_report = Report()
        validate_task_context(pending_spec, pending_report, check_paths=False)
        validate_requirement_gate(pending_spec, "task_create", pending_report, check_paths=False)
        if not any("confirmed Spec+RFC is required" in error for error in pending_report.errors):
            report.error("unconfirmed Spec+RFC task-create denial self-test failed")

        unreviewed_spec = json.loads(json.dumps(business_context))
        unreviewed_spec["requirements"]["spec_rfc"].update({
            "status": "confirmation_pending", "confirmed_by_user": False, "confirmed_at": None,
            "independent_review_status": "pending",
            "quality_review": {
                "skill": "spec-rfc-reviewer", "status": "pending",
                "decision": "OPENSPEC_NOT_READY", "reviewed_revision": None, "evidence": None,
            },
        })
        unreviewed_report = Report()
        validate_requirement_gate(unreviewed_spec, "spec_rfc_confirmation", unreviewed_report, check_paths=False)
        if not any("quality_review.status must be passed" in error for error in unreviewed_report.errors):
            report.error("Spec+RFC quality-review denial self-test failed")

        missing_bypass = json.loads(json.dumps(business_context))
        missing_bypass["requirements"]["artifact_route"] = "openspec_only"
        missing_bypass["requirements"]["spec_rfc"].update({
            "status": "not_required", "reference": None, "revision": 0,
            "validation_status": "not_required", "independent_review_status": "not_required",
            "confirmed_by_user": False, "confirmed_at": None,
        })
        missing_bypass["requirements"]["openspec"].update({
            "consistency_status": "not_required", "traceability_status": "not_required",
            "validated_spec_rfc_revision": None,
        })
        missing_bypass["requirements"]["skill_execution"] = {"explicitly_requested": [], "records": []}
        bypass_report = Report()
        validate_task_context(missing_bypass, bypass_report, check_paths=False)
        if not any("bypass.reason" in error for error in bypass_report.errors):
            report.error("openspec-only bypass denial self-test failed")

        pending_consistency = json.loads(json.dumps(business_context))
        pending_consistency["requirements"]["openspec"].update({
            "consistency_status": "pending", "traceability_status": "pending",
            "validated_spec_rfc_revision": None,
        })
        consistency_report = Report()
        validate_task_context(pending_consistency, consistency_report, check_paths=False)
        validate_requirement_gate(pending_consistency, "openspec_confirmation", consistency_report, check_paths=False)
        if not any("consistency review must pass" in error for error in consistency_report.errors):
            report.error("OpenSpec consistency denial self-test failed")

        wrong_consistency_skill = json.loads(json.dumps(business_context))
        wrong_consistency_skill["requirements"]["openspec"]["consistency_review"]["skill"] = "spec-rfc-reviewer"
        wrong_consistency_report = Report()
        validate_task_context(wrong_consistency_skill, wrong_consistency_report, check_paths=False)
        if not any("consistency_review.skill must be one of" in error for error in wrong_consistency_report.errors):
            report.error("OpenSpec consistency Skill binding self-test failed")

        incomplete_skill = json.loads(json.dumps(business_context))
        incomplete_skill["requirements"]["skill_execution"]["records"][0].update({
            "status": "in_progress", "validation_status": "pending", "evidence": None,
        })
        skill_report = Report()
        validate_task_context(incomplete_skill, skill_report, check_paths=False)
        validate_requirement_gate(incomplete_skill, "member_confirmation", skill_report, check_paths=False)
        if not any("lacks completed and validated execution evidence" in error for error in skill_report.errors):
            report.error("explicit Skill completion denial self-test failed")

        retroactive = json.loads(json.dumps(business_context))
        retroactive["requirements"]["retroactive_normalization"] = {"required": True, "status": "in_progress"}
        retroactive_report = Report()
        validate_task_context(retroactive, retroactive_report, check_paths=False)
        validate_requirement_gate(retroactive, "implementation", retroactive_report, check_paths=False)
        if not any("retroactive_normalization must be completed" in error for error in retroactive_report.errors):
            report.error("retroactive normalization denial self-test failed")

        changed_spec = json.loads(json.dumps(business_context))
        changed_spec["requirements"]["spec_rfc"]["revision"] = 2
        changed_report = Report()
        validate_task_context(changed_spec, changed_report, check_paths=False)
        if not any("consistency_status must reset to pending" in error for error in changed_report.errors):
            report.error("Spec+RFC revision consistency reset self-test failed")
    if (SYSTEM_DIR / "run-record.template.json").exists():
        mismatched_run = json.loads((SYSTEM_DIR / "run-record.template.json").read_text(encoding="utf-8"))
        mismatched_run["task_id"] = "wrong-task"
        mismatch_report = Report()
        validate_run_record(mismatched_run, mismatch_report)
        if not mismatch_report.errors:
            report.error("run-record task binding self-test failed")
        closure_record = json.loads((SYSTEM_DIR / "run-record.template.json").read_text(encoding="utf-8"))
        if closure_rejection_reasons(closure_record):
            report.error("successful run closure self-test failed")
        failed_gate = json.loads(json.dumps(closure_record))
        failed_gate["gates"][0]["status"] = "failed"
        if not closure_rejection_reasons(failed_gate):
            report.error("failed gate closure denial self-test failed")
        failed_verification = json.loads(json.dumps(closure_record))
        failed_verification["verification"][0]["status"] = "failed"
        if not closure_rejection_reasons(failed_verification):
            report.error("failed verification closure denial self-test failed")
        rejected_result = json.loads(json.dumps(closure_record))
        rejected_result["metrics"]["result_accepted"] = False
        if not closure_rejection_reasons(rejected_result):
            report.error("rejected result closure denial self-test failed")
        legacy_record = json.loads(json.dumps(closure_record))
        legacy_record["schema_version"] = "1.1"
        if not closure_rejection_reasons(legacy_record):
            report.error("legacy run closure denial self-test failed")
        digest_value = "0" * 64
        brief = {
            "schema_version": "1.0", "task_id": "example-task", "task_context": "/tmp/context.json",
            "context_hash": digest_value, "delegated_agent": "reviewer", "agent_type": "reviewer",
            "task_name": "review", "authority": "task_context_is_authoritative",
        }
        brief_hash = hashlib.sha256(json.dumps(
            brief, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        attested = {
            "state": "attested", "source": "subagent-start-stop", "effective_brief": brief,
            "effective_brief_hash": brief_hash, "transport_message_hash": digest_value,
            "receipt_hash": digest_value, "last_message_hash": digest_value, "hook_hash": digest_value,
            "agent_transcript_path": "/tmp/agent.jsonl",
        }
        attested_report = Report()
        validate_attested_binding(attested, brief, "/tmp/agent.jsonl", attested_report)
        if attested_report.errors:
            report.error("attested proof acceptance self-test failed")
        unattested = json.loads(json.dumps(attested))
        unattested["state"] = "started"
        unattested["receipt_hash"] = "invalid"
        unattested_report = Report()
        validate_attested_binding(unattested, brief, "/tmp/agent.jsonl", unattested_report)
        if len(unattested_report.errors) < 2:
            report.error("unattested proof denial self-test failed")
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            context_template = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
            old_context_path = run_dir / "context.r1.json"
            old_context_path.write_text(json.dumps(context_template), encoding="utf-8")
            old_hash = hashlib.sha256(old_context_path.read_bytes()).hexdigest()
            current_context = json.loads(json.dumps(context_template))
            current_context["revision"] = 2
            current_context["previous_context"] = {"path": str(old_context_path), "hash": old_hash}
            current_context_path = run_dir / "context.r2.json"
            current_context_path.write_text(json.dumps(current_context), encoding="utf-8")
            current_hash = (
                task_authority_hash(current_context)
                if current_context.get("schema_version") == "1.6"
                else hashlib.sha256(current_context_path.read_bytes()).hexdigest()
            )
            old_run = json.loads(json.dumps(closure_record))
            old_run["run_id"] = "head-only-old"
            old_run["context_pack"] = str(old_context_path)
            old_run["context_hash"] = old_hash
            old_run_path = run_dir / "old.json"
            old_run_path.write_text(json.dumps(old_run), encoding="utf-8")
            head_only_report = Report()
            validate_task_closure(current_context_path, run_dir, head_only_report)
            if not any("missing completed required agents: xiaoh" in error for error in head_only_report.errors):
                report.error("head-only closure rejection self-test failed")
            current_run = json.loads(json.dumps(closure_record))
            current_run["run_id"] = "head-only-current"
            current_run["context_pack"] = str(current_context_path)
            current_run["context_hash"] = current_hash
            current_run["outputs"] = {key: "verified" for key in current_context["output_contract"]["required_fields"]}
            (run_dir / "current.json").write_text(json.dumps(current_run), encoding="utf-8")
            current_report = Report()
            validate_task_closure(current_context_path, run_dir, current_report)
            if current_report.errors:
                report.error("head-only closure acceptance self-test failed")
    stage_report = Report()
    validate_agent_stages(
        {
            "schema_version": "1.0",
            "agents": [{
                "name": "known", "stage": "trial", "since": "2026-07-18",
                "evidence_runs": 0, "last_evaluated_at": None,
            }],
        },
        stage_report,
        {"known", "stray"},
        {"trial"},
    )
    if not stage_report.errors:
        report.error("unregistered agent-stage drift self-test failed")
    routing_report = Report()
    evaluate_routing_case(
        {"cases": [{
            "id": "probe", "intent_domain": "global_agent_capability",
            "required_agents": [], "optional_agents": [],
            "independent_review_agents": [],
        }]},
        "probe", ["unexpected"], "global_agent_capability", routing_report,
    )
    if not routing_report.errors:
        report.error("over-routing self-test failed")
    if EVOLUTION_POLICY.exists():
        policy = json.loads(EVOLUTION_POLICY.read_text(encoding="utf-8"))
        good_metrics = {
            "valid_runs": 8, "task_types": ["analysis", "implementation", "review"],
            "acceptance_observations": 8, "acceptance_rate": 1.0,
            "rework_run_rate": 0.0, "context_supplement_run_rate": 0.0,
            "verification_failure_run_rate": 0.0, "boundary_violations": 0,
            "escaped_defects": 0,
        }
        _, _, recommendation = evaluate_stage(good_metrics, Counter(), "trial", policy)
        if recommendation != "eligible_for_stable_review":
            report.error("stable eligibility self-test failed")
        _, _, recommendation = evaluate_stage(good_metrics, Counter({"routing": 3}), "stable", policy)
        if recommendation != "enter_optimization_review":
            report.error("optimization trigger self-test failed")
    stage_probe = {
        "schema_version": "1.0",
        "agents": [{
            "name": ROOT_AGENT, "stage": "trial", "since": "2026-07-18",
            "evidence_runs": 0, "last_evaluated_at": None,
        }],
    }
    synced = sync_stage_evidence(stage_probe, ROOT_AGENT, 3, "2026-07-20T00:00:00+00:00")
    if synced["evidence_runs"] != 3 or synced["stage"] != "trial" or not synced["last_evaluated_at"]:
        report.error("stage evidence sync self-test failed")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-context", type=Path)
    parser.add_argument("--authority-hash", type=Path)
    parser.add_argument("--execution-binding", type=Path)
    parser.add_argument("--migrate-task-context", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--local-review-manifest", type=Path)
    parser.add_argument("--requirement-gate", type=Path)
    parser.add_argument("--action", choices=sorted(ALLOWED_REQUIREMENT_GATE_ACTIONS))
    parser.add_argument("--playbook-receipt", type=Path)
    parser.add_argument("--playbook-receipt-sha256")
    parser.add_argument("--delegated-execution-binding", type=Path)
    parser.add_argument("--run-record", type=Path)
    parser.add_argument("--close-task-context", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--routing-case")
    parser.add_argument("--intent-domain", choices=sorted(ALLOWED_INTENT_DOMAINS))
    parser.add_argument(
        "--selected-agents", "--delegated-agents", dest="selected_agents",
        help="comma-separated delegated specialist agent names; omit when root handles the task directly",
    )
    parser.add_argument(
        "--evaluate-runs", type=Path, action="append",
        help="directory containing run-record JSON files; repeat for multiple workspaces",
    )
    parser.add_argument("--agent", help="registered agent to evaluate")
    parser.add_argument(
        "--sync-stage-evidence", action="store_true",
        help="write evaluated evidence_runs and last_evaluated_at to agent-stages.json; never changes stage",
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = Report()
    if args.migrate_task_context:
        if not args.output:
            report.error("--migrate-task-context requires --output")
        elif args.output.exists():
            report.error("--output already exists; migration never overwrites evidence")
        else:
            source = load_json(args.migrate_task_context, report)
            if source is not None:
                validate_task_context(source, report)
            if source is not None and not report.errors:
                try:
                    migrated = migrate_task_context_15_to_16(
                        source, args.migrate_task_context
                    )
                except (KeyError, ValueError) as exc:
                    report.error("task context migration failed: {}".format(exc))
                else:
                    migrated_report = Report()
                    validate_task_context(migrated, migrated_report)
                    for error in migrated_report.errors:
                        report.error("migrated task context: {}".format(error))
                    if not report.errors:
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        descriptor, temporary_name = tempfile.mkstemp(
                            prefix=".task-context-", dir=args.output.parent
                        )
                        try:
                            with os.fdopen(
                                descriptor, "w", encoding="utf-8", newline="\n"
                            ) as stream:
                                json.dump(
                                    migrated,
                                    stream,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    indent=2,
                                )
                                stream.write("\n")
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.link(temporary_name, args.output)
                        finally:
                            if os.path.exists(temporary_name):
                                os.unlink(temporary_name)
                        report.details["migrated_task_context"] = str(
                            args.output.resolve()
                        )
                        report.details["authority_hash"] = task_authority_hash(
                            migrated
                        )
    elif args.authority_hash:
        data = load_json(args.authority_hash, report)
        if data is not None:
            validate_task_context(data, report)
            if not report.errors:
                report.details["authority_hash"] = task_authority_hash(data)
    elif args.execution_binding:
        if not args.task_context:
            report.error("--execution-binding requires --task-context")
        else:
            context = load_json(args.task_context, report)
            binding = load_json(args.execution_binding, report)
            if context is not None:
                validate_task_context(context, report)
            if binding is not None and context is not None and not report.errors:
                validate_execution_binding(
                    binding, context, args.task_context, report
                )
    elif args.local_review_manifest:
        if not args.task_context:
            report.error("--local-review-manifest requires --task-context")
        else:
            context = load_json(args.task_context, report)
            manifest = load_json(args.local_review_manifest, report)
            if context is not None:
                validate_task_context(context, report)
            if manifest is not None and context is not None and not report.errors:
                validate_local_review_manifest(
                    manifest, context, args.task_context, report
                )
    elif args.requirement_gate:
        data = load_json(args.requirement_gate, report)
        delegated_binding = (
            load_json(args.delegated_execution_binding, report)
            if args.delegated_execution_binding
            else None
        )
        if not args.action:
            report.error("--requirement-gate requires --action")
        elif data is not None:
            validate_task_context(data, report)
            if not report.errors:
                validate_requirement_gate(
                    data,
                    args.action,
                    report,
                    root_playbook_receipt=args.playbook_receipt,
                    root_playbook_receipt_sha256=args.playbook_receipt_sha256,
                    delegated_execution_binding=delegated_binding,
                    delegated_execution_binding_context_path=args.requirement_gate,
                )
    elif args.task_context:
        data = load_json(args.task_context, report)
        if data is not None:
            validate_task_context(data, report)
    elif args.run_record:
        data = load_json(args.run_record, report)
        if data is not None:
            validate_run_record(data, report)
    elif args.close_task_context:
        if not args.run_dir or not args.run_dir.is_dir():
            report.error("--close-task-context requires an existing --run-dir")
        else:
            validate_task_closure(args.close_task_context, args.run_dir, report)
    elif args.routing_case:
        data = load_json(ROUTING_CASES, report)
        if data is not None:
            registered = {path.stem for path in AGENTS_DIR.glob("*.toml")}
            validate_routing_cases(data, report, registered)
            selected = [name.strip() for name in (args.selected_agents or "").split(",") if name.strip()]
            evaluate_routing_case(data, args.routing_case, selected, args.intent_domain, report)
    elif args.evaluate_runs:
        if not args.agent:
            report.error("--evaluate-runs requires --agent")
        elif any(not directory.is_dir() for directory in args.evaluate_runs):
            missing = [str(directory) for directory in args.evaluate_runs if not directory.is_dir()]
            report.error("evidence directories do not exist: {}".format(", ".join(missing)))
        else:
            policy = load_json(EVOLUTION_POLICY, report)
            stages = load_json(AGENT_STAGES, report)
            if policy is not None and stages is not None:
                validate_evolution_policy(policy, report)
                validate_agent_stages(
                    stages, report,
                    {path.stem for path in AGENTS_DIR.glob("*.toml")},
                    set(policy.get("allowed_stages", [])),
                )
                if not report.errors:
                    evaluate_runs(
                        args.evaluate_runs, args.agent, policy, stages, report,
                        sync_evidence=args.sync_stage_evidence,
                    )
    elif args.sync_stage_evidence:
        report.error("--sync-stage-evidence requires --evaluate-runs and --agent")
    elif args.action:
        report.error("--action requires --requirement-gate")
    else:
        validate_global(report)
    if args.self_test:
        self_test(report)
    return report.emit(args.as_json)


if __name__ == "__main__":
    sys.exit(main())
