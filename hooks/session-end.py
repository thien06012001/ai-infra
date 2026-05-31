"""
SessionEnd hook - captures conversation transcript for memory extraction.

When a Claude Code session ends, this hook reads the transcript path from
stdin, extracts conversation context, and spawns flush.py as a background
process to extract knowledge into the daily log.

The hook itself does NO API calls - only local file I/O for speed (<10s).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Recursion guard: if we were spawned by flush.py (which calls Agent SDK,
# which runs Claude Code, which would fire this hook again), exit immediately.
if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)

# Profile gate runs after the recursion guard. Both exit 0; ordering is
# purely a micro-optimization (recursion guard is the cheaper check).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _profile_gate import check_enabled  # noqa: E402

check_enabled("session-end", min_profile="minimal")

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "daily"
SCRIPTS_DIR = ROOT / "scripts"
STATE_DIR = SCRIPTS_DIR

logging.basicConfig(
    filename=str(SCRIPTS_DIR / "flush.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [hook] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

MAX_TURNS = 30
MAX_CONTEXT_CHARS = 15_000
# Session-end flushes even single-turn sessions (e.g. a quick question answered
# by Claude). Pre-compact uses a higher minimum (5 turns) because compaction
# mid-session is only worth capturing if substantial work has happened.
MIN_TURNS_TO_FLUSH = 1


def extract_conversation_context(transcript_path: Path) -> tuple[str, int]:
    """Read a JSONL transcript and extract the last N conversation turns as markdown.

    Claude Code transcripts are newline-delimited JSON files where each line is
    either a message entry (with a nested "message" dict) or a flat entry with
    "role"/"content" at the top level. Both formats are handled here.

    Content blocks come in two forms:
      - A string (legacy / simple messages)
      - A list of typed blocks (e.g. [{"type": "text", "text": "..."}, ...])
    Only text blocks are extracted; tool use, tool results, and image blocks
    are silently dropped — they carry no prose worth saving to the daily log.

    The tail truncation logic (lines after MAX_CONTEXT_CHARS) finds the nearest
    "\\n**" boundary so the returned context always starts at the beginning of a
    turn label ("**User:**" or "**Assistant:**"), never mid-sentence.

    Args:
        transcript_path: Path to the .jsonl session transcript file.

    Returns:
        Tuple of (context_markdown, turn_count) where turn_count is the number
        of turns in the tail window (capped at MAX_TURNS).
    """
    turns: list[str] = []

    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg = entry.get("message", {})
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
            else:
                role = entry.get("role", "")
                content = entry.get("content", "")

            if role not in ("user", "assistant"):
                continue

            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = "\n".join(text_parts)

            if isinstance(content, str) and content.strip():
                label = "User" if role == "user" else "Assistant"
                turns.append(f"**{label}:** {content.strip()}\n")

    recent = turns[-MAX_TURNS:]
    context = "\n".join(recent)

    if len(context) > MAX_CONTEXT_CHARS:
        # Trim from the start (oldest content) and re-align to a turn boundary
        # so flush.py receives clean, parseable turn sequences.
        context = context[-MAX_CONTEXT_CHARS:]
        boundary = context.find("\n**")
        if boundary > 0:
            context = context[boundary + 1 :]

    return context, len(recent)


def main() -> None:
    """SessionEnd hook entry point.

    Reads the hook JSON payload from stdin, extracts conversation context from
    the transcript, writes it to a temp file, then spawns flush.py as a
    background process to do the actual LLM extraction asynchronously.

    The hook itself does no API calls because Claude Code enforces a strict
    time budget on hooks — heavy work must be off-loaded to a subprocess.

    Windows note: Claude Code may pass Windows paths with unescaped backslashes
    in the JSON payload (e.g. "C:\\Users\\..."), which is invalid JSON. The
    two-pass parse below first tries standard json.loads, then falls back to
    escaping lone backslashes before retrying.
    """
    # Read hook input from stdin
    # Claude Code on Windows may pass paths with unescaped backslashes
    try:
        raw_input = sys.stdin.read()
        try:
            hook_input: dict = json.loads(raw_input)
        except json.JSONDecodeError:
            # Escape lone backslashes (not already escaped, not before quotes)
            # to repair Windows path strings before retrying the parse.
            fixed_input = re.sub(r'(?<!\\)\\(?!["\\])', r'\\\\', raw_input)
            hook_input = json.loads(fixed_input)
    except (json.JSONDecodeError, ValueError, EOFError) as e:
        logging.error("Failed to parse stdin: %s", e)
        return

    session_id = hook_input.get("session_id", "unknown")
    source = hook_input.get("source", "unknown")
    transcript_path_str = hook_input.get("transcript_path", "")

    logging.info("SessionEnd fired: session=%s source=%s", session_id, source)

    if not transcript_path_str or not isinstance(transcript_path_str, str):
        logging.info("SKIP: no transcript path")
        return

    transcript_path = Path(transcript_path_str)
    if not transcript_path.exists():
        logging.info("SKIP: transcript missing: %s", transcript_path_str)
        return

    # Extract conversation context in the hook (fast, no API calls)
    try:
        context, turn_count = extract_conversation_context(transcript_path)
    except Exception as e:
        logging.error("Context extraction failed: %s", e)
        return

    if not context.strip():
        logging.info("SKIP: empty context")
        return

    if turn_count < MIN_TURNS_TO_FLUSH:
        logging.info("SKIP: only %d turns (min %d)", turn_count, MIN_TURNS_TO_FLUSH)
        return

    # Write context to a temp file for the background process
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    context_file = STATE_DIR / f"session-flush-{session_id}-{timestamp}.md"
    context_file.write_text(context, encoding="utf-8")

    # Spawn flush.py as a background process
    flush_script = SCRIPTS_DIR / "flush.py"

    cmd = [
        "uv",
        "run",
        "--directory",
        str(ROOT),
        "python",
        str(flush_script),
        str(context_file),
        session_id,
    ]

    # On Windows, use CREATE_NO_WINDOW to avoid flash console window.
    # Do NOT use DETACHED_PROCESS — it breaks the Agent SDK's subprocess I/O.
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        logging.info("Spawned flush.py for session %s (%d turns, %d chars)", session_id, turn_count, len(context))
    except Exception as e:
        logging.error("Failed to spawn flush.py: %s", e)


def _run_git(*args: str) -> tuple[int, str, str]:
    """Run a git command rooted at ROOT. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 127, "", "git executable not found"


