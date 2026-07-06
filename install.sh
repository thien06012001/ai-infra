#!/usr/bin/env bash
# ai-infra remote installer (Linux / macOS / Windows-via-Git-Bash or WSL).
#
#   curl -fsSL https://raw.githubusercontent.com/thien06012001/ai-infra/main/install.sh | bash
#
# Installs the ai-infra Claude setup + Personal Knowledge Base into the CURRENT
# directory, then installs the external CLI tools (graphify, rtk). Reports exactly
# what was installed, overwritten, appended, skipped, or failed.
#
# Env overrides:
#   AI_INFRA_TARGET=<dir>                 install target (default: current dir)
#   AI_INFRA_MODE=override|append|skip    conflict handling (default: ask, else override)
#   AI_INFRA_REF=<branch>                 git ref to install (default: main)
#   AI_INFRA_SRC=<dir>                    install from a local payload dir (skip download)
#   AI_INFRA_SKIP_TOOLS=1                 skip the graphify/rtk install (CI/testing)
#   AI_INFRA_SKIP_PLUGINS=1               skip installing the declared Claude plugins (CI/testing)
#   AI_INFRA_SKIP_PREREQS=1               skip auto-installing prerequisites (git, jq, node, uv)
set -uo pipefail

REPO="thien06012001/ai-infra"
REF="${AI_INFRA_REF:-main}"
TARGET="${AI_INFRA_TARGET:-$PWD}"
MODE="${AI_INFRA_MODE:-}"

# ---------- pretty output ----------
if [ -t 1 ]; then C_B=$'\033[1m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_D=$'\033[2m'; C_0=$'\033[0m'
else C_B=''; C_G=''; C_Y=''; C_R=''; C_D=''; C_0=''; fi
say()  { printf '%s\n' "$*"; }
step() { printf '%s\n' "${C_B}==>${C_0} $*"; }
ok()   { printf '  %s\n' "${C_G}✓${C_0} $*"; }
warn() { printf '  %s\n' "${C_Y}!${C_0} $*"; }
err()  { printf '  %s\n' "${C_R}✗${C_0} $*"; }

# ---------- result tracking ----------
INSTALLED=(); OVERWROTE=(); APPENDED=(); SKIPPED=(); KEPT=(); FAILED=()
TOOLS_OK=(); TOOLS_FAIL=(); WIRE_OK=(); WIRE_FAIL=()

# Top-level paths that make up the infra payload (everything else in the repo —
# README, SETUP, the installers, .git — is NOT installed into your project).
PAYLOAD_PATHS=(CLAUDE.md program.md pyproject.toml uv.lock .mcp.json .gitignore
  .gitattributes setup.sh .claude hooks scripts .githooks docs knowledge daily reports)

say "${C_B}ai-infra installer${C_0}  ${C_D}($REPO@$REF → $TARGET)${C_0}"
say ""

# ---------- 0. prerequisite preflight (auto-install when missing) ----------
# git, jq, node and uv are load-bearing for a full install: git wires the
# hooksPath, jq drives the guardrail/statusline shell hooks, node runs the .cjs
# Edit/Write guard hooks (and npx launches the context7 MCP server), and uv syncs
# the env + installs graphify. When one is missing we try to install it — system
# packages (git, jq, node) through whatever OS package manager is present, and uv
# through its official installer. Disable all auto-install with
# AI_INFRA_SKIP_PREREQS=1.

# sudo prefix for system package managers — empty when already root or when sudo
# is unavailable. Homebrew must never run under sudo, so pkg_install skips it there.
SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

# detect_pkg_mgr — print the first supported OS package manager found on PATH,
# or fail. Ordered brew-first so macOS Homebrew wins in a mixed environment.
detect_pkg_mgr() {
  local m
  for m in brew apt-get dnf yum pacman apk zypper; do
    command -v "$m" >/dev/null 2>&1 && { printf '%s' "$m"; return 0; }
  done
  return 1
}

# pkg_install <pkg> <mgr> — install one already-resolved package (see
# pkg_name_for) with the given manager. brew runs unprivileged; the rest are
# prefixed with $SUDO. Uses ';' (not '&&') after apt-get update so a failed index
# refresh still attempts the install from cache; the branch's exit status is the
# install itself.
pkg_install() {
  case "$2" in
    brew)    brew install "$1" ;;
    apt-get) $SUDO apt-get update -qq; $SUDO apt-get install -y "$1" ;;
    dnf)     $SUDO dnf install -y "$1" ;;
    yum)     $SUDO yum install -y "$1" ;;
    pacman)  $SUDO pacman -Sy --noconfirm "$1" ;;
    apk)     $SUDO apk add "$1" ;;
    zypper)  $SUDO zypper install -y "$1" ;;
    *)       return 1 ;;
  esac
}

