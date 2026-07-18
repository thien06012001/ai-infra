# User-Chosen Project Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After installing this template into a directory, the project is named whatever the user chose — with no residual claim to be `ai-infra`.

**Architecture:** A single `{{PROJECT_NAME}}` placeholder lives literally in three tracked payload files. Both installers capture a name (env var → prompt → target basename), normalize it to a PEP 508-safe slug, and render the placeholder while copying those three files; every other file is copied byte-for-byte. Statements that are *true about the template but false about a user's project* are reworded to be name-free rather than renamed. `docs/superpowers/` leaves the install payload entirely.

**Tech Stack:** Bash (`install.sh`), PowerShell (`install.ps1`), `uv` for Python env wiring, `git` for payload enumeration in the test harness.

**Spec:** `docs/superpowers/specs/2026-07-18-user-chosen-project-name-design.md`

## Global Constraints

- Placeholder token is exactly `{{PROJECT_NAME}}`. No other token is introduced.
- The templated-file allowlist is exactly: `CLAUDE.md`, `pyproject.toml`, `program.md`. Nothing else is rendered.
- Normalized name charset is `[a-z0-9-]`; spaces and underscores fold to `-`; leading, trailing, and repeated hyphens collapse. Empty result is a hard error, never a silent fallback.
- New env override name is `AI_INFRA_NAME` on both platforms.
- These must **not** change: `REPO`/`$Repo` values, codeload URLs, installer banner and summary text, all existing `AI_INFRA_*` variable names, the `# --- added by ai-infra ---` and `<!-- added by ai-infra -->` append markers, and the temp-file prefix in `hooks/_kb_edits.py:39`.
- `install.sh` and `install.ps1` must stay behaviorally identical to each other.
- A non-interactive install with no `AI_INFRA_NAME` must still complete unattended, using the target directory's basename.
- Tracked template files keep `{{PROJECT_NAME}}` literal. No task may render placeholders in the working tree.

---

### Task 1: Verification harness + payload narrowing

Builds the test first, and lands the one change it can already prove: `docs/superpowers/` no longer ships.

**Files:**
- Create: `test-install.sh` (repo root — deliberately outside `PAYLOAD_PATHS`, so it never ships)
- Modify: `install.sh:42-43` (`PAYLOAD_PATHS`)
- Modify: `install.ps1:29-31` (`$PayloadPaths`)

**Interfaces:**
- Consumes: nothing.
- Produces: `./test-install.sh`, exit 0 when every assertion passes and 1 otherwise. Later tasks re-run it unchanged. It builds its payload source from **tracked files with working-tree content** (`git ls-files` piped through `tar`), which matches what the published tarball contains and deliberately excludes untracked local KB files.

- [ ] **Step 1: Write the failing test**

Create `test-install.sh`:

```bash
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

# Build the payload source from tracked files only, using working-tree content.
# `find`-based enumeration would sweep in untracked local KB articles.
# GNU tar treats -C as a no-op when it follows -T -, so -C must come first.
git -C "$REPO_ROOT" ls-files -z \
  | tar --null -C "$REPO_ROOT" -T - -c -f - \
  | tar -x -C "$SRC"

# ...except knowledge/ and daily/, which hold operator-local KB content in this
# working tree that never ships from the published tarball.
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
refute "no '{{' remains anywhere in the target"   grep -rqI --exclude-dir=.venv '{{' "$T"

# --- the three templated files carry the project name, not the template's ---
for f in CLAUDE.md pyproject.toml program.md; do
  refute "$f does not mention ai-infra"           grep -q 'ai-infra' "$T/$f"
  assert "$f mentions test-proj"                  grep -q 'test-proj' "$T/$f"
done

# --- residual ai-infra mentions are exactly the expected provenance set ---
# hooks/_kb_edits.py keeps an internal temp-file namespace by design, and is the
# only expected residual. uv.lock is NOT in this set: install.sh's own wiring step
# runs `uv sync` before returning, regenerating the lock against the rendered
# pyproject.toml. .venv/ and the binary search index exist by then too, hence -I
# and --exclude-dir=.venv below.
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
```

