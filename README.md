# ai-infra

My personal **Claude Code AI infrastructure**, ready to clone and use. It bundles
the full setup — behavioral rules, lifecycle + guard/security hooks, statusline,
a Personal Knowledge Base (PKB) pipeline, and the plugin configuration — and it
is **entirely project-scoped**: everything lives in this repo and is active only
while ai-infra is the open project in Claude Code. Setup never touches `~/.claude`
or any global state, so it can't clash with your existing environment.

## Prerequisites
- **`uv`** — Python package/venv manager; hooks and the KB pipeline run via `uv run`. <https://docs.astral.sh/uv/>
- **Node** — the `.cjs` guard hooks run with `node`.
- **git** — hooks are wired through `core.hooksPath`.
- **jq** — used by the guardrail/statusline shell hooks.

## Install into a project (one-liner)
Run this **in the root of any project** to install the infra + tools into it:

**Linux / macOS / WSL / Git Bash**
```bash
curl -fsSL https://raw.githubusercontent.com/thien06012001/ai-infra/main/install.sh | bash
```
**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/thien06012001/ai-infra/main/install.ps1 | iex
```

The installer copies the infra into the current directory, wires it (`git`
hooksPath, `uv sync`, knowledge index), installs the external CLIs (`graphify`,
`rtk`), and prints a full report — *installed / overwrote / appended / skipped /
failed*, plus tool and wiring status. If files already exist in the target it
**asks how to handle them** (or set `AI_INFRA_MODE` to answer up front):
- **override** — back up each to `<name>.<timestamp>.bak`, then write the infra version
- **append** — add infra content onto existing text files (`CLAUDE.md`, `.gitignore`, …); non-text files (JSON / TOML / scripts) are kept untouched
- **skip** — keep every existing file as-is; only add what's missing

Env knobs: `AI_INFRA_MODE=override|append|skip`, `AI_INFRA_TARGET=<dir>`,
`AI_INFRA_REF=<branch>`, `AI_INFRA_SKIP_TOOLS=1`.

## Quickstart (clone & develop ai-infra itself)

```bash
git clone <this-repo> ai-infra && cd ai-infra
./setup.sh            # wire this repo: git hooks, uv env, KB index (project scope only)
```
Then open the repo in Claude Code — `.claude/settings.json` activates every hook,
the statusline, and the plugins for this project. `setup.sh` is safe and local; it
does **not** modify `~/.claude`.

`setup.sh` also installs/updates the external CLIs `graphify` and `rtk` to the
latest version (they're not vendored — they update on their own). That step is the
only part that touches global locations (`~/.local/bin`, and graphify's skill goes
to `~/.claude/skills/graphify` — the tools' own install dirs)..

## Layout
| Path | What it is |
| --- | --- |
| `CLAUDE.md`, `program.md` | Behavioral rules (1–13) + KB docs + perf-loop framing + the `/graphify` trigger. |
| `.claude/settings.json` | **All** Claude config for this project: every hook (KB + guardrail/pre-bash-guard/audit/notify/post-fetch/rtk), the statusline, and the enabled plugins/marketplaces — all `$CLAUDE_PROJECT_DIR`-relative. |
| `.claude/hooks/` | Shell guard/utility hooks: guardrail (+rules), pre-bash-guard, audit, notify, statusline (+format), post-fetch-injection-scan. |
| `.claude/skills/` | `best-practices`, `find-skills`. |
| `.claude/commands/` | `/kb-search`. |
| `hooks/` | PKB lifecycle + generic guard hooks (session start/end, pre-compact, kb-auto-inject, activity tracker, worktree create/cleanup, block-env-edits, block-stray-docs). |
| `scripts/` | PKB pipeline (`compile`, `index`, `query`, `search`, `lint`, `flush`, `measure-infra`). |
| `.githooks/` | Commit-message convention enforcement (`commit-msg`); inert `pre-push`. |
| `knowledge/`, `daily/`, `reports/`, `docs/pkb-schema.md` | The PKB content surfaces + schema. |

## What's intentionally NOT here
- **No user-scope install.** Nothing writes to `~/.claude`; every setting is project-scoped.
- **Stack-specific skills/hooks** (NestJS typecheck, drizzle, shadcn, vercel/next, secret-sync) are excluded. Stack plugins were dropped from `enabledPlugins` too.
- **External tools** aren't vendored — `setup.sh` installs `graphify`/`rtk` to latest.

See **[SETUP.md](SETUP.md)** for hook details and the hook-profile env vars.
