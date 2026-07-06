# ai-infra

My personal **Claude Code AI infrastructure**, ready to clone and use. It bundles
the full setup — behavioral rules, lifecycle + guard/security hooks, statusline,
a Personal Knowledge Base (PKB) pipeline, and the plugin configuration — and it
is **entirely project-scoped**: everything lives in this repo and is active only
while ai-infra is the open project in Claude Code. Setup never touches `~/.claude`
or any global state, so it can't clash with your existing environment.

## Prerequisites
Install these first — every later step assumes they are on your `PATH`. (The
[one-liner installer](#fast-path-one-liner) auto-installs all four — `git`, `jq`,
Node and `uv` — for you via your OS package manager, so this table is mainly for
the manual path.)

| Tool | Why it's needed | Install |
| --- | --- | --- |
| **`uv`** | Python package/venv manager; hooks and the KB pipeline run via `uv run`. | <https://docs.astral.sh/uv/> |
| **Node** (with `npx`) | The `.cjs` guard hooks run with `node`; the `context7` MCP server launches via `npx`. | direct: <https://nodejs.org/> · version manager: [nvm](https://github.com/nvm-sh/nvm) / [fnm](https://github.com/Schniz/fnm) (`nvm install --lts`) |
| **git** | Hooks are wired through `core.hooksPath`. | <https://git-scm.com/> |
| **jq** | Used by the guardrail/statusline shell hooks. | `brew install jq` / `apt install jq` |

Verify them before continuing:
```bash
uv --version && node --version && git --version && jq --version
```

---

## Fast path (one-liner)
Run this **in the root of any project** to install the infra + tools into it:

**Linux / macOS / WSL / Git Bash**
```bash
curl -fsSL https://raw.githubusercontent.com/thien06012001/ai-infra/main/install.sh | bash
```
**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/thien06012001/ai-infra/main/install.ps1 | iex
```

The installer auto-installs any missing prerequisites (`git`, `jq`, Node and `uv`
— via your OS package manager, `winget`/`scoop`/`choco` on Windows, and uv's
official installer), copies the infra into the current directory, wires it
(`git` hooksPath, `uv sync`, knowledge index), installs the external CLIs
(`graphify`, `rtk`), and prints a full report. Set `AI_INFRA_SKIP_PREREQS=1` to
opt out of the auto-install. If you'd rather understand and run each step
yourself, follow the **step-by-step** guide below — it does exactly what the
one-liner does, one command at a time.

---

## Step-by-step install (one by one)

This is the manual equivalent of the one-liner, broken into discrete steps so you
can see (and verify) each part. Run them in order from a terminal.

### Step 1 — Get the code
Pick the scenario that matches what you're doing:

**A. Develop ai-infra itself** — clone the repo and work inside it:
```bash
git clone https://github.com/thien06012001/ai-infra.git ai-infra
cd ai-infra
```

**B. Add ai-infra to an existing project** — run the installer from that project's
root (it downloads the payload and copies it in):
```bash
cd /path/to/your/project
curl -fsSL https://raw.githubusercontent.com/thien06012001/ai-infra/main/install.sh | bash
```
If files already exist, the installer **asks how to handle them** (see
[Conflict handling](#conflict-handling)). Scenario B already performs Steps 2–5
for you — skip ahead to [Step 6](#step-6--open-the-project-in-claude-code).

> The rest of the steps below are the wiring `setup.sh` runs. In scenario **A**
> you can run `./setup.sh` to do Steps 2–5 in one shot, or run them by hand as
> shown — the result is identical.

### Step 2 — Wire git hooks
Point git at the repo-tracked hooks (commit-message convention + `pre-push`):
```bash
git config core.hooksPath .githooks
chmod +x .githooks/* .claude/hooks/*.sh
```
Verify:
```bash
git config --get core.hooksPath   # → .githooks
```

### Step 3 — Provision the Python environment
`uv sync` creates `.venv` from `pyproject.toml`/`uv.lock` — every hook runs via
`uv run`, so this must succeed:
```bash
uv sync
```

### Step 4 — Build the knowledge index
Builds the BM25 index the KB search + auto-inject hooks read from:
```bash
uv run python scripts/index.py
```

### Step 5 — Install the external CLI tools
`graphify` and `rtk` ship their own updates, so they are **never vendored** — you
install the latest. This is the one part that writes to global locations
(`~/.local/bin`, and graphify's skill goes to `~/.claude/skills/graphify`).

```bash
# graphify — the uv tool package is named "graphifyy"; the CLI binary is "graphify"
uv tool install graphifyy        # or: uv tool upgrade graphifyy

# drop the matching Claude skill into ~/.claude/skills/graphify
graphify install --platform claude

# rtk — official installer, updates in place if already present
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/develop/install.sh | sh
```
Verify:
```bash
graphify --version && rtk --version
```
> Both are optional at runtime — the `rtk` Bash hook and the `/graphify` skill
> simply no-op if the binary is missing. Set `AI_INFRA_SKIP_TOOLS=1` to skip this
> step in the one-liner.

### Step 6 — Open the project in Claude Code
Open this directory as your project in Claude Code. On the first session,
`.claude/settings.json` activates **for this project only**:
- every hook (KB lifecycle + guardrail/pre-bash-guard/audit/notify/post-fetch/rtk),
- the **statusline**,
- the **enabled plugins** and their **marketplaces** (next step).

Nothing here is written into your global `~/.claude` *settings*.

### Step 7 — Install / verify the plugins
The plugins are declared in `.claude/settings.json` (`enabledPlugins`) and their
sources in `extraKnownMarketplaces`. Claude Code reads these when the project
opens and **fetches each plugin's code from its marketplace on first use** — no
plugin code is vendored in this repo.

Two marketplaces are involved:
- `claude-plugins-official` — built into Claude Code.
- `addy-agent-skills` — added by this repo via `extraKnownMarketplaces`
  (source: `addyosmani/agent-skills`).

Enabled plugins: `skill-creator`, `claude-md-management`, `claude-code-setup`,
`security-guidance`, `frontend-design`, `feature-dev`, `chrome-devtools-mcp`,
`superpowers`, `context7`, and `agent-skills`.

Run `/plugin` in Claude Code to confirm they're installed and enabled. If a
plugin shows as not yet fetched, trigger it once (or use the `/plugin` menu) and
Claude Code will pull it from the marketplace.

### Step 8 — Confirm the MCP server
`.mcp.json` registers the **context7** MCP server (launched with `npx`, so Node
is required). Run `/mcp` in Claude Code to confirm `context7` is connected. Use
it to pull current library/framework docs on demand.

### Step 9 — Verify the whole setup end-to-end
A quick checklist that everything is live:
- `git config --get core.hooksPath` → `.githooks`
- `.venv/` exists and `uv run python scripts/index.py` runs clean
- `graphify --version` and `rtk --version` both print (if you installed them)
- In Claude Code: the **statusline** renders, `/plugin` lists the plugins above,
  and `/mcp` shows `context7`.
- A new session injects KB context (the SessionStart hook), confirming the hooks
  fire for this project.

Then write your first knowledge article under `knowledge/concepts/general/` and
you're done.

---

## Conflict handling
When the installer finds files that already exist in the target, it asks how to
handle them (or set `AI_INFRA_MODE` to answer up front):
- **override** — back up each to `<name>.<timestamp>.bak`, then write the infra version
- **append** — add infra content onto existing text files (`CLAUDE.md`, `.gitignore`, …); non-text files (JSON / TOML / scripts) are kept untouched
- **skip** — keep every existing file as-is; only add what's missing

Env knobs: `AI_INFRA_MODE=override|append|skip`, `AI_INFRA_TARGET=<dir>`,
`AI_INFRA_REF=<branch>`, `AI_INFRA_SKIP_TOOLS=1`, `AI_INFRA_SKIP_PREREQS=1`.

---

## Layout
| Path | What it is |
| --- | --- |
| `CLAUDE.md`, `program.md` | Behavioral rules (1–13) + KB docs + perf-loop framing + the `/graphify` trigger. |
| `.claude/settings.json` | **All** Claude config for this project: every hook (KB + guardrail/pre-bash-guard/audit/notify/post-fetch/rtk), the statusline, and the enabled plugins/marketplaces — all `$CLAUDE_PROJECT_DIR`-relative. |
| `.claude/hooks/` | Shell guard/utility hooks: guardrail (+rules), pre-bash-guard, audit, notify, statusline (+format), post-fetch-injection-scan. |
| `.claude/skills/` | `best-practices`, `find-skills`. |
| `.claude/commands/` | `/kb-search`. |
| `.mcp.json` | MCP servers for this project (`context7`). |
| `hooks/` | PKB lifecycle + generic guard hooks (session start/end, pre-compact, kb-auto-inject, activity tracker, worktree create/cleanup, block-env-edits, block-stray-docs). |
| `scripts/` | PKB pipeline (`compile`, `index`, `query`, `search`, `lint`, `flush`, `measure-infra`). |
| `.githooks/` | Commit-message convention enforcement (`commit-msg`); inert `pre-push`. |
| `knowledge/`, `daily/`, `reports/`, `docs/pkb-schema.md` | The PKB content surfaces + schema. |

See **[SETUP.md](SETUP.md)** for hook details and the hook-profile env vars.