Make it executable:

```bash
chmod +x test-install.sh
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./test-install.sh`

Expected: exit 1, with at minimum these failures — `docs/superpowers/ is NOT installed` (it currently ships), the three `does not mention ai-infra` checks, both `mentions test-proj` checks, and the residual-set diff.

- [ ] **Step 3: Narrow the payload in `install.sh`**

Replace `install.sh:42-43`:

```bash
PAYLOAD_PATHS=(CLAUDE.md program.md pyproject.toml uv.lock .mcp.json .gitignore
  .gitattributes setup.sh .claude hooks scripts .githooks docs knowledge daily reports)
```

with:

```bash
# `docs/pkb-schema.md` rather than all of `docs`: docs/superpowers/{specs,plans}
# are design records about building this template, not documentation the
# installed project needs.
PAYLOAD_PATHS=(CLAUDE.md program.md pyproject.toml uv.lock .mcp.json .gitignore
  .gitattributes setup.sh .claude hooks scripts .githooks docs/pkb-schema.md
  knowledge daily reports)
```

- [ ] **Step 4: Narrow the payload in `install.ps1`**

Replace `install.ps1:29-31`:

```powershell
$PayloadPaths = @('CLAUDE.md','program.md','pyproject.toml','uv.lock','.mcp.json',
  '.gitignore','.gitattributes','setup.sh','.claude','hooks','scripts','.githooks',
  'docs','knowledge','daily','reports')
```

with:

```powershell
# 'docs/pkb-schema.md' rather than all of 'docs': docs/superpowers/{specs,plans}
# are design records about building this template, not documentation the
# installed project needs.
$PayloadPaths = @('CLAUDE.md','program.md','pyproject.toml','uv.lock','.mcp.json',
  '.gitignore','.gitattributes','setup.sh','.claude','hooks','scripts','.githooks',
  'docs/pkb-schema.md','knowledge','daily','reports')
```

- [ ] **Step 5: Run the test to confirm the payload assertions now pass**

Run: `./test-install.sh`

Expected: still exit 1 overall, but `docs/superpowers/ is NOT installed` and `docs/pkb-schema.md IS installed` now both PASS. The naming assertions still FAIL — Tasks 2 and 3 address those.

- [ ] **Step 6: Commit**

```bash
git add test-install.sh install.sh install.ps1
git commit -m "[TB-26] test: install rename harness; drop docs/superpowers from payload"
```

---

### Task 2: Reword statements that are true of the template but false of a user's project

No placeholders here. These sentences must not carry *any* project name, because renaming them would convert a true claim about the template into a false claim about the user's application.

**Files:**
- Modify: `CLAUDE.md:182`
- Modify: `docs/pkb-schema.md:79`
- Modify: `knowledge/index.md:7`
- Modify: `.claude/README.md:4`
- Modify: `setup.sh:2`, `setup.sh:11`, `setup.sh:174`

**Interfaces:**
- Consumes: `./test-install.sh` from Task 1.
- Produces: no code interface. Removes `.claude/README.md`, `setup.sh`, `docs/pkb-schema.md`, and `knowledge/index.md` from the set of installed files containing `ai-infra`.

- [ ] **Step 1: Reword `CLAUDE.md:182`**

Find:

```
- **Code index (codegraph MCP)** — *what calls this symbol, what breaks if I change it?* Exact call paths and blast radius, via the `codegraph_explore` MCP tool. Only exists in repos where `codegraph init` has been run — **not** in `ai-infra` itself, which has no call graph worth indexing.
```

Replace with:

