# Design — codegraph as the third KB layer

- **Date:** 2026-07-13
- **AI-ID:** AII-5
- **Status:** approved (design); implementation not started
- **Supersedes:** nothing. Extends the two-layer architecture in [`docs/pkb-schema.md`](../../pkb-schema.md).

## Problem

`ai-infra` is not an application — it is the **infrastructure template** that gets stamped onto
application projects. Its own contents are 17 Python files (~76 symbols, mostly standalone hooks),
1.2k lines of shell installers, and ~2k lines of markdown. There is effectively no call graph here.

But the moment the template is applied to a real codebase, the agent needs a structural index, or it
falls back to grep/glob/read loops to reconstruct code structure on every task. The template should
ship that capability so it is present on day one of a new project rather than bolted on later.

Three candidate tools were evaluated. The evaluation is recorded in
`knowledge/concepts/general/` (local narrative layer, not pushed — `ai-infra` is a template repo);
the decision and its consequences are recorded here.

## Decision

**Adopt `@colbymchenry/codegraph` as a third KB layer. Keep graphify. Reject
`DeusData/codebase-memory-mcp`.**

### Why the three tools are not interchangeable

They disagree on what a graph **node** is, and that single difference determines what each can answer.

| Tool | Node | Edges | Corpus it can see | Cost |
|------|------|-------|-------------------|------|
| **graphify** | a **concept** | EXTRACTED / INFERRED / AMBIGUOUS, plus Louvain communities | any file — code, markdown, papers, images | LLM on full build; `graphify update .` is free (AST-only) |
| **codegraph** | a **symbol** (fn/class/method) | CALLS, IMPORTS, INHERITS | source code only | $0 — tree-sitter → SQLite, no LLM, no embeddings |
| **codebase-memory-mcp** | a **symbol** + a local embedding vector | CALLS, IMPORTS, HTTP_CALLS, DATA_FLOWS, SIMILAR_TO | source code only (+ a manual ADR store) | $0 — bundled local embeddings |

`codegraph` and `codebase-memory-mcp` are the same species; one would be chosen, never both.
`graphify` is a different species and is **not** replaced by either: a concept-level graph over a
mixed corpus (including `knowledge/*.md`) answers a question a symbol-level call graph structurally
cannot, and vice versa.

### Why codegraph over codebase-memory-mcp

`codebase-memory-mcp` is the more capable tool on paper (158 tree-sitter grammars, bundled local
embeddings, an openCypher subset, a committable `graph.db.zst` team artifact). It is rejected on
three grounds, in order of severity:

1. **Fail-open integrity check.** Its npm `postinstall` downloads a platform binary from GitHub
   Releases and verifies SHA-256 against a `checksums.txt` from the same origin — but if the
   checksum line is not found it *returns and proceeds with an unverified binary*, and a failed
   install still `process.exit(0)`s. This is a direct regression against the standard already set by
   the plannotator fetch (hard-fail on SHA mismatch) and against CLAUDE.md Rule 13.
