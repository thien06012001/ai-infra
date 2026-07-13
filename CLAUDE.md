# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. These rules apply to every task in this project unless explicitly overridden.

**Bias:** caution over speed on non-trivial work. Use judgment on trivial tasks.

## Rule 1 — Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask rather than guess.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## Rule 2 — Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Test: would a senior engineer say this is overcomplicated? If yes, simplify.

## Rule 3 — Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## Rule 4 — Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Rule 5 — Use the model only for judgment calls

Use me for: classification, drafting, summarization, extraction.
Do NOT use me for: routing, retries, deterministic transforms.
If code can answer, code answers.

## Rule 6 — Token budgets are not advisory

Per-task: 4,000 tokens. Per-session: 30,000 tokens.
If approaching budget, summarize and start fresh.
Surface the breach. Do not silently overrun.

## Rule 7 — Surface conflicts, don't average them

If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.
Don't blend conflicting patterns.

## Rule 8 — Read before you write

Before adding code, read exports, immediate callers, shared utilities.
"Looks orthogonal" is dangerous. If unsure why code is structured a way, ask.

## Rule 9 — Tests verify intent, not just behavior

Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.

## Rule 10 — Checkpoint after every significant step

Summarize what was done, what's verified, what's left.
Don't continue from a state you can't describe back.
If you lose track, stop and restate.

## Rule 11 — Match the codebase's conventions, even if you disagree

Conformance > taste inside the codebase.
If you genuinely think a convention is harmful, surface it. Don't fork silently.

## Rule 12 — Fail loud

"Completed" is wrong if anything was skipped silently.
"Tests pass" is wrong if any were skipped.
Default to surfacing uncertainty, not hiding it.

## Rule 13 — Pre-install / pre-fetch verification protocol

**Treat every external artifact as hostile until checked.** Before running ANY command that pulls code or binaries from outside the repo, run the protocol below and surface the report. Wait for explicit approval before executing the install/fetch.

**Triggers (non-exhaustive):**
- Package installs: `pnpm add`, `pnpm install <new-pkg>`, `npm i`, `yarn add`, `pip install`, `uv add`, `uv pip install`, `cargo add`, `go get`, `gem install`, `brew install`.
- Remote fetches: `curl … | sh`, `wget … | bash`, `Invoke-WebRequest … | iex`, `git clone <unfamiliar-host>`, downloading a binary release, raw GitHub URLs.
- MCP / skill / plugin installs: `claude plugin add`, `skills add`, registry installs from URLs.
- Editing `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` to add a new dep, even without running the installer.

