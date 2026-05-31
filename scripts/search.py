"""Query the BM25 KB index built by scripts/index.py.

Returns top-K chunks ranked by FTS5's BM25 score (note: FTS5's `bm25()`
returns *lower is better*; we negate it so callers can treat higher as
better). Output is either human-readable text (default, Claude-Code-
friendly with `path:start-end` citations) or JSON (for hook consumers).

Usage:
    uv run python scripts/search.py "query text" [-k 5] [--min-score 5.0] [--json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from index import DB_PATH


def _sanitize_query(q: str) -> str:
    """Quote each non-empty token so FTS5 treats user input as a phrase set.

    Why: FTS5's MATCH grammar treats characters like `:` `-` `(` as syntax,
    so passing a raw user prompt as a MATCH expression raises
    `sqlite3.OperationalError: malformed MATCH expression`. Wrapping each
    whitespace-delimited token in double quotes (and escaping internal
    quotes) gives an OR-of-terms query that is always syntactically valid.
    """
    tokens = [t.strip() for t in q.split() if t.strip()]
    quoted = ['"' + t.replace('"', '""') + '"' for t in tokens]
    return " OR ".join(quoted) if quoted else ""


def search(query: str, db_path: Path | None = None, k: int = 5, min_score: float = 0.0) -> list[dict]:
    """Run a BM25 search and return ranked chunks.

    Why: hides FTS5 boilerplate (sanitization, score inversion, schema
    knowledge) from callers (the hook + the CLI + future MCP wrappers).

    Args:
        query: Natural-language query string.
        db_path: SQLite DB. Defaults to the index.py-managed location.
        k: Max hits to return.
        min_score: Drop hits with score < this value (after negation, so
            higher is stricter).

    Returns:
        List of dicts: {path, section, start_line, end_line, body, score}.
        Empty list on no match, no DB, or empty/invalid query.
    """
    if db_path is None:
        db_path = DB_PATH
    if not Path(db_path).exists():
        return []

    sanitized = _sanitize_query(query)
    if not sanitized:
        return []

    with sqlite3.connect(db_path) as conn:
        try:
            rows = conn.execute(
                """
                SELECT path, section, start_line, end_line, body, bm25(kb_chunks) AS raw
                FROM kb_chunks
                WHERE kb_chunks MATCH ?
                ORDER BY raw
                LIMIT ?
                """,
                (sanitized, k),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    hits: list[dict] = []
    for path, section, start, end, body, raw in rows:
        # FTS5 bm25() is lower = better; negate so callers can use the more
        # natural "higher = more relevant" convention everywhere else.
        score = -raw
        if score < min_score:
            continue
        hits.append({
            "path": path,
            "section": section,
            "start_line": start,
            "end_line": end,
            "body": body,
            "score": round(score, 2),
        })
    return hits


def _print_text(hits: list[dict]) -> None:
    """Print hits in a format Claude can chain into a Read() call.

    Line 1 of each hit is `path:start-end` — the exact form Claude's Read
    tool needs as `(file_path, offset, limit)`. Body excerpts are clipped
    to 200 chars so the output stays scannable.
    """
    if not hits:
        print("(no matches)")
        return
    for i, h in enumerate(hits, 1):
        excerpt = h["body"].replace("\n", " ")
        if len(excerpt) > 200:
            excerpt = excerpt[:200].rstrip() + "..."
        print(f"{i}. score={h['score']:.2f}  {h['path']}:{h['start_line']}-{h['end_line']}")
        print(f"   ## {h['section']}")
        print(f"   {excerpt}")
        print()


def main() -> int:
    """Entry point for the search CLI."""
    parser = argparse.ArgumentParser(description="Search the KB BM25 index")
    parser.add_argument("query", help="Natural-language query")
    parser.add_argument("-k", type=int, default=5, help="Max results (default 5)")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Drop hits below this score (higher = stricter, default 0)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    hits = search(args.query, k=args.k, min_score=args.min_score)
    if args.json:
        print(json.dumps(hits))
    else:
        _print_text(hits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
