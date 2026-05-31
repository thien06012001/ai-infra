"""
Memory flush agent - extracts important knowledge from conversation context.

Spawned by session-end.py or pre-compact.py as a background process. Reads
pre-extracted conversation context from a .md file, uses the Claude Agent SDK
to decide what's worth saving, and appends the result to today's daily log.

Usage:
    uv run python scripts/flush.py <context_file.md> <session_id>
"""

from __future__ import annotations

# Recursion prevention: set this BEFORE any imports that might trigger Claude
import os
os.environ["CLAUDE_INVOKED_BY"] = "memory_flush"

import asyncio
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Windows-only: force every child Popen to run hidden.
#
# Why: this process is launched with CREATE_NO_WINDOW (no console), but the
# Claude Agent SDK below spawns the `claude` CLI, which on Windows is an
# npm-installed `.cmd` batch shim. Launching a `.cmd` goes through cmd.exe,
# and because this Python process has no console, Windows allocates a brand
# new console window for the shim — the user sees a black cmd window flash
# at session end. CREATE_NO_WINDOW on our own Popen only covers direct
# children, not grandchildren.
#
# How: monkey-patch subprocess.Popen.__init__ to inject CREATE_NO_WINDOW and
# a hidden STARTUPINFO (SW_HIDE) on every child spawned from this process,
# regardless of whether the Agent SDK, uv, or anything else did the spawning.
if sys.platform == "win32":
    _original_popen_init = subprocess.Popen.__init__

    def _patched_popen_init(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        si = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si
        return _original_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_popen_init

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "daily"
SCRIPTS_DIR = ROOT / "scripts"
STATE_FILE = SCRIPTS_DIR / "last-flush.json"
LOG_FILE = SCRIPTS_DIR / "flush.log"

# Set up file-based logging so we can verify the background process ran.
# The parent process sends stdout/stderr to DEVNULL (to avoid the inherited
# file handle bug on Windows), so this is our only observability channel.
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def load_flush_state() -> dict:
    """Load flush deduplication state from last-flush.json.

    Returns an empty dict if the file doesn't exist or is corrupt, so the
    first run always proceeds regardless of prior state.
    """
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_flush_state(state: dict) -> None:
    """Persist flush deduplication state to last-flush.json.

    Stores the last session_id, its Unix timestamp, and a SHA-256 hash of
    the flushed content — enough to detect duplicate invocations while still
    processing genuinely different context from the same session.
    """
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def append_to_daily_log(content: str, section: str = "Session") -> None:
    """Append content to today's daily log under the correct parent heading.

    The daily log has two top-level sections: ``## Sessions`` and
    ``## Memory Maintenance``. This function locates the right parent heading
    and inserts the new entry immediately after it (before any existing
    entries in that section), so the file's visual structure stays correct.
    Falls back to plain append if the heading is missing.
    """
    today = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"

    if not log_path.exists():
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# Daily Log: {today.strftime('%Y-%m-%d')}\n\n## Sessions\n\n## Memory Maintenance\n\n",
            encoding="utf-8",
        )

    time_str = today.strftime("%H:%M")
    entry = f"### {section} ({time_str})\n\n{content}\n\n"

    # Map the sub-heading type to its parent section heading.
    section_heading = "## Sessions" if section == "Session" else "## Memory Maintenance"
    text = log_path.read_text(encoding="utf-8")

    if section_heading in text:
        # Insert right after the heading (and any trailing newlines).
        insert_pos = text.index(section_heading) + len(section_heading)
        while insert_pos < len(text) and text[insert_pos] == "\n":
            insert_pos += 1
        text = text[:insert_pos] + entry + text[insert_pos:]
        log_path.write_text(text, encoding="utf-8")
    else:
        # Fallback: append to end if heading is somehow missing.
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)