# pkg_name_for <cmd> <mgr> — resolve the OS package that provides <cmd>. Most
# tools share their command name across managers; node is the exception — it
# ships as 'node' on Homebrew but 'nodejs' on Linux, and on the managers that
# split npm/npx into their own package (apt/pacman/apk) we install 'npm' instead,
# which depends on the runtime and so pulls node + npx in together.
pkg_name_for() {
  case "$1" in
    node)
      case "$2" in
        brew)               printf 'node' ;;
        apt-get|pacman|apk) printf 'npm' ;;
        *)                  printf 'nodejs' ;;
      esac ;;
    *) printf '%s' "$1" ;;
  esac
}

# ensure_pkg <cmd> <name> — install the system package providing <cmd> only when
# it is absent. No-op (with a version line) when already present.
ensure_pkg() {
  local mgr pkg
  if command -v "$1" >/dev/null 2>&1; then ok "$2 $("$1" --version 2>/dev/null | head -n1)"; return 0; fi
  if ! mgr="$(detect_pkg_mgr)"; then warn "$2 missing and no known package manager found — install it manually"; return 1; fi
  pkg="$(pkg_name_for "$1" "$mgr")"
  step "Installing $2 via $mgr"
  if pkg_install "$pkg" "$mgr" >/dev/null 2>&1 && command -v "$1" >/dev/null 2>&1; then ok "$2 installed"; else err "$2 install failed — install it manually"; return 1; fi
}

# ensure_uv — install uv via its official installer (astral.sh) when absent, then
# prepend its bin dir to PATH for the rest of this run so the wiring/tools steps
# below can see it without a shell restart (default install target ~/.local/bin).
ensure_uv() {
  if command -v uv >/dev/null 2>&1; then ok "uv $(uv --version 2>/dev/null)"; return 0; fi
  command -v curl >/dev/null 2>&1 || { warn "uv missing and curl unavailable — install from https://docs.astral.sh/uv/"; return 1; }
  step "Installing uv (astral.sh official installer)"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || true
  local d
  for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do [ -x "$d/uv" ] && PATH="$d:$PATH"; done
  export PATH
  if command -v uv >/dev/null 2>&1; then ok "uv installed"; else err "uv install failed — install from https://docs.astral.sh/uv/"; return 1; fi
}

if [ "${AI_INFRA_SKIP_PREREQS:-0}" = 1 ]; then
  step "Skipping prerequisite auto-install (AI_INFRA_SKIP_PREREQS=1)"
else
  step "Checking prerequisites (git, jq, node, uv)"
  ensure_pkg git  git
  ensure_pkg jq   jq
  ensure_pkg node node
  ensure_uv
fi
say ""

# ---------- 1. obtain the payload ----------
TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

if [ -n "${AI_INFRA_SRC:-}" ]; then
  SRC="$AI_INFRA_SRC"
  step "Using local payload: $SRC"
  [ -d "$SRC" ] || { err "AI_INFRA_SRC '$SRC' is not a directory"; exit 1; }
