---
name: wayfinder
description: Navigate a large, uncertain effort as a map of decision tickets, blockers, and a moving frontier. Use when the destination is known but the decisions needed to reach it cannot fit in one session or cannot yet be fully specified.
---

A large effort has a known **destination**, but the route is partly hidden by a **fog of war**. Build
a map of decision tickets, explicit blockers, and the current **frontier**. The map is planning:
questions resolve into decisions; it is not a second implementation lifecycle.

## XiaoH integration boundary

XiaoH task context, requirement artifacts, and Playbook state remain authoritative. Reuse their
stable task and change identities. Do not create an external issue, label, assignee, branch, comment,
or tracker state unless the user and current managed workflow authorize that side effect. A local
Markdown map may be used only as a task artifact, never as a competing source of truth. Research
delegation follows XiaoH's formal delegation gates.

## Map shape

Keep one low-resolution index:

```markdown
## Destination
<the confirmed end state>

## Decisions so far
- <decision name> — <one-line result and authoritative pointer>

## Frontier
- <unblocked, unresolved decision ticket>

## Not yet specified
- <in-scope fog that cannot yet be stated as a precise question>

## Out of scope
- <explicitly excluded work and reason>
```

Each decision ticket contains one precise question, its evidence sources, blockers, owner if one is
already assigned by the authoritative workflow, and the result pointer when resolved. Refer to
tickets by descriptive name; keep IDs as supporting links.

## Ticket types

- **Research**: obtain a fact from primary sources.
- **Prototype**: build an authorized isolated artifact to answer how something should behave or look.
- **Decision discussion**: ask one question at a time when the user requested stress testing or a
  result-changing decision is blocked.
- **Unblocking task**: perform only the authorized work required before a decision can be made.

## Fog and frontier

- Create a ticket when the question is precise, even if blocked.
- Keep it in **Not yet specified** when the question cannot yet be stated precisely.
- The **frontier** contains unresolved tickets whose blockers are resolved.
- Move work beyond the destination to **Out of scope**; do not silently delete it.
- Resolve blockers first. After each decision, update newly visible questions and blocking edges.

## Chart a map

1. Bind the map to the current XiaoH task, confirmed requirement, or Playbook change.
2. State the destination and exclusions. Ask the user only if the destination changes the business
   result and is not already confirmed.
3. Scan breadth-first for precise decision questions and still-vague fog.
4. Record explicit blocking edges, then identify the frontier.
5. Start research in parallel only when independent, authorized, and safely delegated.
6. Stop mapping when the route is clear enough for the existing requirement or task workflow.

## Work through a map

1. Load the map and current authoritative task facts.
2. Choose the first unblocked decision unless the user named another.
3. Resolve one non-research decision per session; independent research may run in parallel.
4. Record the evidence-backed answer and authoritative pointer.
5. Recompute blockers, frontier, fog, and out-of-scope items.

Never mark a XiaoH or Playbook task complete, create implementation authorization, or perform an
external side effect solely because the wayfinding map says so.