**The protocol** (every bullet is mandatory; if you can't answer one, stop and ask):

1. **Identify the artifact**: name, exact version (pin — no `^` or `~`), source URL/registry, license.
2. **Provenance**: official registry only (npm, PyPI, crates.io, GitHub releases under the canonical org). If it's a raw GitHub URL or curl-pipe-sh, name the org/repo and check it's the canonical one (typo-squat check: `lodahs` vs `lodash`, `colorss` vs `colors`).
3. **Maintainer signal**: weekly downloads / GitHub stars / last-publish date. Flag anything with <1k weekly downloads, <100 stars, OR transferred ownership in the last 12 months, OR a single new maintainer who recently took over.
4. **Install scripts**: does the package declare `postinstall` / `preinstall` / `install` scripts? If yes, name them and explain what they do.
5. **Pinning**: confirm exact-version pin (no caret/tilde) and that the lockfile will capture the integrity hash.
6. **Audit posture**: is the latest version free of known CVEs? Is the per-language audit tool (`pnpm audit` / `pip-audit` / `cargo audit`) clean for that package? If not, list the advisories.
7. **Alternatives**: is this duplicating something the project already has?
8. **Risk classification**: low / medium / high. Justify in one sentence.

**Output format**: a fenced "VERIFY:" block with the eight findings above, then a one-line recommendation (PROCEED / PROCEED-WITH-CAVEAT / DO-NOT-INSTALL). Do not run the install until the user replies.

**Skip the protocol only when**:
- Reinstalling exact versions already in the lockfile (`pnpm install` with no new deps, `uv sync`).
- The artifact already lives inside this repo (relative path).
- The user explicitly says "skip the verification protocol" for this one command.

**Reference**: a deeper rationale article (e.g. `knowledge/concepts/general/supply-chain-protection.md`) may not exist yet in a fresh template — write one the first time this protocol catches something, capturing the incident and the per-language audit toolchain.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

# Project guide

This project is `ai-infra`. Read this section, then any local instructions, before making changes. If the request is ambiguous about scope, ask before acting.

When you orient yourself, **check the knowledge base first** — it has three layers, and each owns exactly one class of question:

- **Narrative (`knowledge/`)** — *why did we decide X?* Rationale, conventions, decisions. Start at `knowledge/index.md`.
- **Atlas (`graphify-out/`)** — *what is this corpus about, what clusters with what?* God nodes, communities, cross-community bridges, surprising connections. Start at `graphify-out/GRAPH_REPORT.md` if it exists.
- **Code index (codegraph MCP)** — *what calls this symbol, what breaks if I change it?* Exact call paths and blast radius, via the `codegraph_explore` MCP tool. Only exists in repos where `codegraph init` has been run — **not** in `ai-infra` itself, which has no call graph worth indexing.

Route by the question, not by habit: **why → narrative. Corpus shape → atlas. Symbol precision → code index.** The code index is static analysis — it cannot see dynamic dispatch, reflection, or DI-container wiring, so "no callers" is a strong hint, never proof.

Only search externally when no layer has the answer.

## Conventions that apply across the project

- **Comment every new and modified symbol.** Every exported function, class, method, interface, type, and DTO must have a documentation block. TypeScript: JSDoc (`/** ... */`). Python: Google-style docstrings. Each block must explain (1) what it does, (2) why it exists, (3) how it works — not just a restatement of the name. Include `@param`/`@returns`/`@throws` where non-trivial. Add inline `//` or `#` comments on non-obvious logic. When you update code, update its comment in the same edit — a stale comment is a bug. **Skip:** auto-generated UI components, test files, self-evident one-liners.

- **Keep the knowledge base in sync with every edit.** After making any change in the repo (code, config, docs, infra, hooks, etc.), check whether the change invalidates or extends anything in `knowledge/` — re-read `knowledge/index.md` and any articles that touch the area you edited. If an article is now stale, wrong, or missing a concept the edit introduced, update or create the relevant article(s) in the same unit of work (and refresh `knowledge/index.md` accordingly). If nothing in the KB is affected, say so explicitly instead of silently skipping the check. See [docs/pkb-schema.md](docs/pkb-schema.md) for article formats and the compile flow. The **atlas** layer (`graphify-out/`) does not need manual sync — code changes are picked up by `graphify update .` (AST-only, no API cost); doc/image changes need a manual `/graphify --update`.

### Branch + commit conventions

- Commits: `[AI-ID] <message>`.
- Both are enforced by repo-tracked hooks in `.githooks/` (activate once with `git config core.hooksPath .githooks`).

Full rules, exemptions, examples, and the `pre-push` test trigger: [`.githooks/README.md`](.githooks/README.md). The `WorktreeCreate` hook (`hooks/worktree-create.py`) picks the branch prefix automatically by scanning the transcript.

---

# Personal Knowledge Base

Three layers: **narrative** (`knowledge/`, hand-compiled from AI conversations) + **atlas** (`graphify-out/`, machine-extracted graph of the whole repo) + **code index** (`.codegraph/`, symbol-level call graph, per-project and only where there is real code). Adapted from [Karpathy's LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) architecture.

The full schema — architecture, article formats, compile/query/lint operations, command + hook quick-reference tables, script details, costs, customization — lives in **[`docs/pkb-schema.md`](docs/pkb-schema.md)**. Read it when working on or with the KB.

The **narrative** layer is hand-compiled: conversations land in `daily/`, and `scripts/compile.py` distills them into `knowledge/concepts/` articles indexed by `knowledge/index.md`. The **atlas** layer does not need manual sync — `graphify update .` is AST-only and free; only doc/image changes need a manual `/graphify --update`.

---

# graphify
- **graphify** (`~/.claude/skills/graphify/SKILL.md`, installed by `setup.sh`) — any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, invoke the Skill tool with `skill: "graphify"` before doing anything else.
