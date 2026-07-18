# Knowledge Base Index

The knowledge base is **three layers**:

- **Narrative layer (this file + `knowledge/`)** — hand-compiled editorial articles answering *"why did we do X?"*. Loaded into every session via `hooks/session-start.py`.
- **Atlas layer (`graphify-out/`)** — machine-extracted structural + semantic graph answering *"what is this corpus about?"*. Rebuilt on demand via `/graphify` or incrementally via `graphify update .`.
- **Code index (`.codegraph/`)** — symbol-level call graph answering *"what calls this, what breaks if I change it?"*, via the `codegraph_explore` MCP tool. Per-project, and only where there is real application code to index.

See [docs/pkb-schema.md](../docs/pkb-schema.md) for the full schema, the compile flow, and when to use each layer.

## Atlas (structural layer)

The atlas is generated on first `/graphify` run. Once it exists, these files appear:

| File | What it is |
|------|-----------|
| `../graphify-out/GRAPH_REPORT.md` | God nodes, community labels, surprising connections, suggested questions |
| `../graphify-out/graph.html` | Interactive force-directed viewer (browser) |
| `../graphify-out/graph.json` | Raw nodes + edges for scripting / MCP access |

Consult the atlas first for structural questions (god nodes, cross-community bridges). Consult the narrative (below) for decisions, conventions, and rationale.

## Contents

Articles live under `knowledge/concepts/<category>/`. The template ships with a single `general` category; add more as themes emerge (see `scripts/config.py` → `CONCEPTS_SUBDIRS`).

### general

_No articles yet._ Articles are added automatically as the KB grows: conversations land in `daily/`, and `scripts/compile.py` distills them into `concepts/` articles indexed here.
