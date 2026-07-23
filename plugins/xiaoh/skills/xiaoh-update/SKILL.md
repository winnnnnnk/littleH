---
name: xiaoh-update
description: Synchronize an installed XiaoH runtime with the currently installed plugin version while preserving local configuration and knowledge. Use after upgrading the xiaoh Codex plugin, when setup files or role definitions changed, or when the user asks to update, upgrade, repair, or resync 小H.
---

# 更新小H

Use `../../scripts/xiaoh.py`, resolved from this Skill directory.

1. Run `python3 ../../scripts/xiaoh.py plan --json` and read the existing local XiaoH configuration.
2. Confirm that the resolved targets are the installed XiaoH paths. Ask only if paths conflict or an unregistered Agent prevents a safe update.
3. Run `python3 ../../scripts/xiaoh.py update --json --allow-degraded --active-skill-root <absolute path of this Skill directory>`. A degraded intermediate result is expected while managed task templates are still being reconciled.
4. Read `../../managed-automations.json` and the preserved `managed_automations` bindings. Use only the supported scheduled-task tool; never write internal automation TOML.
5. For each bound task, read its current settings and update only XiaoH-managed name, prompt, and status changes. The daily task must be `ACTIVE` and the optional weekly review must be `PAUSED`; preserve schedule, timezone, target, notification, model, and reasoning.
6. After a successful update, run `python3 ../../scripts/xiaoh.py bind-automation --logical-id <logical-id> --task-id <actual-id> --json`. Missing tools or tasks produce `degraded`; do not recreate or duplicate them without reliable identity.
7. Report the new version, backup location, capability status, automation status, validation result, preserved local paths, configured Vault root, and actual files written by the update.
8. Run `python3 ../../scripts/xiaoh.py doctor --json --active-skill-root <absolute path of this Skill directory>` after reconciliation. Do not report the update complete while the old Skill version or paused daily task is still active.
9. If Hook files changed, require a Codex restart and fresh `/hooks` review before claiming runtime activation.
10. Run `$xiaoh-doctor` with runtime verification after the restart.

Do not overwrite project knowledge, real task evidence, credentials, or unrelated global Agent files.