else
  step "Downloading ai-infra ($REF)"
  command -v curl >/dev/null 2>&1 || { err "curl is required"; exit 1; }
  command -v tar  >/dev/null 2>&1 || { err "tar is required"; exit 1; }
  TMP="$(mktemp -d)"
  if curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$REF" -o "$TMP/src.tgz"; then
    tar -xzf "$TMP/src.tgz" -C "$TMP"
    SRC="$TMP/$(basename "$REPO")-$REF"
    [ -d "$SRC" ] || SRC="$(find "$TMP" -maxdepth 1 -type d -name '*-*' | head -n1)"
    ok "downloaded + extracted"
  else
    err "download failed (is the repo public and the ref '$REF' valid?)"
    exit 1
  fi
fi
[ -d "$SRC" ] || { err "payload not found after fetch"; exit 1; }

# ---------- 2. enumerate payload files (relative paths) ----------
FILES=()
for p in "${PAYLOAD_PATHS[@]}"; do
  [ -e "$SRC/$p" ] || continue
  if [ -d "$SRC/$p" ]; then
    while IFS= read -r f; do FILES+=("${f#"$SRC"/}"); done < <(find "$SRC/$p" -type f)
  else
    FILES+=("$p")
  fi
done
[ "${#FILES[@]}" -gt 0 ] || { err "payload is empty — nothing to install"; exit 1; }

# ---------- 3. detect conflicts, choose mode ----------
CONFLICTS=0
for rel in "${FILES[@]}"; do [ -e "$TARGET/$rel" ] && CONFLICTS=$((CONFLICTS+1)); done

if [ "$CONFLICTS" -gt 0 ] && [ -z "$MODE" ]; then
  if [ -r /dev/tty ]; then
    {
      printf '\n%s%s file(s) already exist in the target.%s How should they be handled?\n' "$C_Y" "$CONFLICTS" "$C_0"
      printf '  1) override  — back up each to <name>.<timestamp>.bak, then write the infra version\n'
      printf '  2) append    — add infra content onto existing TEXT files (others are kept untouched)\n'
      printf '  3) skip      — keep every existing file as-is\n'
      printf 'Choose [1/2/3] (default 1): '
    } > /dev/tty
    read -r ans < /dev/tty || ans=""
    case "$ans" in 2) MODE=append;; 3) MODE=skip;; *) MODE=override;; esac
  else
    MODE=override
    warn "no interactive terminal — defaulting conflict mode to 'override'"
  fi
fi
[ -n "$MODE" ] || MODE=override
[ "$CONFLICTS" -gt 0 ] && step "Conflict mode: ${C_B}$MODE${C_0}"

# ---------- 4. install files ----------
TS="$(date +%Y%m%d-%H%M%S)"
is_text() { case "$1" in *.md|*.txt|*.gitignore|*.gitattributes|.gitignore|.gitattributes) return 0;; *) return 1;; esac; }

step "Installing $((${#FILES[@]})) file(s) into $TARGET"
for rel in "${FILES[@]}"; do
  src="$SRC/$rel"; dst="$TARGET/$rel"
  if [ ! -e "$dst" ]; then
    if mkdir -p "$(dirname "$dst")" && cp -p "$src" "$dst"; then INSTALLED+=("$rel"); else FAILED+=("$rel"); err "failed: $rel"; fi
    continue
  fi
  # conflict
  case "$MODE" in
    override)
      if cp -p "$dst" "$dst.$TS.bak" && cp -p "$src" "$dst"; then OVERWROTE+=("$rel"); else FAILED+=("$rel"); err "failed: $rel"; fi ;;
    append)
      if is_text "$rel"; then
        { printf '\n'; case "$rel" in *.gitignore|*.gitattributes|.gitignore|.gitattributes) printf '# --- added by ai-infra ---\n';; *) printf '<!-- added by ai-infra -->\n';; esac; cat "$src"; } >> "$dst" \
          && APPENDED+=("$rel") || { FAILED+=("$rel"); err "failed: $rel"; }
      else
        KEPT+=("$rel")   # not text-appendable; left untouched
      fi ;;
    skip) SKIPPED+=("$rel") ;;
  esac
done
ok "files done"

