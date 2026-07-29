---
name: xiaoh-workspace-routing
description: Resolve and persist the project and system ownership of a XiaoH development Workspace. Use before business-project knowledge reads or writes, task closeout, project progress updates, or requirement routing when the current Workspace is new, unknown, moved, copied, or potentially mapped to another project.
---

# xiaoh Workspace归属

Use `../../scripts/xiaoh.py`, resolved from this Skill directory.

1. Prefer an authoritative managed-task Workspace path; otherwise use the current working directory or an explicit user path.
2. Run `python3 ../../scripts/xiaoh.py resolve-workspace --path <absolute path> --json`.
3. Handle the result:
   - `known`: use the registered `project`, `system`, and `workspace_id` without asking again.
   - `unknown`: inspect only the relevant `playbook-workspace.yaml`, repository remotes, workspace navigation, and configured Vault project index. Recommend one project and system with evidence, then ask one focused ownership question.
   - `conflict`: stop business-project writes and task lifecycle actions. Report every conflicting mapping and ask for explicit correction; never choose by directory name or recency.
4. After the user confirms an unknown Workspace, run:

   `python3 ../../scripts/xiaoh.py register-workspace --workspace-id <stable-id> --project <project> --system <system> --root <absolute root> --json`

5. Re-run `resolve-workspace` and require `known` before using the mapping for knowledge routing or task context.
6. Treat one project as owning many Workspaces, and one Workspace as belonging to exactly one project and one system. Multiple repositories do not imply multiple systems.
7. Use the stable `workspace_id` across computers. Register each machine's absolute root under the same identity after verifying that it represents the same Workspace; never copy a stale path and claim it is active.
8. Ask again only for an unknown mapping, a real conflict, a copied Workspace with changed purpose, or an explicit ownership change. Do not repeatedly ask for a registered Workspace.
9. Keep `~/.xiaoh/config.json` as the machine-readable routing source. Obsidian project and system pages are the human-readable navigation mirror, not an alternative execution authority.

Report the resolved Workspace ID, project, system, matched root, evidence basis, and any unresolved
conflict. Pass the successful result to `$xiaoh-project-recall`; a known mapping identifies which
project memory may be read but does not by itself prove that history was recalled.
