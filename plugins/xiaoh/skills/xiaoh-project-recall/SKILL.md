---
name: xiaoh-project-recall
description: Recall and reconcile the relevant accepted history of a known XiaoH business Workspace before requirement analysis or task continuation. Use for every business-project request after Workspace routing and before requirement routing, especially when resuming an old task, processing historical work, modifying an existing feature, reusing a similar project solution, or when prior Obsidian baselines, closeouts, progress, or formal knowledge may affect the result.
---

# 小H项目历史召回

Treat recall as a read-only `business_project` gate. It does not authorize repository, Playbook, task-state, or Obsidian writes.

## Resolve scope

1. Run `$xiaoh:xiaoh-workspace-routing` and require `known`.
2. Resolve the only Vault from XiaoH's configured local JSON and enforce the Vault path gate.
3. Classify `task_relation` as exactly one of:
   - `new`: a new topic in an existing project;
   - `continuation`: continuing the same accepted task or work line;
   - `historical_recovery`: reconstructing or correcting old work;
   - `similar_reuse`: applying an earlier project or feature approach to a related task.
4. Derive a narrow query from the user goal, system, topic, stable task IDs, affected modules, and known terminology. Do not batch-read the Vault.

## Recall accepted history

Read in this order:

1. Project homepage and `项目进度.md` for current work lines and links.
2. Referenced task pages and accepted task closeouts.
3. Canonical requirement baselines for the relevant system/topic, including stable confirmation-point IDs and supersession links.
4. Linked project knowledge, domain knowledge, and reusable methods when their applicability matches.
5. Daily digests only as navigation to underlying closeouts or baselines. Never use a digest summary as the sole authority for a business rule.

Prefer exact links and stable IDs. If no relevant history exists, record the indexes and query that were checked plus a concrete `no_relevant_history_reason`; never invent a source.

## Reconcile current facts

After recalling history, read the task-relevant current code, configuration, accepted Spec/RFC or OpenSpec, and managed task state when available.

- Treat accepted history as target, rationale, and prior-result evidence.
- Treat current code, configuration, and runtime evidence as current-behavior facts.
- Preserve any disagreement in `material_conflicts`; neither side silently overwrites the other.
- Mark stale, superseded, rejected, missing, or uncertain material explicitly.
- Produce one recommended working baseline for requirement routing. Ask the user only if the remaining conflict changes the business result.

## Write recall evidence

Write raw evidence outside Obsidian:

- prefer the current managed task evidence directory;
- otherwise use `<xiaoh-config-directory>/evidence/recall/<CODEX_THREAD_ID>/<task_id>.json`.

Use this manifest:

```json
{
  "schema_version": "xiaoh-project-recall/v1",
  "created_at": "ISO-8601 timestamp",
  "task_id": "same task ID as task context",
  "workspace_id": "stable XiaoH workspace ID",
  "project": "project name",
  "system": "system name",
  "task_relation": "new|continuation|historical_recovery|similar_reuse",
  "query": {
    "summary": "what was searched",
    "topics": [],
    "task_ids": [],
    "keywords": []
  },
  "memory_sources": [
    {
      "kind": "project_progress|task_page|task_closeout|requirement_baseline|formal_knowledge|daily_digest",
      "path": "absolute configured-Vault path",
      "sha256": "lowercase SHA-256 of the file read",
      "role": "navigation|authority|evidence",
      "point_ids": [],
      "relevance": "why this source matters"
    }
  ],
  "checked_indexes": [
    {
      "path": "absolute configured-Vault path",
      "sha256": "lowercase SHA-256 of the index file read",
      "relevance": "why this index was checked"
    }
  ],
  "no_relevant_history_reason": null,
  "current_fact_sources": [
    {
      "kind": "code|configuration|spec_rfc|openspec|task_state|runtime_evidence",
      "path": "absolute path to the current fact source",
      "sha256": "lowercase SHA-256 of the file read",
      "relevance": "what current fact it proves"
    }
  ],
  "current_fact_scope": "what current facts were checked",
  "material_conflicts": [],
  "unresolved": [],
  "recommended_baseline": "evidence-backed baseline for the next gate"
}
```

At least one of `query.topics`, `query.task_ids`, or `query.keywords` must be non-empty. At least one memory source is required unless `no_relevant_history_reason` is non-empty; an empty result also requires at least one content-bound `checked_indexes` entry. At least one current fact source is always required before the recall gate can pass.

Memory sources and checked indexes must refer to distinct filesystem identities; path spelling, case aliases, symlinks, hard links, or Unicode aliases cannot turn one physical file into multiple sources. A `daily_digest` must use `role=navigation`; recalled history must contain a distinct non-digest source using `role=authority` or `role=evidence`. A requirement baseline used as authority or evidence must list the stable `point_ids` actually relied upon.

Compute the manifest SHA-256 and set task-context `memory_recall` to:

```json
{
  "status": "completed",
  "workspace_id": "same stable Workspace ID",
  "task_relation": "same relation",
  "manifest_path": "absolute path",
  "manifest_sha256": "lowercase SHA-256",
  "completed_at": "same as manifest created_at"
}
```

The manifest `task_id` must match the task context. Its `workspace_id`, `project`, and `system` must match the configured Workspace registry and a binding for the current operating-system platform.
Every recalled history and current-fact file is content-bound by SHA-256, and every current fact source
must remain within task-context `scope.allowed_paths`.

Run the task-context validator before requirement routing or formal delegation. Report the Workspace, relation, sources read, stable baseline point IDs, conflicts, unknowns, manifest path/hash, and recommended conclusion.

Do not claim recall is complete when the Workspace is unresolved, the configured Vault is unavailable, the manifest is missing or stale, source identity conflicts, or required linked evidence cannot be read.
