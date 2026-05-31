# KB Recall Probes

A frozen set of questions used to measure `kb_recall_hits` (see `program.md`):
how many can be answered correctly from the knowledge base alone.

Add one probe per line as the KB grows, e.g.:

- Q: How is the search index rebuilt? → expect: `scripts/index.py`, BM25/FTS5.

This file is intentionally tracked (the rest of `reports/` is gitignored) so the
probe set stays stable across runs.
