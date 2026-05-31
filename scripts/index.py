"""Build and rebuild the BM25 search index for the knowledge base.

Chunks every `.md` file under `knowledge/` and `daily/` by H2/H3 section
boundaries, then ingests each chunk into a SQLite FTS5 virtual table at
`reports/.search-index.db` (gitignored). Idempotent: drops and recreates
the table on every build, since the corpus is small enough (<2 MB) that
full rebuilds are sub-second.

The chunker is exposed as a pure function (`chunk_markdown`) so it can be
unit-tested without touching the filesystem.

Usage:
    uv run python scripts/index.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Make scripts/ importable as a flat module set (config.py + utils.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DAILY_DIR, KNOWLEDGE_DIR, REPORTS_DIR

DB_PATH = REPORTS_DIR / ".search-index.db"


def chunk_markdown(text: str, path: str) -> list[dict]:
    """Split a markdown document into chunks at H2/H3 boundaries.

    Why: BM25 over whole files dilutes signal. A query that matches one
    section gets buried by noise from unrelated sections. Section-level
    chunks give Claude a `path:start-end` citation it can `Read` directly.

    How: Walk lines tracking the current section. When a line starts with
    `## ` or `### `, finalize the open chunk (if it has non-whitespace body)
    and open a new one named after the heading text. Files with no H2/H3
    are emitted as one chunk named `(file)`.

    Pre-heading content (H1 title, YAML frontmatter, preamble before the
    first H2/H3) is intentionally discarded when at least one H2/H3 exists
    in the file — it would otherwise become BM25 noise on every chunk.
    Files with no H2/H3 still emit the full body as a single `(file)` chunk
    so prose-only daily logs remain searchable.

    Args:
        text: Full markdown source.
        path: File path, used only for error context (not stored here).

    Returns:
        List of dicts with keys: section, start_line, end_line, body.
    """
    lines = text.splitlines()
    chunks: list[dict] = []
    # `is_heading` tracks whether the current chunk was opened by an H2/H3.
    # Pre-heading content (H1 title, preamble) is collected but only flushed
    # when the file has no H2/H3 headings at all (the `(file)` fallback).
    current = {"section": "(file)", "start_line": 1, "body_lines": [], "is_heading": False}

    def flush(end_line: int) -> None:
        body = "\n".join(current["body_lines"]).strip()
        if body and current["is_heading"]:
            chunks.append({
                "section": current["section"],
                "start_line": current["start_line"],
                "end_line": end_line,
                "body": body,
            })

    has_headings = False
    for i, line in enumerate(lines, start=1):
        if line.startswith("## ") or line.startswith("### "):
            has_headings = True
            flush(i - 1)
            heading = line.lstrip("#").strip()
            current = {"section": heading, "start_line": i, "body_lines": [], "is_heading": True}
        else:
            current["body_lines"].append(line)

    if has_headings:
        # Flush the last heading-opened chunk (if non-empty).
        flush(len(lines))
    else:
        # No headings at all: emit entire file as a single `(file)` chunk.
        body = "\n".join(current["body_lines"]).strip()
        if body:
            chunks.append({
                "section": "(file)",
                "start_line": 1,
                "end_line": len(lines),
                "body": body,
            })
    return chunks


def build(corpora: list[Path] | None = None, db_path: Path | None = None) -> int:
    """Rebuild the FTS5 index from scratch over the given corpora.

    Why: full rebuild rather than incremental — the corpus is small (~1 MB
    total, <100 files) so a fresh build costs <1s and avoids the
    complexity of tracking per-chunk deletes/updates.

    How:
      1. Drop and re-create the FTS5 virtual table.
      2. Walk each corpus dir for `*.md`.
      3. Chunk each file, insert one row per chunk.

    Args:
        corpora: Directories to index. Defaults to [KNOWLEDGE_DIR, DAILY_DIR].
        db_path: Destination DB path. Defaults to reports/.search-index.db.

    Returns:
        Total number of chunks ingested.
    """
    if corpora is None:
        corpora = [KNOWLEDGE_DIR, DAILY_DIR]
    if db_path is None:
        db_path = DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS kb_chunks")
        # `path` / `section` / line numbers are UNINDEXED so FTS5 doesn't
        # waste tokenization budget on them; only `body` is searchable.
        conn.execute(
            """
            CREATE VIRTUAL TABLE kb_chunks USING fts5(
                path UNINDEXED,
                section UNINDEXED,
                start_line UNINDEXED,
                end_line UNINDEXED,
                body,
                tokenize = 'porter unicode61'
            )
            """
        )

        total = 0
        for corpus in corpora:
            if not corpus.exists():
                continue
            # Store paths relative to the corpus parent (= repo root in
            # production, = tmp dir in tests). Absolute paths are unportable
            # — every citation would embed the indexer's machine layout —
            # and Claude's Read tool resolves repo-relative paths fine when
            # cwd is the project root.
            base = corpus.parent
            for md_path in sorted(corpus.rglob("*.md")):
                text = md_path.read_text(encoding="utf-8")
                rel = str(md_path.relative_to(base))
                for ch in chunk_markdown(text, path=rel):
                    conn.execute(
                        "INSERT INTO kb_chunks (path, section, start_line, end_line, body) VALUES (?, ?, ?, ?, ?)",
                        (rel, ch["section"], ch["start_line"], ch["end_line"], ch["body"]),
                    )
                    total += 1
        conn.commit()
    return total


def main() -> None:
    """Entry point for the index CLI.

    Rebuilds the search index from the default corpora (knowledge/ + daily/)
    and prints a one-line summary. Wired into scripts/compile.py to keep the
    index fresh after every compile run; can also be invoked standalone.
    """
    n = build()
    print(f"Indexed {n} chunks to {DB_PATH}")


if __name__ == "__main__":
    main()
