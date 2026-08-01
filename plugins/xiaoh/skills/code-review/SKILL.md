---
name: code-review
description: Perform one user-requested review of changes against a fixed commit, branch, tag, or merge-base, separating repository-standards findings from confirmed-spec findings. Use only when the user explicitly asks to review a branch, pull request, work-in-progress diff, or changes since a named fixed point.
---

# Review one fixed diff

Review once and return findings. Do not repair code, schedule another review, create a Campaign, or mutate any gate or task state.

## Pin the comparison

1. Resolve the fixed point with Git before inspecting the diff.
2. Compare its merge-base with `HEAD` unless the user explicitly requests another comparison.
3. Record the exact resolved commit and commit list.
4. Stop with a clear error when the ref is invalid. Report an empty diff as such and finish.

If the user did not identify or confirm a fixed point, ask for it. Do not silently choose a moving baseline.

## Locate evidence

Find repository standards in `AGENTS.md`, `CONTRIBUTING.md`, documented coding rules, and applicable directory-local instructions. Tool-enforced formatting alone is not a review finding.

Find the confirmed requirement source from an explicit user path, linked issue or PRD, accepted Spec+RFC, OpenSpec change, or other named baseline. If none exists, report `no confirmed spec source` on the Spec axis. Do not invent requirements.

## Review both axes

Inspect the same fixed diff once.

### Standards

Report concrete correctness, security, maintainability, compatibility, and repository-rule violations. Include file and line, impact, and the evidence that makes the finding actionable. Treat heuristic smells as judgment calls and let documented repository decisions override generic preferences.

### Confirmed spec

Report missing or partial requirements, incorrect behavior, and unsourced scope expansion. Cite the confirmed requirement or state that no confirmed spec source exists.

Exclude findings outside the diff unless the changed code directly activates an existing defect. Do not report speculative issues that cannot be demonstrated from code or evidence.

## Output and finish

Order findings by severity within each axis, but keep the axes separate. For every finding provide severity, location, impact, and concise evidence. If an axis has no findings, say so explicitly.

Finish after the report. Completion means the fixed point was resolved, the non-empty diff was inspected once on both axes, missing spec evidence was disclosed, and no mutation or follow-up review was initiated.