```
- **Code index (codegraph MCP)** — *what calls this symbol, what breaks if I change it?* Exact call paths and blast radius, via the `codegraph_explore` MCP tool. Only exists where `codegraph init` has been run — worth doing if this project contains real application code, and worth skipping if it is only hooks and scripts.
```

- [ ] **Step 2: Reword `docs/pkb-schema.md:79`**

Find:

```
**Scope of the code index:** it exists only in repos that contain real code. `ai-infra` itself is **not** indexed — 17 hook/script files with ~76 mostly-independent symbols yield a call graph that answers nothing. The template installs the binary globally; `codegraph init` runs per-project, on demand.
```

Replace with:

```
**Scope of the code index:** it exists only in repos that contain real code. A repo that is only hooks and scripts — a few dozen mostly-independent symbols — yields a call graph that answers nothing, so it is left unindexed. The installer places the binary globally; `codegraph init` runs per-project, on demand.
```

- [ ] **Step 3: Reword `knowledge/index.md:7`**

Find:

```
- **Code index (`.codegraph/`)** — symbol-level call graph answering *"what calls this, what breaks if I change it?"*, via the `codegraph_explore` MCP tool. Per-project and only where there is real code — **not** in `ai-infra` itself.
```

Replace with:

```
- **Code index (`.codegraph/`)** — symbol-level call graph answering *"what calls this, what breaks if I change it?"*, via the `codegraph_explore` MCP tool. Per-project, and only where there is real application code to index.
```

- [ ] **Step 4: Reword `.claude/README.md:4`**

Find:

```
Nothing is installed to `~/.claude`; ai-infra never mutates your global setup.
```

Replace with:

```
Nothing is installed to `~/.claude`; this setup never mutates your global config.
```

- [ ] **Step 5: Reword the three `setup.sh` mentions**

`setup.sh:2` — find:

```
# ai-infra setup. Run once after cloning:
```

replace with:

```
# Project setup. Run once after cloning:
```

`setup.sh:11` — find:

```
# repo's .claude/ and is active only while ai-infra is the open project — setup
```

replace with:

```
# repo's .claude/ and is active only while this repo is the open project — setup
```

`setup.sh:174` — find:

```
✅ ai-infra setup complete.
```

replace with:

```
✅ Setup complete.
```

- [ ] **Step 6: Verify no reworded file still names the template**

Run:

```bash
grep -n 'ai-infra' CLAUDE.md docs/pkb-schema.md knowledge/index.md .claude/README.md setup.sh
```

Expected: exactly one line — `CLAUDE.md:176` (`This project is \`ai-infra\`.`), which Task 3 converts to a placeholder. Every other match is gone.

- [ ] **Step 7: Run the harness**

Run: `./test-install.sh`

Expected: still exit 1 (the three templated files are untouched so far), but the residual-set output now lists only `CLAUDE.md`, `hooks/_kb_edits.py`, `program.md`, `pyproject.toml`, `uv.lock`.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md docs/pkb-schema.md knowledge/index.md .claude/README.md setup.sh
git commit -m "[TB-26] docs: reword template-specific claims to hold in any project"
```

---

### Task 3: Placeholders + rendering in `install.sh`

The placeholder and the renderer that resolves it land together, so the tree is never in a state where a template file ships an unrendered token.

**Files:**
- Modify: `CLAUDE.md:176`, and insert one explanatory line after it
- Modify: `pyproject.toml:2,4`
- Modify: `program.md:1`
- Modify: `install.sh` — new name-capture block after the banner; new render helpers and copy-loop changes in section 4

**Interfaces:**
- Consumes: `./test-install.sh` from Task 1.
- Produces, for Task 4 to mirror exactly in PowerShell:
  - `normalize_name <raw>` → prints the slug on stdout; prints empty string when nothing survives.
  - `$PROJECT_NAME` — the normalized slug, set once before file installation.
  - `is_templated <rel>` → exit 0 for `CLAUDE.md`, `pyproject.toml`, `program.md`; exit 1 otherwise.
  - `render <src>` → writes rendered content to stdout.
  - `place <src> <dst> <rel>` → renders when templated, else `cp -p`. Returns the copy's exit status.

- [ ] **Step 1: Add the placeholder to `CLAUDE.md:176`**

Find:

```
This project is `ai-infra`. Read this section, then any local instructions, before making changes. If the request is ambiguous about scope, ask before acting.
```

Replace with (two lines — the second explains the token to anyone reading the template itself):

```
This project is `{{PROJECT_NAME}}`. Read this section, then any local instructions, before making changes. If the request is ambiguous about scope, ask before acting.

