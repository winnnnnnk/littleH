---
name: xiaoh-playbook-adapter
description: Bind XiaoH business-project execution to current AI Dev Playbook worker and task-status facts without modifying Playbook.
---

# XiaoH Playbook Adapter

Use `../../runtime/codex/agent-system/playbook_adapter.py` from this Skill directory.

## Rules

- Activate only when the task context explicitly says `playbook.managed=true`.
- XiaoH reads Playbook facts; it does not create a second task state machine or alter Playbook to fit XiaoH.
- Every delegated write or lifecycle action requires a fresh worker JSON and matching task status JSON.
- Bind `xiaoh_workspace_id` separately from `task_workspace_id`.
- A receipt authorizes one declared action inside the worker's `allowed_scope`; it does not authorize Playbook state changes.
- If evidence is missing, stale, changed, incompatible, or outside scope, stop.
- Playbook CLI installation and version changes remain user-only.

## Probe

```bash
python3 ../../runtime/codex/agent-system/playbook_adapter.py probe --mode <auto|enabled|disabled>
```

## Capture an execution receipt

```bash
python3 ../../runtime/codex/agent-system/playbook_adapter.py capture \
  --worker-json <worker.json> \
  --status-json <task-status.json> \
  --output <receipt.json> \
  --action <action> \
  --xiaoh-workspace-id <workspace-id>
```

Pass the receipt path and SHA-256 into the one-time delegation binding. Capture a new receipt whenever worker facts, task state, allowed scope, action, or source files change.

## Verify

```bash
python3 ../../runtime/codex/agent-system/playbook_adapter.py verify \
  --receipt <receipt.json> \
  --expected-sha256 <sha256> \
  --expected-action <action>
```
