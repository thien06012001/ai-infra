"""
Stop hook - run the knowledge-base checks once, if the KB was actually edited.

The repo ships `scripts/lint.py` (structural KB health) and
`scripts/check-unicode-safety.py` (invisible-Unicode detection), but nothing
invoked either automatically, so both only ran when someone remembered. A check
nobody runs is a check that does not exist.

This hook closes that gap at the one point where it is cheap: the end of a
response, after all edits have landed. `session-activity-tracker.py` records
each touched `knowledge/` or `daily/` markdown file into a session-scoped
accumulator during the turn; this hook drains that list and runs the checks a
single time for the whole response instead of once per edit.

The accumulator is unlinked immediately on read. Stop can fire more than once
for a single logical turn, and without the unlink a second firing would repeat
the same work and re-report findings the user has already seen.

Warn-only by design: it always exits 0. A lint finding in a personal knowledge
base is information, not a reason to interrupt the user mid-thought. Blocking
belongs to guard hooks (see `.claude/hooks/guardrail.sh`), not to advisory ones.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _profile_gate import check_enabled  # noqa: E402
from _kb_edits import accumulator_path  # noqa: E402

check_enabled("stop-kb-lint", min_profile="standard")

ROOT = HERE.parent

# Ceiling for each child check. The structural lint walks the whole corpus, so
# it is not instant, but a Stop hook that hangs is worse than one that skips —
# the user is waiting on it.
CHECK_TIMEOUT_SECONDS = 90


def _read_session_id() -> str:
    """Extract the session ID from the Stop hook payload on stdin.

    Returns:
        The session ID, or "unknown" when the payload is absent or unparseable.
        Falling back to a constant rather than raising keeps a malformed
        payload from turning into a visible hook failure.
    """
    try:
        raw = sys.stdin.read() or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Same Windows-path fix-up as the other hooks: unescaped
            # backslashes in a transcript path break a strict JSON parse.
            payload = json.loads(re.sub(r'(?<!\\)\\(?!["\\])', r"\\\\", raw))
        return str(payload.get("session_id") or "unknown")
    except Exception:
        return "unknown"


def _drain(session_id: str) -> list[str]:
    """Read and delete the accumulator, returning the deduplicated paths.

    The unlink happens before any check runs, so a crash mid-check cannot leave
    a file that causes the same findings to be reported again on the next Stop.

    Args:
        session_id: Session whose accumulator should be drained.

    Returns:
        Repo-relative paths that still exist on disk, in first-seen order. A
        file edited and then deleted within the turn is dropped here rather
        than handed to a checker that would fail on it.
    """
    path = accumulator_path(session_id)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return []
    finally:
        try:
            path.unlink()
        except OSError:
            pass

    seen: dict[str, None] = {}
    for line in content.splitlines():
        rel = line.strip()
        if rel and (ROOT / rel).is_file():
            seen.setdefault(rel, None)
    return list(seen)


def _run(args: list[str]) -> tuple[int, str]:
    """Run a check as a subprocess and capture its combined output.

    Args:
        args: Argument vector, executed with the repo root as the working
            directory so the scripts resolve their sibling imports.

    Returns:
        An (exit_code, output) pair. A timeout or spawn failure returns a
        non-zero code with an explanatory message rather than raising, because
        this hook must never fail loudly enough to interrupt the user.
    """
    env = dict(os.environ)
    # Mirror scripts/lint.py's own guard: mark this as a nested invocation so
    # any hook that would fire on a spawned Claude call stays inert.
    env.setdefault("CLAUDE_INVOKED_BY", "stop_kb_lint")
    try:
        proc = subprocess.run(
            args, cwd=ROOT, env=env, capture_output=True,
            text=True, timeout=CHECK_TIMEOUT_SECONDS,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, f"timed out after {CHECK_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return 1, f"could not run: {exc}"


def main() -> int:
    """Drain the accumulator and report any findings.

    Returns:
        Always 0. See the module docstring for why this hook never blocks.
    """
    edited = _drain(_read_session_id())
    if not edited:
        return 0

    messages: list[str] = []

    # Unicode safety runs only on what changed — it is the ingestion-time check
    # (see CLAUDE.md Rule 14), so the files just written are exactly the ones
    # that could have carried something invisible in from outside.
    code, output = _run(
        [sys.executable, "scripts/check-unicode-safety.py", *edited]
    )
    if code != 0 and output:
        messages.append(output)

    # Structural lint is whole-corpus, so it runs once regardless of how many
    # files changed. LLM-backed checks are skipped: they cost money and latency,
    # which is the wrong trade for an advisory hook on every response.
    #
    # Only hard errors surface here. lint.py exits 0 when it finds nothing worse
    # than warnings and suggestions, of which a healthy corpus always carries
    # some (missing backlinks, orphan sources). Reporting those on every
    # response would train the reader to ignore the hook; they belong in the
    # dated report under reports/, which lint.py writes regardless.
    code, output = _run(
        [sys.executable, "scripts/lint.py", "--structural-only"]
    )
    if code != 0 and output:
        messages.append(output)

    if messages:
        print(f"KB checks flagged {len(edited)} edited file(s):")
        for message in messages:
            print(message)

    return 0


if __name__ == "__main__":
    sys.exit(main())