> `{{PROJECT_NAME}}` is substituted with the real project name at install time. If you are reading this token unrendered, you are in the upstream template repository itself, not an installed project.
```

- [ ] **Step 2: Add the placeholder to `pyproject.toml`**

Find:

```toml
name = "ai-infra"
version = "0.1.0"
description = "ai-infra — Claude harness + Personal Knowledge Base"
```

Replace with:

```toml
name = "{{PROJECT_NAME}}"
version = "0.1.0"
description = "{{PROJECT_NAME}} — Claude harness + Personal Knowledge Base"
```

- [ ] **Step 3: Add the placeholder to `program.md:1`**

Find:

```
# ai-infra — infra-as-performance-loop
```

Replace with:

```
# {{PROJECT_NAME}} — infra-as-performance-loop
```

- [ ] **Step 4: Add the name-capture block to `install.sh`**

Insert immediately after the banner lines (`say "${C_B}ai-infra installer${C_0} …"` and the blank `say ""`, currently `install.sh:45-46`), before the prerequisite preflight section:

```bash
# ---------- 0a. project name ----------
# The payload carries the template's own identity in three files. Capture the
# name the user wants this project to have and render it during the copy, so an
# installed project never claims to be ai-infra. Prompting here rather than
# later means the question is asked before the long download, not after it.

# normalize_name — fold an arbitrary human name into a PEP 508-safe slug.
# Required, not cosmetic: pyproject.toml's `name` field rejects spaces and
# uppercase, and a directory called "My App" is a legitimate install target.
# Prints the slug on stdout; prints nothing when no valid character survives.
normalize_name() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | tr ' _' '--' \
    | tr -cd 'a-z0-9-' \
    | sed 's/--*/-/g; s/^-//; s/-$//'
}

RAW_NAME="${AI_INFRA_NAME:-}"
if [ -z "$RAW_NAME" ]; then
  DEFAULT_NAME="$(basename "$TARGET")"
  if [ -r /dev/tty ]; then
    printf 'Project name? [%s]: ' "$DEFAULT_NAME" > /dev/tty
    read -r RAW_NAME < /dev/tty || RAW_NAME=""
    [ -n "$RAW_NAME" ] || RAW_NAME="$DEFAULT_NAME"
  else
    RAW_NAME="$DEFAULT_NAME"
    warn "no interactive terminal — project name defaulted to '$RAW_NAME'"
  fi
fi

PROJECT_NAME="$(normalize_name "$RAW_NAME")"
if [ -z "$PROJECT_NAME" ]; then
  err "project name '$RAW_NAME' normalizes to empty — use letters, digits, or hyphens"
  exit 1
fi
if [ "$PROJECT_NAME" != "$RAW_NAME" ]; then
  say "  using project name: ${C_B}$PROJECT_NAME${C_0} (from \"$RAW_NAME\")"
else
  say "  project name: ${C_B}$PROJECT_NAME${C_0}"
