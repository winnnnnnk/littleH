---
name: xiaoh-update
description: Synchronize an installed XiaoH runtime with the currently installed plugin version while preserving local configuration and knowledge. Use after upgrading the xiaoh Codex plugin, when setup files or role definitions changed, or when the user asks to update, upgrade, repair, or resync 小H.
---

# 更新小H

Use `../../scripts/xiaoh.py`, resolved from this Skill directory.

1. Run `python3 ../../scripts/xiaoh.py plan --json` and read the existing local XiaoH configuration.
2. Confirm that the resolved targets are the installed XiaoH paths. Ask only if paths conflict or an unregistered Agent prevents a safe update.
3. Run `python3 ../../scripts/xiaoh.py update --json`.
4. Report the new version, backup location, capability status, validation result, preserved local paths, configured Vault root, and actual files written by the update.
5. If Hook files changed, require a Codex restart and fresh `/hooks` review before claiming runtime activation.
6. Run or recommend `$xiaoh-doctor` after the restart.

Do not overwrite project knowledge, real task evidence, credentials, or unrelated global Agent files.
