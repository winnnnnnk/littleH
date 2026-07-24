---
name: xiaoh-requirement-baseline
description: Maintain one evidence-backed, continuously evolving business requirement and design baseline per topic in XiaoH's configured Obsidian Vault. Use immediately after the user confirms, corrects, rejects, or supersedes a material business rule or result-changing design rationale; when accepted evidence resolves a previously open business question; or when the user asks to sync confirmed business discussion, requirement points, or design logic to Obsidian.
---

# 小H业务需求与设计基线

Treat this as a `business_project` knowledge write. It does not authorize repository changes, task lifecycle transitions, or new business decisions.

1. Run `$xiaoh:xiaoh-workspace-routing` against the authoritative task Workspace. Require `known`; stop on `unknown` or `conflict`.
2. Resolve the only Vault from `~/.xiaoh/config.json` and enforce the Vault path gate.
3. Classify every material input as `question`, `hypothesis`, `fact_correction`, `business_decision`, or `execution_instruction`. Record a rule as confirmed only from an explicit result-changing business decision, an accepted artifact, or evidence-backed fact correction. Keep recommendations, questions, hypotheses, and unsupported defaults pending.
4. Read only the relevant accepted conversation turns, Spec/RFC or OpenSpec revision, code/data evidence, existing topic baseline, and task page. Preserve conflicts and unknowns instead of reconciling them by guess.
5. Maintain one canonical page per business topic. Prefer an existing topic page; otherwise create `01-项目/<project>/需求与方案/<system>/<topic>.md` from `03-需求与方案/业务逻辑基线模板.md`. Do not create one page per conversation or confirmation point.
6. Give every point a stable ID. Use exactly one state: `pending`, `confirmed`, `superseded`, or `rejected`. Preserve the old point and link `superseded_by` when semantics change; never silently rewrite history.
7. For each point record the business rule, result-changing design rationale, evidence or confirmation source, applicability and exclusions, acceptance condition, affected Spec/RFC/OpenSpec/tasks, and remaining uncertainty. Fixed values require a sourced meaning and validation.
8. Update the topic summary, confirmed flow, failure and boundary behavior, pending decisions, traceability, and revision history. Increment `baseline_revision` only when business or design semantics change.
9. Link the canonical baseline from the corresponding requirement/task page. Keep the repository Spec/RFC and OpenSpec as implementation facts; the Vault page is a recall baseline and must link to, not replace, those artifacts.
10. Perform this update immediately after confirmation and before deriving or revising lifecycle artifacts from that decision. Task closeout, project progress, daily push, and knowledge promotion may reference the page but must not reconstruct it later.
11. Run `python3 scripts/validate_baseline.py <baseline.md>` after every update. When a prior revision is available, also pass `--previous <previous.md>` so illegal state reversal and missing supersession links fail deterministically.
12. Report the resolved Workspace ID, configured Vault root, exact written files, changed point IDs and states, evidence basis, material conflicts, uncertainties, and recommended conclusion.

Do not write confirmed business semantics when the source interaction, project ownership, or evidence is ambiguous.
