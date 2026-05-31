# SETUP — project-scoped setup, hooks, and tools

## `./setup.sh`
Wires the repo (project scope; does not touch `~/.claude` *settings*) and installs the external tools:
1. `git config core.hooksPath .githooks` (+ makes git hooks executable).
2. `uv sync` — provisions `.venv` from `pyproject.toml`.
3. `uv run python scripts/index.py` — builds the BM25 knowledge index.

That's it. Everything else is configuration that Claude Code reads from
`.claude/` when this repo is the open project.

## What `.claude/settings.json` wires (project scope)
All hook commands are `$CLAUDE_PROJECT_DIR`-relative, so they only run for this
repo — never globally:
- **Bash**: `guardrail.sh` (catastrophic-command denylist), `pre-bash-guard.sh`
  (force-push/curl-pipe-sh/credential-read/disk-wipe blocks + audit log), and the
  `rtk` passthrough (compresses stdout if `rtk` is installed).
- **Edit/Write/MultiEdit**: `block-env-edits` (`.env` guard) + `block-stray-docs`.
- **`.*`**: `audit.sh` — timestamped log of every tool call.
- **WebFetch/WebSearch**: `post-fetch-injection-scan.sh` — flags prompt-injection.
- **PKB lifecycle**: session start/end, pre-compact, kb-auto-inject, activity
  tracker, worktree create/cleanup.
- **Stop / Notification**: `notify.sh` desktop notifications.
- **statusLine**: `statusline.sh`.
- **enabledPlugins / extraKnownMarketplaces**: enabled per-project; Claude fetches
  plugin code from its marketplace on first use (no plugin code vendored here).

## External tools (installed by `setup.sh`)
`graphify` and `rtk` release their own updates, so `setup.sh` **installs them to
the latest version**, never vendored (a committed copy freezes at one version —
exactly the bug we hit with the old graphify skill stuck at 0.4.22 while the binary
was 0.8.4). This is the one part of setup that writes to global locations:
- **graphify** — `uv tool upgrade graphifyy` (install if absent), then
  `graphify install --platform claude` (drops the matching skill into
  `~/.claude/skills/graphify`).
- **rtk** — the official installer (`curl … install.sh | sh`), updates in place.

## Hook profile environment variables
Every Python hook calls a shared gate (`hooks/_profile_gate.py`, `.cjs` twin):
- **`HOOK_PROFILE`** — `minimal` (0) < `standard` (1, default) < `strict` (2). Hooks below the active profile no-op.
- **`DISABLED_HOOKS`** — comma-separated hook IDs to force off regardless of profile.

```bash
export HOOK_PROFILE=minimal
export DISABLED_HOOKS=session-activity-tracker
```
