"""
SessionStart hook - injects knowledge base context into every conversation.

This is the "context injection" layer. When Claude Code starts a session,
this hook reads the knowledge base index and recent daily log, then injects
them as additional context so Claude always "remembers" what it has learned.

Configure in .claude/settings.json:
{
    "hooks": {
        "SessionStart": [{
            "matcher": "",
            "command": "uv run python hooks/session-start.py"
        }]
    }
}
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Profile gate runs before any I/O so a disabled hook costs essentially nothing.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _profile_gate import check_enabled  # noqa: E402

check_enabled("session-start", min_profile="minimal")

# Paths relative to project root
ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
DAILY_DIR = ROOT / "daily"
INDEX_FILE = KNOWLEDGE_DIR / "index.md"

# Budget caps that keep injected context within Claude's context window.
# 20 000 chars is roughly 5 000 tokens — enough for the index + a log tail
# without crowding out the user's actual task prompt.
MAX_CONTEXT_CHARS = 20_000
# Only the last 30 lines of the daily log are injected; older entries from the
# same day are less actionable and would push the index out of the window.
MAX_LOG_LINES = 30


def get_recent_log() -> str:
    """Read the tail of the most recent daily log (today or yesterday).

    Checks today first, then yesterday, to handle the case where a session
    starts early in the morning before the first entry of the day is written.
    Only the last MAX_LOG_LINES lines are returned to stay within the context
    budget — the most recent entries are the most relevant for orienting Claude
    at the start of a new session.

    Returns:
        Markdown string of recent log lines, or a placeholder if no log exists.
    """
    today = datetime.now(timezone.utc).astimezone()

    for offset in range(2):
        date = today - timedelta(days=offset)
        log_path = DAILY_DIR / f"{date.strftime('%Y-%m-%d')}.md"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            # Return last N lines to keep context small
            recent = lines[-MAX_LOG_LINES:] if len(lines) > MAX_LOG_LINES else lines
            return "\n".join(recent)

    return "(no recent daily log)"


def build_context() -> str:
    """Assemble the KB context block to inject at session start.

    Constructs a three-section markdown document:
      1. Today's date — gives Claude an accurate temporal anchor without
         relying on its training cutoff.
      2. Knowledge base index — the one-table catalog of every compiled article.
         This is the primary retrieval mechanism: Claude reads the index, picks
         relevant articles by name, then reads them on demand during the session.
      3. Recent daily log tail — the last 30 lines of today's (or yesterday's)
         log, giving Claude short-term memory of recent work and decisions.

    The assembled context is truncated at MAX_CONTEXT_CHARS to stay within the
    hook output budget. The index is injected before the log so that if
    truncation occurs, the log tail is cut rather than the index.

    Returns:
        Markdown string ready for injection as additionalContext.
    """
    parts = []

    # Today's date
    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%A, %B %d, %Y')}")

    # Knowledge base index (the core retrieval mechanism)
    if INDEX_FILE.exists():
        index_content = INDEX_FILE.read_text(encoding="utf-8")
        parts.append(f"## Knowledge Base Index\n\n{index_content}")
    else:
        parts.append("## Knowledge Base Index\n\n(empty - no articles compiled yet)")

    # Recent daily log
    recent_log = get_recent_log()
    parts.append(f"## Recent Daily Log\n\n{recent_log}")

    context = "\n\n---\n\n".join(parts)

    # Truncate if too long
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n...(truncated)"

    return context


def main():
    """Emit the KB context injection payload to stdout.

    Claude Code's SessionStart hook protocol expects a JSON object printed to
    stdout with this exact shape:

        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "<markdown string>"
            }
        }

    The `additionalContext` value is injected into the conversation's system
    prompt before the user's first message, giving Claude passive access to
    the entire KB index and recent log without any explicit user request.
    """
    context = build_context()

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }

    print(json.dumps(output))


if __name__ == "__main__":
    main()
