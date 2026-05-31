#!/usr/bin/env python3
"""
SessionStart hook: clean up worktrees whose remote branches are gone.

Detects "done" worktrees via git alone (no gh dependency):

  1. `git fetch --prune` removes remote-tracking refs for deleted branches.
  2. `git for-each-ref ... %(upstream:track)` marks branches with a deleted
     upstream as `[gone]` — the standard signal that a PR branch was merged
     on GitHub with "delete branch on merge" enabled.

Handles two kinds of stale state:

  1. Live worktrees whose branch's upstream is gone
     → `git worktree remove` + delete local branch
  2. Orphan folders in .claude/worktrees/ that git no longer tracks
     (worktree was pruned but the directory remains)
     → remove the leftover directory

The active worktree is always skipped. Worktrees with uncommitted changes
are left alone so nothing is lost.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Profile gate runs before any git calls. The cleanup pass is housekeeping
# rather than load-bearing, so a disabled run is purely informational.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _profile_gate import check_enabled  # noqa: E402

check_enabled("cleanup-worktrees", min_profile="minimal")


def run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a shell command and capture its output without raising on failure.

    Returns the CompletedProcess so callers can inspect returncode, stdout,
    and stderr. Never raises CalledProcessError — callers check returncode.
    """
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def log(msg: str) -> None:
    """Write a prefixed diagnostic message to stderr."""
    print(f"[cleanup-worktrees] {msg}", file=sys.stderr)


def list_git_worktrees(repo: Path) -> list[dict]:
    """Parse `git worktree list --porcelain` into a list of dicts."""
    result = run(["git", "worktree", "list", "--porcelain"], cwd=str(repo))
    if result.returncode != 0:
        return []

    worktrees: list[dict] = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch refs/heads/"):]
        elif line == "detached":
            current["detached"] = True
    if current:
        worktrees.append(current)
    return worktrees


def branches_with_gone_upstream(repo: Path) -> set[str]:
    """Return local branch names whose upstream has been deleted on the remote."""
    result = run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname:short)|%(upstream:track)",
            "refs/heads/",
        ],
        cwd=str(repo),
    )
    gone: set[str] = set()
    if result.returncode != 0:
        return gone
    for line in result.stdout.splitlines():
        if "|" not in line:
            continue
        name, track = line.split("|", 1)
        if "[gone]" in track:
            gone.add(name)
    return gone


def has_uncommitted_changes(worktree_path: Path) -> bool:
    """Return True if the worktree has any staged or unstaged changes.

    Uses --porcelain for machine-readable output; a non-empty result means
    at least one file is modified, added, or deleted. Worktrees with changes
    are skipped during cleanup so no in-progress work is accidentally lost.
    """
    result = run(["git", "status", "--porcelain"], cwd=str(worktree_path))
    return bool(result.stdout.strip())


def main():
    """SessionStart hook entry point for worktree cleanup.

    Runs two passes on the .claude/worktrees/ directory:

    Pass 1 — Live worktrees with a gone upstream:
      After `git fetch --prune` removes stale remote-tracking refs, any local
      branch whose upstream no longer exists appears as "[gone]" in the
      for-each-ref output. These branches correspond to PRs that were merged
      with "delete branch on merge" on GitHub. Their worktrees are removed via
      `git worktree remove` and the local branch is force-deleted. A final
      `git worktree prune` cleans the internal git metadata.

    Pass 2 — Orphan directories git no longer tracks:
      Covers the edge case where a worktree was already pruned (e.g. manually
      or by a previous run) but its directory remains on disk. These directories
      are removed with shutil.rmtree since git has no record of them.

    The active worktree (identified via CLAUDE_PROJECT_DIR) and any worktree
    with uncommitted changes are always skipped so no work is lost.

    The fetch step is best-effort: if it fails (e.g. offline), the hook
    continues with the orphan-folder pass, which is always safe to run.
    """
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    cwd = data.get("cwd") or os.getcwd()
    repo = Path(cwd).resolve()
    worktrees_dir = repo / ".claude" / "worktrees"
    # CLAUDE_PROJECT_DIR is set by Claude Code to the directory of the active
    # worktree. Falling back to cwd ensures the active worktree is never removed
    # even if the env var is missing.
    active_wt = Path(os.environ.get("CLAUDE_PROJECT_DIR", cwd)).resolve()

    if not worktrees_dir.exists():
        return

    # Refresh remote state so [gone] tracking is accurate.
    fetch = run(["git", "fetch", "--prune"], cwd=str(repo))
    if fetch.returncode != 0:
        log(f"git fetch --prune failed: {fetch.stderr.strip()}")
        # Continue anyway — the orphan-folder pass is still useful offline.

    gone_branches = branches_with_gone_upstream(repo)

    # --- Pass 1: live worktrees whose upstream is gone ---
    removed_any = False
    for wt in list_git_worktrees(repo):
        path = Path(wt.get("path", "")).resolve()
        branch = wt.get("branch")

        try:
            path.relative_to(worktrees_dir)
        except ValueError:
            continue  # not a managed worktree — skip main worktree and others

        if path == active_wt or path == repo:
            continue
        if not branch or branch not in gone_branches:
            continue
        if has_uncommitted_changes(path):
            log(f"skip {path.name}: uncommitted changes")
            continue

        log(f"removing merged worktree: {path.name} (branch {branch})")
        rm = run(["git", "worktree", "remove", str(path)], cwd=str(repo))
        if rm.returncode != 0:
            log(f"  failed: {rm.stderr.strip()}")
            continue
        # Force-delete the local branch now that the worktree is gone.
        run(["git", "branch", "-D", branch], cwd=str(repo))
        removed_any = True

    if removed_any:
        # Prune stale worktree metadata from .git/worktrees/ after removals.
        run(["git", "worktree", "prune"], cwd=str(repo))

    # --- Pass 2: orphan folders git no longer knows about ---
    tracked = {Path(wt["path"]).resolve() for wt in list_git_worktrees(repo) if "path" in wt}
    for entry in worktrees_dir.iterdir():
        if not entry.is_dir():
            continue
        resolved = entry.resolve()
        if resolved == active_wt or resolved in tracked:
            continue
        log(f"removing orphan folder: {entry.name}")
        try:
            shutil.rmtree(entry)
        except Exception as e:
            log(f"  failed: {e}")


if __name__ == "__main__":
    main()
