# XiaoH Agent System

XiaoH 4.0.0 uses a small deterministic governance runtime:

- `task-context.template.json`: schema 1.6 task authority, source digests, scope, effect authorization, requirement state, delegated read/write policy, acceptance, and verification profile.
- `run-record.template.json`: schema 1.2 command evidence, root scope proof, execution, and verification results.
- `validate.py`: validates global installation, task contexts, requirement gates, one-time execution bindings, run records, and task closure.
- `playbook_adapter.py`: binds managed execution to current read-only Playbook worker and task-status evidence.
- `../hooks/guard_task_writes.py`: prepares and attests short-lived root execution bindings and composes repository scope with the Vault guard.
- `routing-cases.json`: representative specialist routing examples.
- `agent-stages.json` and `evolution-policy.json`: evidence counters and human-controlled Agent evolution.

The runtime has no formal review lifecycle. Quality comes from an accepted baseline, precise write scope, appropriate tests and static checks, deterministic evidence, and root-cause repair when a check fails.

Common commands:

```bash
python3 validate.py --self-test
python3 validate.py --task-context <task-context.json>
python3 validate.py --requirement-gate <task-context.json> --action implementation
python3 validate.py --run-record <run-record.json>
python3 validate.py --close-task-context <task-context.json> --run-dir <evidence-dir>
```
