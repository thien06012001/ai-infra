"""
measure-infra.py — harness for the infra performance loop defined in /program.md.

Prints a summary block that the loop greps for:

    ---
    cycle_seconds:   <float>
    friction_events: <int>
    kb_recall_hits:  <int>
    infra_loc:       <int>
    commit:          <short-hash>
    notes:           <free text>

This is a stub. Only `infra_loc` and `commit` are computed automatically —
everything else is a placeholder until a real end-to-end harness exists.
Building that harness is itself a valid early experiment in the loop.

Fields:
    cycle_seconds   wall-clock time for session -> edit -> commit -> PR ->
                    flush -> KB compile. Stopwatch for now.
    friction_events manual interventions observed during the cycle. Stopwatch.
    kb_recall_hits  score against reports/kb-probes.md (out of 10).
    infra_loc       total LOC under hooks/ scripts/ .githooks/ .github/workflows/.
    commit          short HEAD hash.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories whose total LOC counts as "infra surface".
INFRA_DIRS = [
    REPO_ROOT / "hooks",
    REPO_ROOT / "scripts",
    REPO_ROOT / ".githooks",
    REPO_ROOT / ".github" / "workflows",
]

# File extensions considered "code" for the LOC count. Keep this narrow —
# we are counting the infra surface the loop is trying to shrink, not docs.
CODE_SUFFIXES = {".py", ".sh", ".yml", ".yaml", ".ts", ".js", ".mjs", ".cjs"}


def count_infra_loc() -> int:
    """Count total lines of code across all infra directories.

    Walks INFRA_DIRS recursively and sums line counts for files whose suffix
    is in CODE_SUFFIXES. Binary files and documentation are excluded so the
    metric reflects executable infra surface, not comment/doc bloat.

    The `errors="replace"` open mode means malformed UTF-8 bytes are silently
    replaced rather than raising — keeps the count robust against generated
    files with non-standard encodings.

    Returns:
        Total line count across all infra code files.
    """
    total = 0
    for root in INFRA_DIRS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in CODE_SUFFIXES:
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    total += sum(1 for _ in fh)
            except OSError:
                continue
    return total


def short_commit() -> str:
    """Return the 7-char short hash of the current HEAD commit.

    Returns "unknown" if git is unavailable or the repo has no commits yet,
    so the summary block is always printable even in CI or fresh-clone state.
    """
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def main() -> int:
    """Print the infra performance metrics block to stdout.

    Outputs a YAML-like summary that the program.md loop harness greps for.
    Only `infra_loc` and `commit` are computed automatically; the other three
    metrics (cycle_seconds, friction_events, kb_recall_hits) remain placeholder
    values (-1 or 0.0) until a real end-to-end timing harness is implemented.

    Optional CLI args are joined and used as the `notes` field so ad-hoc
    observations can be captured alongside the automated metrics:

        uv run python measure-infra.py "after hook refactor"

    Returns:
        Exit code 0 (always — this script is informational only).
    """
    notes = " ".join(sys.argv[1:]) or "stub run — cycle_seconds/friction_events/kb_recall_hits are placeholders"

    print("---")
    print("cycle_seconds:   0.0")
    print("friction_events: -1")
    print("kb_recall_hits:  -1")
    print(f"infra_loc:       {count_infra_loc()}")
    print(f"commit:          {short_commit()}")
    print(f"notes:           {notes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
