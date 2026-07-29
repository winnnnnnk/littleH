---
name: xiaoh-knowledge-promotion
description: "Promote an evidence-backed XiaoH knowledge candidate into exactly one durable Obsidian scope: project knowledge, domain knowledge, reusable method, or personal system. Use after task closeout or knowledge review when a candidate should become formal knowledge, when the user asks to reuse a prior project approach, or when XiaoH must decide whether a lesson is project-specific or cross-project."
---

# xiaoh知识晋升

Treat this as a `global_agent_capability` knowledge operation. It may write project-specific knowledge inside the configured Vault, but it does not modify business repositories or lifecycle state.

1. Resolve the only Vault from `~/.xiaoh/config.json` and enforce the Vault path gate.
2. Read the candidate projection, its authoritative closeout record, and the referenced accepted evidence. Stop when the source cannot be located, is not accepted, or conflicts materially with the candidate.
3. Distinguish the reusable invariant from project parameters, examples, fixed values, customer conventions, security decisions, and unknowns. Do not generalize from names or one successful instance alone.
4. If the candidate contains a business rule or result-changing design decision, locate its canonical `requirement_baseline` first. Do not copy the rule text into another independently evolving knowledge page. Promote only a reference containing the baseline path and stable point IDs; if no canonical baseline exists, stop and route the candidate through `$xiaoh:xiaoh-requirement-baseline`.
5. Select exactly one scope:
   - `project`: facts and decisions needed to understand, operate, or evolve one project; write under `01-项目/<project>/知识/`;
   - `domain`: stable PKI, Java, architecture, security, or other domain semantics that hold across projects; write under `02-领域知识/<domain>/`;
   - `reusable`: a repeatable engineering method with explicit prerequisites, variables, exclusions, validation, and rollback; write under `03-可复用方法/<domain>/`;
   - `personal_system`: XiaoH, Agent governance, personal workflow, templates, or tool-operation knowledge; write under `90-个人系统/`.
6. Prefer updating an existing canonical page over creating a synonym. When several candidates describe one capability, merge only non-conflicting evidence and preserve every source link.
7. Write formal frontmatter with `type`, `knowledge_scope`, `knowledge_state: formal`, `status: accepted`, `domain`, `owner: xiaoh`, `updated`, `source_project`, and `source_evidence` as applicable.
8. Use the matching structure:
   - project/domain knowledge: definition or conclusion, context, baseline references and stable point IDs, decision reasons, boundaries, verification, sources, unknowns;
   - reusable method: problem, applicability, prerequisites, variable parameters, exclusions, procedure, validation, failure handling or rollback, source examples;
   - personal system: purpose, operating rule, boundary, verification, evolution trigger, source.
9. Link project knowledge from the corresponding project homepage or knowledge index. Do not copy raw logs into formal knowledge.
10. Update the candidate projection to `knowledge_state: promoted`, `status: accepted`, add `promoted_to`, promotion date, scope, and evidence summary. Keep the authoritative closeout record unchanged.
11. If promotion would change Agent permissions, governance gates, Skill behavior, security rules, or an accepted business result, stop at a promotion recommendation and obtain the required user decision first.
12. Report the configured Vault root, exact written files, selected scope and why the other scopes were rejected, evidence basis, remaining uncertainty, and whether a Skill or Agent improvement candidate was created.

A formal knowledge page must explain what is true, why it is true, where it applies, and how it is verified. A completion list is not knowledge.
