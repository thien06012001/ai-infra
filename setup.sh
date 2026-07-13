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

# --- Claude plugins declared in settings.json ---
# settings.json only DECLARES plugins: enabledPlugins toggles them on and
# extraKnownMarketplaces names their sources. Neither key fetches code — Claude
# Code loads a plugin only once it is installed under ~/.claude/plugins via the
# `claude` CLI, so we reconcile the declaration into real installs here: register
# each marketplace (official + any extras), then install every enabled plugin at
# project scope. This is the one bit of Claude *plugin* state that lives in
# ~/.claude/plugins — the plugins' own install dir — analogous to the external
# CLI tools below; project settings.json still owns the enable/config.
SETTINGS="$REPO_DIR/.claude/settings.json"
if command -v claude >/dev/null 2>&1 && command -v jq >/dev/null 2>&1 && [ -f "$SETTINGS" ]; then
  echo "→ claude plugins: installing the plugins declared in settings.json"
  {
    printf '%s\n' 'anthropics/claude-plugins-official'
    jq -r '(.extraKnownMarketplaces // {}) | to_entries[] | select(.value.source.source=="github") | .value.source.repo' "$SETTINGS"
  } | while IFS= read -r repo; do
    [ -n "$repo" ] || continue
    claude plugin marketplace add "$repo" >/dev/null 2>&1 || true
  done
  jq -r '(.enabledPlugins // {}) | to_entries[] | select(.value==true) | .key' "$SETTINGS" | while IFS= read -r plugin; do
    [ -n "$plugin" ] || continue
    if ( cd "$REPO_DIR" && claude plugin install "$plugin" --scope project >/dev/null 2>&1 ); then
      echo "    ✓ $plugin"
    else
      echo "    ⚠ $plugin (retry: claude plugin install $plugin --scope project)"
    fi
  done
else
  echo "⚠ claude CLI or jq not found — plugins in settings.json NOT installed. Run: claude plugin install <name>@<marketplace> --scope project"
fi

# --- plannotator binary (companion to the plannotator plugin) ---
# The plannotator plugin only wires hooks that call a bare `plannotator` on PATH
# (ExitPlanMode / EnterPlanMode); it does NOT ship the executable. When that plugin
# is enabled in settings.json we fetch the pinned, SIGNED release binary from GitHub
# Releases and verify its SHA256 sidecar before installing to ~/.local/bin (no
# install on mismatch). This avoids the upstream `curl … | bash` installer. Pin the
# release with PLANNOTATOR_VERSION.
PLANNOTATOR_VERSION="${PLANNOTATOR_VERSION:-v0.22.0}"

# install_plannotator_bin — download + verify + install the plannotator binary for
# the current OS/arch. Exit codes: 0 installed, 1 download/io failure, 2 unsupported
# platform, 3 SHA256 mismatch. All risky steps are guarded so `set -e` won't abort
# the whole setup on an expected non-zero (the caller inspects the return code).
install_plannotator_bin() {
  local os arch asset base dest tmpf tmps want got
  case "$(uname -s)" in
    Linux)  os=linux ;;
    Darwin) os=darwin ;;
    *)      return 2 ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64)  arch=x64 ;;
    arm64|aarch64) arch=arm64 ;;
    *)             return 2 ;;
  esac
  command -v curl >/dev/null 2>&1 || return 1
  asset="plannotator-${os}-${arch}"
  base="https://github.com/backnotprop/plannotator/releases/download/${PLANNOTATOR_VERSION}"
  dest="$HOME/.local/bin"
  mkdir -p "$dest" || return 1
  tmpf="$(mktemp)"; tmps="$(mktemp)"
  curl -fsSL "$base/$asset"        -o "$tmpf" || { rm -f "$tmpf" "$tmps"; return 1; }
  curl -fsSL "$base/$asset.sha256" -o "$tmps" || { rm -f "$tmpf" "$tmps"; return 1; }
  want="$(awk '{print $1}' "$tmps" 2>/dev/null)"
  got="$( { sha256sum "$tmpf" 2>/dev/null || shasum -a 256 "$tmpf" 2>/dev/null; } | awk '{print $1}')" || got=""
  { [ -n "$want" ] && [ "$want" = "$got" ]; } || { rm -f "$tmpf" "$tmps"; return 3; }
  command -v gh >/dev/null 2>&1 && gh attestation verify "$tmpf" --repo backnotprop/plannotator >/dev/null 2>&1 || true
  chmod +x "$tmpf"
  mv "$tmpf" "$dest/plannotator" || { rm -f "$tmpf" "$tmps"; return 1; }
  rm -f "$tmps"
}

if command -v jq >/dev/null 2>&1 && [ -f "$SETTINGS" ] &&
   [ "$(jq -r '(.enabledPlugins // {})["plannotator@plannotator"] // false' "$SETTINGS")" = true ]; then
  echo "→ plannotator: installing the pinned, verified binary the plugin hooks call ($PLANNOTATOR_VERSION)"
  rc=0; install_plannotator_bin || rc=$?
  case "$rc" in
    0) echo "    ✓ plannotator $PLANNOTATOR_VERSION → ~/.local/bin/plannotator"
       case ":$PATH:" in
         *":$HOME/.local/bin:"*) : ;;
         *) echo "    ⚠ ~/.local/bin not on PATH — add it so the plannotator hooks resolve the binary" ;;
       esac ;;
    2) echo "    ⚠ plannotator: unsupported platform — install manually from github.com/backnotprop/plannotator/releases" ;;
    3) echo "    ✗ plannotator: SHA256 mismatch — NOT installed" ;;
    *) echo "    ⚠ plannotator: download/install failed — retry setup or install manually" ;;
  esac
fi

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
