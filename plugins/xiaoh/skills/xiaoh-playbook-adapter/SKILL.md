---
name: xiaoh-playbook-adapter
description: Bind XiaoH business-project delegation to the current AI Dev Playbook task and worker contract without modifying Playbook. Use before a formal specialist-Agent delegation in a Playbook-managed Workspace, after worker restart or scope changes, when resuming an old task, or when diagnosing whether the installed Playbook CLI still exposes the read-only status and worker JSON contracts XiaoH requires.
---

# 小H Playbook适配

Treat Playbook as the only execution-state authority. Never modify Playbook source, configuration, task state, OpenSpec, Git, MR, or approval state through this Skill except for the separately authorized managed command that produced the worker context.

Use `../../runtime/codex/agent-system/playbook_adapter.py`, resolved from this Skill directory.

## Activation

Read `integrations.playbook` from XiaoH's configured local JSON before any capture:

- `auto` (default): use this Skill only when the current task carries an explicit Playbook-managed context. A missing CLI means `not_enabled`, not a XiaoH core failure.
- `enabled`: require the adapter probe to be compatible whenever a Playbook-managed action is requested.
- `disabled`: do not probe or capture. A Playbook-managed delegation must fail closed until the user changes the local configuration.

The presence of a `playbook` executable alone never activates this Skill and never converts an unmanaged task into a managed task.

## Diagnose compatibility

Run:

```bash
python3 ../../runtime/codex/agent-system/playbook_adapter.py probe --mode <auto|enabled|disabled>
```

For an actual Playbook-managed delegation, require `status=compatible`. `status=not_enabled` is healthy for standalone XiaoH but does not authorize managed delegation. A missing or incompatible CLI is a blocker for the managed action, not a XiaoH core failure. Report the detected version and missing contract; do not patch Playbook.

## Capture a worker binding

1. Resolve the business Workspace with `$xiaoh:xiaoh-workspace-routing` and require `known`.
2. Use Playbook's managed lifecycle to obtain the current worker JSON. Request JSON and give only `child_worker_context` to the specialist Agent.
3. Immediately capture a read-only full task status JSON:

   ```bash
   playbook workspace task status \
     --workspace-root <workspace-root> \
     --workspace-id <playbook-task-workspace-id> \
     --output json --full > <task-evidence>/playbook-status.json
   ```

4. Save the worker command's complete JSON output at `<task-evidence>/playbook-worker.json`.
   Do not reuse, copy, or `touch` an earlier JSON file. The status file must be generated after the worker file, both must be at most two minutes old, the task must remain non-terminal, and the current member worktree must appear in the status facts. A task-level `blocked` state may coexist with a worker-start-approved member in a multi-member task; the current member worktree is still required.
5. Create the XiaoH binding:

   ```bash
   python3 ../../runtime/codex/agent-system/playbook_adapter.py capture \
     --worker-json <task-evidence>/playbook-worker.json \
     --status-json <task-evidence>/playbook-status.json \
     --output <task-evidence>/xiaoh-playbook-binding.json \
     --action <delegated-action> \
     --xiaoh-workspace-id <stable-xiaoh-workspace-id> \
     --playbook-version "<playbook --version output>"
   ```

6. Read `receipt_path` and `receipt_sha256` from the command result and put them in `task_context.playbook.adapter_receipt` and `adapter_receipt_sha256`. Use `task_workspace_id` for the Playbook task identity and `xiaoh_workspace_id` for XiaoH's stable project/system identity. Never substitute one for the other.
7. Map every delegated Agent to one action in `routing.delegated_actions`. The formal delegation Hook revalidates the receipt, its source hashes, freshness, action, and requirement gate.
8. Immediately before both intent preparation and `SubagentStart`, XiaoH re-runs the read-only Playbook task status command from the receipt and compares the current task identity, non-terminal state, and member worktree. This never advances Playbook state.

## Refresh and failure behavior

- Capture a new binding after worker restart, member change, worktree recreation, scope change, task takeover, task resume, or any material task-status change.
- Bindings expire after 15 minutes by default. Never extend the timestamp or edit a receipt; recapture it.
- Stop when status and worker JSON disagree, the worktree is missing, an allowed scope is not absolute, source hashes changed, the action differs, or Playbook no longer exposes the required fields.
- Do not create a compatibility default for a missing field. Report the incompatible Playbook version and wait for a XiaoH adapter update.
- Keep raw JSON and bindings in Playbook task evidence or the task evidence directory, not in Obsidian.
- Current freshness is an authorization-time rule. Historical closeout verifies that the receipt was fresh when the attested Agent started; it does not require the same receipt to remain younger than 15 minutes forever.
