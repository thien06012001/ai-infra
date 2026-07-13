# codegraph Third KB Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `@colbymchenry/codegraph` in the `ai-infra` template as a symbol-level code index — a third KB layer alongside the narrative (`knowledge/`) and atlas (`graphify-out/`) layers — installed globally at setup time but indexed only per-project.

**Architecture:** The binary installs globally via the existing "external CLI tools" section of the three installers. The MCP server is declared project-scoped in `.mcp.json`. A routing rule in `CLAUDE.md` and `docs/pkb-schema.md` assigns each layer exactly one class of question, so graphify and codegraph never become competing structural authorities. `ai-infra` itself is never indexed.

**Tech Stack:** bash (`setup.sh`, `install.sh`), PowerShell (`install.ps1`), npm (global install), JSON (`.mcp.json`), markdown (`CLAUDE.md`, `docs/pkb-schema.md`).

**Spec:** [`docs/superpowers/specs/2026-07-13-codegraph-third-layer-design.md`](../specs/2026-07-13-codegraph-third-layer-design.md)

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec.

- **Exact version pin: `@colbymchenry/codegraph@1.4.1`.** No caret, no tilde, no `@latest`.
- **Install method: `npm i -g` ONLY.** Never `curl -fsSL … | sh`, never `irm … | iex`. The npm route is chosen specifically because the published manifest declares `scripts: null` — zero install hooks. This is the entire basis of the Rule 13 LOW-MEDIUM risk verdict; changing the install method invalidates it.
- **Telemetry must be disabled in the same breath as the install**, never as a follow-up step a user could skip. It is ON by default and POSTs to `telemetry.getcodegraph.com` (PostHog, US).
- **Installer ordering is load-bearing.** The installer changes (Tasks 1–3) land BEFORE the `.mcp.json` declaration (Task 4). Declaring a server that nothing installs reproduces `knowledge/concepts/general/declaring-config-is-not-installing.md` (AII-4) for a third time. Config-after-installer is safe; installer-after-config is the bug.
- **`ai-infra` itself is never indexed.** No task creates a `.codegraph/` directory in this repo. 76 symbols across eight standalone hooks do not justify a SQLite database.
- **Match existing installer conventions (Rule 11).** `install.sh` uses `TOOLS_OK+=()` / `TOOLS_FAIL+=()` arrays and the `AI_INFRA_SKIP_TOOLS` gate; `install.ps1` uses `$ToolsOk` / `$ToolsFail`; `setup.sh` uses bare `echo "→ …"` lines. Do not invent a new pattern.
- **Commit convention: `[AII-5] <message>`.** Branch is already `thien06012001/aii-5-adopt-codegraph-as-third-kb-layer`.
- **Rule 12 — fail loud.** `install.ps1` cannot be executed in this environment (no `pwsh` in WSL). It is hand-reviewed only. Never report it as "verified."

## Testing approach — read this before Task 1

This repo has **no shell test framework**, and adding one is out of scope. TDD here means: **write the check that currently fails, watch it fail, make the change, watch it pass.** The check is a shell command with a stated expected output, not a `pytest` file. Every task below follows that cycle honestly — a step that says "expected: FAIL" must actually be run and actually fail before you proceed.

Do not fabricate a test harness to satisfy the letter of TDD. Do not skip the fail-first step because the outcome seems obvious.

---

### Task 0: Confirm the CLI's real surface before wiring anything

**Why this task exists:** The plan hardcodes two command strings — the install target and the telemetry-off subcommand. Both came from research, not from running the tool. If `codegraph telemetry off` is not the real subcommand, Tasks 1–3 would silently ship an installer that installs the tool and leaves telemetry **on**. Verify first, then wire.

**Files:** none (verification only).

**Interfaces:**
- Produces: the confirmed exact strings `<INSTALL_CMD>` and `<TELEMETRY_OFF_CMD>` used verbatim by Tasks 1, 2, and 3.

