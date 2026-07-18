# Design — installing under a user-chosen project name

**Date:** 2026-07-18
**Status:** approved, ready for planning

## Problem

`ai-infra` is a template repo. Its installers (`install.sh`, `install.ps1`) copy a
payload into the *current* directory so that any project can adopt the Claude
harness plus the Personal Knowledge Base. The payload, however, carries the
template's own identity with it. After installing into `~/projects/my-app`, the
project's `CLAUDE.md` still opens its project guide with:

> This project is `ai-infra`.

That line is read into context at the start of every session. `pyproject.toml`
declares the package as `ai-infra`, `program.md` is titled `ai-infra`, and three
further documents assert facts about `ai-infra` as though they were facts about
the user's project. The result is a freshly installed project that believes it is
the template it was stamped from.

The goal is that after installation the project is named whatever the user wants,
with no residual claim to be `ai-infra` — while the *installer* keeps its own
name, because the tool doing the installing genuinely is `ai-infra`.

## The two roles of the name

Every occurrence of the string `ai-infra` in this repo plays one of two roles,
and conflating them is what makes a naive global rename wrong.

**Installer identity.** `REPO="thien06012001/ai-infra"`, the codeload download
URLs, the installer banner and summary headings, the `AI_INFRA_*` environment
variable names, the `# --- added by ai-infra ---` markers written into appended
files, and the temp-file prefix in `hooks/_kb_edits.py`. These name the tool or
record provenance. They are correct as they stand and must not change.

**Installed-project identity.** Text inside the payload that lands in the target
directory and then asserts something about the project that now contains it.
This is the entire scope of the change.

## Approach

### Placeholder set

Exactly one token: `{{PROJECT_NAME}}`. No description, author, or repository
placeholders. Each additional token is another opportunity for an unrendered
placeholder to reach a user's project, and none of the others were asked for.

### Name capture

Both installers gain a new override, `AI_INFRA_NAME`. Resolution order:

1. `$AI_INFRA_NAME` when set and non-empty — no prompt.
2. Otherwise, an interactive prompt defaulting to the basename of the install
   target: `Project name? [my-app]`.
3. Otherwise — no TTY, as in a `curl … | bash` CI run — the target basename,
   silently accepted but announced through a warning line so the choice is
   visible in the log rather than inferred later from the result.

This mirrors how the existing conflict-mode prompt already degrades without a
terminal, so the installer gains no new class of behavior.

### Normalization

The captured value is normalized to a slug: lowercased, spaces and underscores
folded to hyphens, and any character outside `[a-z0-9-]` stripped. Normalization
is required rather than cosmetic, because `pyproject.toml`'s `name` field must be
a valid PEP 508 distribution name and a directory called `My App` is not one.

When normalization changes the input, the installer says so explicitly —
`using project name: my-app (from "My App")` — rather than quietly mangling what
the user typed. A single normalized name is used in every destination; there is
no separate display name, because two names would mean two things to keep in
agreement for no benefit anyone asked for.

### Substitution

The copy loop renders text files on a small explicit allowlist, substituting
`{{PROJECT_NAME}}` as the bytes are written; every other file is copied
unchanged as it is today. The `append` conflict mode renders as well, since
appended content reaches the same file the copied content would have. The `skip`
mode copies nothing and is therefore unaffected.

An allowlist rather than a blanket pass, because a blanket substitution over the
payload would also rewrite the provenance mentions catalogued above.

### Files carrying the placeholder

| File | Change |
| ---- | ------ |
| `CLAUDE.md` (project-guide opening) | ``This project is `{{PROJECT_NAME}}`.`` |
| `pyproject.toml` | `name` and `description` fields |
| `program.md` | the H1 title |

### Files reworded rather than substituted

Four mentions are statements *about the template* whose truth does not survive a
name swap. `CLAUDE.md`, `docs/pkb-schema.md`, and `knowledge/index.md` each
assert that `ai-infra` itself is not worth indexing with codegraph, justified by
its seventeen hook and script files and roughly seventy-six largely independent
symbols. Substituting the name turns a true statement about the template into a
confident falsehood about the user's application: *"not in `my-app` itself, which
has no call graph worth indexing."* A real application may well have a call graph
worth indexing, and the installed guidance would be steering the reader away from
it.

These three are reworded to a conditional that holds either way: run
`codegraph init` here if this project contains real application code, and skip it
if the repo is only hooks and scripts.

`.claude/README.md` states that "ai-infra never mutates your global setup." This
becomes "this setup never mutates your global setup" — the sentence needs no
project name at all, and the guarantee it makes is true regardless of naming.

