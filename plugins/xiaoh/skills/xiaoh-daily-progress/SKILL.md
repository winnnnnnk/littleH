---
name: xiaoh-daily-progress
description: Push a concise daily achievement digest from results already closed into XiaoH's configured Obsidian Vault. Use for XiaoH's managed daily scheduled task, a manual daily achievement push, or checking which completed tasks lack immediate closeout; never use it as a delayed substitute for task or project summarization.
---

# 小H每日成果推送

Treat this as a `global_agent_capability` reporting operation. It publishes already-closed results; it does not perform task closeout or maintain project progress.

1. Read `~/.xiaoh/config.json` and resolve `obsidian_vault`. Stop if it is missing, not an absolute path, lacks `.obsidian`, or conflicts with the Vault write Hook.
2. Use the previous natural day in the automation environment's local timezone unless the caller supplies another explicit date. Report the exact range and timezone.
3. Read project `工作记录/YYYY-MM-DD.md` entries and `07-工作记录/全局能力/YYYY-MM-DD.md` or `07-工作记录/平台/YYYY-MM-DD.md` entries created by `$xiaoh:xiaoh-task-closeout`. Read project `项目进度.md` only for blocker and next-action context.
4. Group the push by business project, XiaoH global capability, and Playbook platform. Include accepted achievements, verification, key decisions, blockers, next action, and knowledge-candidate count. Link each source daily record and any applicable project snapshot.
5. When accessible completed-task summaries exist, compare their task IDs with closeout keys. List missing keys as `未即时收口`; do not reconstruct, summarize, or write those missing results during the scheduled run.
6. Do not modify business repositories, requirement pages, daily records, project snapshots, formal knowledge, or processing cursors.
7. Return a concise user-facing digest suitable for an automation notification. Report `当日无已收口成果` when no eligible result exists and separately report any missing closeouts.

A rerun may repeat the same digest but must not create duplicate knowledge or silently repair the project record.