> **RESOLVED 2026-07-13 — Task 0 complete. Findings, confirmed against the installed binary:**
>
> - **Rule 13 re-check passes.** `npm view @colbymchenry/codegraph@1.4.1` → no `scripts` field at all; `license = MIT`; integrity hash present; `optionalDependencies` all exact-pinned to `1.4.1`. The spec's LOW-MEDIUM verdict stands.
> - **`codegraph telemetry off` and `codegraph telemetry status` are correct** as written. Verified: status now reports `Telemetry: disabled (your saved choice)`, config at `~/.codegraph/telemetry.json`.
> - **`codegraph init` / `status` / `callers` / `impact` are all real verbs** — Task 6 needs no change.
> - **⚠ THE PLAN WAS WRONG ABOUT MCP.** There is **no `codegraph mcp` subcommand.** `codegraph mcp` silently falls through to printing top-level help, so an MCP client would have received help text instead of a stdio server — a silent failure. The real invocation is the *hidden* command **`codegraph serve --mcp`**, confirmed via `codegraph install --print-config claude`. **Task 4 Step 2 is corrected below.** Do not use `["mcp"]`.
> - **We deliberately do NOT run `codegraph install`.** It writes to the *global* `~/.claude.json` and injects an auto-allow permissions list into Claude Code settings. We hand-write the project-scoped `.mcp.json` instead, so nothing outside this repo is mutated.

- [ ] **Step 1: Confirm the version exists on the registry and has no install scripts**

```bash
npm view @colbymchenry/codegraph@1.4.1 version scripts dist.integrity license
```

Expected: prints `1.4.1`, an empty/absent `scripts` field, an integrity hash, and `MIT`.

**STOP if `scripts` is non-empty.** The Rule 13 verdict in the spec rests on `scripts: null`. If a postinstall hook has appeared in this version, do not proceed — report it and re-run the Rule 13 protocol.

- [ ] **Step 2: Install it (this is the Rule 13 install; the user approved PROCEED-WITH-CAVEAT by approving the spec)**

```bash
npm i -g @colbymchenry/codegraph@1.4.1
codegraph --version
```

Expected: prints `1.4.1`.

- [ ] **Step 3: Discover the real telemetry subcommand — do not assume**

```bash
codegraph --help 2>&1 | grep -i -A2 telemetry
codegraph telemetry --help 2>&1 | head -20
```

