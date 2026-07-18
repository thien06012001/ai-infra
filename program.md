# {{PROJECT_NAME}} — infra-as-performance-loop

This is an optional experiment frame: have the LLM continuously improve the performance of this project's own supporting infrastructure — the hooks, the KB pipeline, the branch/commit conventions, and the scripts under `scripts/` and `hooks/`.

**This program optimizes how well the project's infra serves the human + LLM workflow** across a fixed per-experiment budget. The shape of the loop is: pick an idea, apply it, measure, keep or discard.

## Setup

To set up a new infra-improvement experiment, work with the user to:

1. **Pick a task ID + branch.** Use whatever branch name your workflow prefers; commits follow `[<TASK-ID>] <message>` (enforced by `.githooks/commit-msg`).
2. **Create the branch** from current `main`.
3. **Read the in-scope files** — the infra surface is small:
   - `README.md` / `SETUP.md` — project overview and setup flow.
   - `CLAUDE.md` — the rules the agent operates under, including the KB-sync-on-edit convention.
   - `.githooks/` — branch + commit message enforcement.
   - `hooks/` — the Claude Code lifecycle hooks.
   - `scripts/` — supporting utilities (including `compile.py` for the KB pipeline).
   - `knowledge/index.md` — current KB index.
4. **Verify the toolchain exists**: `uv` resolves (`uv run python --version`), `core.hooksPath` is `.githooks`.
5. **Confirm and go.**

## Experimentation

Each experiment targets one concrete, measurable infra weakness. The per-experiment budget is **one focused unit of work** — roughly a single PR's worth of changes — verifiable in under 10 minutes of real wall-clock time.

**What you CAN do:**
- Modify anything under `hooks/`, `scripts/`, `.githooks/`, `CLAUDE.md`, `README.md`, `pyproject.toml`.
- Add new scripts or hooks if they remove friction from the workflow.
- Rewrite `compile.py` and the `daily/` → `knowledge/` pipeline.
- Change branch/commit conventions (but if you do, update `.githooks/` and `CLAUDE.md` in the same commit).

**What you CANNOT do:**
- Modify `daily/` entries retroactively. Daily logs are append-only history; fix the compiler, not the input.
- Modify `knowledge/` articles by hand. The KB is a **compiled artifact**; any change must flow through `daily/` → `compile.py` → `knowledge/`.
- Add secrets or credentials to any tracked file.
- Skip `.githooks/` enforcement with `--no-verify`.

**Simplicity criterion**: All else being equal, simpler is better. **Deleting a hook or a script and getting the same behavior is a great outcome.**

**The first run** should always establish the baseline: run the measurement protocol against `main` as-is, change nothing, and record those numbers.

## The four metrics

Infra performance is multi-dimensional. Each experiment records four numbers:

1. **`cycle_seconds`** — wall-clock time for a representative end-to-end flow: start a session → make a trivial edit → commit → push → session ends → KB compiled. Lower is better.
2. **`friction_events`** — count of manual interventions required during the cycle: hook failures, path-config prompts, venv rebuilds, KB-sync reminders the agent forgot, `--no-verify` temptations, etc. Lower is better. Zero is the target.
3. **`kb_recall_hits`** — out of a fixed set of probe questions (stored in `reports/kb-probes.md`), how many are correctly answerable from the index + one article read, without touching source files. Higher is better.
4. **`infra_loc`** — total lines of code across `hooks/`, `scripts/`, `.githooks/`. Lower is better, all else equal. This is the simplicity counterweight.

An experiment is a **keep** only if at least one metric improved and no metric regressed beyond a small tolerance (± 5% for the continuous metrics, ± 1 for the discrete ones).

## Output format

The measurement harness prints a summary block like this:

```
---
cycle_seconds:   47.3
friction_events: 2
kb_recall_hits:  8
infra_loc:       1124
commit:          a1b2c3d
notes:           baseline
```

Extract the key metrics with:

```
grep "^cycle_seconds:\|^friction_events:\|^kb_recall_hits:\|^infra_loc:" run.log
```

## Logging results

When an experiment is done, log it to `reports/infra-runs.tsv` (tab-separated). The TSV has a header row and 7 columns:

```
commit	cycle_seconds	friction_events	kb_recall_hits	infra_loc	status	description
```

`reports/infra-runs.tsv` is intentionally **untracked by git** — the whole `reports/` directory is gitignored. It's a working-tree artifact of the run, not history.

## The experiment loop

The experiment runs on a dedicated branch.

LOOP:

1. Look at the git state: the current branch/commit.
2. Pick one concrete infra weakness to attack. Favor ones the previous experiment exposed.
3. Apply the change. Remember the KB-sync-on-edit rule in `CLAUDE.md`.
4. `git commit` — obey `.githooks/commit-msg` (`[<TASK-ID>] <message>`).
5. Run the measurement harness: `uv run scripts/measure-infra.py > run.log 2>&1`.
6. Read out the results with the grep command above.
7. If the grep output is empty, the run crashed — diagnose, fix if trivial, otherwise log `crash` and move on.
8. Record the results in `reports/infra-runs.tsv` (do not commit this file).
9. If any metric improved and none regressed beyond tolerance, **keep**: advance the branch.
10. Otherwise **discard**: `git reset --hard` back to where you started.

## Scope

This program optimizes the scaffolding the project depends on. Metrics: `cycle_seconds` / `friction_events` / `kb_recall_hits` / `infra_loc`. Surface: `hooks/`, `scripts/`, `.githooks/`, `CLAUDE.md`, `README.md`.