fi
say ""
```

Also add `AI_INFRA_NAME=<name>` to the env-override comment block at the top of the file. Find:

```
#   AI_INFRA_TARGET=<dir>                 install target (default: current dir)
```

Replace with:

```
#   AI_INFRA_NAME=<name>                  project name (default: ask, else target dir name)
#   AI_INFRA_TARGET=<dir>                 install target (default: current dir)
```

- [ ] **Step 5: Add the render helpers and rewire the copy loop**

In section 4, find:

```bash
TS="$(date +%Y%m%d-%H%M%S)"
is_text() { case "$1" in *.md|*.txt|*.gitignore|*.gitattributes|.gitignore|.gitattributes) return 0;; *) return 1;; esac; }
```

Replace with:

```bash
TS="$(date +%Y%m%d-%H%M%S)"
is_text() { case "$1" in *.md|*.txt|*.gitignore|*.gitattributes|.gitignore|.gitattributes) return 0;; *) return 1;; esac; }

# is_templated — true for the three payload files that carry {{PROJECT_NAME}}.
# An explicit allowlist rather than a blanket pass: a global substitution would
# also rewrite the provenance mentions ("added by ai-infra") that must survive.
is_templated() { case "$1" in CLAUDE.md|pyproject.toml|program.md) return 0;; *) return 1;; esac; }

# render — write $1 to stdout with {{PROJECT_NAME}} resolved. $PROJECT_NAME is a
# normalized slug ([a-z0-9-] only), so it needs no sed metacharacter escaping.
render() { sed "s/{{PROJECT_NAME}}/$PROJECT_NAME/g" "$1"; }

# place — install one payload file, rendering it when templated. Mirrors the
# `cp -p` it replaces, including its exit status, so callers are unchanged.
place() {
  if is_templated "$3"; then render "$1" > "$2"; else cp -p "$1" "$2"; fi
}
```

Then in the same loop, find the fresh-install branch:

```bash
    if mkdir -p "$(dirname "$dst")" && cp -p "$src" "$dst"; then INSTALLED+=("$rel"); else FAILED+=("$rel"); err "failed: $rel"; fi
```

Replace with:

```bash
    if mkdir -p "$(dirname "$dst")" && place "$src" "$dst" "$rel"; then INSTALLED+=("$rel"); else FAILED+=("$rel"); err "failed: $rel"; fi
```

Find the override branch:

```bash
      if cp -p "$dst" "$dst.$TS.bak" && cp -p "$src" "$dst"; then OVERWROTE+=("$rel"); else FAILED+=("$rel"); err "failed: $rel"; fi ;;
```

Replace with:

```bash
      if cp -p "$dst" "$dst.$TS.bak" && place "$src" "$dst" "$rel"; then OVERWROTE+=("$rel"); else FAILED+=("$rel"); err "failed: $rel"; fi ;;
```

Find the append branch's `cat "$src"`:

```bash
        { printf '\n'; case "$rel" in *.gitignore|*.gitattributes|.gitignore|.gitattributes) printf '# --- added by ai-infra ---\n';; *) printf '<!-- added by ai-infra -->\n';; esac; cat "$src"; } >> "$dst" \
```

Replace with (appended content reaches the same file copied content would, so it renders too):

```bash
        { printf '\n'; case "$rel" in *.gitignore|*.gitattributes|.gitignore|.gitattributes) printf '# --- added by ai-infra ---\n';; *) printf '<!-- added by ai-infra -->\n';; esac; if is_templated "$rel"; then render "$src"; else cat "$src"; fi; } >> "$dst" \
