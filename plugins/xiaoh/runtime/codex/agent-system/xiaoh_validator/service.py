"""Command-line service for XiaoH deterministic validation."""

from xiaoh_validator.runtime import *
from xiaoh_validator.diagnostics import Report
from xiaoh_validator.evidence import *
from xiaoh_validator.task_context import validate_task_context, validate_requirement_gate
from xiaoh_validator.run_record import validate_run_record
from xiaoh_validator.delegation import validate_execution_binding, closure_rejection_reasons
from xiaoh_validator.global_validation import validate_global_configuration, validate_task_closure


def self_test(report):
    if canonical_json_hash({"b": 2, "a": 1}) != canonical_json_hash({"a": 1, "b": 2}):
        report.error("canonical JSON hashing is unstable")
    good = {"schema_version": "1.2", "status": "completed", "gates": [{"status": "passed"}], "verification": [{"status": "passed"}], "metrics": {"result_accepted": True}}
    if closure_rejection_reasons(good):
        report.error("accepted run record closure rule is broken")
    bad = copy.deepcopy(good)
    bad["verification"][0]["status"] = "failed"
    if not closure_rejection_reasons(bad):
        report.error("failed verification was not rejected")
    report.details["self_test"] = "passed" if not report.errors else "failed"


def evaluate_runs(directory, agent, report):
    accepted = 0
    total = 0
    for path in sorted(Path(directory).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if data.get("agent") != agent:
            continue
        total += 1
        if not closure_rejection_reasons(data):
            accepted += 1
    report.details["run_evaluation"] = {"agent": agent, "total": total, "accepted": accepted}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--task-context", type=Path)
    parser.add_argument("--previous-task-context", type=Path)
    parser.add_argument("--migrate-task-context", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--requirement-gate", type=Path)
    parser.add_argument("--action")
    parser.add_argument("--execution-binding", type=Path)
    parser.add_argument("--delegated-agent")
    parser.add_argument("--run-record", type=Path)
    parser.add_argument("--close-task-context", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--evaluate-runs", type=Path)
    parser.add_argument("--agent")
    parser.add_argument("--sync-stage-evidence", action="store_true")
    parser.add_argument("--routing-case")
    parser.add_argument("--intent-domain")
    parser.add_argument("--selected-agents")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    report = Report()
    if args.self_test:
        self_test(report)
    elif args.migrate_task_context:
        source = load_json(args.migrate_task_context, report)
        if isinstance(source, dict):
            try:
                migrated = migrate_task_context_15_to_16(source, args.migrate_task_context)
            except ValueError as exc:
                report.error(str(exc))
            else:
                if not args.output:
                    report.error("--migrate-task-context requires --output")
                elif args.output.exists():
                    report.error("migration output must not already exist")
                else:
                    args.output.write_text(json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    report.details["migrated_task_context"] = str(args.output)
    elif args.requirement_gate:
        context = load_json(args.requirement_gate, report)
        if isinstance(context, dict):
            validate_task_context(context, report)
            if not args.action:
                report.error("--requirement-gate requires --action")
            else:
                validate_requirement_gate(context, args.action, report)
    elif args.execution_binding:
        if not args.task_context or not args.delegated_agent or not args.action:
            report.error("--execution-binding requires --task-context, --delegated-agent and --action")
        else:
            context = load_json(args.task_context, report)
            binding = load_json(args.execution_binding, report)
            if isinstance(context, dict) and isinstance(binding, dict):
                validate_execution_binding(binding, context, args.task_context, args.delegated_agent, args.action, report)
    elif args.close_task_context:
        if not args.run_dir:
            report.error("--close-task-context requires --run-dir")
        else:
            validate_task_closure(args.close_task_context, args.run_dir, report)
    elif args.task_context:
        context = load_json(args.task_context, report)
        if isinstance(context, dict):
            validate_task_context(context, report, check_freshness=False)
    elif args.run_record:
        record = load_json(args.run_record, report)
        if isinstance(record, dict):
            validate_run_record(record, report)
    elif args.evaluate_runs:
        if not args.agent:
            report.error("--evaluate-runs requires --agent")
        else:
            evaluate_runs(args.evaluate_runs, args.agent, report)
    elif args.routing_case:
        selected = {item for item in (args.selected_agents or "").split(",") if item}
        from xiaoh_validator.policy import REGISTERED_AGENTS
        unknown = selected - REGISTERED_AGENTS
        if unknown:
            report.error("routing case selects unregistered agents: {}".format(", ".join(sorted(unknown))))
        report.details["routing_case"] = {"name": args.routing_case, "selected_agents": sorted(selected)}
    else:
        validate_global_configuration(report)
    return report.emit(args.json)
