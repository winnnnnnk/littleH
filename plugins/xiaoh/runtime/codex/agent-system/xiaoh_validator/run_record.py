"""XiaoH validator run record boundary."""

from xiaoh_validator.runtime import *

from xiaoh_validator.policy import *
from xiaoh_validator.diagnostics import Report
from xiaoh_validator.evidence import *
from xiaoh_validator.delegation import *

def validate_run_record(data, report, check_paths=True):
    required = [
        "schema_version", "run_id", "task_id", "agent", "role", "selection_reason",
        "context_pack", "context_hash", "started_at", "ended_at", "status", "gates",
        "verification", "outputs", "runtime_evidence", "rework", "metrics", "agent_improvement_candidates",
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