async def run_flush(context: str) -> str:
    """Extract important knowledge from a conversation context string.

    Sends the conversation context to the Claude Agent SDK with a structured
    prompt that instructs the LLM to identify and format only the high-value
    content: decisions made, lessons learned, key exchanges, and action items.
    Routine tool calls, file reads, and trivial back-and-forth are explicitly
    excluded from the output to keep daily logs signal-dense.

    The LLM is given NO tools (allowed_tools=[]) so it can only return text —
    file writes are handled by the caller (append_to_daily_log), keeping I/O
    out of the LLM's hands.

    The sentinel "FLUSH_OK" is returned when the LLM finds nothing worth saving,
    and "FLUSH_ERROR" when the SDK itself fails. Both are handled by the caller.

    Args:
        context: Conversation turns formatted as "**User:** ... / **Assistant:** ..."
                 markdown, pre-extracted from the JSONL transcript.

    Returns:
        Formatted daily log entry text, or "FLUSH_OK" / "FLUSH_ERROR: ..." sentinels.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    prompt = f"""Review the conversation context below and respond with a concise summary
of important items that should be preserved in the daily log.
Do NOT use any tools — just return plain text.

Format your response as a structured daily log entry with these sections:

**Context:** [One line about what the user was working on]

**Key Exchanges:**
- [Important Q&A or discussions]

**Decisions Made:**
- [Any decisions with rationale]

**Lessons Learned:**
- [Gotchas, patterns, or insights discovered]

**Action Items:**
- [Follow-ups or TODOs mentioned]

Skip anything that is:
- Routine tool calls or file reads
- Content that's trivial or obvious
- Trivial back-and-forth or clarification exchanges

Only include sections that have actual content. If nothing is worth saving,
respond with exactly: FLUSH_OK

## Conversation Context

