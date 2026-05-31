"""
Compile daily conversation logs into structured knowledge articles.

This is the "LLM compiler" - it reads daily logs (source code) and produces
organized knowledge articles (the executable).

Usage:
    uv run python scripts/compile.py                    # compile new/changed logs only
    uv run python scripts/compile.py --all              # force recompile everything
    uv run python scripts/compile.py --file daily/2026-04-01.md  # compile a specific log
    uv run python scripts/compile.py --dry-run          # show what would be compiled
"""

from __future__ import annotations

# Recursion prevention: set this BEFORE any imports that might trigger Claude
# Code hooks when the Agent SDK spawns a subprocess.
import os
os.environ.setdefault("CLAUDE_INVOKED_BY", "knowledge_base_compile")

import argparse
import asyncio
import sys
from pathlib import Path

from config import CONCEPTS_DIR, CONNECTIONS_DIR, DAILY_DIR, KNOWLEDGE_DIR, PKB_SCHEMA_FILE, now_iso
from utils import (
    file_hash,
    list_raw_files,
    list_wiki_articles,
    load_state,
    read_wiki_index,
    save_state,
)

import index  # rebuilds reports/.search-index.db at end of compile

# ── Paths for the LLM to use ──────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent


async def compile_daily_log(log_path: Path, state: dict) -> float:
    """Compile a single daily log into knowledge articles.

    Sends the full daily log content to the Claude Agent SDK with a structured
    prompt that instructs the LLM to act as a "knowledge compiler" — reading
    the raw conversation transcript and extracting atomic concept articles,
    connection articles, and index updates, then writing them directly to disk.

    The LLM uses the Write/Edit tools (permission_mode="acceptEdits") to create
    and update files in knowledge/ without requiring human approval per-file.
    max_turns=30 gives the agent enough headroom to write several articles,
    update the index, and append to the compile log in a single session.

    After a successful run, the file's SHA-256 hash is stored in state.json so
    that subsequent calls to compile.py (without --all) skip unchanged logs.

    Args:
        log_path: Path to the daily .md log file to compile.
        state: Mutable state dict loaded from state.json; updated in-place and
               persisted to disk before returning.

    Returns:
        API cost in USD for this compilation run, or 0.0 on error.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    log_content = log_path.read_text(encoding="utf-8")
    schema = PKB_SCHEMA_FILE.read_text(encoding="utf-8")
    wiki_index = read_wiki_index()

    # Read existing articles for context so the LLM can extend them rather than
    # creating duplicate articles when the same concept appears across multiple logs.
    existing_articles_context = ""
    existing = {}
    for article_path in list_wiki_articles():
        rel = article_path.relative_to(KNOWLEDGE_DIR)
        existing[str(rel)] = article_path.read_text(encoding="utf-8")

    if existing:
        parts = []
        for rel_path, content in existing.items():
            parts.append(f"### {rel_path}\n```markdown\n{content}\n```")
        existing_articles_context = "\n\n".join(parts)

    timestamp = now_iso()

    # ── Prompt design notes ────────────────────────────────────────────────────
    # The prompt injects three layers of context:
    #   1. Schema (pkb-schema.md): defines article formats, YAML frontmatter
    #      fields, and wikilink conventions the LLM must follow exactly.
    #   2. Index: the one-table catalog of every existing article so the LLM
    #      knows what already exists before creating new files.
    #   3. Existing article bodies: lets the LLM merge new information into
    #      existing articles rather than fragmenting knowledge across files.
    # Quality standards (bullet 6) are explicit minimums — they prevent the LLM
    # from producing stub articles with only a title and one sentence.
    prompt = f"""You are a knowledge compiler. Your job is to read a daily conversation log
and extract knowledge into structured wiki articles.

## Schema (docs/pkb-schema.md — Personal Knowledge Base reference)

{schema}

## Current Wiki Index

{wiki_index}

## Existing Wiki Articles

{existing_articles_context if existing_articles_context else "(No existing articles yet)"}

## Daily Log to Compile

**File:** {log_path.name}

{log_content}

## Your Task

Read the daily log above and compile it into wiki articles following the schema exactly.

### Rules:

1. **Extract key concepts** - Identify 3-7 distinct concepts worth their own article
2. **Create concept articles** in the appropriate category subdirectory under `knowledge/concepts/`. Use the existing category subdirectories if present; otherwise
   create a sensibly-named category directory (e.g. `general/`). One .md file per concept.
   - Use the exact article format from the schema (YAML frontmatter + sections)
   - Include `sources:` in frontmatter pointing to the daily log file
   - Use `[[concepts/slug]]` wikilinks to link to related concepts
   - Write in encyclopedia style - neutral, comprehensive
3. **Create connection articles** in `knowledge/connections/` if this log reveals non-obvious
   relationships between 2+ existing concepts
4. **Update existing articles** if this log adds new information to concepts already in the wiki
   - Read the existing article, add the new information, add the source to frontmatter
5. **Update knowledge/index.md** - Add new entries to the table
   - Each entry: `| [[path/slug]] | One-line summary | source-file | {timestamp[:10]} |`
