"""Shared location for the cross-hook knowledge-base edit accumulator.

Two hooks coordinate through one file: ``session-activity-tracker.py``
(PostToolUse) appends the path of every touched ``knowledge/`` or ``daily/``
markdown file, and ``stop-kb-lint.py`` (Stop) drains it to decide whether the
KB checks need to run at all.

Why a module rather than each hook computing the path itself: the two must
agree exactly, and a silent mismatch would be invisible — the Stop hook would
simply find nothing and report success, which is the worst failure mode for a
check. One definition removes that class of bug.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path


def accumulator_path(session_id: str) -> Path:
    """Return the accumulator file path for one session.

    The session ID reaches us from the hook payload, so it is untrusted input
    that is about to become part of a filename. Everything outside
    ``[A-Za-z0-9_-]`` is replaced and the result is length-capped, which
    removes any path traversal (``../``) or separator before it can escape the
    temp directory.

    Args:
        session_id: Session identifier from the hook payload. May be empty or
            malformed; callers do not need to pre-validate it.

    Returns:
        Path to this session's accumulator file. The file may not exist yet —
        an absent file simply means no KB edits have been recorded.
    """
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "unknown")[:64] or "unknown"
    return Path(tempfile.gettempdir()) / f"ai-infra-kb-edits-{safe}.txt"
