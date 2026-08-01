"""Global XiaoH installation validation."""

from pathlib import Path

from xiaoh_validator.policy import (
    AGENTS_DIR,
    HOOK_RUNTIME_VERIFIER,
    REGISTERED_AGENTS,
    ROOT_AGENT,
    ROOT_AGENT_HOOK,
    SYSTEM_DIR,
    VAULT_WRITE_HOOK,
)
from xiaoh_validator.diagnostics import Report
from xiaoh_validator.evidence import load_json
from xiaoh_validator.run_record import validate_run_record
from xiaoh_validator.task_context import validate_task_context
from xiaoh_validator.delegation import closure_rejection_reasons


REMOVED_REVIEW_ASSETS = {
    "code_quality_reviewer.toml", "test_integration_verifier.toml", "pki_security_reviewer.toml",
}


def validate_agent_catalog(report):
    if not AGENTS_DIR.is_dir():
        report.error("agents directory does not exist: {}".format(AGENTS_DIR))
        return
    found = {path.stem for path in AGENTS_DIR.glob("*.toml")}
    missing = REGISTERED_AGENTS - found
    if missing:
        report.error("missing managed agents: {}".format(", ".join(sorted(missing))))
    if ROOT_AGENT in found:
        report.error("reserved root identity must not be registered as an Agent")
    stale = {name for name in REMOVED_REVIEW_ASSETS if (AGENTS_DIR / name).exists()}
    if stale:
        report.error("removed review agents are still installed: {}".format(", ".join(sorted(stale))))
    report.details["managed_agents"] = sorted(REGISTERED_AGENTS)


def validate_required_runtime(report):
    required = [ROOT_AGENT_HOOK, VAULT_WRITE_HOOK, HOOK_RUNTIME_VERIFIER, SYSTEM_DIR / "task-context.template.json", SYSTEM_DIR / "run-record.template.json"]
    for path in required:
        if not path.is_file():
            report.error("required runtime file is missing: {}".format(path))


def validate_global_configuration(report=None):
    report = report or Report()
    validate_agent_catalog(report)
    validate_required_runtime(report)
    return report


def load_context_chain(path, report):
    data = load_json(Path(path), report)
    return [data] if isinstance(data, dict) else []


def validate_task_closure(context_path, run_dir, report):
    context_path = Path(context_path)
    context = load_json(context_path, report)
    if not isinstance(context, dict):
        return
    validate_task_context(context, report, context_path=context_path)
    records = []
    for path in sorted(Path(run_dir).glob("*.json")):
        record = load_json(path, report)
        if isinstance(record, dict) and record.get("schema_version") == "1.2" and record.get("task_id") == context.get("task_id"):
            validate_run_record(record, report)
            records.append(record)
    if not records:
        report.error("task closure requires at least one schema 1.2 run record")
    elif not any(not closure_rejection_reasons(record) for record in records):
        report.error("task closure has no accepted completed run record")