Expected: a `telemetry` subcommand with an `off`/`disable` form. **Write down the exact string.** If no such subcommand exists, fall back to the env var `CODEGRAPH_TELEMETRY=0` (documented in the project's `TELEMETRY.md`) and record that substitution here before continuing.

- [ ] **Step 4: Disable telemetry and prove it is off**

```bash
codegraph telemetry off
codegraph telemetry status
```

Expected: status reports telemetry **disabled**. This exact command pair is what Tasks 1–3 wire into the installers.

- [ ] **Step 5: Record findings in the plan**

Edit this file, replacing every `<TELEMETRY_OFF_CMD>` placeholder below with the confirmed string, then commit:

```bash
git add docs/superpowers/plans/2026-07-13-codegraph-third-layer.md
git commit -m "[AII-5] plan: pin confirmed codegraph CLI surface"
```

---

### Task 1: Install codegraph from `setup.sh`

**Files:**
- Modify: `setup.sh:129-140` (the `# --- External CLI tools (latest, never vendored) ---` section, immediately after the graphify block and before the rtk block)

**Interfaces:**
- Consumes: `<TELEMETRY_OFF_CMD>` confirmed in Task 0.
- Produces: a globally-installed, telemetry-disabled `codegraph` binary on `PATH`. Tasks 4 and 6 depend on it existing.

- [ ] **Step 1: Write the failing check**

```bash
npm ls -g --depth=0 2>/dev/null | grep codegraph; echo "exit=$?"
```

Expected: **FAIL** — no `codegraph` line, `exit=1`. (If Task 0 left it installed globally, uninstall first with `npm rm -g @colbymchenry/codegraph` so this check genuinely fails. The point is to prove `setup.sh` is what installs it, not Task 0.)

- [ ] **Step 2: Add the codegraph block to `setup.sh`**

Insert **after** line 138 (the `fi` closing the graphify block) and **before** line 139 (the rtk `echo`):

```bash
# codegraph: symbol-level code index (third KB layer — see docs/pkb-schema.md).
# Pinned exactly and installed via npm on purpose: the published manifest declares
# no install scripts, unlike the advertised `curl | sh` path. Telemetry ships ON by
# default and POSTs to a third-party PostHog instance, so we disable it in the same
# breath as the install rather than leaving it to the user to remember.
CODEGRAPH_VERSION="${CODEGRAPH_VERSION:-1.4.1}"
echo "→ codegraph: installing v${CODEGRAPH_VERSION} via npm (pinned)"
if command -v npm >/dev/null 2>&1; then
  if npm i -g "@colbymchenry/codegraph@${CODEGRAPH_VERSION}" >/dev/null 2>&1; then
    if codegraph telemetry off >/dev/null 2>&1; then
      echo "    ✓ codegraph v${CODEGRAPH_VERSION} (telemetry off)"
    else
      echo "    ⚠ codegraph v${CODEGRAPH_VERSION} installed, but telemetry is STILL ON — run 'codegraph telemetry off' manually"
    fi
  else
    echo "    ⚠ codegraph: npm install failed — install manually: npm i -g @colbymchenry/codegraph@${CODEGRAPH_VERSION}"
  fi
else
  echo "    ⚠ codegraph: npm not found — skipped"
fi

# codegraph's own README documents unreliable local-socket comms on WSL2 Windows-drive
# mounts. We never auto-init a repo, but warn early so a /mnt/ clone doesn't silently
# produce a broken index the first time someone runs `codegraph init`.
case "$REPO_DIR" in
  /mnt/*) echo "    ⚠ codegraph: this repo is on a Windows mount (/mnt) — 'codegraph init' needs CODEGRAPH_NO_DAEMON=1 here, or move the repo to the Linux filesystem" ;;
esac
```

Note the `CODEGRAPH_VERSION` override env var — same escape hatch as `PLANNOTATOR_VERSION`, keeping the pin escapable without editing the script.

- [ ] **Step 3: Run the check again — it must now pass**

```bash
bash setup.sh
npm ls -g --depth=0 2>/dev/null | grep codegraph
codegraph --version
codegraph telemetry status
```

Expected: the grep finds `@colbymchenry/codegraph@1.4.1`; `--version` prints `1.4.1`; telemetry status reports **disabled**.

- [ ] **Step 4: Verify the per-project boundary held (spec success criterion 4)**

```bash
test -d .codegraph && echo "FAIL — ai-infra was indexed" || echo "PASS — no .codegraph/ in ai-infra"
```

Expected: `PASS`. `setup.sh` installs the binary; it must never run `codegraph init` here.

- [ ] **Step 5: Commit**

```bash
git add setup.sh
git commit -m "[AII-5] setup.sh: install pinned codegraph, telemetry off"
```

---

### Task 2: Install codegraph from `install.sh`

**Files:**
- Modify: `install.sh:353-378` (the `# ---------- 6. external tools ----------` block, inside the `AI_INFRA_SKIP_TOOLS` else-branch, after the graphify `if` and before the rtk `if`)

**Interfaces:**
- Consumes: `<TELEMETRY_OFF_CMD>` from Task 0; the existing `TOOLS_OK` / `TOOLS_FAIL` bash arrays and the `step` / `ok` / `err` helpers already defined in `install.sh`.
- Produces: nothing new — mirrors Task 1 so that a fresh bootstrap and a `setup.sh` re-run converge on the same machine state.

- [ ] **Step 1: Write the failing check**

```bash
grep -c "codegraph" install.sh
```

Expected: **FAIL** — prints `0`.

- [ ] **Step 2: Update the step banner**

`install.sh:356` currently reads:

```bash
  step "Installing external tools (graphify, rtk)"
```

Change to:

```bash
  step "Installing external tools (graphify, codegraph, rtk)"
```

- [ ] **Step 3: Add the codegraph block**

Insert after the graphify `if/else/fi` (the block ending `TOOLS_FAIL+=("graphify — uv not found")`) and before the `if command -v curl` rtk block:

```bash
  # codegraph: symbol-level code index. Pinned + npm-only (no install scripts in the
  # published manifest); telemetry is on by default so we turn it off at install time.
  CODEGRAPH_VERSION="${CODEGRAPH_VERSION:-1.4.1}"
  if command -v npm >/dev/null 2>&1; then
    if npm i -g "@colbymchenry/codegraph@${CODEGRAPH_VERSION}" >/dev/null 2>&1; then
      TOOLS_OK+=("codegraph v${CODEGRAPH_VERSION} (npm, pinned)")
      if codegraph telemetry off >/dev/null 2>&1; then
        TOOLS_OK+=("codegraph telemetry off")
      else
        TOOLS_FAIL+=("codegraph telemetry — run 'codegraph telemetry off' manually")
      fi
    else
      TOOLS_FAIL+=("codegraph (npm)")
    fi
  else
    TOOLS_FAIL+=("codegraph — npm not found")
  fi
```

- [ ] **Step 4: Run the check again**

```bash
grep -c "codegraph" install.sh
bash -n install.sh && echo "SYNTAX OK"
```

Expected: grep count > 0; `SYNTAX OK` (this is a syntax-only parse — it does not execute the installer).

- [ ] **Step 5: Verify the skip gate still works**

```bash
AI_INFRA_SKIP_TOOLS=1 bash -n install.sh && echo "gate intact"
grep -n "AI_INFRA_SKIP_TOOLS" install.sh
```

Expected: the codegraph block sits **inside** the `else` branch of the `AI_INFRA_SKIP_TOOLS` check, so `AI_INFRA_SKIP_TOOLS=1` still skips it. Confirm by reading the surrounding indentation — if the block is outside the gate, it is a bug.

- [ ] **Step 6: Commit**

```bash
git add install.sh
git commit -m "[AII-5] install.sh: install pinned codegraph, telemetry off"
```

---

### Task 3: Install codegraph from `install.ps1` (hand-reviewed only)

**Files:**
- Modify: `install.ps1:297-308` (the `Step "Installing external tools (graphify, rtk)"` block, after the graphify `if/else` and before the rtk `$sh` block)
- Modify: `install.ps1:6` (the header comment listing the external tools)

**Interfaces:**
- Consumes: the existing `$ToolsOk` / `$ToolsFail` PowerShell arrays and the `Step` / `Ok` / `Err` helpers.
- Produces: parity with Tasks 1–2 on Windows.

**Rule 12 constraint:** there is no `pwsh` in this WSL environment. This task **cannot be executed**. It is hand-reviewed only, and the final report must say so explicitly. Do not claim it is tested.

- [ ] **Step 1: Write the failing check**

```bash
grep -c "codegraph" install.ps1
```

Expected: **FAIL** — prints `0`.

- [ ] **Step 2: Update the header comment**

`install.ps1:6` currently reads:

```powershell
# directory, then installs the external CLI tools (graphify, rtk). Reports exactly
```

Change to:

```powershell
# directory, then installs the external CLI tools (graphify, codegraph, rtk). Reports exactly
```

- [ ] **Step 3: Update the step banner**

`install.ps1:297` currently reads:

```powershell
    Step "Installing external tools (graphify, rtk)"
```

Change to:

```powershell
    Step "Installing external tools (graphify, codegraph, rtk)"
```

- [ ] **Step 4: Add the codegraph block**

Insert after the graphify block's closing `} else { $ToolsFail += "graphify — uv not found" }` and before the `# rtk ships a POSIX installer` comment:

```powershell
    # codegraph: symbol-level code index. Pinned + npm-only (the published manifest
    # declares no install scripts, unlike the advertised irm|iex path). Telemetry is
    # ON by default, so disable it at install time rather than trusting a follow-up.
    $CodegraphVersion = if ($env:CODEGRAPH_VERSION) { $env:CODEGRAPH_VERSION } else { '1.4.1' }
    if (Get-Command npm -ErrorAction SilentlyContinue) {
      npm i -g "@colbymchenry/codegraph@$CodegraphVersion" 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) {
        $ToolsOk += "codegraph v$CodegraphVersion (npm, pinned)"
        codegraph telemetry off 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $ToolsOk += "codegraph telemetry off" }
        else { $ToolsFail += "codegraph telemetry — run 'codegraph telemetry off' manually" }
      } else { $ToolsFail += "codegraph (npm)" }
    } else { $ToolsFail += "codegraph — npm not found" }
```

- [ ] **Step 5: Hand-review checklist (no execution possible)**

Read the inserted block and confirm each line by eye:
- It sits inside the `else` branch of the `$env:AI_INFRA_SKIP_TOOLS -eq '1'` gate (check indentation against the graphify block above it).
- `$LASTEXITCODE` is checked immediately after each external call, before any other command can overwrite it — this is the exact pattern the existing graphify block uses.
- Array names are `$ToolsOk` / `$ToolsFail`, matching the surrounding code (not `$ToolsOK`).
- The npm package string is quoted, so PowerShell does not try to interpret `@colbymchenry` as a splat.

- [ ] **Step 6: Run the check again**

```bash
grep -c "codegraph" install.ps1
grep -n "graphify, codegraph, rtk" install.ps1
```

Expected: grep count > 0; the banner and header both updated.

- [ ] **Step 7: Commit**

```bash
git add install.ps1
git commit -m "[AII-5] install.ps1: install pinned codegraph, telemetry off (hand-reviewed, untested)"
```

---

### Task 4: Declare the MCP server and ignore the index

**Files:**
- Modify: `.mcp.json` (add `codegraph` alongside the existing `context7` server)
- Modify: `.gitignore` (add `.codegraph/`)

**Interfaces:**
- Consumes: the `codegraph` binary on `PATH`, installed by Tasks 1–3. **This task must not land before them** — see the Global Constraints note on AII-4.
- Produces: an MCP server Claude Code can reach; a gitignored index directory.

- [ ] **Step 1: Write the failing check**

```bash
python3 -c "import json; print('codegraph' in json.load(open('.mcp.json'))['mcpServers'])"
```

Expected: **FAIL** — prints `False`.

- [ ] **Step 2: Add the server to `.mcp.json`**

The file currently reads:

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp@2.1.7"]
    }
  }
}
```

Replace with:

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp@2.1.7"]
    },
    "codegraph": {
      "type": "stdio",
      "command": "codegraph",
      "args": ["serve", "--mcp"]
    }
  }
}
```

