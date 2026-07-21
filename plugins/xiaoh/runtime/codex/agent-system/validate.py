#!/usr/bin/env python3
"""Validate XiaoH's global agent configuration and explicitly sync evidence counters."""

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


HOME = Path.home()
CODEX = Path(os.environ.get("CODEX_HOME", str(HOME / ".codex"))).expanduser()
OBSIDIAN_VAULT = Path(
    os.environ.get("XIAOH_VAULT", str(HOME / "obsidian/development-vault"))
).expanduser()
AGENTS_DIR = CODEX / "agents"
ROOT_AGENT = "xiaoh"
ROOT_AGENT_HOOK = CODEX / "hooks/block_reserved_root_agent.py"
ROOT_AGENT_HOOK_WINDOWS = CODEX / "hooks/block_reserved_root_agent.ps1"
HOOK_RUNTIME_VERIFIER = CODEX / "hooks/verify_agent_hook_runtime.py"
ROLE_CATALOG = OBSIDIAN_VAULT / "04-架构与决策/Agent协作角色.md"
EVOLUTION_LEDGER = OBSIDIAN_VAULT / "04-架构与决策/Agent进化台账.md"
SYSTEM_DIR = CODEX / "agent-system"
ROUTING_CASES = SYSTEM_DIR / "routing-cases.json"
EVOLUTION_POLICY = SYSTEM_DIR / "evolution-policy.json"
AGENT_STAGES = SYSTEM_DIR / "agent-stages.json"
ALLOWED_SANDBOXES = {"read-only", "workspace-write", "danger-full-access"}
ALLOWED_TASK_TYPES = {"analysis", "design", "implementation", "verification", "review", "operations"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high", "critical"}
ALLOWED_INTENT_DOMAINS = {"global_agent_capability", "playbook_platform", "business_project"}
ALLOWED_ARTIFACT_ROUTES = {"openspec_only", "spec_rfc_then_openspec", "class_skill"}
ALLOWED_SPEC_RFC_STATUS = {
    "not_required", "pending", "drafting", "validating", "review_pending",
    "confirmation_pending", "confirmed",
}
ALLOWED_REQUIREMENT_CHECK_STATUS = {"not_required", "pending", "passed", "failed"}
ALLOWED_RETROACTIVE_STATUS = {"not_required", "pending", "in_progress", "review_pending", "completed"}
ALLOWED_SKILL_STATUS = {"pending", "in_progress", "completed"}
ALLOWED_SKILL_CONFIRMATION_STATUS = {"not_required", "pending", "confirmed"}
ALLOWED_REQUIREMENT_GATE_ACTIONS = {
    "readonly_analysis", "artifact_routing", "spec_rfc_baseline", "member_confirmation",
    "task_create", "openspec_authoring", "openspec_consistency_review", "openspec_confirmation",
    "task_start", "implementation",
}
ALLOWED_RUN_STATUS = {"completed", "blocked", "failed", "cancelled"}
ALLOWED_GATE_STATUS = {"passed", "failed", "blocked", "not-run", "blocked-as-required", "blocked-as-designed"}
ALLOWED_VERIFICATION_STATUS = {"passed", "failed", "blocked", "not-run", "blocked-as-required", "blocked-as-designed"}
SENSITIVE_KEYS = re.compile(r"(^|_)(password|token|secret|private_key|credential)s?($|_)", re.I)
ABSOLUTE_PATH = re.compile(r"/(?:Users|home|opt|var|srv|workspace)/[^\s'\"`]+")
RESERVED_AGENT_ALIASES = {"xiaoh", "小h"}
IMPLEMENTATION_AGENTS = {"java_implementer", "frontend_implementer"}
MAX_CONTEXT_AGE_HOURS = 24


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
    validate_string_list(requirements["required_gates"], "requirements.required_gates", report)

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


def validate_requirement_gate(context, action, report):
    if action not in ALLOWED_REQUIREMENT_GATE_ACTIONS:
        report.error("requirement gate action must be one of {}".format(sorted(ALLOWED_REQUIREMENT_GATE_ACTIONS)))
        return
    intent = context.get("intent", {})
    if intent.get("domain") != "business_project":
        report.error("requirement lifecycle gates apply only to business_project contexts")
        return
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


def example_requirements():
    return {
        "artifact_route": "spec_rfc_then_openspec",
        "route_reason": "总体需求涉及需要稳定基线的跨阶段语义",
        "risk_signals": ["multi_phase"],
        "required_gates": [
            "spec_rfc_validation", "independent_review", "user_confirmation",
            "openspec_consistency", "traceability",
        ],
        "spec_rfc": {
            "status": "confirmed",
            "reference": "/tmp/spec-rfc.md",
            "revision": 1,
            "validation_status": "passed",
            "independent_review_status": "passed",
            "confirmed_by_user": True,
            "confirmed_at": "2026-07-21T00:00:00+08:00",
        },
        "openspec": {
            "consistency_status": "passed",
            "traceability_status": "passed",
            "validated_spec_rfc_revision": 1,
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
    if isinstance(context, dict) and context.get("revision", 0) >= 6 and schema_version != "1.2":
        report.error("current task context requires an attested delegation proof schema 1.2")
        return
    if schema_version not in {"1.0", "1.1", "1.2"}:
        report.error("delegation proof schema_version must be 1.0, 1.1, or 1.2")
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
        expected_brief = {
            "schema_version": "1.0",
            "task_id": data.get("task_id"),
            "task_context": str(context_path.resolve(strict=False)),
            "context_hash": data.get("context_hash"),
            "delegated_agent": data.get("agent"),
            "agent_type": runtime_evidence["agent_type"],
            "task_name": runtime_evidence["task_name"],
            "authority": "task_context_is_authoritative",
        }
        validate_attested_binding(proof, expected_brief, runtime_evidence["transcript_path"], report)
    for key, value in expected.items():
        if proof.get(key) != value:
            report.error("delegation proof {} does not match the run/context binding".format(key))
    hook_path = Path(str(proof["hook_path"])).resolve(strict=False)
    allowed_hooks = {ROOT_AGENT_HOOK.resolve(strict=False), ROOT_AGENT_HOOK_WINDOWS.resolve(strict=False)}
    if hook_path not in allowed_hooks:
        report.error("delegation proof hook_path is not an installed delegation Hook")
    elif not hook_path.is_file():
        report.error("delegation proof Hook does not exist: {}".format(hook_path))
    elif (
        isinstance(context, dict)
        and context.get("revision", 0) >= 6
        and re.fullmatch(r"[0-9a-f]{64}", str(proof.get("hook_hash")))
        and hashlib.sha256(hook_path.read_bytes()).hexdigest() != proof["hook_hash"]
    ):
        report.error("delegation proof hook_hash does not match the installed Hook")


def active_global_instructions():
    override = CODEX / "AGENTS.override.md"
    if override.exists() and override.read_text(encoding="utf-8").strip():
        return override
    return CODEX / "AGENTS.md"


def validate_task_context(data, report, check_paths=True, check_freshness=True):
    required = [
        "schema_version", "task_id", "task_type", "risk_level", "goal", "behavior",
        "scope", "sources", "confirmed_decisions", "routing", "playbook", "acceptance",
        "verification", "output_contract", "stop_conditions", "freshness", "revision", "previous_context",
    ]
    if not require_keys(data, required, "task context", report):
        return
    if data["schema_version"] not in {"1.2", "1.3"}:
        report.error("task context schema_version must be 1.2 or 1.3")
    if data["schema_version"] == "1.3":
        validate_intent(data.get("intent"), data, report)
        domain = data.get("intent", {}).get("domain") if isinstance(data.get("intent"), dict) else None
        if domain == "business_project":
            validate_requirements(data.get("requirements"), report)
        elif data.get("requirements") is not None:
            report.error("requirements must be null outside business_project contexts")
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
    if require_keys(
        data["routing"],
        ["root_agent", "delegated_agents", "delegation_names", "selection_reason", "independent_review_required", "independent_review_agents"],
        "routing", report,
    ):
        root_agent = data["routing"]["root_agent"]
        selected = data["routing"]["delegated_agents"]
        delegation_names = data["routing"]["delegation_names"]
        reviewers = data["routing"]["independent_review_agents"]
        if root_agent != ROOT_AGENT:
            report.error("routing.root_agent must be {}".format(ROOT_AGENT))
        selected = validate_string_list(selected, "routing.delegated_agents", report)
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
        required_review = data["risk_level"] in {"high", "critical"}
        if required_review and not data["routing"]["independent_review_required"]:
            report.error("high-risk task context must require independent review")
        if data["routing"]["independent_review_required"] and not reviewers:
            report.error("independent review requires at least one reviewer")
    require_keys(data["playbook"], ["managed", "workspace_id", "change_id", "stage", "worker_contract_source"], "playbook", report)
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
    if isinstance(data["playbook"], dict) and data["playbook"].get("managed"):
        for key in ("workspace_id", "stage", "worker_contract_source"):
            if not data["playbook"].get(key):
                report.error("managed Playbook context requires playbook.{}".format(key))
    sensitive = find_sensitive_keys(data)
    if sensitive:
        report.error("task context contains forbidden sensitive fields: {}".format(", ".join(sensitive)))


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
    if check_paths and not context_path.exists():
        report.error("context_pack does not exist: {}".format(context_path))
    elif check_paths:
        actual_hash = hashlib.sha256(context_path.read_bytes()).hexdigest()
        if actual_hash != data["context_hash"]:
            report.error("context_hash does not match {}".format(context_path))
        try:
            context = json.loads(context_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report.error("cannot load context_pack {}: {}".format(context_path, exc))
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
    if not require_keys(data, ["schema_version", "policy", "cases"], "routing cases", report):
        return
    if data["schema_version"] != "1.3":
        report.error("routing cases schema_version must be 1.3")
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
        ROOT_AGENT_HOOK, ROOT_AGENT_HOOK_WINDOWS, HOOK_RUNTIME_VERIFIER,
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
            expected_commands = [
                'command = \'python3 "{}"\''.format(ROOT_AGENT_HOOK.as_posix()),
                'command_windows = \'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{}"\''.format(ROOT_AGENT_HOOK_WINDOWS.as_posix()),
                'command = \'python3 "{}" --subagent-start\''.format(ROOT_AGENT_HOOK.as_posix()),
                'command_windows = \'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{}" -SubagentStart\''.format(ROOT_AGENT_HOOK_WINDOWS.as_posix()),
                'command = \'python3 "{}" --subagent-stop\''.format(ROOT_AGENT_HOOK.as_posix()),
                'command_windows = \'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{}" -SubagentStop\''.format(ROOT_AGENT_HOOK_WINDOWS.as_posix()),
            ]
            for expected in expected_commands:
                if expected not in hook_block.group(0):
                    report.error("xiaoh root-agent hook command drift: {}".format(expected))
            if not re.search(r'^\[\[hooks\.SubagentStart\]\]\s*$[\s\S]*?^matcher\s*=\s*["\']\.\*["\']\s*$', hook_block.group(0), re.M):
                report.error("xiaoh root-agent hook must include the SubagentStart proof binder")
            if not re.search(r'^\[\[hooks\.SubagentStop\]\]\s*$[\s\S]*?^matcher\s*=\s*["\']\.\*["\']\s*$', hook_block.group(0), re.M):
                report.error("xiaoh root-agent hook must include the SubagentStop proof attestor")

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
        validate_task_context(context, report, check_freshness=not chain)
        digest = hashlib.sha256(current_path.read_bytes()).hexdigest()
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
        if count > 1
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
        business_context = json.loads((SYSTEM_DIR / "task-context.template.json").read_text(encoding="utf-8"))
        business_context["intent"]["domain"] = "business_project"
        business_context["requirements"] = example_requirements()
        business_report = Report()
        validate_task_context(business_context, business_report, check_paths=False)
        validate_requirement_gate(business_context, "implementation", business_report)
        if business_report.errors:
            report.error("valid business requirement gate self-test failed")

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
        validate_requirement_gate(pending_spec, "task_create", pending_report)
        if not any("confirmed Spec+RFC is required" in error for error in pending_report.errors):
            report.error("unconfirmed Spec+RFC task-create denial self-test failed")

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
        validate_requirement_gate(pending_consistency, "openspec_confirmation", consistency_report)
        if not any("consistency review must pass" in error for error in consistency_report.errors):
            report.error("OpenSpec consistency denial self-test failed")

        incomplete_skill = json.loads(json.dumps(business_context))
        incomplete_skill["requirements"]["skill_execution"]["records"][0].update({
            "status": "in_progress", "validation_status": "pending", "evidence": None,
        })
        skill_report = Report()
        validate_task_context(incomplete_skill, skill_report, check_paths=False)
        validate_requirement_gate(incomplete_skill, "member_confirmation", skill_report)
        if not any("lacks completed and validated execution evidence" in error for error in skill_report.errors):
            report.error("explicit Skill completion denial self-test failed")

        retroactive = json.loads(json.dumps(business_context))
        retroactive["requirements"]["retroactive_normalization"] = {"required": True, "status": "in_progress"}
        retroactive_report = Report()
        validate_task_context(retroactive, retroactive_report, check_paths=False)
        validate_requirement_gate(retroactive, "implementation", retroactive_report)
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
            current_hash = hashlib.sha256(current_context_path.read_bytes()).hexdigest()
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-context", type=Path)
    parser.add_argument("--requirement-gate", type=Path)
    parser.add_argument("--action", choices=sorted(ALLOWED_REQUIREMENT_GATE_ACTIONS))
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
    if args.requirement_gate:
        data = load_json(args.requirement_gate, report)
        if not args.action:
            report.error("--requirement-gate requires --action")
        elif data is not None:
            validate_task_context(data, report)
            if not report.errors:
                validate_requirement_gate(data, args.action, report)
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
