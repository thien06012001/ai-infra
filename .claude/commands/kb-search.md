---
description: Manual BM25 search over knowledge/ + daily/ logs. Use when auto-injection didn't surface what you need, or when you want top-K results in the conversation rather than as injected context.
---

Run the following and use the results to answer the user's question. Each hit prints `path:start-end` which you can pass directly to Read.

```bash
uv run python scripts/search.py "$ARGUMENTS" -k 5
```

If no hits are relevant, fall back to:

```bash
uv run python scripts/query.py "$ARGUMENTS"
```

(`/kb-search` is the cheap path; `query.py` loads the full KB into a single LLM call and is the high-effort synthesis path.)