**Use exactly `["serve", "--mcp"]`.** This was confirmed in Task 0 via `codegraph install --print-config claude`, which is the tool telling you its own canonical config. There is **no `codegraph mcp` subcommand** — passing `["mcp"]` makes the binary print top-level help to stdout, which an MCP client cannot parse, and it fails *silently* rather than erroring. `serve` is a hidden command absent from `codegraph --help`; do not "correct" it back to something that appears in the help output.

Re-confirm before committing:

```bash
codegraph install --print-config claude
```

Expected: a snippet whose `args` are exactly `["serve", "--mcp"]`. If it disagrees, the tool is authoritative — use what it prints and note the correction.

- [ ] **Step 3: Add `.codegraph/` to `.gitignore`**

Append to `.gitignore`, after the "Knowledge base runtime state" block:

```gitignore
# codegraph symbol index — machine-local SQLite, rebuilt by `codegraph init` + its watcher.
.codegraph/
```

- [ ] **Step 4: Run the checks again**

```bash
python3 -c "import json; d=json.load(open('.mcp.json')); print('codegraph' in d['mcpServers'])"
git check-ignore -v .codegraph/ && echo "ignored OK"
```

Expected: `True`; `ignored OK`.

- [ ] **Step 5: Prove the AII-4 lesson holds — config declares, installer installs**

