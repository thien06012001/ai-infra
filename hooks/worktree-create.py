#!/usr/bin/env python3
"""
WorktreeCreate hook for Claude Code.

Decides the branch prefix for a new worktree based on which parts of the
monorepo the upcoming work is expected to touch. The hook can't see
"changed files" at creation time, so it scans the conversation transcript
for path references and applies these rules:

  - work scoped to a single project under ``projects/<name>/``
        -> ``<name>/<branch-name>``
  - work scoped to multiple projects under ``projects/``, or to both
    ``projects/`` and infra (root-level files / dirs outside ``projects/``)
        -> ``integrate/<branch-name>``
  - work scoped to infra only (no ``projects/`` references)
        -> ``infra/<branch-name>``
  - nothing detected
        -> ``claude/<branch-name>`` (default)

Projects are auto-discovered by listing subdirectories of ``projects/``,
so adding a new project requires no configuration changes.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Profile gate runs before any work. Worktree management is critical
# infrastructure, so it stays at the minimal profile (never gated off by
# profile alone — only explicit DISABLED_HOOKS opts out).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _profile_gate import check_enabled  # noqa: E402

check_enabled("worktree-create", min_profile="minimal")


# Root-level files / directories that count as "infra" when referenced in
# the transcript. A mention is only counted when it appears with a path
# separator or file extension (e.g. ``hooks/``, ``CLAUDE.md``) to avoid
# matching the bare English words.
INFRA_ROOT_DIRS = {
    "hooks",
    "scripts",
    "daily",
    "knowledge",
    "reports",
    ".claude",
    ".githooks",
    ".github",
}
INFRA_ROOT_FILES = {
    "CLAUDE.md",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
    ".gitattributes",
}


def discover_projects(root: Path) -> list[str]:
    """Return the list of project directory names under ``projects/``."""
    projects_dir = root / "projects"
    if not projects_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in projects_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def _read_transcript(transcript_path: str) -> str:
    """Read the raw transcript file content, returning an empty string on failure.

    errors="ignore" silently drops undecodable bytes rather than crashing — the
    transcript is a heuristic input used only for prefix detection, so a slightly
    corrupt read is better than no read at all.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        print(f"[worktree-create] Warning: could not read transcript: {e}", file=sys.stderr)
        return ""


def detect_scope(transcript: str, projects: list[str]) -> tuple[set[str], bool]:
    """Scan the transcript for project and infra path references.

    Uses regex rather than simple substring search to avoid false positives.
    For example, bare words like "hooks" in prose ("the hooks are the key
    feature") must not trigger infra detection; only explicit path references
    like "hooks/" or "hooks\\" should count.

    Args:
        transcript: Full raw text of the JSONL transcript (read as a string).
        projects: List of project directory names under projects/.

    Returns:
        Tuple of (referenced_projects, infra_hit) where:
          - referenced_projects: set of project names matched in the transcript
          - infra_hit: True if any infra directory or file was referenced
    """
    if not transcript:
        return set(), False

    text = transcript.lower()

    # Project scope: match "projects/<name>" with either forward or back slash.
    # The word boundary \b prevents "dashboard" from matching "dashboard-api".
    referenced: set[str] = set()
    for name in projects:
        name_l = name.lower()
        if re.search(rf"projects[\\/]{re.escape(name_l)}\b", text):
            referenced.add(name)

    # Infra scope: match root-level dirs only when followed by a path separator
    # (e.g. "hooks/", "hooks\"), and root-level files only when preceded by a
    # word boundary. This prevents prose mentions like "the hooks pattern" or
    # "README" in a sentence from counting as infra references.
    infra_hit = False
    for d in INFRA_ROOT_DIRS:
        if re.search(rf"(^|[\s`\"'(]){re.escape(d.lower())}[\\/]", text):
            infra_hit = True
            break
    if not infra_hit:
        for f in INFRA_ROOT_FILES:
            if re.search(rf"(^|[\s`\"'(/\\]){re.escape(f.lower())}\b", text):
                infra_hit = True
                break

    return referenced, infra_hit


def decide_prefix(referenced: set[str], infra_hit: bool) -> str:
    """Determine the branch prefix from the detected scope.

    Decision table:
      - One project, no infra  → "<project-name>"  (e.g. "dashboard")
      - Multiple projects      → "integrate"
      - Infra only             → "infra"
      - Both project + infra   → "integrate"
      - Nothing detected       → "claude" (safe default for ambiguous sessions)

    Args:
        referenced: Set of project names detected in the transcript.
        infra_hit: True if any infra path was detected in the transcript.

    Returns:
        Branch prefix string.
    """
    if referenced and not infra_hit:
        if len(referenced) == 1:
            return next(iter(referenced))
        return "integrate"
    if infra_hit and not referenced:
        return "infra"
    if referenced and infra_hit:
        return "integrate"
    return "claude"


def main():
    """WorktreeCreate hook entry point.

    Reads the hook payload from stdin, determines the branch prefix by scanning
    the transcript, constructs the full branch name as "<prefix>/<worktree-name>",
    creates the worktree directory under .claude/worktrees/, then prints the
    absolute worktree path to stdout (the only line Claude Code reads).

    Branch creation logic:
      - If the branch already exists (git rev-parse --verify succeeds), attach
        the new worktree to that existing branch. This handles the case where
        a worktree was previously removed but the branch was kept.
      - Otherwise, create a new branch with `git worktree add -b`.
    """
    data = json.load(sys.stdin)

    name: str = data.get("name", "")
    cwd: str = data.get("cwd", "")
    transcript_path: str = data.get("transcript_path", "")

    if not name or not cwd:
        print("[worktree-create] Error: missing 'name' or 'cwd' in hook input", file=sys.stderr)
        sys.exit(1)

    root = Path(cwd)
    projects = discover_projects(root)
    transcript = _read_transcript(transcript_path)
    referenced, infra_hit = detect_scope(transcript, projects)
    prefix = decide_prefix(referenced, infra_hit)

    print(
        f"[worktree-create] projects={sorted(referenced) or '-'} infra={infra_hit} prefix={prefix}",
        file=sys.stderr,
    )

    branch = f"{prefix}/{name}"
    worktree_path = root / ".claude" / "worktrees" / name

    print(f"[worktree-create] branch={branch}  worktree={worktree_path}", file=sys.stderr)

    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    # Check whether the branch already exists before deciding which git command to use.
    check = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        cwd=cwd,
        capture_output=True,
    )

    if check.returncode == 0:
        # Branch exists — attach a new worktree to it without recreating the branch.
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch],
            cwd=cwd,
            check=True,
            stderr=sys.stderr,
        )
    else:
        # Branch does not exist — create it and the worktree simultaneously.
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path)],
            cwd=cwd,
            check=True,
            stderr=sys.stderr,
        )

    # Output ONLY the absolute path — Claude Code parses this line to determine
    # where to open the worktree. Any other stdout output would break the parse.
    print(str(worktree_path.resolve()))


if __name__ == "__main__":
    main()