### `uv.lock`

The lockfile cannot be templated; it is generated output that pins the root
package as `ai-infra`. The installer already runs `uv sync` while wiring the
project, which re-locks against the rendered `pyproject.toml`. Implementation
must verify that the transient mismatch between a rendered `pyproject.toml` and a
stale `uv.lock` does not hard-error before `uv sync` gets the chance to repair
it. If it does, the remedy is an explicit `uv lock` ahead of the sync.

### Template self-consistency

Tracked files keep `{{PROJECT_NAME}}` literal, so the working tree stays clean
and no commit can accidentally ship a rendered `CLAUDE.md` back into the template
and silently disable the feature. One explanatory line is added near the top of
the project guide: `{{PROJECT_NAME}}` is substituted at install time, and in this
repo it should be read as `ai-infra`. The explanation sits where the question
arises, so an agent reading the guide resolves the token in the same breath.

The alternatives were rejected: rendering placeholders in place via `setup.sh`
permanently dirties the git tree and risks committing rendered output back to the
template, and a `.tmpl` split doubles the file count while making the real
`CLAUDE.md` gitignored and easy to lose.

### Payload scope — `docs/superpowers/`

`PAYLOAD_PATHS` currently lists `docs` wholesale, so `docs/superpowers/specs/`
and `docs/superpowers/plans/` install into every target. Those are design records
about building the template — the 2026-07-13 codegraph documents alone carry
roughly twenty `ai-infra` mentions plus an absolute path into the author's home
directory. They are the same confusion this work exists to remove, in files the
original problem statement had not counted.

Renaming them would not help, because their prose is *about* constructing
`ai-infra`; a correctly renamed copy still reads as someone else's engineering
history sitting inside the user's project. So `docs` is replaced in
`PAYLOAD_PATHS` by the single file `docs/pkb-schema.md`, which is the opposite
case: it documents the knowledge base the user just installed and belongs in
every target.

This has a second benefit. With `docs/superpowers/` out of the payload, specs and
plans may discuss `ai-infra` by name and quote `{{PROJECT_NAME}}` literally
without either leaking into a user's project or tripping the verification greps —
including this document.

## Scope

`install.sh` and `install.ps1` change together in one unit of work. A rename that
lands only on Unix leaves every PowerShell installation still claiming to be
`ai-infra`, which is the defect this work exists to remove.

`README.md` needs no placeholder — it is absent from `PAYLOAD_PATHS` and never
ships to a target. `setup.sh` needs no change, since the template repo keeps its
placeholders literal.

## Verification

Install into a temporary directory named `test-proj`, with `AI_INFRA_SRC`
pointing at the working tree and `AI_INFRA_SKIP_TOOLS=1`:

1. `grep -rn '{{' <target>` across payload files returns nothing — no unrendered
   placeholder escaped into a real project.
2. `grep -c 'ai-infra' <target>/CLAUDE.md <target>/pyproject.toml
   <target>/program.md` returns zero for each.
3. `grep -rn 'ai-infra' <target>` returns only the expected provenance mentions.
   Each is itemized and checked individually, and none may appear in a sentence
   asserting a fact about the user's project.
4. `uv sync` succeeds in the target.
5. A rerun with `AI_INFRA_NAME="My App"` renders `my-app` and prints the
   normalization notice.
6. `test -d <target>/docs/superpowers` fails, and `<target>/docs/pkb-schema.md`
   exists — the payload narrowing took effect in both directions.
7. The PowerShell installer is exercised against the same assertions.

**Boundary conditions.** No existing behavior changes for a user who never
supplies a name: a non-interactive install into `~/projects/foo` must still
complete unattended and produce a working setup, differing only in being named
`foo`. No file leaves the payload, no conflict mode changes meaning, and no
provenance or installer-identity mention is rewritten.

Checks 1 through 3 reconcile against the actual installed bytes rather than
against the installer's own report of what it did, per the reconciliation
preference in CLAUDE.md Rule 4.

## Out of scope

Renaming the GitHub repository, the `AI_INFRA_*` environment variable names, or
the temp-file namespace in `hooks/_kb_edits.py`. Templating any value other than
the project name. Migrating projects that were installed before this change.

One adjacent leak is noted and deliberately not addressed here. The payload is
enumerated with `find` over the source directory rather than from git, so an
install run with `AI_INFRA_SRC` pointing at a working tree copies untracked files
too — including the local, never-pushed `knowledge/` articles and `daily/` logs.
Installs from the published tarball are unaffected, since untracked files are not
in it. This is a separate defect with a separate fix and does not belong in a
rename change.
