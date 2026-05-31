#!/usr/bin/env bash
# ai-infra setup. Run once after cloning:
#
#   ./setup.sh
#
# Wires this repo (git hooksPath, uv env, KB index) AND installs/updates the
# external CLI tools (graphify, rtk) to the latest version.
#
# Claude config is 100% PROJECT-SCOPED: every hook/statusline/plugin lives in this
# repo's .claude/ and is active only while ai-infra is the open project — setup
# never writes Claude *settings* into ~/.claude. The external tools are the one
# thing that installs to global locations (~/.local/bin, ~/.claude/skills/graphify
# — the tools' own install dirs), because that is simply where these CLIs live.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v uv >/dev/null 2>&1 || { echo "❌ uv not found — install from https://docs.astral.sh/uv/ and re-run." >&2; exit 1; }

# --- Runtime prerequisite preflight (soft) ---
# node + jq are needed at runtime (node → .cjs guard hooks; jq → shell hooks),
# not for setup itself — so warn with install options but don't block.
if ! command -v node >/dev/null 2>&1; then
  echo "⚠ node not found — the .cjs Edit/Write guard hooks won't run. Install it via:"
  echo "    • direct download:  https://nodejs.org/  (or your OS package manager)"
  echo "    • version manager:  nvm (https://github.com/nvm-sh/nvm) or fnm (https://github.com/Schniz/fnm), then 'nvm install --lts' / 'fnm install --lts'"
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "⚠ jq not found — the guardrail/statusline shell hooks need it. Install it via:"
  echo "    • macOS: brew install jq   • Debian/Ubuntu: sudo apt install jq   • other: https://jqlang.github.io/jq/download/"
fi

# --- Project wiring ---
echo "→ wiring git hooks + Python env"
git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1 || git -C "$REPO_DIR" init -q
git -C "$REPO_DIR" config core.hooksPath .githooks
chmod +x "$REPO_DIR/.githooks/"* 2>/dev/null || true
uv --directory "$REPO_DIR" sync || echo "⚠ uv sync failed — run it manually in $REPO_DIR"
uv run --directory "$REPO_DIR" python scripts/index.py || echo "⚠ index build failed — run scripts/index.py manually"

# --- External CLI tools (latest, never vendored) ---
echo "→ graphify: installing/upgrading via uv tool"
uv tool upgrade graphifyy 2>/dev/null || uv tool install graphifyy
if command -v graphify >/dev/null 2>&1; then
  # `graphify install` copies the skill matching the installed binary version
  # into the platform config dir (~/.claude/skills/graphify). Pin the platform
  # so we never get the windows/other variant.
  echo "→ graphify: installing latest Claude skill"
  graphify install --platform claude || true
fi
echo "→ rtk: running the official installer (updates in place if present)"
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/develop/install.sh | sh || echo "⚠ rtk install failed — re-run its installer manually"

cat <<EOF

✅ ai-infra setup complete.

  • Claude config is project-scoped (.claude/) — your ~/.claude *settings* are untouched.
  • Open this repo in Claude Code; .claude/settings.json wires every hook, the
    statusline, and the plugins for this project.
  • Write your first knowledge article under knowledge/concepts/general/.
EOF
