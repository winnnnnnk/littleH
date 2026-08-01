---
name: xiaoh-doctor
description: Diagnose XiaoH 4.0.0 installation and activation across plugin, Skill governance, managed runtime, Agents, Hooks, Validator, Vault, Workspace, automation, and optional Playbook facts. Use when the user asks whether XiaoH is installed, active, trusted, working, or ready.
---

# 检查xiaoh

Use `../../scripts/xiaoh.py`, resolved from this Skill directory.

1. Run `python3 ../../scripts/xiaoh.py doctor --json --active-skill-root <absolute path of this Skill directory>` for static verification. This binds the report to the Skill version loaded by the current thread.
2. Add `--runtime` only after Codex has restarted and the user says the Hooks were reviewed and trusted, or explicitly requests runtime verification. When invoked through a Codex tool sandbox, request approved non-sandbox execution; the runtime probe fails fast inside `CODEX_SANDBOX` because a sandboxed app-server result is not authoritative.
3. Run every independent diagnostic even when another one fails. Doctor is read-only and must not repair files, create tasks, install plugins, modify trust, or change external state.
4. Read `../../managed-automations.json` and the static automation report. If the supported automation tool is available, use read/view operations for configured task IDs; inspect local task files only to resolve duplicates or missing IDs.
5. Verify that existing tasks invoke the expected namespaced Skill and template version. Treat optional paused tasks as healthy; report a missing or drifted required task as degradation of that capability.
6. Report installation status first and activation state separately. Then show plugin/deployed alignment, Skill-source integrity and quality, configured Vault and `.obsidian` marker, managed Agents and Hooks, Validator, Workspace, automation, optional Playbook facts, and each actionable failure with one recovery condition.
7. Interpret `integrations.playbook` as follows: `auto` reports a missing CLI as `not_enabled`; `disabled` skips probing and forbids Playbook-managed delegation; `enabled` requires compatible read-only facts. Compatibility never makes an unmanaged task Playbook-managed by itself.
8. Do not claim runtime delegation or Vault gates are active from static success or matching version alone. Runtime activation requires current-process plugin and Skill facts plus trusted Hook evidence after restart.
9. Do not repair files or tasks unless the user separately asks for setup or update; route writes through `$xiaoh-setup` or `$xiaoh-update`.
