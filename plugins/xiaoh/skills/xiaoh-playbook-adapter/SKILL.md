---
name: xiaoh-playbook-adapter
description: Bind XiaoH business-project delegation to current AI Dev Playbook task facts without modifying Playbook. Use a status_review binding for pre-worker read-only review actions and a worker binding for implementation or other non-read-only actions.
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

`--prepare` accepts a JSON envelope containing the candidate `tool_input` and a sibling `binding`
object. For managed execution, the binding object carries `review_round`, `purpose`,
`subject_digest`, `playbook_adapter_receipt`, and `playbook_adapter_receipt_sha256`. Use the
returned `tool_input` exactly once; it contains the generated `execution_binding` and
`binding_hash` headers. Do not reuse the candidate input or append those headers manually.

Before XiaoH requests or accepts a managed lifecycle transition into `handoff`, `remote_review`, or
`ready_to_finalize`, run `$xiaoh:xiaoh-local-review` and require its final manifest to validate
against the current task context and current code subject. These names are Playbook lifecycle
phases, not adapter `--action` values. The adapter remains a read-only delegation binding and does
not advance those phases. This is XiaoH's local quality gate; it does not replace or copy Playbook
state.

## Diagnose compatibility

Run:

```bash
python3 ../../runtime/codex/agent-system/playbook_adapter.py probe --mode <auto|enabled|disabled>
```

The command-only result is `status=available`: it proves that the CLI surface exists, but it does not claim that the current status payload is compatible. After obtaining the fresh worker and status files, run:

```bash
python3 ../../runtime/codex/agent-system/playbook_adapter.py probe \
  --mode <auto|enabled> \
  --worker-json <task-evidence>/playbook-worker.json \
  --status-json <task-evidence>/playbook-status.json
```

For an actual Playbook-managed delegation, require this evidence-backed probe to return `status=compatible`. `status=available` or `status=not_enabled` is healthy for standalone XiaoH but does not authorize managed delegation. A missing or incompatible CLI or payload is a blocker for the managed action, not a XiaoH core failure. Report the detected version and missing contract; do not patch Playbook.

## Choose one binding kind

- `status_review`: only for `read_only_analysis`, `design_review`, `spec_rfc_review`, and `openspec_consistency_review`. It requires either the complete `task_truth_v1` contract or the dedicated public status contract with a bound Task Truth source and current Git identity. It does not require or emulate `worker start`; legacy `current_state` remains compatible only with worker bindings.
- `worker`: required for every action outside that whitelist, including implementation, verification, operations, task start, authoring, confirmation, and code review.

Never use `status_review` as a fallback for a missing worker contract when the delegated action can write files or advance lifecycle state.

## Capture a status review binding

1. Resolve the business Workspace with `$xiaoh:xiaoh-workspace-routing` and require `known`.
2. Prepare the schema 1.6 stable task context with exact Playbook task identity, member,
   member worktree and allowed scope. Do not put binding kind, reviewed artifacts, receipt paths,
   worker sources or concrete delegated actions into the stable context.
3. Capture a fresh task status JSON after the task context. Compatible Playbook versions may
   return either a dedicated public projection or the older full status wrapper:

   ```bash
   playbook workspace task status \
     --workspace-root <workspace-root> \
     --workspace-id <playbook-task-workspace-id> \
     --output json --full > <task-evidence>/playbook-status.json
   ```

4. Create the binding from that status, the task context, and every reviewed artifact:

   ```bash
   python3 ../../runtime/codex/agent-system/playbook_adapter.py capture-review \
     --task-context <task-evidence>/task-context.json \
     --status-json <task-evidence>/playbook-status.json \
     --artifact <member-worktree>/docs/spec-rfc.md \
     --output <task-evidence>/xiaoh-playbook-binding.json \
     --action spec_rfc_review \
     --playbook-version "<playbook --version output>"
   ```