2. **Silent index degradation.** Open issue #333: it reports `status: "indexed"` while having built
   only ~500 nodes for a 72k-LOC repo. An index that lies about being complete is worse than no
   index, because the agent will confidently answer "nothing calls this." Also open: a memory leak
   growing to 50+ GB (#581) and "never finishes indexing large Python project" (#524).
3. **Hook collision.** Its installer writes Skills and a `PreToolUse` hook that intercepts `Grep` /
   `Glob` and injects graph results as `additionalContext`. `ai-infra` already runs
   `kb-auto-inject.py` on `UserPromptSubmit`. Two tools racing to prepend context to the same turn
   is an unnecessary debugging surface.

**Re-evaluation trigger:** `codebase-memory-mcp` is the only candidate with cross-service
`HTTP_CALLS` / `DATA_FLOWS` edges. If a real multi-service fleet is ever built with this template,
reopen the comparison — but not before, and not until items (1) and (2) are fixed upstream.

## Architecture — three layers and a routing rule

The routing rule is the load-bearing part of this design. CLAUDE.md currently instructs every
session to "check the atlas first" for structural questions. Adding codegraph without a routing rule
would create **two competing authorities for structural questions**, which is exactly the Rule 7
failure mode (blending contradictory patterns) that CLAUDE.md forbids.

| Layer | Question it answers | Lives in | Produced by |
|-------|--------------------|----------|-------------|
| **narrative** | *Why did we decide X?* — rationale, conventions | `knowledge/` | hand-compiled from `daily/` via `compile.py` |
| **atlas** | *What is this corpus about? What clusters with what? What is surprisingly connected?* | `graphify-out/` | `/graphify` (full) or `graphify update .` (free, AST-only) |
| **code index** | *What calls this symbol? What breaks if I change it?* | `.codegraph/` (SQLite) | `codegraph init` + file watcher |

Read as: **why → narrative. Corpus shape → atlas. Symbol precision → code index.**

The layers are combined by cross-reference at the index level, not merged into one corpus — the same
principle already used to join narrative and atlas.

## Components — the changes to make

Six files. All additive; none rewrite existing behaviour.

### 1. `setup.sh` — External CLI tools section

The section that already installs graphify (`uv tool`) and rtk gains a codegraph install:

- `npm i -g @colbymchenry/codegraph@1.4.1` — **exact pin, no caret/tilde**.
- Immediately followed by `codegraph telemetry off`. Telemetry is **on by default** and POSTs to
  `telemetry.getcodegraph.com` (PostHog, US). Disabling it is part of the install, not a follow-up
  step a user might skip.
- **Never** the advertised `curl -fsSL … | sh` path. The npm route is chosen specifically because
  the published manifest declares `scripts: null` — no preinstall/postinstall/install hooks at all.

### 2. `install.sh` — same addition

`install.sh:359` already installs graphify. Mirror the codegraph install there so a fresh bootstrap
and a `setup.sh` re-run converge on the same state.

### 3. `install.ps1` — same addition

Mirrored for parity. **Known gap:** `install.ps1` remains untested at runtime (no `pwsh` in WSL) —
hand-review only, same caveat carried by all prior installer work.

### 4. `.mcp.json` — declare the MCP server

codegraph is declared alongside `context7`, project-scoped so every project stamped from the
template inherits it.

> **AII-4 lesson, applied.** Declaring a server in `.mcp.json` does **not** install it — see
> `knowledge/concepts/general/declaring-config-is-not-installing.md`. The installer change (1–3) and
> this config change must ship in the **same commit**, or the failure reproduces a third time.

### 5. `CLAUDE.md` — the routing rule

The "check the knowledge base first" orientation block gains the third row of the routing table
above, so the agent knows which layer owns which question.

### 6. `docs/pkb-schema.md` — the third layer

The "Two-Layer Architecture" section becomes three-layer: the table, the cross-link convention, and
the "when to use each" guidance are extended. The section heading changes accordingly.

## Data flow — the per-project boundary

This is the part that keeps the change cheap and non-speculative.

- **Binary: installed globally, once, at setup time.** Present on the machine, ready for any repo.
- **Index: created per-repo, on demand.** `codegraph init` writes a `.codegraph/` SQLite database
  only in a repo that has code worth indexing. A file watcher (2s debounce) keeps it fresh from
  then on; there is no manual re-index step.
- **`ai-infra` itself is never indexed.** 76 symbols across standalone hook scripts do not justify a
  SQLite database, and a call graph over eight scripts that barely call each other answers nothing.
  The atlas layer already covers this repo correctly.

So nothing speculative runs today. The template is simply *ready* on the day a real codebase starts.

## Error handling and known constraints

- **WSL2 `/mnt/` cross-mounts are broken by codegraph's own admission** — its local-socket comms are
  unreliable on Windows-drive mounts. The current working tree (`~/projects/ai-infra`) is
  Linux-native and unaffected, but the installer must not silently produce a broken index for a repo
  cloned onto `C:`. Guard: skip the per-repo init on a `/mnt/` path and print the
  `CODEGRAPH_NO_DAEMON=1` workaround rather than failing.
- **Static analysis only.** Dynamic dispatch, reflection, and DI-container wiring are not captured.
  The code index is a strong hint, not proof — the agent must not treat "no callers" as certainty.
- **Files > 1 MB are skipped.**
- **2s staleness window** after an edit; MCP responses carry a staleness banner during it.
- **`.codegraph/` must be gitignored.** It is a machine-local derived artifact.

## Supply-chain verification (CLAUDE.md Rule 13)

Verdict: **PROCEED-WITH-CAVEAT.** Recorded here so the reasoning survives the conversation.

| # | Check | Finding |
|---|-------|---------|
| 1 | Artifact | npm `@colbymchenry/codegraph`, pinned `1.4.1` exactly. Platform binaries via `optionalDependencies` `codegraph-{darwin,linux,win32}-{arm64,x64}@1.4.1`, themselves exact-pinned. MIT. |
| 2 | Provenance | Canonical npm registry; sole maintainer `colbymchenry <me@colbymchenry.com>` matching `github.com/colbymchenry/codegraph`. No typo-squat vector. Not using `curl \| sh`. |
| 3 | Maintainer signal | ~59.6k stars, 39 contributors, ~83.6k weekly downloads, last commit 2026-07-13. **Flags:** single maintainer; repo created 2026-01-18 (~6 months old); fast cadence (1.2.0 → 1.4.1 in 8 days); 315 open issues. |
| 4 | Install scripts | **`scripts: null`** — no preinstall/postinstall/install hooks. `bin` is a shim dispatching to the platform binary. |
| 5 | Pinning | Exact `1.4.1`; npm records the integrity hash. |
| 6 | Audit posture | No known CVEs found. Zero runtime deps beyond its own platform binaries. |
| 7 | Alternatives | Overlaps graphify only at the "structure" boundary, with a different node type (symbol vs concept). Not a duplicate — but the routing rule is mandatory or Rule 7 is violated. |
| 8 | Risk | **LOW-MEDIUM.** Low on install mechanics (no scripts, exact pin, MIT, large install base). Medium on governance (solo maintainer, young repo, fast releases). Telemetry on by default — disabled in the same breath as the install. |

### Pre-existing inconsistency (flagged, not fixed)

`setup.sh` currently installs graphify **unpinned** (`uv tool upgrade graphifyy`) and rtk via
**`curl … | sh`**. Both fall short of the Rule 13 standard codegraph is being held to. Per Rule 3
(surgical changes) these are **not** touched by this work — recorded here so the inconsistency is
known rather than discovered later.

## Success criteria (Rule 4)

Each is a check that can fail:

1. `codegraph --version` prints `1.4.1` after a clean `setup.sh` run.
2. `codegraph telemetry status` reports telemetry **disabled** — verified, not assumed.
3. In a scratch repo containing real code, `codegraph_explore` returns a correct answer through MCP
   from inside Claude Code (end-to-end through the agent, not just the CLI).
4. After `setup.sh`, `ai-infra` itself has **no** `.codegraph/` directory — the per-project boundary
   holds.
5. `.gitignore` excludes `.codegraph/`.
6. A repo on a `/mnt/` path prints the WSL2 guard message and skips init, rather than building a
   broken index.
7. `install.ps1` is hand-reviewed for parity; its runtime-untested status is stated explicitly and
   not claimed as verified (Rule 12).

## Out of scope

- Indexing `ai-infra` itself with codegraph.
- Any change to graphify's role, invocation, or output.
- Adopting `codebase-memory-mcp` in any form.
- Pinning graphify or replacing rtk's `curl | sh` installer (flagged above; separate work).
- A `SessionStart` hook that auto-runs `codegraph init` in any repo above a size threshold —
  deliberately deferred as speculative until the per-project flow is used in anger.