def stash_and_switch_to_main() -> None:
    """If there are unstaged/staged changes, stash them, switch to main, and pop.

    Called at session end to keep the main worktree on the main branch after
    work branches are created in linked worktrees. This means opening a new
    session from the repo root always starts on a clean main, regardless of
    which branch was active when the previous session ended.

    Linked worktrees (created by worktree-create.py) are skipped because they
    have their own independent HEAD — switching them to main would destroy the
    branch isolation that worktrees provide.
    """
    rc, git_dir, _ = _run_git("rev-parse", "--git-dir")
    if rc != 0:
        return

    # Detect linked worktrees: in a linked worktree, --git-dir points to a
    # per-worktree path (e.g. .git/worktrees/<name>) while --git-common-dir
    # points to the shared .git root. If they differ, we're in a linked
    # worktree and should not attempt to switch branches here.
    rc, common_dir, _ = _run_git("rev-parse", "--git-common-dir")
    if rc == 0:
        gd = (ROOT / git_dir).resolve() if not Path(git_dir).is_absolute() else Path(git_dir).resolve()
        cd = (ROOT / common_dir).resolve() if not Path(common_dir).is_absolute() else Path(common_dir).resolve()
        if gd != cd:
            logging.info("stash-switch: skipped (linked worktree)")
            return

    rc, branch, _ = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or branch == "main":
        logging.info("stash-switch: skipped (already on main or detached)")
        return

    rc, status, _ = _run_git("status", "--porcelain")
    if rc != 0:
        logging.info("stash-switch: skipped (git status failed)")
        return

    has_changes = bool(status)

    if has_changes:
        rc, _, err = _run_git("stash", "push", "-u", "-m", f"auto-stash from {branch}")
        if rc != 0:
            logging.error("stash-switch: stash failed: %s", err)
            return
        logging.info("stash-switch: stashed changes from %s", branch)

    rc, _, err = _run_git("checkout", "main")
    if rc != 0:
        logging.error("stash-switch: checkout main failed: %s", err)
        if has_changes:
            _run_git("stash", "pop")
        return

    rc, _, err = _run_git("pull", "--ff-only", "origin", "main")
    if rc != 0:
        logging.error("stash-switch: pull failed: %s", err)
    else:
        logging.info("stash-switch: pulled origin/main")

    if has_changes:
        rc, _, err = _run_git("stash", "pop")
        if rc != 0:
            logging.error("stash-switch: stash pop failed (changes in stash): %s", err)
        else:
            logging.info("stash-switch: popped stash on main")

    logging.info("stash-switch: switched from %s to main", branch)


if __name__ == "__main__":
    main()
    stash_and_switch_to_main()