5. Pass `receipt_path` as `playbook_adapter_receipt`, `receipt_sha256` as
   `playbook_adapter_receipt_sha256`, and the receipt's
   `playbook.artifact_manifest_sha256` as `subject_digest` into the one-time execution-binding
   preparation. The receipt already carries `binding_kind=status_review` and the complete immutable
   artifact set. Do not copy either into the stable task context. A receipt refresh therefore leaves
   the stable `authority_hash` unchanged.
6. Validate the stable task context and the generated execution binding. Immediately before
   `SubagentStart`,
   re-read live task status, require its captured task/member semantics and current Git identity to
   match the fingerprint, and re-hash every declared artifact.

`status_review` does not approve the artifact, create OpenSpec, start a worker, or modify Playbook state.

## Capture a worker binding

1. Resolve the business Workspace with `$xiaoh:xiaoh-workspace-routing` and require `known`.
2. Use Playbook's managed lifecycle to obtain the current worker JSON. Request JSON and give only `child_worker_context` to the specialist Agent.
3. Immediately capture the current task status JSON. Compatible Playbook versions may return
   either a dedicated public projection or the older full status wrapper:

   ```bash
   playbook workspace task status \
     --workspace-root <workspace-root> \
     --workspace-id <playbook-task-workspace-id> \
     --output json --full > <task-evidence>/playbook-status.json
   ```

4. Save the worker command's complete JSON output at `<task-evidence>/playbook-worker.json`.
   Do not reuse, copy, or `touch` an earlier JSON file. The status file must be generated after the
   worker file, both must be at most two minutes old, and the task must remain non-terminal. For the
   dedicated public projection, the adapter binds `task_truth_path` and cross-checks the projected
   member branch and HEAD against the worker worktree. For a compact status wrapper with
   `evidence.raw_json_path`, it binds and validates both the wrapper and raw status file. A task-level
   `blocked` state may coexist with a worker-start-approved member in a multi-member task.
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

6. Read `receipt_path` and `receipt_sha256` from the command result and pass them to
   `block_reserved_root_agent.py --prepare` as execution-binding parameters. Use
   `task_workspace_id` for the Playbook task identity and `xiaoh_workspace_id` for XiaoH's stable
   project/system identity. Never substitute one for the other and never write the receipt back to
   the stable task context.
7. Map every delegated Agent to one action in
   `routing.delegation_policies.<role>.action`. The formal delegation Hook writes that action and
   the current receipt into one `xiaoh-delegation-binding/v1`, then revalidates its source hashes,
   freshness and requirement gate.
8. Immediately before both execution-binding preparation and `SubagentStart`, XiaoH re-runs the
   read-only Playbook task status command from the receipt and compares the current task identity,
   non-terminal state and member worktree. This never advances Playbook state.

## Refresh and failure behavior

- Capture a new binding after worker restart, member change, worktree recreation, scope change, task takeover, task resume, or any material task-status change.
- Capture a new `status_review` binding after any declared artifact-set or artifact-content change,
  or any task/member/worktree/phase/terminal/closure/cleaned-state change. A stable authority change
  also requires a new task-context revision before capture.
- Bindings expire after 15 minutes by default. Never extend the timestamp or edit a receipt; recapture it.
- Stop when status and worker JSON disagree, the worktree is missing, an allowed scope is not absolute, source hashes changed, the action differs, or Playbook no longer exposes the required fields.
- Do not create a compatibility default for a missing field. Report the incompatible Playbook version and wait for a XiaoH adapter update.
- Treat remote `disabled`, `skipped`, and `accepted_without_verdict` as Playbook-recorded exception
  decisions, not as local quality pass or human Approval. XiaoH may accept them only when an explicit
  project policy or impact-aware user decision authorizes the exception.
- Keep raw JSON and bindings in Playbook task evidence or the task evidence directory, not in Obsidian.
- Current freshness is an authorization-time rule. Historical closeout verifies
  `captured_at <= agent_started_at <= expires_at` from the consumed execution binding and attested
  proof; it does not require the same receipt to remain younger than 15 minutes forever.
