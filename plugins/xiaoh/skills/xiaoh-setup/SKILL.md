---
name: xiaoh-setup
description: Initialize the XiaoH local runtime after installing the Codex plugin. Use when the user says to initialize, install, configure, migrate, or enable 小H on a computer, or when XiaoH Agent files, governance hooks, validator, global contract, or the Obsidian development vault are missing.
---

# 初始化小H

Use the deterministic plugin script at `../../scripts/xiaoh.py`, resolved from this Skill directory. Do not recreate its copy, merge, backup, or validation logic manually.

1. Run `python3 ../../scripts/xiaoh.py plan --json` (`py -3` on Windows if needed).
2. Explain the resolved Codex and Obsidian paths and whether they already exist. Recommend the defaults unless the user supplied different paths.
3. If the user explicitly requested initialization and no path conflict changes the result, proceed. Ask one focused question only when a different target path or an existing unregistered Agent requires a decision.
4. Run `python3 ../../scripts/xiaoh.py setup --json`, passing `--codex-home` or `--vault` only when selected.
5. Report the backup directory, installed version, static validation result, and any conflict exactly.
6. Tell the user to restart Codex, review and trust the three XiaoH Hooks in `/hooks`, then use `$xiaoh-doctor` with runtime verification.

Never initialize a business project, copy project knowledge, or store credentials as part of this Skill.
