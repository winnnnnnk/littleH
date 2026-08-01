---
name: resolving-merge-conflicts
description: "Use when you need to resolve an in-progress git merge/rebase conflict."
---

Resolving conflicts authorizes edits only to the identified merge or rebase scope. It does not
authorize aborting, staging, committing, continuing a rebase, pushing, or changing unrelated files.
Before each Git state transition, follow the user's instruction, repository rules, and XiaoH task
authority. Never use destructive reset or checkout to discard either side.

1. **See the current state** of the merge/rebase. Check git history, and the conflicting files.

2. **Find the primary sources** for each conflict. Understand deeply why each change was made, and what the original intent was. Read the commit messages, check the PRs, check original issues/tickets.

3. **Resolve each authorized hunk.** Preserve both intents where possible. Where incompatible, pick
   the one matching the merge's stated goal and note the trade-off. Do **not** invent new behaviour.
   If the correct result changes business semantics or cannot be proven, stop and request that
   decision instead of guessing.

4. Discover the project's **automated checks** and run them — typically typecheck, then tests, then format. Fix anything the merge broke.

5. **Report the resolved files and remaining Git state.** Stage, commit, continue the rebase, push,
   or abort only when that action is explicitly authorized. Any resulting implementation remains
   subject to the configured XiaoH deterministic verification gates.
