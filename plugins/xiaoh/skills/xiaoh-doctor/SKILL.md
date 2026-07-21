---
name: xiaoh-doctor
description: Diagnose and verify a XiaoH installation, including registered specialist Agents, the reserved root identity, global contract, Hook configuration and trust state, task validator, local paths, and Obsidian role catalog. Use when the user asks whether 小H is installed, trusted, active, working, misconfigured, or ready to use.
---

# 检查小H

Use `../../scripts/xiaoh.py`, resolved from this Skill directory.

1. Run `python3 ../../scripts/xiaoh.py doctor --json` for static verification.
2. Add `--runtime` only after Codex has restarted and the user says the Hooks were reviewed and trusted, or explicitly requests runtime verification.
3. Report the overall status first, then bundled Skill count, companion plugin status, optional external capability status, and each actionable failure with its recovery condition.
4. Do not claim runtime delegation gates are active from static success alone.
5. Do not repair files unless the user also asks to initialize or update; use `$xiaoh-setup` or `$xiaoh-update` for writes.
