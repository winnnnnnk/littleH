---
name: humanizer
version: 1.0.0
description: >-
  Edit user-facing prose so it reads naturally without changing its meaning.
  Use for README files, guides, explanations, proposals, summaries, handoffs,
  and other documents written for people. Do not use it to rewrite code,
  commands, schemas, evidence, machine-readable files, or exact contract text.
license: MIT
---

# Humanizer

This bundled edition follows the editorial method of Humanizer 2.8.2. It is
kept small so XiaoH can apply the same writing gate on a new computer without
depending on a separately installed personal Skill.

## Scope

Use this Skill for prose that a person is expected to read:

- README files and user guides
- design explanations and decision summaries
- proposals, reports, handoffs, and release notes
- user-facing text produced by XiaoH

Do not rewrite:

- code, commands, paths, identifiers, API names, or schema fields
- JSON, TOML, YAML, hashes, receipts, transcripts, or generated evidence
- exact security, legal, governance, or compatibility clauses whose wording is
  part of the contract

When a document mixes prose and exact material, edit only the prose.

## Process

1. Read the whole source and identify its audience and purpose.
2. Draft a rewrite that preserves every material fact, limit, and decision.
3. Ask: "What still makes this sound obviously AI generated?"
4. Audit the draft for the patterns below.
5. Revise once more and scan the final prose for forbidden punctuation.

Keep the draft and audit in task evidence when the writing change is part of an
implementation or release. Deliver the final version to the reader.

## What to remove

- Promotional claims, inflated importance, and vague authority.
- Warm-up sentences that repeat a heading or announce what comes next.
- Mechanical groups of three, repeated sentence shapes, and synonym cycling.
- Chatbot residue such as "当然", "希望有帮助", "需要我继续吗", or praise
  added only to please the reader.
- Filler, excessive hedging, generic conclusions, and unsupported guesses.
- Diff narration in reference documentation. Describe how the system works now.
- Excessive bold text, inline mini-headings, emojis, and manufactured punchlines.
- Passive or subjectless sentences when naming the actor is clearer.

Prefer concrete nouns, direct verbs, varied sentence length, and simple
constructions. Technical reference material should remain neutral. A first
person voice is appropriate only when the document is explicitly XiaoH's own
introduction.

## Hard checks

- Preserve meaning and technical precision.
- Do not turn an unknown into a fact.
- Keep quoted text and exact identifiers unchanged.
- Final prose must contain no em dash or en dash characters.
- Do not delete detail merely to make the document shorter.
- Do not invent personality in security, legal, or machine-facing material.

## Output

Return:

1. the draft rewrite;
2. a short audit of remaining AI patterns;
3. the final rewrite.

For repository edits, the draft and audit may live in evidence while the final
rewrite is committed.
