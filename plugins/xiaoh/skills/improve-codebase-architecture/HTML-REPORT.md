# HTML Report Format

Render the architectural review as one offline HTML file in the OS temp directory. Use embedded CSS,
semantic HTML, and inline SVG only. Do not require a CDN, package install, network request, build
step, or external asset.

## Scaffold

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Architecture review — {{repo name}}</title>
    <style>
      :root { color-scheme: light; font-family: system-ui, sans-serif; }
      body { margin: 0; background: #fafaf9; color: #0f172a; }
      main { max-width: 64rem; margin: auto; padding: 3rem 1.5rem; }
      article, .recommendation { background: white; border: 1px solid #e2e8f0;
        border-radius: .75rem; padding: 1.25rem; margin: 1.5rem 0; }
      .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
      .diagram { min-height: 18rem; border: 1px solid #e2e8f0; border-radius: .5rem;
        padding: 1rem; position: relative; }
      .seam { stroke-dasharray: 4 4; }
      .leak { stroke: #dc2626; }
      .deep { background: linear-gradient(135deg, #0f172a, #1e293b); color: white; }
      code, .files { font-family: ui-monospace, monospace; font-size: .875rem; }
      @media (max-width: 720px) { .comparison { grid-template-columns: 1fr; } }
    </style>
  </head>
  <body>
    <main>
      <header>...</header>
      <section id="candidates">...</section>
      <section id="top-recommendation">...</section>
    </main>
  </body>
</html>
```

## Header

Repo name, date, and a compact legend: solid box = module, dashed line = seam, red arrow = leakage, thick dark box = deep module. No introduction paragraph — straight into the candidates.

## Candidate card

The diagrams carry the weight. Prose is sparse, plain, and uses the glossary terms from `$xiaoh:codebase-design` without ceremony.

Each candidate is one `<article>`:

- **Title** — short, names the deepening (e.g. "Collapse the Order intake pipeline").
- **Badge row** — recommendation strength (`Strong` = emerald, `Worth exploring` = amber, `Speculative` = slate), plus a tag for the dependency category (`in-process`, `local-substitutable`, `ports & adapters`, `mock`).
- **Files** — monospaced list, `font-mono text-sm`.
- **Before / After diagram** — the centrepiece. Two columns, side by side. See patterns below.
- **Problem** — one sentence. What hurts.
- **Solution** — one sentence. What changes.
- **Wins** — bullets, ≤6 words each. e.g. "Tests hit one interface", "Pricing logic stops leaking", "Delete 4 shallow wrappers".
- **ADR callout** (if applicable) — one line in an amber-tinted box.

No paragraphs of explanation. If the diagram needs a paragraph to be understood, redraw the diagram.

## Diagram patterns

Pick the pattern that fits the candidate. Mix them. Don't make every diagram look the same — variety is part of the point.

### Inline SVG graph (the workhorse for dependencies / call flow)

Use inline SVG when the point is "X calls Y calls Z, and look at the mess." Draw module boxes,
arrow markers, and labels directly so the file remains deterministic and offline.

```html
<div class="diagram">
  <svg viewBox="0 0 640 240" role="img" aria-label="Order call flow">
    <defs>
      <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 z" fill="currentColor" />
      </marker>
    </defs>
    <rect x="20" y="80" width="150" height="64" rx="8" fill="#fff" stroke="#64748b" />
    <text x="95" y="116" text-anchor="middle">OrderHandler</text>
    <line x1="170" y1="112" x2="260" y2="112" stroke="#64748b" marker-end="url(#arrow)" />
    <rect x="270" y="80" width="150" height="64" rx="8" fill="#0f172a" stroke="#0f172a" />
    <text x="345" y="116" text-anchor="middle" fill="#fff">Order module</text>
  </svg>
</div>
```

### Hand-built boxes-and-arrows

Modules as `<div>`s with borders and labels. Arrows as inline SVG `<line>` or `<path>` elements
positioned absolutely over a relative container. Use this when the "after" diagram should feel like
one thick-bordered deep module with greyed-out internals.

### Cross-section (good for layered shallowness)

Stack horizontal bands (`h-12 border-l-4`) to show layers a call passes through. Before: 6 thin layers each doing nothing. After: 1 thick band labelled with the consolidated responsibility.

### Mass diagram (good for "interface as wide as implementation")

Two rectangles per module — one for interface surface area, one for implementation. Before: interface rectangle is nearly as tall as the implementation rectangle (shallow). After: interface rectangle is short, implementation rectangle is tall (deep).

### Call-graph collapse

Before: a tree of function calls rendered as nested boxes. After: the same tree collapsed into one box, with the now-internal calls shown faded inside it.

## Style guidance

- Lean editorial, not corporate-dashboard. Use generous whitespace and system fonts.
- Colour sparingly: one accent (emerald or indigo) plus red for leakage and amber for warnings.
- Keep diagrams ~320px tall so before/after sits comfortably side by side without scrolling.
- Use `text-xs uppercase tracking-wider` for module labels inside diagrams — they should read as schematic, not as UI.
- Keep the report static. Do not add scripts, external fonts, network assets, or app code.

## Top recommendation section

One larger card. Candidate name, one sentence on why, anchor link to its card. That's it.

## Tone

Plain English, concise — but the architectural nouns and verbs come straight from `$xiaoh:codebase-design`. Concision is not an excuse to drift.

**Use exactly:** module, interface, implementation, depth, deep, shallow, seam, adapter, leverage, locality.

**Never substitute:** component, service, unit (for module) · API, signature (for interface) · boundary (for seam) · layer, wrapper (for module, when you mean module).

**Phrasings that fit the style:**

- "Order intake module is shallow — interface nearly matches the implementation."
- "Pricing leaks across the seam."
- "Deepen: one interface, one place to test."
- "Two adapters justify the seam: HTTP in prod, in-memory in tests."

**Wins bullets** name the gain in glossary terms: *"locality: bugs concentrate in one module"*, *"leverage: one interface, N call sites"*, *"interface shrinks; implementation absorbs the wrappers"*. Don't write *"easier to maintain"* or *"cleaner code"* — those terms aren't in the glossary and don't earn their place.

No hedging, no throat-clearing, no "it's worth noting that…". If a sentence could be a bullet, make it a bullet. If a bullet could be cut, cut it. If a term isn't in the `$xiaoh:codebase-design` glossary, reach for one that is before inventing a new one.
