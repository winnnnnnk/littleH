---
name: xiaoh-knowledge-review
description: Review XiaoH daily-record knowledge candidates for reuse without silently promoting them. Use for XiaoH's managed weekly scheduled task, a manual weekly knowledge review, candidate deduplication, or deciding which project lessons deserve later human-reviewed promotion.
---

# 小H每周知识候选评审

Treat this as a `global_agent_capability` operation. It reviews accepted daily records; it does not inspect or modify business repositories.

1. Resolve and validate the only Vault from `~/.xiaoh/config.json`.
2. Read daily work records for the requested week, defaulting to the latest completed local calendar week. Consume only entries explicitly marked as knowledge candidates.
3. Do not rescan Codex tasks or repositories. If a candidate lacks its referenced evidence, mark it `insufficient_evidence`.
4. Deduplicate candidates by capability, preconditions, inputs, outputs, and failure boundaries rather than by similar wording.
5. Classify every candidate as one of:
   - `project_only`;
   - `reusable_candidate`;
   - `material_conflict`;
   - `insufficient_evidence`.
6. For reusable candidates, record:
   - source project and task;
   - observed evidence;
   - reusable problem and solution pattern;
   - applicability and exclusions;
   - parameters that must change in another project;
   - risks, uncertainty, and validation needed.
7. Write or update `02-领域知识/知识候选/YYYY-Www-知识评审.md` using archive key `xiaoh-weekly:<ISO-week>`. A rerun updates the same candidate IDs and must not duplicate them.
8. Do not automatically overwrite formal knowledge, ADRs, Skills, Agent roles, or global contracts. List promotion recommendations for an interactive XiaoH review.
9. Report the configured Vault root, exact written file, candidate counts by classification, conflicts, skipped candidates, and recommended promotions. Report `无新增` when no candidate exists.

Stop rather than generalize a project-specific value, customer convention, fixed default, security decision, or PKI behavior without independent evidence.
