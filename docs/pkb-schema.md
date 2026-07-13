# Personal Knowledge Base — Full Schema & Operations

> Adapted from [Andrej Karpathy's LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) architecture.
> Instead of ingesting external articles, this system compiles knowledge from your own AI conversations.

## Contents
- [Quick Reference](#quick-reference) (commands + hooks at a glance)
- [The Compiler Analogy](#the-compiler-analogy)
- [Three-Layer Architecture](#three-layer-architecture) (narrative `knowledge/` + atlas `graphify-out/` + code index `.codegraph/`)
- [Architecture](#architecture) (Layer 1: daily/, Layer 2: knowledge/, Layer 3: schema reference)
- [Structural Files](#structural-files) (index.md, log.md)
- [Article Formats](#article-formats) (concepts, connections)
- [Core Operations](#core-operations) (compile, query, lint)
- [Conventions](#conventions)
- [Hook System](#hook-system-automatic-capture) (settings format, hook details, background flush, JSONL transcript format)
- [Script Details](#script-details) (compile.py, query.py, lint.py, measure-infra.py)
- [State Tracking](#state-tracking)
- [Dependencies](#dependencies)
- [Costs](#costs)
- [Customization](#customization)

## Quick Reference

### Commands

| Command                                     | Layer     | Purpose                                       |
| ------------------------------------------- | --------- | --------------------------------------------- |
| `uv run python scripts/compile.py`          | narrative | Compile daily logs → `knowledge/` articles    |
| `uv run python scripts/query.py "question"` | narrative | Ask the narrative KB (index-guided, no RAG)   |
| `uv run python scripts/lint.py`             | narrative | Run health checks on `knowledge/` (incl. BM25 probe recall) |
| `uv run python scripts/measure-infra.py`    | narrative | Infra perf loop harness (stub)                |
| `uv run python scripts/search.py "..."`     | narrative | BM25 search (cheap, ~10ms) over knowledge/ + daily/ |
| `/graphify`                                 | atlas     | Rebuild full graph from scratch (AST + LLM)   |
| `graphify update .`                         | atlas     | Incremental AST-only rebuild (free, no LLM)   |
| `/graphify query "question"`                | atlas     | Subgraph traversal answer with `source_location` citations |
| `graphify save-result ...`                  | atlas     | File a query answer back into the graph       |

### Hooks (Claude Code)

| Hook                    | Event                | Purpose                                    |
| ----------------------- | -------------------- | ------------------------------------------ |
| `session-start.py`      | SessionStart         | Injects KB index + auto-syncs main         |
| `session-end.py`        | SessionEnd           | Extracts conversation → daily log          |
| `pre-compact.py`        | PreCompact           | Captures context before compaction         |
| `worktree-create.py`    | WorktreeCreate       | Derives branch prefix from transcript      |
| `cleanup-worktrees.py`  | SessionStart (async) | Removes merged worktrees                   |
| `block-env-edits.cjs`   | PreToolUse           | Blocks accidental edits to `.env*` files   |
| `block-stray-docs.cjs`  | PreToolUse           | Blocks stray `.md` files outside allowed locations |
| `kb-auto-inject.py`     | UserPromptSubmit     | Auto-injects top-3 BM25 hits before each prompt; `KB_AUTO_INJECT=0` to disable |

The auto-injection hook fires on every user prompt, runs BM25 over the KB, and prepends a `<kb-context>` block with up to three citations (`path:start-end` form, ready to pass to `Read`). It is silenced when (a) the prompt is short / a slash command / a pure acknowledgment, (b) `KB_AUTO_INJECT=0` is set in the env, or (c) `CLAUDE_INVOKED_BY` is already set (nested-Claude recursion guard).

The PKB-specific hooks (session-start, session-end, pre-compact, cleanup-worktrees) are documented in detail under [Hook System](#hook-system-automatic-capture) below. The generic guards (block-env-edits, block-stray-docs) live as `.cjs` files in `hooks/` — read the source for details.

## Three-Layer Architecture

The knowledge system is three complementary layers. They are combined at the index layer, not merged into one corpus.

| Layer | Location | Role | Produced by |
|-------|----------|------|-------------|
| **Narrative** | `knowledge/` | *Why did we do X?* — rationale, conventions, decisions | Hand-compiled from `daily/` via `compile.py` |
| **Atlas** | `graphify-out/` | *What is this corpus about?* — god nodes, communities, cross-cutting edges | Machine-extracted (AST + semantic) via `/graphify` |
| **Code index** | `.codegraph/` | *What calls this symbol? What breaks if I change it?* — call paths, blast radius | `codegraph init` + its file watcher (AST, $0, no LLM) |

The three layers differ in what a **node** is — a concept, a cluster, and a symbol respectively. That is why none replaces another: a symbol-level call graph cannot answer "what is this corpus about," and a concept-level graph cannot tell you precisely what calls `ProcessOrder`.

**Combined via cross-links, not duplication:**
- `knowledge/index.md` carries an **Atlas** section at the top linking to `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.html`, and `graphify-out/graph.json`.
- Graphify ingests every `knowledge/*.md` file as doc nodes, so the narrative appears inside the atlas automatically.
- The code index is queried live over MCP (`codegraph_explore`); it produces no committed artifact. `.codegraph/` is gitignored.
- No Q&A layer — `graphify save-result` saves query answers directly back into the graph.

**When to use each:**
- Decision rationale, conventions, "why" questions → **narrative**
- Corpus shape, god nodes, cross-community bridges, INFERRED-edge verification → **atlas**
- "Who calls this?", "what is the blast radius of this change?" → **code index**
- Together: a narrative article explains *why*, the atlas shows *where it applies*, the code index shows *exactly what it touches*

**Scope of the code index:** it exists only in repos that contain real code. `ai-infra` itself is **not** indexed — 17 hook/script files with ~76 mostly-independent symbols yield a call graph that answers nothing. The template installs the binary globally; `codegraph init` runs per-project, on demand.

**Known limits of the code index:** static analysis only (no dynamic dispatch, reflection, or DI wiring); files > 1 MB are skipped; a 2s staleness window follows each edit; on WSL2, repos on `/mnt/` Windows mounts need `CODEGRAPH_NO_DAEMON=1`.

**`codegraph impact` truncates by default — this one bites.** Its `--depth` defaults to `2`, and a truncated blast radius is indistinguishable from a complete one in the output. Verified on a 4-function, 2-file probe: `impact validate` reported 3 affected symbols and stopped inside the first file; `impact validate --depth 5` reported all 5, including the cross-file caller. Cross-file resolution itself works correctly — the default depth was the whole difference. Always pass an explicit `--depth` before acting on a blast radius, and state the depth you used.

## The Compiler Analogy

```
daily/          = source code    (your conversations - the raw material)
LLM             = compiler       (extracts and organizes knowledge)
knowledge/      = executable     (structured, queryable knowledge base)
lint            = test suite     (health checks for consistency)
queries         = runtime        (using the knowledge)
```

You don't manually organize your knowledge. You have conversations, and the LLM handles the synthesis, cross-referencing, and maintenance.

## Architecture

### Layer 1: `daily/` - Conversation Logs (Immutable Source)

Daily logs capture what happened in your AI coding sessions. These are the "raw sources" - append-only, never edited after the fact.

```
daily/
├── 2026-04-01.md
├── 2026-04-02.md
├── ...
```

Each file follows this format:

```markdown
# Daily Log: YYYY-MM-DD

## Sessions

### Session (HH:MM) - Brief Title

**Context:** What the user was working on.

**Key Exchanges:**

- User asked about X, assistant explained Y
- Decided to use Z approach because...

**Decisions Made:**

- Chose library X over Y because...

**Lessons Learned:**

- Always do X before Y to avoid...

**Action Items:**

- [ ] Follow up on X
```

### Layer 2: `knowledge/` - Compiled Knowledge (LLM-Owned)

The LLM owns this directory entirely. Humans read it but rarely edit it directly.

```
knowledge/
├── index.md              # Master catalog - category-grouped with TOC; top-of-file Atlas section links to graphify-out/
├── log.md                # Append-only chronological build log
├── concepts/             # Atomic knowledge articles, organized by category
│   ├── general/          #   Default category — split into more as the KB grows
│   └── <your-category>/  #   Add categories that fit your project (e.g. api/, infra/, frontend/)
└── connections/          # Cross-cutting insights linking 2+ concepts (hand-authored narrative only — machine-discovered cross-community edges live in graphify-out/GRAPH_REPORT.md)
```

> Categories are discovered, not fixed. Start with `general/` and create new category subdirectories under `concepts/` as themes emerge. `scripts/config.py` lists the active categories (`CONCEPTS_SUBDIRS`); add yours there if a script needs to enumerate them.

### Layer 3: Schema Reference

This file (`docs/pkb-schema.md`) is the "compiler specification" — the canonical reference for the system's behavior. It is read by `compile.py` to provide the LLM compiler with article formats and operational guidelines.

## Structural Files

### `knowledge/index.md` - Master Catalog

A table listing every knowledge article. This is the primary retrieval mechanism - the LLM reads this FIRST when answering any query, then selects relevant articles to read in full.

Format:

```markdown
# Knowledge Base Index

| Article                           | Summary                                  | Compiled From          | Updated    |
| --------------------------------- | ---------------------------------------- | ---------------------- | ---------- |
| [[concepts/general/some-concept]] | One-line summary of the concept          | daily/2026-04-02.md    | 2026-04-02 |
```

### `knowledge/log.md` - Build Log

Append-only chronological record of every compile, query, and lint operation.

```markdown
# Knowledge Base Compilation Log

## [2026-04-01T14:30:00] compile | Daily Log 2026-04-01

- Source: daily/2026-04-01.md
- Articles created: [[concepts/general/some-concept]]
- Articles updated: (none)
```

## Article Formats

### Concept Articles (`knowledge/concepts/`)

One article per atomic piece of knowledge. These are facts, patterns, decisions, preferences, and lessons extracted from your conversations.

```markdown
---
title: "Concept Name"
aliases: [alternate-name, abbreviation]
tags: [domain, topic]
sources:
  - "daily/2026-04-01.md"
created: 2026-04-01
updated: 2026-04-03
---

# Concept Name

[2-4 sentence core explanation]

## Key Points

- [Bullet points, each self-contained]

## Details

[Deeper explanation, encyclopedia-style paragraphs]

## Related Concepts

- [[concepts/general/related-concept]] - How it connects

## Sources

- [[daily/2026-04-01.md]] - Initial discovery
```

### Connection Articles (`knowledge/connections/`)

Cross-cutting synthesis linking 2+ concepts. Created when a conversation reveals a non-obvious relationship.

```markdown
---
title: "Connection: X and Y"
connects:
  - "concepts/general/concept-x"
  - "concepts/general/concept-y"
sources:
  - "daily/2026-04-04.md"
created: 2026-04-04
updated: 2026-04-04
---

# Connection: X and Y

## The Connection

[What links these concepts]

## Key Insight

[The non-obvious relationship discovered]

## Related Concepts

- [[concepts/general/concept-x]]
- [[concepts/general/concept-y]]
```

## Core Operations

### 1. Compile (daily/ -> knowledge/)

When processing a daily log:

1. Read the daily log file
2. Read `knowledge/index.md` to understand current knowledge state
3. Read existing articles that may need updating
4. For each piece of knowledge found in the log:
   - If an existing concept article covers this topic: UPDATE it, add the daily log as a source
   - If it's a new topic: CREATE a new `concepts/` article in the appropriate category
5. If the log reveals a non-obvious connection between 2+ existing concepts: CREATE a `connections/` article
6. UPDATE `knowledge/index.md` with new/modified entries
7. APPEND to `knowledge/log.md`

**Important guidelines:**

- A single daily log may touch 3-10 knowledge articles
- Prefer updating existing articles over creating near-duplicates
- Use Obsidian-style `[[wikilinks]]` with full relative paths from knowledge/
- Write in encyclopedia style - factual, concise, self-contained
- Every article must have YAML frontmatter
- Every article must link back to its source daily logs

### 2. Query (Ask the Knowledge Base)

Two paths, matched to the layer:

**Narrative query (`scripts/query.py`)** — for decisions, conventions, rationale:
1. Read `knowledge/index.md` (the master catalog)
2. Based on the question, identify relevant articles from the index
3. Read those articles in full
4. Synthesize an answer with `[[wikilink]]` citations

**Atlas query (`/graphify query "..."`)** — for structural / cross-cutting lookups:
1. BFS or DFS traversal over `graphify-out/graph.json` starting from best-matching nodes
2. Answer using only subgraph edges, citing `source_location` from each node
3. `graphify save-result` stores the answer back into the graph for compounding

**Why narrative has no RAG:** At personal knowledge base scale (50-500 articles), the LLM reading a structured index outperforms cosine similarity. At repo scale (10K+ nodes) the atlas takes over.

### 3. Lint (Health Checks)

Run periodically:

1. **Broken links** - `[[wikilinks]]` pointing to non-existent articles
2. **Orphan pages** - Articles with zero inbound links
3. **Orphan sources** - Daily logs that haven't been compiled yet
4. **Stale articles** - Source daily log changed since article was last compiled
5. **Contradictions** - Conflicting claims across articles (requires LLM judgment)
6. **Missing backlinks** - A links to B but B doesn't link back to A
7. **Sparse articles** - Below 200 words, likely incomplete

Output: a markdown report with severity levels (error, warning, suggestion).

## Conventions

- **Wikilinks:** Use Obsidian-style `[[path/to/article]]` without `.md` extension
- **Writing style:** Encyclopedia-style, factual, third-person where appropriate
- **Dates:** ISO 8601 (YYYY-MM-DD for dates, full ISO for timestamps in log.md)
- **File naming:** lowercase, hyphens for spaces (e.g., `git-rebase-workflow.md`)
- **Frontmatter:** Every article must have YAML frontmatter with at minimum: title, sources, created, updated
- **Sources:** Always link back to the daily log(s) that contributed to an article

## Hook System (Automatic Capture)

Hooks are configured in `.claude/settings.json` and fire automatically when you use Claude Code in this project.

### `.claude/settings.json` Format

Commands use `uv run --directory "$CLAUDE_PROJECT_DIR" python "$CLAUDE_PROJECT_DIR/hooks/<hook>.py"`. Empty `matcher` catches all events. The `"async": true` flag means a hook runs in the background without blocking. See the shipped `.claude/settings.json` for the full wiring.

### Hook Details

**`session-start.py`** (SessionStart)

- Pure local I/O, no API calls, runs in under 1 second
- Reads `knowledge/index.md` and the most recent daily log
- **Auto-syncs `main`**: if the current branch is `main` and the working tree is clean, runs `git pull --ff-only`. Skips in linked worktrees and when the tree is dirty.
- Outputs JSON to stdout: `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`
- Max context: 20,000 characters

**`session-end.py`** (SessionEnd)

- Reads hook input from stdin (JSON with `session_id`, `transcript_path`, `cwd`)
- Copies the raw JSONL transcript to a temp file
- Spawns `flush.py` as a fully detached background process
- Recursion guard: exits immediately if `CLAUDE_INVOKED_BY` env var is set

**`pre-compact.py`** (PreCompact)

- Same architecture as session-end.py
- Fires before Claude Code auto-compacts the context window
- Captures context before summarization discards it

**`cleanup-worktrees.py`** (SessionStart, async)

- Runs asynchronously alongside `session-start.py`
- Calls `git fetch --prune`, detects local branches whose upstream is `[gone]`, removes their worktrees and deletes the local branch
- Skips the active worktree and any worktree with uncommitted changes

### Background Flush Process (`flush.py`)

Spawned by both hooks as a fully detached background process (`DETACHED_PROCESS` on Windows, `start_new_session=True` on Mac/Linux).

**What flush.py does:**

1. Sets `CLAUDE_INVOKED_BY=memory_flush` env var (prevents recursive hook firing)
2. Reads the pre-extracted conversation context from the temp `.md` file
3. Skips if context is empty or the same session was flushed within 60 seconds (dedup)
4. Calls Claude Agent SDK (`query()` with `allowed_tools=[]`, `max_turns=2`)
5. Claude decides what's worth saving — returns structured bullet points or `FLUSH_OK`
6. Appends result to `daily/YYYY-MM-DD.md`
7. **End-of-day auto-compilation:** past `COMPILE_AFTER_HOUR` (18:00 local), if today's log changed since its last compilation, spawns `compile.py` as another detached process.

### JSONL Transcript Format

Claude Code stores conversations as `.jsonl` files. Messages are nested under a `message` key:

```python
entry = json.loads(line)
msg = entry.get("message", {})
role = msg.get("role", "")        # "user" or "assistant"
content = msg.get("content", "")  # string or list of content blocks
```

## Script Details

### compile.py - The Compiler

Uses the Claude Agent SDK's async streaming `query()`. Builds a prompt with the schema (this file), current index, all existing articles, and the daily log; Claude reads the log, decides what to extract, and writes files directly. Incremental: tracks SHA-256 hashes of daily logs in `state.json`, skips unchanged files.

```bash
uv run python scripts/compile.py              # compile new/changed only
uv run python scripts/compile.py --all        # force recompile everything
uv run python scripts/compile.py --file daily/2026-04-01.md
uv run python scripts/compile.py --dry-run
```

### query.py - Index-Guided Retrieval

Loads the entire knowledge base into context (index + all articles). No RAG.

```bash
uv run python scripts/query.py "What conventions do I use?"
```

### lint.py - Health Checks

```bash
uv run python scripts/lint.py                    # all checks
uv run python scripts/lint.py --structural-only  # skip LLM check (free)
```

Reports saved to `reports/lint-YYYY-MM-DD.md`.

### measure-infra.py - Infra Perf Harness

Stub harness that writes a row into `reports/infra-runs.tsv` with the four infra-loop metrics from [`program.md`](../program.md): `cycle_seconds`, `friction_events`, `kb_recall_hits`, `infra_loc`. The frozen probe set used by `kb_recall_hits` lives at `reports/kb-probes.md`.

```bash
uv run python scripts/measure-infra.py
```

### index.py - BM25 Index Builder

Chunks all `knowledge/` articles and `daily/` logs into overlapping windows, then ingests them into a SQLite FTS5 table. Run automatically at the end of `compile.py`; also invocable standalone.

```bash
uv run python scripts/index.py
```

### search.py - BM25 Search

Queries the FTS5 index and returns ranked `path:start-end` citations. Used by `hooks/kb-auto-inject.py`.

```bash
uv run python scripts/search.py "query string"
```

## State Tracking

`scripts/state.json` tracks ingested daily-log hashes, compilation timestamps, query count, and last-lint timestamp. `scripts/last-flush.json` tracks flush deduplication. Both are gitignored and regenerated automatically.

## Dependencies

`pyproject.toml`:

- `claude-agent-sdk` - Claude Agent SDK for LLM calls with tool use
- `python-dotenv` - Environment variable management
- `tzdata` - Timezone data
- Python 3.12+, managed by [uv](https://docs.astral.sh/uv/)

No API key needed — uses Claude Code's built-in credentials at `~/.claude/.credentials.json`.

## Costs

| Operation                       | Cost        |
| ------------------------------- | ----------- |
| Compile one daily log           | $0.45-0.65  |
| Query (no file-back)            | ~$0.15-0.25 |
| Full lint (with contradictions) | ~$0.15-0.25 |
| Structural lint only            | $0.00       |
| Memory flush (per session)      | ~$0.02-0.05 |

## Customization

### Additional Article Types

Add directories like `people/`, `projects/`, `tools/` to `knowledge/`. Define the article format in this file and update `utils.py`'s `list_wiki_articles()` to include them.

### Categories

Categories live under `knowledge/concepts/<category>/`. The active set is listed in `scripts/config.py` as `CONCEPTS_SUBDIRS`. The template ships with `general` only — add categories as the KB grows.

### Obsidian Integration

The knowledge base is pure markdown with `[[wikilinks]]` — works natively in Obsidian. Point a vault at `knowledge/` for graph view, backlinks, and search.

### Scaling Beyond Index-Guided Retrieval

At ~2,000+ articles, the index becomes too large for the context window. At that point, add hybrid RAG (keyword + semantic search) as a retrieval layer before the LLM.