```bash
command -v codegraph >/dev/null && echo "PASS — declared AND installed" || echo "FAIL — declared but not installed (this is the AII-4 bug)"
```

Expected: `PASS`. If this prints FAIL, Tasks 1–3 did not land first and the ordering constraint was violated.

- [ ] **Step 6: Commit**

```bash
git add .mcp.json .gitignore
git commit -m "[AII-5] mcp: declare codegraph server, gitignore .codegraph/"
```

---

### Task 5: Write the routing rule (the load-bearing change)

**Files:**
- Modify: `CLAUDE.md:148-152` (the "check the knowledge base first" orientation block)
- Modify: `docs/pkb-schema.md:55-72` (the `## Two-Layer Architecture` section)

**Interfaces:**
- Consumes: nothing.
- Produces: the single source of truth for which layer answers which question. Without this, `CLAUDE.md:150` — which today claims the atlas answers **"call graphs"** — makes graphify and codegraph competing authorities for the same question, violating Rule 7.

- [ ] **Step 1: Write the failing check**

```bash
grep -n "call graphs" CLAUDE.md
```

Expected: **FAIL for our purposes** — it prints line 150, proving the atlas currently claims the call-graph question that codegraph is being adopted to own. This is the contradiction the task removes.

- [ ] **Step 2: Rewrite the `CLAUDE.md` orientation block**

