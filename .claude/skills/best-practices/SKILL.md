---
name: best-practices
description: Analyze and implement best practices from `knowledge/best-practices/`. Use when the user says "analyze and implement best practices" (optionally followed by a topic like "for security" or "for testing/flaky-tests"). Reads external reference files (PDF, image, text) under that folder, extracts concrete rules, judges each against the current monorepo, and produces a review-ready report. Does not modify code without explicit per-finding approval.
user-invocable: true
---

# best-practices

Run a phrase-triggered audit of the monorepo against externally-sourced best-practice documents in `knowledge/best-practices/`. Output is a review-ready report at `reports/best-practices/<date>-<topic>.md`. Implementation happens only on explicit per-finding approval.

## Pipeline (run strictly in order)

### Phase 1 — Discover

1. Parse the user's prompt for an optional topic suffix:
   - `Analyze and implement best practices` → scope = `knowledge/best-practices/`
   - `... for <path>` → scope = `knowledge/best-practices/<path>/`
2. Walk the scope recursively. Build an inventory of `{ path, type (pdf/image/text/md), size, page_count_for_pdf }`.
3. Skip rules:
   - Skip files starting with `_` (e.g. `_implemented.md`, `_notes.md`).
   - Skip anything matched by `.gitignore`.
   - **Skip any folder containing an `_implemented.md` file** — this is the "decided" marker (see Phase 5). It signals that every finding from this source has already been processed in a prior sweep (implemented, rejected, or deferred — the marker doesn't distinguish, and shouldn't matter for future scans). The skip applies to the folder and all its descendants. Surface skipped folders in the inventory as a one-line entry tagged `[implemented]` so the user can see what was filtered without re-reading their files.
4. Show the inventory as a table and ask the user to confirm before proceeding to Phase 2. Token cost scales with file count. If every folder under the scope is `[implemented]`, say so explicitly and stop — there is nothing new to extract.

### Phase 2 — Extract rules

For each inventory entry:

- `.md` / `.txt` → Read directly. Extract actionable rules — lines with must/should/always/never patterns and bulleted recommendations.
- `.pdf` → Use `Read(pages: "1-10")`, then `Read(pages: "11-20")`, etc. For files >100 pages, surface a token-cost warning and confirm before reading.
- `.png` / `.jpg` / `.svg` → Read as image (multimodal). Describe content; extract any visible rules.

Maintain a rule list: `[{ id (1-indexed), source_file, source_locator (page or section), rule_text, category (from folder name), confidence (high/medium/low) }]`.

### Phase 3 — Judge per rule

For each rule, in order:

1. Read root `CLAUDE.md`.
2. Read the relevant project `CLAUDE.md` files based on the rule's scope.
3. Read your auto-memory `MEMORY.md` (under `~/.claude/projects/<this-project>/memory/`) and any memory file slugs that look relevant by description.
4. Identify scope: which projects + which files would the rule touch.
5. Sample 5–10 representative files inside that scope.
6. Classify into **exactly one** bucket:

   - `already-followed` — evidence found that the rule is in effect; cite `path:line`.
   - `partially-followed` — applies in N of M places, not all.
   - `not-followed` — applies and isn't followed; attach a one-paragraph proposed change.
   - `not-applicable` — doesn't fit our stack/scope; give a reason.
   - `conflicts-with-convention` — contradicts root CLAUDE.md, a project CLAUDE.md, or a saved memory. **FLAG for user review. Never silently apply.**

A rule that contradicts a saved memory is `conflicts-with-convention`, never `not-followed`. This is the most important judgment rule.

### Phase 4 — Write the report

Write `reports/best-practices/<YYYY-MM-DD>-<topic-or-all>.md` using today's date (system clock) and the topic (or literal string `all` if no topic). Format:

```markdown
# Best-practices sweep — <YYYY-MM-DD> — topic: <topic-or-all>

**Inventory:** N files scanned (X pdf, Y png, Z md), M rules extracted.

## Summary
| Bucket | Count |
|---|---|
| already-followed | … |
| partially-followed | … |
| not-followed | … |
| not-applicable | … |
| conflicts-with-convention | … |

## Findings (sorted: conflicts → not-followed → partial → done)

### ⚠️ #1 — CONFLICT — "<rule text>"
- **Source:** <file>, p.<page> or §<heading>
- **Conflicts with:** <CLAUDE.md path / memory slug>
- **Recommendation:** reject / discuss
- **Action:** none unless you want to revisit the convention.

### 🔴 #N — NOT-FOLLOWED — "<rule text>"
- **Source:** <file>, p.<page>
- **Applies to:** <project names>
- **Current state:** <evidence>
- **Proposed change:** <one paragraph>
- **Estimated scope:** <files × LOC>
- **Action:** reply "implement #N" to schedule

### 🟡 #N — PARTIAL — "<rule text>"
- **Source:** …
- **Followed in:** …
- **Missing in:** …
- **Action:** reply "implement #N"

### ✅ #N — ALREADY-FOLLOWED — "<rule text>"
- **Source:** …
- **Evidence:** path:line
```

After writing the report, surface the path to the user and stop. Do NOT proceed to Phase 5 automatically.

### Phase 5 — Implement (only on explicit per-finding approval)

User reply pattern: `implement #2, #7` or `implement #2`.

For each approved finding, in order:

1. Confirm or create a Linear ticket for the change.
2. Create a scoped branch using the monorepo convention: `<prefix>/<TASK-ID>-<short-name>` where prefix is `<project-name>` for project-scoped work, `infra` for root-only, `integrate` for cross-project.
3. Make the change surgically — only the files needed for this finding (per CLAUDE.md Rule 3).
4. Add or update tests where applicable.
5. Commit with `[<TASK-ID>] <message>`.
6. Move to the next finding.

**No bulk implementation.** Even if 10 findings target the same project, each is its own commit so diffs stay reviewable. The exception: 2–3 findings that touch the same lines in the same file may share one commit if separating them would create churn.

### Phase 6 — Mark the source folder as decided

Once every finding from a source folder has been resolved — whether
implemented, rejected, or deliberately deferred — write a marker file at
`knowledge/best-practices/<folder>/_implemented.md` so future scanner
runs skip the folder (see Phase 1 skip rules).

The marker is required on **completion of the user's decision pass**, not
only on full implementation. A folder where every finding is deferred is
still "decided" — the user has consciously chosen not to act, and re-
extracting the same rules on the next sweep would be noise.

The file's content is free-form Markdown but must include a per-finding
status table — `IMPLEMENTED <TICKET-ID>` / `REJECTED <reason>` /
`DEFERRED <reason>` per row — plus a pointer to the original report.
Example template:

```markdown
# <folder-name> — decision log

All findings from this source were resolved on <YYYY-MM-DD>.

| # | Rule (one-line) | Decision | Reference |
|---|---|---|---|
| 1 | … | REJECTED — conflicts with CLAUDE.md Rule X | — |
| 2 | … | IMPLEMENTED | THI-NNN |
| 3 | … | DEFERRED — <reason> | — |

Original report: `reports/best-practices/<YYYY-MM-DD>-<topic>.md`.
Delete this file to re-scan.
```

To **re-open** a decided folder (e.g. you've added new pages and want
those scanned against the existing decisions plus any fresh extractions),
delete the `_implemented.md` and run the trigger phrase again.

## Edge cases

- **PDF 21–100 pages:** chunk by 10 pages with separate `Read` calls; merge.
- **PDF >100 pages:** warn user about token cost and confirm before reading.
- **Image with no extractable text:** rule list for that file = `[]`; note in report as "image contains no actionable rules".
- **Empty topic folder:** report says `inventory: 0 files; nothing to analyze`; no error.
- **Conflicting rules across sources:** surface both as separate findings; user decides.
- **Rule applies to a project not in this monorepo:** `not-applicable`.

## Do not

- Do not modify source files in `knowledge/best-practices/` — read-only inputs.
- Do not auto-fire on general questions like "what are some best practices for X" — that's not a folder scan.
- Do not implement findings without explicit per-ID approval.
- Do not produce a single bulk commit covering many unrelated findings.
- Do not skip the Phase 1 confirmation gate — token cost matters.

## Related

- Source folder: [`knowledge/best-practices/`](../../../knowledge/best-practices/)
- Report output: [`reports/best-practices/`](../../../reports/best-practices/)