6. **Append to knowledge/log.md** - Add a timestamped entry:
   ```
   ## [{timestamp}] compile | {log_path.name}
   - Source: daily/{log_path.name}
   - Articles created: [[concepts/x]], [[concepts/y]]
   - Articles updated: [[concepts/z]] (if any)
   ```

### File paths:
- Write concept articles to: {CONCEPTS_DIR}
- Write connection articles to: {CONNECTIONS_DIR}
- Update index at: {KNOWLEDGE_DIR / 'index.md'}
- Append log at: {KNOWLEDGE_DIR / 'log.md'}

### Quality standards:
- Every article must have complete YAML frontmatter
- Every article must link to at least 2 other articles via [[wikilinks]]
- Key Points section should have 3-5 bullet points
- Details section should have 2+ paragraphs
- Related Concepts section should have 2+ entries
- Sources section should cite the daily log with specific claims extracted
"""

    cost = 0.0

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT_DIR),
                # claude_code preset gives the LLM file-system tools and
                # the same permissions as a Claude Code session.
                system_prompt={"type": "preset", "preset": "claude_code"},
                # Write + Edit are essential: the LLM must create and update
                # knowledge/ files directly. Read/Glob/Grep let it verify
                # existing content before overwriting.
                allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
                # acceptEdits means the LLM's Write/Edit calls execute without
                # pausing for human confirmation — required for unattended runs.
                permission_mode="acceptEdits",
                max_turns=30,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        pass  # compilation output - LLM writes files directly
            elif isinstance(message, ResultMessage):
                cost = message.total_cost_usd or 0.0
                print(f"  Cost: ${cost:.4f}")
    except Exception as e:
        print(f"  Error: {e}")
        return 0.0

    # Record the file hash so the next incremental compile can skip this log
    # if it hasn't changed. Using only the first 16 hex chars keeps state.json
    # compact while still being collision-resistant for this use case.
    rel_path = log_path.name
    state.setdefault("ingested", {})[rel_path] = {
        "hash": file_hash(log_path),
        "compiled_at": now_iso(),
        "cost_usd": cost,
    }
    state["total_cost"] = state.get("total_cost", 0.0) + cost
    save_state(state)

    return cost


def main():
    """Entry point for the compile CLI.

    Determines which daily logs need recompilation (new files or files whose
    content has changed since the last compile), then runs each through the
    LLM compiler sequentially.

    Sequential compilation (not parallel) is intentional: each log's output
    may add or update articles that the next log's prompt needs to see, so
    preserving order avoids the LLM creating duplicate articles for the same
    concept when multiple logs cover overlapping topics.
    """
    parser = argparse.ArgumentParser(description="Compile daily logs into knowledge articles")
    parser.add_argument("--all", action="store_true", help="Force recompile all logs")
    parser.add_argument("--file", type=str, help="Compile a specific daily log file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be compiled")
    args = parser.parse_args()

    state = load_state()

    # Determine which files to compile
    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = DAILY_DIR / target.name
        if not target.exists():
            # Try resolving relative to project root
            target = ROOT_DIR / args.file
        if not target.exists():
            print(f"Error: {args.file} not found")
            sys.exit(1)
        to_compile = [target]
    else:
        all_logs = list_raw_files()
        if args.all:
            to_compile = all_logs
        else:
            # Incremental mode: only compile logs that are new or have been
            # modified since the last compile (detected via SHA-256 hash stored
            # in state.json). This avoids re-spending API budget on unchanged logs.
            to_compile = []
            for log_path in all_logs:
                rel = log_path.name
                prev = state.get("ingested", {}).get(rel, {})
                if not prev or prev.get("hash") != file_hash(log_path):
                    to_compile.append(log_path)

    if not to_compile:
        print("Nothing to compile - all daily logs are up to date.")
        return

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Files to compile ({len(to_compile)}):")
    for f in to_compile:
        print(f"  - {f.name}")

    if args.dry_run:
        return

    # Compile each file sequentially
    total_cost = 0.0
    for i, log_path in enumerate(to_compile, 1):
        print(f"\n[{i}/{len(to_compile)}] Compiling {log_path.name}...")
        cost = asyncio.run(compile_daily_log(log_path, state))
        total_cost += cost
        print("  Done.")

    articles = list_wiki_articles()
    print(f"\nCompilation complete. Total cost: ${total_cost:.2f}")
    print(f"Knowledge base: {len(articles)} articles")

    # Keep the BM25 search index fresh after every compile run. The index
    # is small (~1 MB DB) and fully rebuilt in <1s, so this is cheap and
    # eliminates a drift class where new daily/ logs are unsearchable.
    try:
        n = index.build()
        print(f"Search index: {n} chunks indexed")
    except Exception as e:
        # Compile must not fail if the index can't be built — the daily
        # logs are still correctly compiled into knowledge/, which is the
        # primary purpose of this script.
        print(f"Search index: SKIPPED ({e})")


if __name__ == "__main__":
    main()
