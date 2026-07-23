---
name: xiaoh-project-progress
description: Maintain an evidence-backed current project progress snapshot in XiaoH's configured Obsidian Vault. Use after a task or milestone closeout, when project status changes, when a project dashboard is missing or stale, or when the user asks what is completed, active, blocked, risky, and next for a project.
---

# 小H项目进度维护

Maintain `01-项目/<project>/项目进度.md` as the current-state view. Daily records remain the chronological history.

1. Resolve and validate the configured Vault and an existing project identity. Do not infer a project from similar names.
2. Read only accepted closeout records, linked requirement/task pages, and authoritative managed-task status needed for the snapshot. Do not reconstruct progress from unverified repository artifacts.
3. Ensure `项目进度.md` uses the shared Vault properties with `type: project_progress`, the exact `project` identity, `domain`, lifecycle `status`, independent `health`, `owner: xiaoh`, `needs_user_decision: false`, `focus: false`, `next_action`, `updated`, and `evidence_cutoff`. Then upsert these sections:
   - update time, current phase, overall status, and evidence cutoff;
   - workstream table with status, accepted result, blocker, and next milestone;
   - recently completed;
   - currently active;
   - blockers and risks;
   - ordered next actions and owners;
   - recent daily records and linked requirements, decisions, and verification.
4. Do not invent a completion percentage. Include one only when an authoritative scoped plan supplies a measurable denominator.
5. Preserve uncertainty and conflicting evidence explicitly. Do not turn `planned`, `blocked`, or `stage_completed` into `completed`.
6. Ensure the project home links `项目进度.md` and uses `type: project` with the same project identity, update time, lifecycle status, health, owner, decision flag, focus flag, and next action. Preserve any old nonstandard state as `legacy_status` when normalizing it. Update a global project overview only when it already exists and the same evidence supports the change.
7. Report the Vault root, exact files updated, evidence cutoff, changed statuses, conflicts, and stale sources.

Do not copy raw logs into the snapshot. A rerun with unchanged evidence must be idempotent.