# ---------- 5. wire the project ----------
step "Wiring the project"
if command -v git >/dev/null 2>&1; then
  git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1 || git -C "$TARGET" init -q
  if git -C "$TARGET" config core.hooksPath .githooks; then WIRE_OK+=("git hooksPath → .githooks"); else WIRE_FAIL+=("git hooksPath"); fi
  chmod +x "$TARGET/.githooks/"* "$TARGET/.claude/hooks/"*.sh 2>/dev/null || true
else
  WIRE_FAIL+=("git not found — skipped hooksPath")
fi
if command -v uv >/dev/null 2>&1; then
  if uv --directory "$TARGET" sync >/dev/null 2>&1; then WIRE_OK+=("uv sync"); else WIRE_FAIL+=("uv sync"); fi
  if uv run --directory "$TARGET" python scripts/index.py >/dev/null 2>&1; then WIRE_OK+=("knowledge index"); else WIRE_FAIL+=("knowledge index"); fi
else
  WIRE_FAIL+=("uv not found — skipped sync + index (install from https://docs.astral.sh/uv/)")
fi
for w in "${WIRE_OK[@]:-}";   do [ -n "$w" ] && ok "$w"; done
for w in "${WIRE_FAIL[@]:-}"; do [ -n "$w" ] && warn "$w"; done

# ---------- 5b. install the declared Claude plugins ----------
# The installed .claude/settings.json only DECLARES plugins: `enabledPlugins`
# toggles them on and `extraKnownMarketplaces` names where they come from. Neither
# key fetches anything — Claude Code loads a plugin only after its code is actually
# installed under ~/.claude/plugins via the `claude` CLI. Without this step the
# plugins show up as "enabled in project settings but isn't installed" and never
# load. So we reconcile the declaration into real installs: register each
# marketplace, then install every enabled plugin at project scope (matching how
# settings.json enables them per-project). Skipped with a warning when the claude
# CLI or jq is missing, or when AI_INFRA_SKIP_PLUGINS=1.
PLUGINS_OK=(); PLUGINS_FAIL=()
SETTINGS="$TARGET/.claude/settings.json"
if [ "${AI_INFRA_SKIP_PLUGINS:-0}" = 1 ]; then
  step "Skipping Claude plugin install (AI_INFRA_SKIP_PLUGINS=1)"
elif ! command -v claude >/dev/null 2>&1; then
  warn "claude CLI not found — plugins declared in settings.json were NOT installed. In the project run: claude plugin install <name>@<marketplace> --scope project"
elif ! command -v jq >/dev/null 2>&1 || [ ! -f "$SETTINGS" ]; then
  warn "jq or settings.json missing — skipped plugin install"
else
  step "Installing Claude plugins declared in settings.json"
  # 1) register every marketplace the plugins resolve against (idempotent). The
  #    official marketplace is added explicitly because plugins reference it but it
  #    is not listed in extraKnownMarketplaces; the extras come from settings.json.
  {
    printf '%s\n' 'anthropics/claude-plugins-official'
    jq -r '(.extraKnownMarketplaces // {}) | to_entries[] | select(.value.source.source=="github") | .value.source.repo' "$SETTINGS"
  } | while IFS= read -r repo; do
    [ -n "$repo" ] || continue
    claude plugin marketplace add "$repo" >/dev/null 2>&1 || true
  done
  # 2) install each enabled plugin at project scope, run from inside TARGET so the
  #    install attaches to this project (claude plugin uses the working directory).
  while IFS= read -r plugin; do
    [ -n "$plugin" ] || continue
    if ( cd "$TARGET" && claude plugin install "$plugin" --scope project >/dev/null 2>&1 ); then PLUGINS_OK+=("$plugin"); else PLUGINS_FAIL+=("$plugin"); fi
  done < <(jq -r '(.enabledPlugins // {}) | to_entries[] | select(.value==true) | .key' "$SETTINGS")
  for p in "${PLUGINS_OK[@]:-}";   do [ -n "$p" ] && ok "$p"; done
  for p in "${PLUGINS_FAIL[@]:-}"; do [ -n "$p" ] && err "plugin failed: $p (retry: claude plugin install $p --scope project)"; done
