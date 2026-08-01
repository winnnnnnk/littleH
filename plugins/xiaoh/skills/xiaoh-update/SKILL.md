---
name: xiaoh-update
description: Synchronize or repair an installed XiaoH 3.1.2 runtime from the currently installed plugin while preserving allowlisted user data.
---

# Synchronize XiaoH

Use `../../scripts/xiaoh.py`.

1. Run `python3 ../../scripts/xiaoh.py plan --json`. Plan is read-only.
2. Confirm the resolved paths are the installed XiaoH targets. Ask only when a path conflict changes the result.
3. Run `python3 ../../scripts/xiaoh.py update --json --allow-degraded --active-skill-root <this Skill directory>`.
4. Update is a same-version sync/repair or an explicit clean reinstall. It does not migrate legacy runtime schemas or reactivate legacy task evidence.
5. Confirm the recovery backup exists and the exact 3.1.2 managed manifest is installed. Preserve allowlisted configuration extensions, Workspace identities, the configured Vault, knowledge, unrelated plugins, automation preferences, and non-reserved custom Agents.
6. Reconcile only the bound daily progress automation through the supported automation tool. Missing automation support is `degraded`, not a failed core installation.
7. Run `python3 ../../scripts/xiaoh.py doctor --effective-status --json --active-skill-root <this Skill directory>`.
8. Report version, backup, status, preserved paths, actual writes, validation, warnings, and conflicts.
9. If Hook files changed, require a Codex restart and fresh Hook trust before claiming runtime activation.

Do not overwrite project knowledge or credentials, and do not install, update, downgrade, relink, or otherwise modify the Playbook CLI.
