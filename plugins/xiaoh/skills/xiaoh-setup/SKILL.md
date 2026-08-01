---
name: xiaoh-setup
description: Initialize or cleanly reinstall the XiaoH 3.1.2 local runtime after installing the Codex plugin.
---

# Initialize XiaoH

Use `../../scripts/xiaoh.py`; do not recreate its backup, copy, merge, or validation logic.

1. Run `python3 ../../scripts/xiaoh.py plan --json` and report resolved Codex, Vault, configuration, and plugin paths.
2. When the user requested installation and paths are unambiguous, run `python3 ../../scripts/xiaoh.py setup --json --allow-degraded --active-skill-root <this Skill directory>`.
3. Setup creates a recovery backup, removes the previously managed runtime surface, installs the exact 3.1.2 manifest, and preserves allowlisted local configuration, Workspace identities, knowledge, unrelated plugins, and non-reserved custom Agents.
4. Read `../../managed-automations.json`. Reconcile only the daily progress task through the supported automation tool; never write automation internals directly. Preserve an existing task's schedule, timezone, target, notification, model, and reasoning.
5. Run `python3 ../../scripts/xiaoh.py doctor --json --active-skill-root <this Skill directory>`.
6. Report installed version, backup, preserved data, written paths, validation, automation state, warnings, and conflicts.
7. If Hook content changed, report `restart_required`. Ask the user to restart Codex, trust the four XiaoH Hooks in `/hooks`, and then run `$xiaoh-doctor` with runtime verification.

Never initialize a business project, overwrite project knowledge, store credentials, install external binaries, or change the Playbook CLI.
