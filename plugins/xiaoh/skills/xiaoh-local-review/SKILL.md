---
name: xiaoh-local-review
description: >-
  Converge implementation work through multiple local specialist-review rounds and bind the accepted
  result to the current Git commit or artifact digest before delivery. Use after code or other
  implementation artifacts are complete, after review findings are repaired, before standalone
  delivery or task closeout, and before a Playbook-managed handoff, MR Ready transition, or remote
  AI review request.
---

# xiaoh本地评审闭环

Keep this gate independent of Playbook. Playbook may govern remote delivery, but it never replaces
local specialist judgment.

## Select the mode

- Use `standalone` when the current project or task is not explicitly Playbook-managed.
- Use `playbook_managed` only when the task context says `playbook.managed=true`.
- Do not select a mode from CLI availability. A managed task fails closed when Playbook is
  unavailable; it never falls back silently to `standalone`.

## Run the review loop

1. Finish implementation self-checks and the applicable tests.
2. Bind the review subject to one repository HEAD or one immutable artifact SHA-256.
3. Select at least two judgment roles that did not implement the subject:
   - always use `code_quality_reviewer` and `test_integration_verifier` for code;
   - add `java_architect` for material boundary, compatibility, or lifecycle changes;
   - add `pki_domain_expert` and `pki_security_reviewer` for applicable PKI semantics or security.
4. For every role and round, prepare a new `xiaoh-delegation-binding/v1`. The trusted
   `--prepare` response generates the nonce-derived
   `<task_name_prefix>__r<round>__<nonce-prefix>` task name; use the returned `tool_input`
   exactly. Never reuse an Agent session, binding, Playbook receipt, proof, run record, or
   concrete task name.
   In `playbook_managed` mode, capture a fresh `local_review` receipt from the current task status
   and immutable review subject for each role. Use action `code_review` for
   `code_quality_reviewer`, action `verification` for `test_integration_verifier`, and
   `purpose=local_review`. Pass the subject file as the receipt's only artifact and use
   `playbook.local_review_subject_sha256` as the execution binding's `subject_digest`. Do not reuse
   the implementation worker receipt; a
   `main_agent_direct` implementation topology does not suppress independent review.
5. Run one multi-role review round. Keep each role's raw report in the task evidence directory.
6. Reconcile findings, repair the implementation, rerun affected verification, and update the
   immutable subject when it changed.
7. Run a convergence round with the configured independent reviewers. Repeat repair and convergence
   while any blocking finding remains.
8. Create exactly one final `xiaoh-local-review/v1` manifest for the current task revision. Keep
   superseded round evidence for audit, but do not treat it as current acceptance.
9. Validate it:

   ```text
   python3 <CODEX_HOME>/agent-system/validate.py \
     --local-review-manifest <absolute-manifest-path> \
     --task-context <absolute-current-context-path>
   ```

Do not ask the user to drive review rounds or select technical reviewers.

## Manifest contract

Use this shape:

```json
{
  "schema_version": "xiaoh-local-review/v1",
  "task_id": "task-id",
  "task_context": {
    "path": "/absolute/task-context.json",
    "authority_hash": "64-lowercase-hex"
  },
  "mode": "standalone",
  "subject": {
    "kind": "git_commit",
    "repository": "/absolute/repository",
    "artifact_path": null,
    "value": "40-or-64-lowercase-hex"
  },
  "implementers": ["java_implementer"],
  "rounds": [
    {
      "number": 1,
      "subject_value": "40-or-64-lowercase-hex",
      "reviewers": ["code_quality_reviewer", "test_integration_verifier"],
      "verdict": "changes_requested",
      "blocking_findings": 1,
      "evidence": [
        {
          "reviewer": "code_quality_reviewer",
          "path": "/absolute/review-report.json",
          "sha256": "64-lowercase-hex"
        },
        {
          "reviewer": "test_integration_verifier",
          "path": "/absolute/test-report.json",
          "sha256": "64-lowercase-hex"
        }
      ]
    },
    {
      "number": 2,
      "subject_value": "40-or-64-lowercase-hex",
      "reviewers": ["code_quality_reviewer", "test_integration_verifier"],
      "verdict": "passed",
      "blocking_findings": 0,
      "evidence": [
        {
          "reviewer": "code_quality_reviewer",
          "path": "/absolute/review-report-round-2.json",
          "sha256": "64-lowercase-hex"
        },
        {
          "reviewer": "test_integration_verifier",
          "path": "/absolute/test-report-round-2.json",
          "sha256": "64-lowercase-hex"
        }
      ]
    }
  ],
  "final_status": "passed",
  "completed_at": "RFC-3339 timestamp"
}
```

Provide exactly one evidence entry per reviewer in every round.
Every evidence path must contain a `xiaoh-local-review-evidence/v1` report:

```json
{
  "schema_version": "xiaoh-local-review-evidence/v1",
  "task_id": "task-id",
  "context_hash": "64-lowercase-hex",
  "reviewer": "code_quality_reviewer",
  "round": 2,
  "subject_value": "40-or-64-lowercase-hex",
  "verdict": "passed",
  "blocking_findings": 0,
  "execution_binding_hash": "64-lowercase-hex",
  "attested_message": "exact final Agent message containing the canonical claim and delegation receipt",
  "run_record": {
    "path": "/absolute/authenticated-run-record.json",
    "sha256": "64-lowercase-hex"
  }
}
```

Each evidence report keeps that reviewer's own `verdict` and `blocking_findings`.
The manifest round is an aggregate, not a value copied into every report:

- if any reviewer returns `changes_requested`, the round verdict is `changes_requested`;
- otherwise the round verdict is `passed`;
- round `blocking_findings` is the sum of all reviewer-reported blocking findings;
- the final round passes only when every configured reviewer passes with zero blocking findings.

The authenticated schema 1.2 run record must be unique to that reviewer and round, bind
`context_hash` to the schema 1.6 `authority_hash`, bind the same
round, subject, verdict, finding count, and canonical claim hash in `outputs.local_review`, and carry passed
`independent_review` and verification evidence. Never wrap or copy one run record to simulate
multiple rounds.

For schema 1.6, `execution_binding_hash` must equal the attested proof's binding hash. The
binding itself must carry the same review round, `local_review` purpose, and immutable subject
digest. A concrete task name or binding hash cannot be reused by another review round.

The final Agent message must contain exactly one line in this form, using compact JSON with keys
sorted lexicographically, plus the exact delegation receipt required by the runtime Hook:

```text
xiaoh-local-review-claim: {"blocking_findings":0,"context_hash":"...","reviewer":"code_quality_reviewer","round":2,"schema_version":"xiaoh-local-review-claim/v1","subject_value":"...","task_id":"task-id","verdict":"passed"}
```

Store that exact final message as `attested_message`. Its SHA-256 must equal the attested schema 1.3
delegation proof's `last_message_hash`. The proof must also bind the consumed execution binding and,
in managed mode, the Playbook receipt that was fresh when the Agent started. The same Agent session,
task name, execution binding, transcript, proof, run ID, or run
record content cannot represent more than one review result.

`git_commit` is valid only for a single scoped repository and requires a clean worktree. For
multi-repository work, generate one deterministic artifact manifest listing every repository and
reviewed commit, bind `subject.kind=artifact_digest`, set `subject.artifact_path` to that manifest,
and use its SHA-256 as `subject.value`. An artifact subject must always name the actual scoped file;
a digest without content is invalid.

Use this exact multi-repository manifest shape; repository paths must cover
`task_context.scope.repositories` exactly once, and every worktree must be clean at the declared
HEAD:

```json
{
  "schema_version": "xiaoh-repository-set/v1",
  "repositories": [
    {
      "path": "/absolute/repository-a",
      "commit": "40-or-64-lowercase-hex"
    },
    {
      "path": "/absolute/repository-b",
      "commit": "40-or-64-lowercase-hex"
    }
  ]
}
```

## Deliver by mode

For `standalone`:

- Treat a validated local manifest as the mandatory implementation quality gate.
- Use remote MR review only when the repository policy or available integration requires it.
- Keep human merge approval as an external boundary when the repository requires approval.
- Close the task with XiaoH run records, the final manifest, verification, immediate closeout, and
  project progress refresh.

For `playbook_managed`:

- Validate the local manifest before submitting `ready_for_integration=true`, marking an MR Ready, or
  delegating remote AI review.
- Let Playbook remain the sole authority for task state, MR/HEAD review state, pipeline, human
  Approval, archive, merge, and cleanup.
- Treat `changes_requested` as a return to implementation, affected tests, and another local
  convergence round before requesting review for the new HEAD.
- Treat `disabled`, `skipped`, and `accepted_without_verdict` as audited exceptions, never as local
  quality pass or human Approval. Require an explicit project policy or user-approved exception for
  them.

## Invalidate stale evidence

- Invalidate the final manifest when the reviewed Git HEAD or artifact digest changes.
- Do not invalidate accepted historical rounds merely because a Playbook receipt later expires;
  verify `captured_at <= started_at <= expires_at` from the attested proof instead.
- Create a new stable task-context revision when goal, role, action, scope, Workspace, or managed
  task identity changes. Receipt refresh, a new review round, or a new subject digest does not change
  the stable `authority_hash`.
- Do not reuse remote review evidence across a changed effective code HEAD.
- Preserve superseded evidence as audit history; never edit it to match the new subject.