```

- [ ] **Step 6: Run the harness**

Run: `./test-install.sh`

Expected: every assertion in the first block PASSES — no `{{` in the target, all three files free of `ai-infra` and mentioning `test-proj`, the residual set now exactly `hooks/_kb_edits.py` + `uv.lock`, `uv sync` succeeding, and `uv.lock` naming `test-proj`. The `normalized-proj` block also PASSES. Exit 0.

If `uv sync` fails, do not weaken the assertion — the spec requires the lock to be repairable by sync, and a failure here means the pyproject render is malformed.

- [ ] **Step 7: Confirm the working tree still holds literal placeholders**

Run:

```bash
grep -c '{{PROJECT_NAME}}' CLAUDE.md pyproject.toml program.md
```

Expected: `CLAUDE.md:2`, `pyproject.toml:2`, `program.md:1` — `grep -c` counts matching *lines*, not occurrences, and `CLAUDE.md`'s explanatory line holds two tokens on one line. A zero anywhere means a render leaked into the tracked tree and must be reverted.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md pyproject.toml program.md install.sh
git commit -m "[TB-26] install.sh: render {{PROJECT_NAME}} from a user-chosen name"
```

---

### Task 4: Mirror the rendering in `install.ps1`

**Files:**
- Modify: `install.ps1` — env-override comment block, new name-capture block after the banner (`install.ps1:33-34`), render helpers and copy-loop changes in section 4

**Interfaces:**
- Consumes: the placeholders already present in `CLAUDE.md`, `pyproject.toml`, `program.md` from Task 3; the behavioral contract of `normalize_name`, `is_templated`, `render`, and `place`.
- Produces: `Get-NormalizedName`, `$ProjectName`, `Test-Templated`, `Copy-Payload` — PowerShell equivalents with identical semantics.

- [ ] **Step 1: Document the new override**

Find:

```
# Env overrides: $env:AI_INFRA_TARGET, $env:AI_INFRA_MODE (override|append|skip),
```

Replace with:

```
# Env overrides: $env:AI_INFRA_NAME (project name; default: ask, else target dir name),
#   $env:AI_INFRA_TARGET, $env:AI_INFRA_MODE (override|append|skip),
```

- [ ] **Step 2: Add the name-capture block**

Insert immediately after the banner (`Write-Host "ai-infra installer ($Repo@$Ref -> $Target)"` and its following blank `Write-Host ""`, currently `install.ps1:33-34`):

```powershell
# ---------- 0a. project name ----------
# The payload carries the template's own identity in three files. Capture the
# name the user wants this project to have and render it during the copy, so an
# installed project never claims to be ai-infra.

# Get-NormalizedName — fold an arbitrary human name into a PEP 508-safe slug.
# Required, not cosmetic: pyproject.toml's `name` field rejects spaces and
# uppercase, and a directory called "My App" is a legitimate install target.
# Returns an empty string when no valid character survives.
function Get-NormalizedName($raw) {
  $s = $raw.ToLower() -replace '[ _]', '-' -replace '[^a-z0-9-]', '' -replace '-{2,}', '-'
  return $s.Trim('-')
}

$RawName = $env:AI_INFRA_NAME
if (-not $RawName) {
  $DefaultName = Split-Path $Target -Leaf
  if ([Environment]::UserInteractive) {
    $RawName = Read-Host "Project name? [$DefaultName]"
    if (-not $RawName) { $RawName = $DefaultName }
  } else {
    $RawName = $DefaultName
    Warn "non-interactive session — project name defaulted to '$RawName'"
  }
}

$ProjectName = Get-NormalizedName $RawName
if (-not $ProjectName) {
  Err "project name '$RawName' normalizes to empty — use letters, digits, or hyphens"
  exit 1
}
if ($ProjectName -ne $RawName) {
  Write-Host "  using project name: $ProjectName (from ""$RawName"")"
} else {
  Write-Host "  project name: $ProjectName"
}
Write-Host ""
```

- [ ] **Step 3: Add the render helpers**

In section 4, find:

```powershell
  $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
  function Is-Text($rel){ $rel -match '\.(md|txt)$' -or $rel -match '(^|[\\/])\.gitignore$' -or $rel -match '(^|[\\/])\.gitattributes$' }
```

Replace with:

```powershell
  $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
  function Is-Text($rel){ $rel -match '\.(md|txt)$' -or $rel -match '(^|[\\/])\.gitignore$' -or $rel -match '(^|[\\/])\.gitattributes$' }

  # Test-Templated — true for the three payload files carrying {{PROJECT_NAME}}.
  # An explicit allowlist rather than a blanket pass: a global substitution would
  # also rewrite the provenance mentions ("added by ai-infra") that must survive.
  function Test-Templated($rel){ @('CLAUDE.md','pyproject.toml','program.md') -contains ($rel -replace '\\','/') }

  # Get-Rendered — return the file's content with {{PROJECT_NAME}} resolved.
  function Get-Rendered($path){ (Get-Content $path -Raw).Replace('{{PROJECT_NAME}}', $ProjectName) }

  # Copy-Payload — install one payload file, rendering it when templated.
  function Copy-Payload($s, $d, $rel) {
    if (Test-Templated $rel) { Set-Content -Path $d -Value (Get-Rendered $s) -NoNewline }
    else { Copy-Item $s $d -Force }
  }
```

- [ ] **Step 4: Rewire the copy loop**

Find the fresh-install branch:

```powershell
        New-Item -ItemType Directory -Force -Path (Split-Path $d -Parent) | Out-Null
        Copy-Item $s $d -Force; $Installed += $rel; continue
```

Replace with:

```powershell
        New-Item -ItemType Directory -Force -Path (Split-Path $d -Parent) | Out-Null
        Copy-Payload $s $d $rel; $Installed += $rel; continue
```

Find the override branch:

```powershell
        'override' { Copy-Item $d "$d.$ts.bak" -Force; Copy-Item $s $d -Force; $Overwrote += $rel }
```

Replace with:

```powershell
        'override' { Copy-Item $d "$d.$ts.bak" -Force; Copy-Payload $s $d $rel; $Overwrote += $rel }
```

Find the append branch's content read:

```powershell
            Add-Content -Path $d -Value ($sep + (Get-Content $s -Raw)); $Appended += $rel
```

Replace with:

```powershell
            $body = if (Test-Templated $rel) { Get-Rendered $s } else { Get-Content $s -Raw }
            Add-Content -Path $d -Value ($sep + $body); $Appended += $rel
```

- [ ] **Step 5: Verify the two installers agree**

Run:

```bash
grep -n 'CLAUDE.md|pyproject.toml|program.md' install.sh
grep -n "'CLAUDE.md','pyproject.toml','program.md'" install.ps1
grep -n 'AI_INFRA_NAME' install.sh install.ps1
```

Expected: the allowlist appears once in each installer with the same three entries, and `AI_INFRA_NAME` appears in both files (twice in `install.sh` — the doc comment and the capture; twice in `install.ps1` for the same reason).

- [ ] **Step 6: Exercise the PowerShell installer if `pwsh` is available**

Run:

```bash
command -v pwsh >/dev/null && {
  D="$(mktemp -d)/ps-proj"; mkdir -p "$D"
  AI_INFRA_SRC="$PWD" AI_INFRA_TARGET="$D" AI_INFRA_MODE=override \
  AI_INFRA_NAME="ps-proj" AI_INFRA_SKIP_TOOLS=1 AI_INFRA_SKIP_PLUGINS=1 \
  AI_INFRA_SKIP_PREREQS=1 pwsh -File install.ps1
  grep -rq '{{' "$D" && echo "FAIL: unrendered placeholder" || echo "PASS: no placeholder"
  grep -q 'name = "ps-proj"' "$D/pyproject.toml" && echo "PASS: pyproject renamed" || echo "FAIL: pyproject"
  test -d "$D/docs/superpowers" && echo "FAIL: superpowers shipped" || echo "PASS: payload narrowed"
} || echo "SKIP: pwsh not installed — PowerShell path unverified, state this in the summary"
```

Expected: three PASS lines, or an explicit SKIP. If it skips, say so plainly in the task summary rather than implying the PowerShell path was tested.

- [ ] **Step 7: Confirm the bash path did not regress**

Run: `./test-install.sh`

Expected: exit 0, zero failures.

- [ ] **Step 8: Commit**

```bash
git add install.ps1
git commit -m "[TB-26] install.ps1: mirror the {{PROJECT_NAME}} rendering"
```

---

### Task 5: User-facing documentation

**Files:**
- Modify: `README.md` — install section
- Modify: `SETUP.md` — install section

**Interfaces:**
- Consumes: the `AI_INFRA_NAME` contract from Tasks 3 and 4.
- Produces: nothing consumed downstream.

- [ ] **Step 1: Read both files to find the install sections**

Run:

```bash
grep -n 'curl -fsSL\|irm https' README.md SETUP.md
```

Note each line number — the new prose goes immediately after the install command block in each file.

- [ ] **Step 2: Document the prompt in `README.md`**

Insert after the block containing the `curl`/`irm` one-liners (around `README.md:35-40`):

```markdown
The installer asks what to call the project, defaulting to the target directory's
name. The answer is normalized to a lowercase slug and written into `CLAUDE.md`,
`pyproject.toml`, and `program.md`, so the installed project carries your name
rather than `ai-infra`. Set `AI_INFRA_NAME` to skip the prompt:

```bash
AI_INFRA_NAME=my-app curl -fsSL https://raw.githubusercontent.com/thien06012001/ai-infra/main/install.sh | bash
```

With no terminal available — a CI run, for instance — the target directory's name
is used and the choice is reported in the log.
```

- [ ] **Step 3: Add the same note to `SETUP.md`**

Insert the identical paragraph after `SETUP.md`'s install command block. Repeat the text rather than cross-referencing; each file is read on its own.

- [ ] **Step 4: Verify the docs describe real behavior**

Run:

```bash
AI_INFRA_NAME=doc-check ./test-install.sh
```

Expected: exit 0. Then confirm by hand that the documented default matches the code:

```bash
grep -n 'basename "$TARGET"' install.sh
grep -n 'Split-Path $Target -Leaf' install.ps1
```

Expected: one match in each — the documented "defaults to the target directory's name" is what the code actually does.

- [ ] **Step 5: Full-suite final check**

Run: `./test-install.sh`

Expected: exit 0, zero failures, and the residual-mentions listing shows exactly `hooks/_kb_edits.py`.

- [ ] **Step 6: Commit**

```bash
git add README.md SETUP.md
git commit -m "[TB-26] docs: document AI_INFRA_NAME and the install-time name prompt"
```

---

## Knowledge base sync

The project convention requires checking `knowledge/` after any change. This work touches `knowledge/index.md` (Task 2, Step 3) and establishes a reusable distinction — *installer identity versus installed-project identity*, and the rule that a statement true of a template can become false when its subject is renamed. That is a candidate narrative article, and it has now appeared twice (the codegraph indexing claims and the `setup.sh` completion message), which clears the two-sources bar.

Per the standing convention that this is a template repo, any resulting article, `daily/` entry, or `index.md`/`log.md` edit stays **local and unpushed**. Do not include KB content in the `[TB-26]` branch.

## Verification summary

| Spec requirement | Task |
| ---------------- | ---- |
| Single `{{PROJECT_NAME}}` token | 3 |
| `AI_INFRA_NAME` → prompt → basename resolution | 3 (bash), 4 (PowerShell) |
| Slug normalization, empty is a hard error | 3, 4 |
| Allowlisted rendering, append mode included | 3, 4 |
| Three files carry the placeholder | 3 |
| Four reworded template-fact statements | 2 |
| `setup.sh` mentions reworded | 2 |
| `docs/superpowers/` out of the payload | 1 |
| `uv.lock` repaired by `uv sync` | 1 (asserted), confirmed empirically before planning |
| Installer identity preserved | 1–5 (residual-set assertion) |
| Template keeps literal placeholders | 3, Step 7 |
| Both installers change together | 3, 4 |
