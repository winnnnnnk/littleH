# Design It Twice

When the user wants to explore alternative interfaces for a chosen deepening candidate, use this
independent-alternatives pattern. Based on "Design It Twice" (Ousterhout), your first idea is
unlikely to be the best.

Uses the vocabulary in [SKILL.md](SKILL.md) — **module**, **interface**, **seam**, **adapter**, **leverage**.

## Process

### 1. Frame the problem space

Before producing alternatives, write a user-facing explanation of the problem space for the chosen candidate:

- The constraints any new interface would need to satisfy
- The dependencies it would rely on, and which category they fall into (see [DEEPENING.md](DEEPENING.md))
- A rough illustrative code sketch to ground the constraints — not a proposal, just a way to make the constraints concrete

Show this to the user, then immediately proceed to Step 2. Do not block when the remaining work is
already authorized.

### 2. Produce independent alternatives

Produce at least three **radically different** interfaces for the deepened module. Use parallel
sub-agents only when the current XiaoH task authorizes delegation and every formal delegation can
use the required role, execution binding, proof, and isolated scope. Otherwise develop the
alternatives locally and keep their assumptions separate.

Give each alternative a separate technical brief (file paths, coupling details, dependency category
from [DEEPENING.md](DEEPENING.md), what sits behind the seam). When sub-agents are authorized, use
the same separation in their prompts. Apply a different design constraint to each alternative:

- Agent 1: "Minimize the interface — aim for 1–3 entry points max. Maximise leverage per entry point."
- Agent 2: "Maximise flexibility — support many use cases and extension."
- Agent 3: "Optimise for the most common caller — make the default case trivial."
- Agent 4 (if applicable): "Design around ports & adapters for cross-seam dependencies."

Include both [SKILL.md](SKILL.md) vocabulary and CONTEXT.md vocabulary in the brief so every
alternative uses the architecture and project domain language consistently.

Each alternative outputs:

1. Interface (types, methods, params — plus invariants, ordering, error modes)
2. Usage example showing how callers use it
3. What the implementation hides behind the seam
4. Dependency strategy and adapters (see [DEEPENING.md](DEEPENING.md))
5. Trade-offs — where leverage is high, where it's thin

### 3. Present and compare

Present designs sequentially so the user can absorb each one, then compare them in prose. Contrast by **depth** (leverage at the interface), **locality** (where change concentrates), and **seam placement**.

After comparing, give your own recommendation: which design you think is strongest and why. If elements from different designs would combine well, propose a hybrid. Be opinionated — the user wants a strong read, not a menu.
