"""XiaoH validator run record boundary."""

import hashlib
import json
from pathlib import Path
import re

from xiaoh_validator.policy import (
    AGENTS_DIR,
    ALLOWED_GATE_STATUS,
    ALLOWED_RUN_STATUS,
    ALLOWED_VERIFICATION_STATUS,
    CODEX,
    ROOT_AGENT,
)
from xiaoh_validator.evidence import (
    parse_timestamp,
    path_is_covered,
    require_keys,
    task_authority_hash,
    validate_result_entries,
    validate_string_list,
)
from xiaoh_validator.delegation import validate_delegation_proof
from xiaoh_validator.schemas import ROOT_SCOPE_PROOF_SCHEMA, VERIFICATION_EVIDENCE_SCHEMA

def validate_run_record(data, report, check_paths=True):
    required = [
        "schema_version", "run_id", "task_id", "agent", "role", "selection_reason",
        "context_pack", "context_hash", "started_at", "ended_at", "status", "gates",
        "verification", "outputs", "runtime_evidence", "rework", "metrics", "agent_improvement_candidates",
        "execution_evidence",
    ]
    if not require_keys(data, required, "run record", report):
        return
    if (
        not isinstance(data["schema_version"], str)
        or data["schema_version"] not in {"1.1", "1.2"}
    ):
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
    verification_ids = set()
    verification_by_id = {}
    entries = data["verification"]
    if not isinstance(entries, list):
        report.error("verification must be a list")
    else:
        keys = [
            "id", "category", "command", "status", "summary", "exit_code",
            "started_at", "ended_at", "evidence_path", "evidence_sha256",
        ]
        for index, entry in enumerate(entries):
            label = "verification[{}]".format(index)
            if not require_keys(entry, keys, label, report):
                continue
            for key in ("id", "category", "command", "status", "summary", "started_at", "ended_at", "evidence_path", "evidence_sha256"):
                if not isinstance(entry[key], str) or not entry[key].strip():
                    report.error("{}.{} must be a non-empty string".format(label, key))
            verification_id = entry["id"]
            if isinstance(verification_id, str) and verification_id in verification_ids:
                report.error("verification id must be unique: {}".format(verification_id))
            if isinstance(verification_id, str):
                verification_ids.add(verification_id)
                verification_by_id[verification_id] = entry
            if not isinstance(entry["status"], str) or entry["status"] not in ALLOWED_VERIFICATION_STATUS:
                report.error("{}.status must be one of {}".format(label, sorted(ALLOWED_VERIFICATION_STATUS)))
            if not isinstance(entry["exit_code"], int) or isinstance(entry["exit_code"], bool):
                report.error("{}.exit_code must be an integer".format(label))
            item_started = parse_timestamp(entry["started_at"], label + ".started_at", report)
            item_ended = parse_timestamp(entry["ended_at"], label + ".ended_at", report)
            if item_started and item_ended and item_ended < item_started:
                report.error("{}.ended_at must not be earlier than started_at".format(label))
            if item_started and started and item_started < started:
                report.error("{} starts before the run".format(label))
            if item_ended and ended and item_ended > ended:
                report.error("{} ends after the run".format(label))
            evidence_path = Path(str(entry["evidence_path"])).expanduser()
            evidence_hash = str(entry["evidence_sha256"])
            if not re.fullmatch(r"[0-9a-f]{64}", evidence_hash):
                report.error("{}.evidence_sha256 must be a lowercase SHA-256 digest".format(label))
            if entry["status"] == "passed" and entry["exit_code"] != 0:
                report.error("{} passed verification requires exit_code=0".format(label))
            if check_paths:
                if not evidence_path.is_absolute():
                    report.error("{}.evidence_path must be absolute".format(label))
                elif not evidence_path.is_file():
                    report.error("verification evidence does not exist: {}".format(evidence_path))
                elif re.fullmatch(r"[0-9a-f]{64}", evidence_hash) and hashlib.sha256(evidence_path.read_bytes()).hexdigest() != evidence_hash:
                    report.error("verification evidence hash does not match: {}".format(evidence_path))
                else:
                    _validate_verification_evidence(
                        evidence_path, entry, data, context, report
                    )
    if not isinstance(data["agent_improvement_candidates"], list):
        report.error("agent_improvement_candidates must be a list")
    if data.get("status") == "completed":
        for key in ("gates", "verification"):
            if not isinstance(data.get(key), list) or not data[key]:
                report.error("completed run record requires non-empty {}".format(key))
        if isinstance(context, dict):
            required_items = {
                item.get("id"): item
                for item in context.get("verification", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("required") is True
            }
            missing = set(required_items) - verification_ids
            if missing:
                report.error("completed run record lacks required verification ids: {}".format(", ".join(sorted(missing))))
            for verification_id, expected in required_items.items():
                actual = verification_by_id.get(verification_id)
                if not actual:
                    continue
                if actual.get("command") != expected.get("command") or actual.get("category") != expected.get("category"):
                    report.error("verification {} does not match task context".format(verification_id))
                if actual.get("status") != "passed":
                    report.error("required verification {} did not pass".format(verification_id))
            if context.get("task_type") == "implementation" and data.get("agent") == ROOT_AGENT:
                _validate_root_execution_evidence(
                    data.get("execution_evidence"), data, context, report, check_paths
                )
    if not isinstance(data.get("outputs"), dict):
        report.error("outputs must be a JSON object")
    elif data.get("status") == "completed" and data.get("schema_version") == "1.2":
        if require_keys(
            data["outputs"],
            ["conclusion", "changed_scope", "verification_summary", "unresolved_items"],
            "completed run record outputs",
            report,
        ):
            if not isinstance(data["outputs"]["conclusion"], str) or not data["outputs"]["conclusion"].strip():
                report.error("completed run record outputs.conclusion must be a non-empty string")
            for key in ("changed_scope", "verification_summary", "unresolved_items"):
                validate_string_list(
                    data["outputs"][key], "outputs.{}".format(key), report
                )
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
    if (
        not isinstance(data["rework"]["count"], int)
        or isinstance(data["rework"]["count"], bool)
        or data["rework"]["count"] < 0
    ):
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


def _validate_root_execution_evidence(value, record, context, report, check_paths):
    if not require_keys(
        value,
        ["scope_proof_path", "scope_proof_sha256"],
        "execution_evidence",
        report,
    ):
        return
    proof_path = Path(str(value["scope_proof_path"])).expanduser()
    proof_hash = value["scope_proof_sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", str(proof_hash)):
        report.error("execution_evidence.scope_proof_sha256 must be a lowercase SHA-256 digest")
        return
    if not check_paths:
        return
    if not proof_path.is_absolute() or not proof_path.is_file():
        report.error("root scope proof does not exist: {}".format(proof_path))
        return
    if hashlib.sha256(proof_path.read_bytes()).hexdigest() != proof_hash:
        report.error("root scope proof hash does not match")
        return
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report.error("root scope proof is invalid JSON: {}".format(exc))
        return
    if proof.get("schema_version") != ROOT_SCOPE_PROOF_SCHEMA:
        report.error("root scope proof schema is not supported")
    if proof.get("task_id") != record.get("task_id"):
        report.error("root scope proof task_id does not match")
    if proof.get("context_hash") != record.get("context_hash"):
        report.error("root scope proof context_hash does not match")
    if proof.get("status") != "passed" or proof.get("scope_violations") or proof.get("preexisting_change_violations"):
        report.error("root scope proof did not pass")
    for item in record.get("verification", []):
        evidence_path = Path(str(item.get("evidence_path", ""))).expanduser()
        if not evidence_path.is_file():
            continue
        try:
            verification_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if verification_evidence.get("binding_hash") != proof.get("binding_hash"):
            report.error("verification evidence binding_hash does not match root scope proof")
    if sorted(proof.get("changed_paths", [])) != sorted(record.get("outputs", {}).get("changed_scope", [])):
        report.error("outputs.changed_scope does not match root scope proof")


def _validate_verification_evidence(path, entry, record, context, report):
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report.error("verification evidence is invalid JSON: {}".format(exc))
        return
    if evidence.get("schema_version") != VERIFICATION_EVIDENCE_SCHEMA:
        report.error("verification evidence schema is not supported")
    expected = {
        "task_id": record.get("task_id"),
        "context_hash": record.get("context_hash"),
        "verification_id": entry.get("id"),
        "category": entry.get("category"),
        "command": entry.get("command"),
        "exit_code": entry.get("exit_code"),
        "started_at": entry.get("started_at"),
        "ended_at": entry.get("ended_at"),
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            report.error("verification evidence {} does not match run record".format(key))
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("binding_hash"))):
        report.error("verification evidence binding_hash is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("output_sha256"))):
        report.error("verification evidence output_sha256 is invalid")
    if isinstance(context, dict):
        source = next(
            (item for item in context.get("verification", []) if isinstance(item, dict) and item.get("id") == entry.get("id")),
            None,
        )
        if not source or evidence.get("expected") != source.get("expected"):
            report.error("verification evidence expected result does not match task context")
