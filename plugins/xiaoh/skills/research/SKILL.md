---
name: research
description: Investigate a question against high-trust primary sources and, when authorized, capture the findings as a Markdown file. Use when the user wants a topic researched, documentation or API facts gathered, or evidence collected for a decision.
---

Use a background Agent only when delegation is available, useful, and authorized through XiaoH.
Otherwise research directly. This skill grants no repository write, external mutation, or production
access. Follow the current task scope, source policy, and sensitive-data boundary.

The research job:

1. Investigate the question against **primary sources** — official docs, source code, specs, first-party APIs — not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Cite each claim at the point it is used and distinguish observed facts from inference.
3. Write one Markdown artifact only when the user or accepted workflow authorizes repository
   writing. Match the existing convention; otherwise return the findings in the current task.