Lines 148–152 currently read:

```markdown
When you orient yourself, **check the knowledge base first** — it has two layers:
- **Narrative (`knowledge/`)** for *why* questions: rationale, conventions, decisions. Start at `knowledge/index.md`.
- **Atlas (`graphify-out/`)** for *structure* questions: god nodes, cross-community bridges, call graphs. Start at `graphify-out/GRAPH_REPORT.md` if it exists.

Only search externally when neither layer has the answer.
```

Replace with:

```markdown
When you orient yourself, **check the knowledge base first** — it has three layers, and each owns exactly one class of question:

- **Narrative (`knowledge/`)** — *why did we decide X?* Rationale, conventions, decisions. Start at `knowledge/index.md`.
- **Atlas (`graphify-out/`)** — *what is this corpus about, what clusters with what?* God nodes, communities, cross-community bridges, surprising connections. Start at `graphify-out/GRAPH_REPORT.md` if it exists.
- **Code index (codegraph MCP)** — *what calls this symbol, what breaks if I change it?* Exact call paths and blast radius. Query it with the `codegraph_explore` MCP tool. Only exists in repos where `codegraph init` has been run — **not** in `ai-infra` itself, which has no call graph worth indexing.

Route by the question, not by habit: **why → narrative. Corpus shape → atlas. Symbol precision → code index.** The code index is static analysis — it cannot see dynamic dispatch, reflection, or DI-container wiring, so "no callers" is a strong hint, never proof.

Only search externally when no layer has the answer.
```

Note what changed: the atlas bullet **no longer claims "call graphs"**. That phrase moves to the code-index bullet. This is the whole point of the task.

- [ ] **Step 3: Rewrite the `docs/pkb-schema.md` section**

Change the heading at line 55 from `## Two-Layer Architecture` to `## Three-Layer Architecture`, and replace the section body (lines 57–72) with:

```markdown
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
```

- [ ] **Step 4: Verify the contradiction is gone**

```bash
grep -n "call graphs" CLAUDE.md; echo "---"
grep -n "Two-Layer" docs/pkb-schema.md; echo "---"
grep -n "Three-Layer\|Code index" docs/pkb-schema.md CLAUDE.md
```

Expected: the first grep finds **nothing** (the atlas no longer claims call graphs); the second finds **nothing** (heading renamed); the third finds the new three-layer rows in both files.

- [ ] **Step 5: Check for stale cross-references to "two layers"**

```bash
grep -rn "two layers\|two-layer\|Two-Layer" --include=*.md . | grep -v "^./docs/superpowers/" | grep -v "^./.venv"
```

Expected: any hit outside the spec/plan is a **stale reference that must be fixed in this task** — likely candidates are `knowledge/index.md` and `README.md`. Update each to say three layers. Do not leave a doc claiming two.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/pkb-schema.md
# plus any stale-reference files found in Step 5
git commit -m "[AII-5] docs: route structural questions to the code index (three-layer KB)"
```

---

### Task 6: End-to-end verification in a scratch repo

**Files:** none in this repo. Uses the scratchpad.

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: evidence for spec success criterion 3 — the one criterion no earlier task proves.

**Why this task exists:** Tasks 1–5 prove the binary installs and the docs are consistent. None of them proves **an agent can actually get a useful answer through MCP**. That is the only thing that makes this adoption worth anything, and it is the easiest thing to assume rather than check (Rule 12).

- [ ] **Step 1: Build a scratch repo with a real, non-trivial call chain**

```bash
SCRATCH="/tmp/claude-1000/-home-thien2001-projects-ai-infra/7b240aa3-a965-43e2-aafe-091f48eaecb7/scratchpad/codegraph-probe"
mkdir -p "$SCRATCH" && cd "$SCRATCH" && git init -q
cat > orders.py <<'EOF'
def validate(order):
    return order.get("total", 0) > 0

