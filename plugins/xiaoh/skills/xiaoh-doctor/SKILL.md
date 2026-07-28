---
name: xiaoh-doctor
description: Diagnose and verify a XiaoH installation, including registered specialist Agents, the reserved root identity, global contract, deployed/plugin version alignment, Hook configuration and trust state, task validator, configured Obsidian Vault, and role catalog. Use when the user asks whether 小H is installed, trusted, active, working, misconfigured, or ready to use.
---

# 检查小H

Use `../../scripts/xiaoh.py`, resolved from this Skill directory.

1. Run `python3 ../../scripts/xiaoh.py doctor --json --active-skill-root <absolute path of this Skill directory>` for static verification. This binds the report to the Skill version loaded by the current thread.
2. Add `--runtime` only after Codex has restarted and the user says the Hooks were reviewed and trusted, or explicitly requests runtime verification. When invoked through a Codex tool sandbox, request approved non-sandbox execution; the runtime probe fails fast inside `CODEX_SANDBOX` because a sandboxed app-server result is not authoritative.
3. Read `../../managed-automations.json` and the static `automations` report. If the scheduled-task tool is available, call its read/view operation for every configured task ID and inspect local task files only to resolve duplicates or missing IDs; never modify them.
4. Verify that each existing task invokes the expected namespaced Skill and that the configured template version matches. Treat the optional paused weekly task as healthy; treat a missing or drifted daily task as `degraded`, not as a XiaoH core failure.
5. Report the XiaoH core status first, then plugin/deployed version alignment, configured Vault and `.obsidian` marker, bundled Skill count, companion plugin status, optional external capability status, integration mode/status, managed automation status, and each actionable failure with its recovery condition.
6. Interpret `integrations.playbook` as follows: `auto` is the default and reports a missing CLI as `not_enabled` without degrading core; `disabled` skips probing and forbids Playbook-managed delegation; `enabled` requires a compatible CLI and reports missing or incompatible contracts as `degraded`. A compatible CLI never makes an unmanaged task Playbook-managed by itself.
7. Do not claim runtime delegation or Vault gates are active from static success alone. Confirm that scheduled runs use the same trusted Hook environment before reporting automation write protection as verified.
8. Do not repair files or tasks unless the user also asks to initialize or update; use `$xiaoh-setup` or `$xiaoh-update` for writes.