{context}"""

    response = ""

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT),
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
            elif isinstance(message, ResultMessage):
                # Fallback: some SDK versions put final text only in
                # ResultMessage.result instead of AssistantMessage blocks.
                if not response and message.result and isinstance(message.result, str):
                    response = message.result
    except Exception as e:
        import traceback
        logging.error("Agent SDK error: %s\n%s", e, traceback.format_exc())
        response = f"FLUSH_ERROR: {type(e).__name__}: {e}"

    if not response:
        logging.warning("Agent returned empty response — treating as FLUSH_OK")
        return "FLUSH_OK"

    return response


# Trigger end-of-day compilation after this hour (local time). 6 PM is chosen
# as a reasonable "work day over" boundary — late enough to capture a full
# day's worth of sessions before the first compile runs.
COMPILE_AFTER_HOUR = 18  # 6 PM local time


def maybe_trigger_compilation() -> None:
    """Trigger an end-of-day compile.py run if today's log hasn't been compiled yet.

    Called at the end of every flush. Checks two conditions before spawning:
      1. The current local hour is at or after COMPILE_AFTER_HOUR (6 PM).
      2. The today's daily log either hasn't been compiled, or has changed
         (via hash comparison) since the last compile run.

    Spawns compile.py as a fully detached background process so this function
    returns immediately. On Windows, DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP
    is used (unlike session-end.py's CREATE_NO_WINDOW) because compile.py needs
    to invoke the Claude Agent SDK, which spawns its own subprocesses — those
    require a new process group to inherit I/O cleanly on Windows.
    """
    import subprocess as _sp

    now = datetime.now(timezone.utc).astimezone()
    if now.hour < COMPILE_AFTER_HOUR:
        return

    # Check if today's log has already been compiled
    today_log = f"{now.strftime('%Y-%m-%d')}.md"
    compile_state_file = SCRIPTS_DIR / "state.json"
    if compile_state_file.exists():
        try:
            compile_state = json.loads(compile_state_file.read_text(encoding="utf-8"))
            ingested = compile_state.get("ingested", {})
            if today_log in ingested:
                # Already compiled today - check if the log has changed since
                from hashlib import sha256
                log_path = DAILY_DIR / today_log
                if log_path.exists():
                    current_hash = sha256(log_path.read_bytes()).hexdigest()[:16]
                    if ingested[today_log].get("hash") == current_hash:
                        return  # log unchanged since last compile
        except (json.JSONDecodeError, OSError):
            pass

    compile_script = SCRIPTS_DIR / "compile.py"
    if not compile_script.exists():
        return

    logging.info("End-of-day compilation triggered (after %d:00)", COMPILE_AFTER_HOUR)

    cmd = ["uv", "run", "--directory", str(ROOT), "python", str(compile_script)]

    kwargs: dict = {}
    if sys.platform == "win32":
        # DETACHED_PROCESS fully decouples the child from the parent's console,
        # which is required for Agent SDK subprocess I/O on Windows.
        # (session-end.py uses CREATE_NO_WINDOW instead, because that process
        #  does NOT need Agent SDK — it only spawns flush.py.)
        kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    try:
        log_handle = open(str(SCRIPTS_DIR / "compile.log"), "a")
        _sp.Popen(cmd, stdout=log_handle, stderr=_sp.STDOUT, cwd=str(ROOT), **kwargs)
    except Exception as e:
        logging.error("Failed to spawn compile.py: %s", e)


def main():
    """Entry point for the memory flush background process.

    Expected to be invoked by session-end.py or pre-compact.py (never directly
    by the user) after a context file has been written:

        uv run python scripts/flush.py <context_file.md> <session_id>

    Pipeline:
      1. Deduplication check: if the same session_id was flushed within 60 s,
         skip and clean up the context file. The 60 s window is wide enough to
         debounce the rare case where both SessionEnd and PreCompact fire in the
         same session closing sequence without being so wide that a genuine
         second session within the same minute is suppressed.
      2. LLM extraction: run_flush() sends context to the Claude Agent SDK.
      3. Daily log update: append the result to today's daily .md file.
      4. End-of-day trigger: maybe_trigger_compilation() spawns compile.py if
         it's past 6 PM and today's log hasn't been compiled yet.

    All output goes to flush.log (not stdout/stderr) because the parent process
    sends those handles to DEVNULL to avoid an inherited file-handle bug on Windows.
    """
    if len(sys.argv) < 3:
        logging.error("Usage: %s <context_file.md> <session_id>", sys.argv[0])
        sys.exit(1)

    context_file = Path(sys.argv[1])
    session_id = sys.argv[2]

    logging.info("flush.py started for session %s, context: %s", session_id, context_file)

    if not context_file.exists():
        logging.error("Context file not found: %s", context_file)
        return

    # Read pre-extracted context first (before dedup check), so we can
    # compare by content hash rather than time window.
    context = context_file.read_text(encoding="utf-8").strip()

    # Deduplication: skip if the same session already flushed identical content.
    # Both SessionEnd and PreCompact can fire for the same session, but may
    # capture different context (e.g. SessionEnd includes end-of-session turns
    # that PreCompact didn't see). Using a content hash instead of a time window
    # ensures genuinely new context is always processed.
    from hashlib import sha256

    context_hash = sha256(context.encode()).hexdigest()
    state = load_flush_state()
    if (
        state.get("session_id") == session_id
        and state.get("context_hash") == context_hash
    ):
        logging.info("Skipping duplicate flush for session %s (identical content)", session_id)
        context_file.unlink(missing_ok=True)
        return

    if not context:
        logging.info("Context file is empty, skipping")
        context_file.unlink(missing_ok=True)
        return

    logging.info("Flushing session %s: %d chars", session_id, len(context))

    # Run the LLM extraction
    response = asyncio.run(run_flush(context))

    # Append to daily log — but NOT for FLUSH_OK, which means nothing worth
    # saving. Writing a placeholder would mutate the log's hash and trigger
    # spurious recompiles via maybe_trigger_compilation().
    if response.strip() == "FLUSH_OK":
        logging.info("Result: FLUSH_OK — nothing worth saving, log unchanged")
    elif response.strip().startswith("FLUSH_ERROR") or "FLUSH_ERROR" in response:
        logging.error("Result: %s", response)
        append_to_daily_log(response, "Memory Flush")
    else:
        logging.info("Result: saved to daily log (%d chars)", len(response))
        append_to_daily_log(response, "Session")

    # Update dedup state (include content hash for content-based deduplication)
    save_flush_state({"session_id": session_id, "timestamp": time.time(), "context_hash": context_hash})

    # Clean up context file
    context_file.unlink(missing_ok=True)

    # End-of-day auto-compilation: if it's past the compile hour and today's
    # log hasn't been compiled yet, trigger compile.py in the background.
    maybe_trigger_compilation()

    logging.info("Flush complete for session %s", session_id)


if __name__ == "__main__":
    main()