def charge(order):
    if not validate(order):
        raise ValueError("invalid order")
    return {"ok": True}

def process_order(order):
    return charge(order)
EOF
cat > api.py <<'EOF'
from orders import process_order

def handle_request(payload):
    return process_order(payload)
EOF
```

- [ ] **Step 2: Index it and confirm the index is not silently empty**

```bash
cd "$SCRATCH"
codegraph init
codegraph status
```

Expected: status reports a node count > 0. **A node count of 0 or a suspiciously tiny number while reporting "indexed" is the exact silent-degradation failure that disqualified codebase-memory-mcp** — if codegraph does it too, stop and report it, because the whole adoption rationale collapses.

- [ ] **Step 3: Prove the call graph is actually correct**

```bash
cd "$SCRATCH"
codegraph callers validate
codegraph impact validate
```

Expected: `callers validate` names `charge`. `impact validate` reaches `charge` → `process_order` → `handle_request` across the file boundary. If it only finds same-file callers, cross-file resolution is broken and the tool is not delivering its core claim.

- [ ] **Step 4: Prove it works through MCP from inside Claude Code, not just the CLI**

This is the step that cannot be scripted — it must be done by the agent in a real session.

Open a Claude Code session in `$SCRATCH` and ask: *"What breaks if I change the `validate` function?"* Confirm the agent answers using the `codegraph_explore` MCP tool (not by grepping the two files, which would prove nothing on a repo this small).

Expected: the tool is invoked and the answer names `charge`, `process_order`, and `handle_request`.

**If the agent greps instead of calling the tool**, the MCP server is either not registered or not being routed to — go back to Task 4 Step 2 (wrong subcommand?) and Task 5 (is the routing rule actually telling the agent the code index exists?).

- [ ] **Step 5: Confirm `ai-infra` is still unindexed**

```bash
cd /home/thien2001/projects/ai-infra
test -d .codegraph && echo "FAIL — ai-infra got indexed" || echo "PASS — per-project boundary holds"
git status --short | grep -i codegraph || echo "PASS — nothing codegraph-related untracked"
```

Expected: both `PASS`.

- [ ] **Step 6: Clean up the scratch repo**

```bash
rm -rf "$SCRATCH"
```

- [ ] **Step 7: Record the verification result**

Write the outcome of Steps 2–4 into `daily/2026-07-13.md` under a session heading (the narrative layer's raw material — `compile.py` will distil it later). State plainly whether MCP routing worked. **If any step failed, say so — a partial pass is not a pass (Rule 12).**

---

### Task 7: Sync the knowledge base (CLAUDE.md convention — not optional)

**Files:**
- Create: `knowledge/concepts/general/node-type-determines-tool-fit.md`
- Modify: `knowledge/index.md` (add the article row)

**Interfaces:**
- Consumes: the decision recorded in the spec.
- Produces: the narrative-layer article. **Local only — never pushed.** `ai-infra` is a template repo; per the standing memory, KB articles, daily logs, and `index.md`/`log.md` edits stay out of the pushed template.

**Why this task exists:** CLAUDE.md mandates keeping `knowledge/` in sync with every edit, and explicitly forbids silently skipping the check. This change adds a whole KB layer — the KB unambiguously needs updating.

- [ ] **Step 1: Write the failing check**

```bash
ls knowledge/concepts/general/ | grep node-type
```

Expected: **FAIL** — no such file.

- [ ] **Step 2: Write the article**

Create `knowledge/concepts/general/node-type-determines-tool-fit.md`, following the format of the existing `mechanical-vs-philosophical-fit.md` (read it first and match its frontmatter and section structure exactly — Rule 11).

The thesis, stated plainly: **when comparing graph/index tools, the first question is not "which is better" but "what is a node."** graphify's node is a *concept*, codegraph's is a *symbol*, codebase-memory-mcp's is a *symbol + vector*. Tools with the same node type are substitutes — pick one. Tools with different node types are layers — they compose. This is why "should I combine them?" had a different answer for graphify+codegraph (yes, different node types) than for codegraph+codebase-memory-mcp (no, same node type).

It must also record the **rejection of codebase-memory-mcp** and the reason that actually decided it — not the solo maintainer, but the **fail-open SHA-256 check** (missing checksum line → proceeds with an unverified binary; failed install still exits 0) and the **silent index degradation** (issue #333: `status: "indexed"` with ~500 nodes for a 72k-LOC repo). Generalise it: *an index that can lie about being complete is worse than no index, because the agent will confidently report "nothing calls this."*

Link it to the existing articles with `[[…]]`: `[[mechanical-vs-philosophical-fit]]` (this is a *sub-test* of mechanical fit — the node-type check is what makes mechanical fit concrete for graph tools), `[[caveman-skill-rejection]]`, `[[plannotator-adoption]]`, and `[[declaring-config-is-not-installing]]` (the AII-4 ordering constraint that shaped this implementation).

- [ ] **Step 3: Add the row to `knowledge/index.md`**

In the `### general` table, matching the existing column format exactly:

