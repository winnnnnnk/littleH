---
name: xiaoh-requirement-routing
description: >-
  Route a business-project request to openspec_only, spec_rfc_then_openspec, or class_skill and
  determine the required lifecycle gates. Use after Workspace resolution, project-history recall, and
  current-fact reconciliation, and before final
  member scope, Playbook task creation, OpenSpec authoring or confirmation, or implementation. Also use
  when the user explicitly requests spec-rfc, when an existing OpenSpec may have skipped an overall
  requirements baseline, or when substantive requirement changes may invalidate OpenSpec consistency.
---

# 路由需求工件

Keep routing in the current root thread. Never create or delegate to an Agent named `xiaoh`.

## Produce one route

Require task-context schema 1.5 with `memory_recall.status=completed`. The recall manifest must match
the resolved Workspace, contain current fact sources, and record any material history-versus-current
conflicts. Do not route from daily digests alone or treat recalled Obsidian content as permission.

Return all four fields:

```yaml
route: openspec_only | spec_rfc_then_openspec | class_skill
reason: <evidence-based reason>
risk_signals: []
required_gates: []
```

Choose `spec_rfc_then_openspec` when any signal exists: multiple changes, cross-stage/module/repository scope, migration or compatibility, transaction/consistency/idempotency/recovery, permission/security/sensitive data/PKI/key semantics, architecture/model/interface changes, multiple viable designs, phased delivery, an explicit design/Spec/RFC request, or explicit `$spec-rfc` invocation.

Choose `openspec_only` only when all are true: one repository, local change, clear goal/scope/acceptance, no durable semantic or cross-module contract change, no high-risk data/security/transaction/compatibility strategy, and one OpenSpec can fully describe and verify the result. Record a non-empty bypass reason.

Choose `class_skill` for governed A/B/C formal artifacts. The class artifact remains authoritative; use Spec+RFC only for analysis or gap filling unless the class workflow explicitly selects it.

`requirement-structuring` may clean up ambiguous input before routing but never counts as the accepted baseline.

## Enforce progression

Allow read-only code/document exploration and candidate impact analysis before baseline confirmation.

For `spec_rfc_then_openspec`:

1. Execute `$spec-rfc` completely from the root thread.
2. Run `$xiaoh:spec-rfc-reviewer` against the complete current revision. Absorb findings, revise, and repeat until it grants `OPENSPEC_READY`.
3. Run the `spec_rfc_confirmation` validator action, then present the reviewed Spec+RFC to the user for confirmation.
4. Only then confirm final member scope and create the workspace task.
5. Derive each member OpenSpec from the accepted Spec+RFC and trace FR/NFR through requirements/scenarios, tasks, implementation, and verification.
6. Execute `$xiaoh:spec-rfc-openspec-consistency-review`. Absorb findings, revise OpenSpec, and repeat until it returns `PASS` for the current Spec+RFC revision.
7. Confirm OpenSpec and start implementation only after the applicable gate passes.

These are two separate lifecycle reviews. The source-quality review cannot replace the OpenSpec consistency review, and the consistency review cannot run before OpenSpec artifacts exist.

Record explicitly requested Skills as started, completed, validated, and confirmed. Reading or imitating a Skill is not completion.

## Recover omissions and changes

- If a task or OpenSpec exists without a required Spec+RFC, set `retroactive_normalization.required=true`, pause approval and implementation, reconstruct the baseline from existing evidence, confirm it, review consistency, then mark normalization completed.
- If overall business, architecture, data, or security semantics change, increment the Spec+RFC revision and reset affected OpenSpec consistency to `pending`.
- Do not reset Spec+RFC confirmation when only task status, implementation detail, or verification evidence changes.

Before a governed action, run the installed validator with `--requirement-gate <task-context> --action <action>` and stop on failure. Governed actions include final member confirmation, task creation, OpenSpec authoring and confirmation, task start, and implementation.