fi

# ---------- 6. external tools ----------
if [ "${AI_INFRA_SKIP_TOOLS:-0}" = 1 ]; then
  step "Skipping external tools (AI_INFRA_SKIP_TOOLS=1)"
else
  step "Installing external tools (graphify, rtk)"
  if command -v uv >/dev/null 2>&1; then
    if uv tool upgrade graphifyy >/dev/null 2>&1 || uv tool install graphifyy >/dev/null 2>&1; then
      TOOLS_OK+=("graphify (uv tool)")
      if command -v graphify >/dev/null 2>&1; then graphify install --platform claude >/dev/null 2>&1 && TOOLS_OK+=("graphify claude skill") || TOOLS_FAIL+=("graphify claude skill"); fi
    else
      TOOLS_FAIL+=("graphify (uv tool)")
    fi
  else
    TOOLS_FAIL+=("graphify — uv not found")
  fi
  if command -v curl >/dev/null 2>&1; then
    if curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/develop/install.sh | sh >/dev/null 2>&1; then TOOLS_OK+=("rtk"); else TOOLS_FAIL+=("rtk"); fi
  else
    TOOLS_FAIL+=("rtk — curl not found")
  fi
  for t in "${TOOLS_OK[@]:-}";   do [ -n "$t" ] && ok "$t"; done
  for t in "${TOOLS_FAIL[@]:-}"; do [ -n "$t" ] && err "$t"; done
fi

# ---------- 7. report ----------
n() { local a=("$@"); local c=0; for x in "${a[@]:-}"; do [ -n "$x" ] && c=$((c+1)); done; echo "$c"; }
list() { local a=("$@"); for x in "${a[@]:-}"; do [ -n "$x" ] && printf '      %s\n' "$x"; done; }

say ""
say "${C_B}──────── ai-infra install summary ────────${C_0}"
printf '  installed:  %s\n' "$(n "${INSTALLED[@]:-}")"
printf '  overwrote:  %s%s\n' "$(n "${OVERWROTE[@]:-}")" "$([ "$(n "${OVERWROTE[@]:-}")" -gt 0 ] && echo "  (backups: *.$TS.bak)")"
printf '  appended:   %s\n' "$(n "${APPENDED[@]:-}")"
printf '  skipped:    %s\n' "$(n "${SKIPPED[@]:-}")"
[ "$(n "${KEPT[@]:-}")" -gt 0 ] && printf '  kept(*):    %s   %s(not text-appendable; left untouched)%s\n' "$(n "${KEPT[@]:-}")" "$C_D" "$C_0"
say ""
say "  ${C_B}tools:${C_0}"; list "${TOOLS_OK[@]:-}"; [ "$(n "${TOOLS_FAIL[@]:-}")" -gt 0 ] && { say "  ${C_R}tools failed:${C_0}"; list "${TOOLS_FAIL[@]:-}"; }
[ "$(n "${PLUGINS_OK[@]:-}")" -gt 0 ] && { say "  ${C_B}plugins installed:${C_0}"; list "${PLUGINS_OK[@]:-}"; }
[ "$(n "${PLUGINS_FAIL[@]:-}")" -gt 0 ] && { say "  ${C_R}plugins failed:${C_0}"; list "${PLUGINS_FAIL[@]:-}"; }
[ "$(n "${WIRE_FAIL[@]:-}")" -gt 0 ] && { say "  ${C_Y}wiring warnings:${C_0}"; list "${WIRE_FAIL[@]:-}"; }

FAILN="$(n "${FAILED[@]:-}")"
if [ "$FAILN" -gt 0 ]; then
  say ""; say "  ${C_R}${C_B}$FAILN file(s) FAILED to install:${C_0}"; list "${FAILED[@]:-}"
  say ""; err "Install finished with errors."
  exit 1
fi
say ""
ok "${C_B}ai-infra installed.${C_0} Open this project in Claude Code — .claude/settings.json is live."
