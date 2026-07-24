---
name: xiaoh-task-closeout
description: Immediately close an accepted XiaoH task or stable milestone into the configured Obsidian Vault. Use when implementation, analysis, delivery, troubleshooting, documentation, global capability work, platform work, or a meaningful project stage has completed and its result, reasons, verification, risks, next action, and reusable knowledge must be recorded before the root thread finishes.
---

# 小H任务即时收口

Treat this as part of the current task, not as a scheduled recap. Run it after outcome verification and before the root thread declares the task or milestone complete.

1. Resolve the only Vault from `~/.xiaoh/config.json`; apply the Vault path gate and stop on missing, conflicting, or unsafe configuration.
2. Confirm that the result is accepted or that a named milestone is complete. Do not mark the whole task complete when only a stage completed.
3. Use the current task, Playbook state, repository diff, tests, reviews, and evidence locations as facts. Keep raw logs in task evidence and exclude credentials, tokens, private keys, and production secrets.
4. Classify exactly one intent domain and route the record:
   - `business_project`: run `$xiaoh:xiaoh-workspace-routing`, require a `known` Workspace mapping, then use `01-项目/<project>/工作记录/YYYY-MM-DD.md`;
   - `global_agent_capability`: use `07-工作记录/全局能力/YYYY-MM-DD.md`;
   - `playbook_platform`: use `07-工作记录/平台/YYYY-MM-DD.md`.
   Do not guess a business project. A pure consultation with no accepted durable result is `no_durable_knowledge` and does not write the Vault.
5. Generate the key with `scripts/closeout_key.py` using these authority rules:
   - source: use the managed Playbook task ID when present; otherwise the script must read `CODEX_THREAD_ID` from the current Codex execution environment. Never substitute a title, date, user label, or generated UUID;
   - stage: use the authoritative Playbook stage or milestone ID; for the final result of an ordinary Codex task use `--final`, which resolves to `task-complete`; a partial milestone may use `--stage-id` only when that ID already exists in the current Goal, task context, or accepted artifact;
   - revision: use the accepted Playbook/artifact revision when supplied by that system. An ordinary Codex task must pass one or more accepted task-context, review, diff, or verification evidence files with `--evidence-path`; the script computes their content revision and rejects a caller-provided revision.
   Do not write when the runtime thread ID, stable stage, or accepted evidence is unavailable.
6. Upsert the routed daily record immediately. Ensure the file uses the shared Vault properties with `type: work_record`, the routed `project` or `domain`, `status: accepted`, `health`, `owner: xiaoh`, `date`, and `updated`. Add or update one result entry using the generated key with:
   - completed target or milestone;
   - accepted result and actual changes;
   - key decisions and reasons;
   - verification and evidence paths;
   - risks, blockers, remaining work, and next owner;
   - reusable-knowledge candidates.
7. Give each candidate a stable ID, source task, evidence path, applicability, exclusions, parameters, uncertainty, suggested `knowledge_scope`, and status `candidate`. Also upsert its projection at `02-领域知识/知识候选/<candidate_id>.md` with `type: knowledge_candidate`, `knowledge_state: candidate`, `status: candidate`, `owner: xiaoh`, `next_action`, `updated`, and a link to the source daily record. The daily record remains authoritative; the projection is only a discoverable index. Do not promote it to formal knowledge.
8. For `business_project`, update a clearly identified requirement/task knowledge page when appropriate and normalize only its workbench properties (`type`, `project`, `domain`, `status`, `health`, `owner`, `needs_user_decision`, `focus`, `next_action`, `updated`, and `legacy_status` when migrating an old state) without changing its evidence-backed business conclusions. Then run `$xiaoh:xiaoh-project-progress`. If that Skill is unavailable, report the incomplete project snapshot update. Global capability and platform records do not invoke project progress.
9. Report the configured Vault root, exact written files including candidate projections, closeout key and its identity components, evidence basis, unresolved ownership, and any skipped update.

A rerun must update the same closeout key without duplicating the result. A failed or partial write is not a completed closeout.
