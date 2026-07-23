---
name: xiaoh-setup
description: Initialize the XiaoH local runtime after installing the Codex plugin. Use when the user says to initialize, install, configure, migrate, or enable 小H on a computer, or when XiaoH Agent files, governance hooks, validator, global contract, or the Obsidian development vault are missing.
---

# 初始化小H

Use the deterministic plugin script at `../../scripts/xiaoh.py`, resolved from this Skill directory. Do not recreate its copy, merge, backup, or validation logic manually.

1. Run `python3 ../../scripts/xiaoh.py plan --json` (`py -3` on Windows if needed).
2. Explain the resolved Codex and Obsidian paths and whether they already exist. Recommend the defaults unless the user supplied different paths.
3. If the user explicitly requested initialization and no path conflict changes the result, proceed. Ask one focused question only when a different target path or an existing unregistered Agent requires a decision.
4. Run `python3 ../../scripts/xiaoh.py setup --json --allow-degraded --active-skill-root <absolute path of this Skill directory>`, passing `--codex-home` or `--vault` only when selected. The temporary degraded result is expected until managed tasks are created and bound.
5. Setup automatically installs machine-readable Codex companion plugins from `../../dependencies.json`. Report the backup directory, installed version, capability status, static validation result, warnings, and any conflict exactly.
6. Read `../../managed-automations.json`. Search for the supported scheduled-task management tool; never write `~/.codex/automations/*/automation.toml`.
7. If scheduled tasks are unavailable, leave the bindings `unbound`, report automation status as `degraded`, and keep the XiaoH core installation successful.
8. For `xiaoh.daily-progress`, prefer the configured task ID. Otherwise inspect existing task configuration read-only and adopt a legacy task only when exactly one candidate matches both its XiaoH archive purpose and prompt semantics. Stop for one user decision when zero-risk identification is impossible.
9. Create or update the daily task through the supported tool using the manifest name, prompt, and `ACTIVE` status. Preserve an adopted task's schedule, timezone, target, notification, model, and reasoning. Use the manifest's local-time default only for a new task.
10. Create `xiaoh.weekly-knowledge-review` as paused when it is not already bound. Read it back because some hosts may ignore the create-time paused state; if needed, issue one supported update to pause it and verify again. If it still cannot be paused, delete the new task and leave the template unbound.
11. After each successful create or update, run `python3 ../../scripts/xiaoh.py bind-automation --logical-id <logical-id> --task-id <actual-id> --json` (`py -3` on Windows). Never record a binding before the tool succeeds.
12. Run `python3 ../../scripts/xiaoh.py doctor --json --active-skill-root <absolute path of this Skill directory>`. Report `passed` only when the installed plugin, loaded Skill, deployed runtime, Vault templates, and actual managed task states align.
13. Tell the user to restart Codex, review and trust the four XiaoH Hooks in `/hooks` (Agent delegation, Vault path, SubagentStart, SubagentStop), then use `$xiaoh-doctor` with runtime verification.

Never initialize a business project, copy project knowledge, or store credentials as part of this Skill.
Never download or execute installers for external binaries. Optional external capabilities are detected and reported by the deterministic script.
