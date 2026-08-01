---
name: xiaoh-setup
description: Build and transactionally install the XiaoH 4.0.1 local runtime after the Codex plugin is installed. Use only when the user explicitly requests setup or a clean reinstall.
---

# Initialize XiaoH

Use `../../scripts/xiaoh.py`; do not recreate its backup, copy, merge, or validation logic.

1. Run `python3 ../../scripts/xiaoh.py plan --json` and report the resolved Codex home, Vault, configuration path, expected writes, conflicts, backup requirements, and recovery conditions. Plan must remain read-only.
2. When the user has requested installation and the paths are unambiguous, run `python3 ../../scripts/xiaoh.py setup --json --active-skill-root <this Skill directory>`.
3. Require a complete isolated candidate and verified recovery manifest before switching managed targets. A failed switch must report either `rolled_back` or `recovery_required`; never report partial success.
4. Preserve supported durable configuration, Workspace identities, Vault knowledge and compatible workbench customization, unrelated plugins, and non-reserved custom Agents. Do not import old Hook state, bindings, transaction journals, or legacy runtime schemas.
5. Read `../../managed-automations.json`. Use the supported automation host tool for creation or updates, then bind an existing task with `bind-automation`; never write automation internals directly. Preserve user schedule, timezone, target, notification, model, and reasoning preferences.
6. Run `python3 ../../scripts/xiaoh.py doctor --json --active-skill-root <this Skill directory>` and report installation status separately from activation state.
7. Report version, transaction ID, backup, preserved data, exact managed writes, deterministic validation, automation state, warnings, conflicts, and recovery conditions.
8. If Hook content changed, report `runtime_unverified`. Ask the user to restart Codex, review and trust the four XiaoH Hooks, start a new root task, and then run `$xiaoh-doctor` with runtime verification.

Never initialize a business project, overwrite project knowledge, store credentials, install companion plugins or external binaries, mutate plugin cache or Hook trust, or change the Playbook CLI.