```markdown
| [[concepts/general/node-type-determines-tool-fit]] | Comparing graph tools starts with "what is a node" — same node type means substitutes, different node types means layers. | daily/2026-07-13.md | 2026-07-13 |
```

- [ ] **Step 4: Verify**

```bash
uv run python scripts/lint.py
```

Expected: passes. If the linter flags a broken `[[link]]` to an article that does not exist, that is a real finding — fix the link, do not suppress the check.

- [ ] **Step 5: Commit (local branch only — do NOT push this commit's KB files)**

```bash
git add knowledge/concepts/general/node-type-determines-tool-fit.md knowledge/index.md
git commit -m "[AII-5] kb: node type determines whether tools are substitutes or layers"
```

**Before any `git push`, confirm with the user which commits ship.** The infra commits (Tasks 1–5) belong in the template; this KB commit and the `daily/` log do not.

---

## Self-Review

**Spec coverage:** every spec section maps to a task. Installers → Tasks 1–3. `.mcp.json` + `.gitignore` → Task 4. `CLAUDE.md` + `pkb-schema.md` routing rule → Task 5. Success criteria 1, 2, 4, 5 → Tasks 1 and 4. Criterion 3 (end-to-end MCP) → Task 6. Criterion 7 (`install.ps1` untested, stated honestly) → Task 3's Rule 12 note. The KB-sync convention → Task 7.

**One deliberate spec deviation, recorded here rather than hidden:** the spec says the installer should "skip the per-repo init on a `/mnt/` path." That instruction was incoherent — the installers never run `codegraph init` at all (init is per-project and on-demand, which is the whole point of the design). Task 1 therefore implements the WSL2 concern as an **early warning** when `setup.sh` runs on a `/mnt/` path, plus a documented limit in `pkb-schema.md`. Same protection, correct location.

**Placeholder scan:** the only intentional placeholder is `<TELEMETRY_OFF_CMD>`, which Task 0 exists specifically to resolve before any task consumes it. Every code step contains the literal code to write.

**Type/name consistency:** `TOOLS_OK`/`TOOLS_FAIL` (bash) and `$ToolsOk`/`$ToolsFail` (PowerShell) match the existing files' casing. `CODEGRAPH_VERSION` is the env var name in all three installers. The package string `@colbymchenry/codegraph@1.4.1` is identical everywhere.

**Known unverified assumptions**, all gated behind a check rather than assumed:
- The telemetry subcommand — Task 0 Step 3 confirms it before use.
- The MCP subcommand (`codegraph mcp`) — Task 4 Step 2 confirms it before commit.
- The CLI verbs `callers` / `impact` / `status` — Task 6 will surface it immediately if they differ.
