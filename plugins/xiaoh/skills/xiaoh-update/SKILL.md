---
name: xiaoh-update
description: Transactionally synchronize or repair an installed XiaoH 4.0.1 runtime from the currently loaded plugin while preserving supported durable user assets. Use when the user explicitly requests an update, same-version repair, or runtime synchronization.
---

# Synchronize XiaoH

Use `../../scripts/xiaoh.py`.

1. Run `python3 ../../scripts/xiaoh.py plan --json`. Plan is read-only.
2. Confirm the resolved paths are the installed XiaoH targets. Ask only when a path conflict changes the result.
3. Run `python3 ../../scripts/xiaoh.py update --json --active-skill-root <this Skill directory>`.
4. Update always uses an isolated candidate, verified recovery manifest, atomic managed switches, deterministic static Doctor, and commit or reverse compensation. It does not migrate legacy runtime schemas or reactivate legacy task evidence.
5. Confirm the recovery backup exists and the exact 4.0.1 manifest is installed. Preserve supported configuration extensions, Workspace identities, the configured Vault, knowledge, unrelated plugins, automation preferences, and non-reserved custom Agents.
6. Reconcile only explicitly managed automation through the supported host tool and `bind-automation`. Missing automation support degrades that optional capability; it must not be hidden as core success.
7. Run `python3 ../../scripts/xiaoh.py doctor --json --active-skill-root <this Skill directory>`.
8. Report version, transaction ID, backup, installation status, activation state, preserved paths, exact writes, validation, warnings, conflicts, and recovery conditions.
9. If Hook files changed, require a Codex restart, user-managed Hook trust, and new-root runtime Doctor before claiming activation.

Do not overwrite project knowledge or credentials, install companion plugins, mutate plugin cache or Hook trust, or install, update, downgrade, relink, or otherwise modify the Playbook CLI.
