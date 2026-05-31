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
[ "$(n "${WIRE_FAIL[@]:-}")" -gt 0 ] && { say "  ${C_Y}wiring warnings:${C_0}"; list "${WIRE_FAIL[@]:-}"; }

FAILN="$(n "${FAILED[@]:-}")"
if [ "$FAILN" -gt 0 ]; then
  say ""; say "  ${C_R}${C_B}$FAILN file(s) FAILED to install:${C_0}"; list "${FAILED[@]:-}"
  say ""; err "Install finished with errors."
  exit 1
fi
say ""
ok "${C_B}ai-infra installed.${C_0} Open this project in Claude Code — .claude/settings.json is live."
