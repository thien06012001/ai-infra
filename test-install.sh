#!/usr/bin/env bash
# Verification harness for the install-time project rename.
#
# Installs the payload into a throwaway directory from a clean, tracked-files-only
# source (matching what the published tarball contains) and asserts that the
# installed project carries the chosen name and no residual template identity.
#
# Usage: ./test-install.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
SRC="$WORK/src"; mkdir -p "$SRC"

# Build the payload source from tracked files only, using working-tree content, so
# in-progress installer edits are exercised. `find`-based enumeration would sweep in
# untracked local KB articles. GNU tar treats -C as a no-op after -T -, hence the order.
git -C "$REPO_ROOT" ls-files -z \
  | tar --null -C "$REPO_ROOT" -T - -c -f - \
  | tar -x -C "$SRC"

# ...except knowledge/ and daily/, which hold the operator's personal KB content in
# this working tree. That content never reaches a user — the published tarball carries
# only committed files — so taking the working-tree form here would test a state no
# user can install. Overwrite those two trees with their committed form.
git -C "$REPO_ROOT" archive HEAD knowledge daily | tar -x -C "$SRC" --overwrite

PASS=0; FAIL=0
ok_()   { printf '  PASS  %s\n' "$1"; PASS=$((PASS+1)); }
bad_()  { printf '  FAIL  %s\n' "$1"; FAIL=$((FAIL+1)); }
# assert <description> <command...> — passes when the command exits 0.
assert() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then ok_ "$d"; else bad_ "$d"; fi; }
# refute <description> <command...> — passes when the command exits non-zero.
refute() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then bad_ "$d"; else ok_ "$d"; fi; }

# install_into <dir-name> [name-override] — run install.sh into a fresh target.
# The override is exported inside a subshell rather than written as a command
# prefix: an unquoted ${2:+VAR="$2"} prefix word-splits, so a name containing a
# space — which is exactly the normalization case under test — would break apart.
install_into() {
  local t="$WORK/$1"; mkdir -p "$t"
  (
    export AI_INFRA_SRC="$SRC" AI_INFRA_TARGET="$t" AI_INFRA_MODE=override \
           AI_INFRA_SKIP_TOOLS=1 AI_INFRA_SKIP_PLUGINS=1 AI_INFRA_SKIP_PREREQS=1
    if [ -n "${2:-}" ]; then export AI_INFRA_NAME="$2"; fi
    bash "$REPO_ROOT/install.sh" < /dev/null
  ) > "$t.log" 2>&1
  printf '%s' "$t"
}

echo "== install into test-proj (name from directory basename) =="
T="$(install_into test-proj)"

# --- payload scope ---
refute "docs/superpowers/ is NOT installed"      test -d "$T/docs/superpowers"
assert "docs/pkb-schema.md IS installed"          test -f "$T/docs/pkb-schema.md"

# --- no unrendered placeholder escaped ---
# Scoped past .venv for the same reason as the residual check below: the venv is
# dependency content, not installed payload, and a future dependency shipping a
# template file would fail this assertion for a reason unrelated to the installer.
refute "no '{{' remains anywhere in the target"   grep -rqI --exclude-dir=.venv '{{' "$T"

# --- the three templated files carry the project name, not the template's ---
for f in CLAUDE.md pyproject.toml program.md; do
  refute "$f does not mention ai-infra"           grep -q 'ai-infra' "$T/$f"
  assert "$f mentions test-proj"                  grep -q 'test-proj' "$T/$f"
done

# --- residual ai-infra mentions are exactly the expected provenance set ---
# hooks/_kb_edits.py keeps an internal temp-file namespace by design, and is the
# only file expected to still say ai-infra. uv.lock is NOT in this set: the
# installer's own wiring step (install.sh, `uv --directory "$TARGET" sync`) runs
# before the installer returns, so the lock has already been regenerated against
# the rendered pyproject.toml by the time this check executes.
# The installer's wiring step runs `uv sync` and scripts/index.py before returning,
# so .venv/ and the binary search index exist by now; neither is installed content,
# so -I (skip binaries) and --exclude-dir=.venv keep them out of the comparison.
echo "-- files still containing 'ai-infra': --"
( cd "$T" && grep -rlI --exclude-dir=.venv 'ai-infra' . 2>/dev/null | sed 's|^\./||' | sort | tee "$WORK/residual.txt" )
printf 'hooks/_kb_edits.py\n' | sort > "$WORK/expected.txt"
assert "residual ai-infra mentions match the expected set" \
  diff -q "$WORK/expected.txt" "$WORK/residual.txt"

# --- uv re-locks against the renamed root package ---
if command -v uv >/dev/null 2>&1; then
  assert "uv sync succeeds in the target"         uv --directory "$T" sync
  refute "uv.lock no longer names ai-infra"       grep -q 'ai-infra' "$T/uv.lock"
  assert "uv.lock names test-proj"                grep -q 'name = "test-proj"' "$T/uv.lock"
else
  echo "  SKIP  uv not on PATH — lock assertions not run"
fi

echo
echo "== install into normalized-proj with AI_INFRA_NAME='My App' =="
T2="$(install_into normalized-proj "My App")"
assert "normalizes 'My App' to my-app in pyproject" grep -q 'name = "my-app"' "$T2/pyproject.toml"
assert "prints the normalization notice"            grep -q 'from "My App"' "$T2.log"

echo
printf 'passed: %s   failed: %s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
