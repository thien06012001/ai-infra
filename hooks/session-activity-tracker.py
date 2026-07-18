"""PostToolUse hook — append a sanitized activity record to reports/session-activity.jsonl.

Why this hook exists:
    ``program.md`` frames the monorepo as an infra performance loop and lists
    metrics like ``cycle_seconds``, ``friction_events``, ``kb_recall_hits``.
    Today those metrics are computed by ``scripts/measure-infra.py`` purely
    from on-disk artifacts (commit cadence, hook counts, KB article counts).
    This hook adds a second feed — a rolling JSONL log of every tool the
    agent invoked, with file and command summaries — so future iterations of
    ``measure-infra.py`` can surface real interaction telemetry.

What it writes:
    A single line of JSON per PostToolUse fire, appended to
    ``reports/session-activity.jsonl``. Each record carries:

        ts:        ISO-8601 timestamp with local TZ offset.
        session:   The Claude Code session id (from the hook payload).
        tool:      The tool name (Edit / Write / Bash / ...).
        file:      For file-touching tools: the relative path edited.
        cmd:       For Bash: a redacted, truncated summary of the command.
        ok:        Boolean — true unless the hook payload reports a failure
                   status.

Sanitization mirrors ECC's ``session-activity-tracker.js``: strip secrets
(``--token=...``, ``ghp_*``, AWS access keys, ``Authorization:`` headers,
``password=...``), collapse whitespace, truncate to a bounded length.

Failure mode:
    Any exception is swallowed and the hook exits 0. The activity log is
    advisory; it must never block the agent or surface noise.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Profile gate sits at module top so a disabled / minimal-profile run pays
# no I/O cost. Imports above are stdlib only — also cheap.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _profile_gate import check_enabled  # noqa: E402
from _kb_edits import accumulator_path  # noqa: E402

check_enabled("session-activity-tracker", min_profile="standard")

ROOT = HERE.parent
REPORTS_DIR = ROOT / "reports"
LOG_PATH = REPORTS_DIR / "session-activity.jsonl"

# Cap line size so a single huge tool call cannot blow up the JSONL file. The
# limits below mirror ECC's tracker — short enough to be greppable, long
# enough to retain context for debugging.
MAX_CMD_LEN = 220
MAX_FILE_LEN = 240

# Secret-redaction patterns. Apply BEFORE truncation so we never persist a
# half-redacted token. Order matters: longer / more-specific patterns first.
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"--token[= ]\S+"), "--token=<REDACTED>"),
    (re.compile(r"Authorization:\s*\S+", re.IGNORECASE), "Authorization:<REDACTED>"),
    (re.compile(r"\bAKIA[A-Z0-9]{16}\b"), "<REDACTED-AWS-KEY>"),
    (re.compile(r"\bASIA[A-Z0-9]{16}\b"), "<REDACTED-AWS-KEY>"),
    (re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"), "<REDACTED-GH-PAT>"),
    (re.compile(r"\bgho_[A-Za-z0-9_]{20,}\b"), "<REDACTED-GH-OAUTH>"),
    (re.compile(r"\bghs_[A-Za-z0-9_]{20,}\b"), "<REDACTED-GH-SERVER>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<REDACTED-GH-PAT>"),
    (re.compile(r"password[= ]\S+", re.IGNORECASE), "password=<REDACTED>"),
]


def _redact(text: str) -> str:
    """Strip well-known secret patterns from ``text``.

    Conservative by design: only patterns with high precision (provider-issued
    prefixes, explicit ``--token=`` flags) are rewritten. Free-form strings
    that merely contain the word "password" are not heuristically scrubbed —
    false positives there would corrupt legitimate commit messages and the
    like.

    Args:
        text: Arbitrary input string (command line, file path, etc.).

    Returns:
        Same text with secret patterns replaced by ``<REDACTED-*>`` markers.
    """
    out = text
    for pattern, replacement in SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def _summarize(text: str, max_len: int) -> str:
    """Redact, collapse whitespace, and truncate ``text`` to ``max_len`` chars.

    The pipeline is:
        1. Replace secret patterns (see ``_redact``).
        2. Replace any whitespace run with a single space so newlines and tabs
           don't break the JSONL contract (one logical record per line).
        3. Truncate with an ellipsis when the result still exceeds ``max_len``.

    Args:
        text: Raw value to summarize.
        max_len: Maximum permitted character count for the returned summary.

    Returns:
        A single-line, secret-free, length-bounded summary.
    """
    redacted = _redact(text)
    collapsed = re.sub(r"\s+", " ", redacted).strip()
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 3] + "..."


def _read_payload() -> dict:
    """Read and parse the PostToolUse hook payload from stdin.

    The Windows-path fix-up trick from ``session-end.py`` is replicated here
    because the same payload formatting bug surfaces in PostToolUse too: a
    transcript path with unescaped backslashes makes the JSON parse fail.

    Returns:
        Parsed payload dict, or empty dict if the payload could not be parsed.
    """
    try:
        raw = sys.stdin.read() or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            fixed = re.sub(r'(?<!\\)\\(?!["\\])', r"\\\\", raw)
            return json.loads(fixed)
    except Exception:
        return {}


def _build_record(payload: dict) -> dict | None:
    """Translate a hook payload into a JSONL record, or return ``None`` to skip.

    Skip conditions:
        - Missing or empty ``tool_name`` (malformed payload).
        - Tool is not one of the activity-relevant set. We deliberately exclude
          read-only tools (Read, Grep, Glob, LS) because they generate orders
          of magnitude more noise than write tools, and the loop metrics we
          actually care about live on writes.

    Args:
        payload: Parsed hook payload.

    Returns:
        Dict ready for ``json.dumps``, or ``None`` if this call should not be
        recorded.
    """
    tool = str(payload.get("tool_name") or "").strip()
    if not tool or tool in {"Read", "Grep", "Glob", "LS", "TodoWrite", "TodoRead"}:
        return None

    tool_input = payload.get("tool_input") or {}
    record: dict = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "session": payload.get("session_id") or "unknown",
        "tool": tool,
        "ok": True,
    }

    # File-touching tools share the ``file_path`` parameter convention.
    file_path = tool_input.get("file_path")
    if isinstance(file_path, str) and file_path:
        normalized = file_path.replace("\\", "/")
        try:
            normalized = str(Path(normalized).resolve().relative_to(ROOT))
        except Exception:
            # Path is outside the repo or unresolvable; keep the original form.
            pass
        record["file"] = _summarize(normalized, MAX_FILE_LEN)

    # Bash records the command itself; the output is intentionally ignored to
    # keep the JSONL line short and to avoid persisting secrets that may have
    # appeared in stdout/stderr.
    if tool == "Bash":
        command = tool_input.get("command")
        if isinstance(command, str):
            record["cmd"] = _summarize(command, MAX_CMD_LEN)

    # PostToolUseFailure events surface as tool_response.error or status > 0;
    # mark the record so downstream analytics can count friction events.
    resp = payload.get("tool_response") or {}
    if isinstance(resp, dict):
        if resp.get("error") or resp.get("exit_code", 0):
            record["ok"] = False

    return record


def _accumulate_kb_edit(record: dict) -> None:
    """Note a touched knowledge-base file for the Stop hook to drain.

    Why accumulate instead of linting on every edit: the KB linter is a
    whole-corpus structural pass, so running it per-edit would repeat the same
    work many times inside one response. Recording the paths here and draining
    once at Stop collapses that to a single run, and costs no extra process
    spawn because this hook already parsed the payload.

    The accumulator is session-scoped and lives in the system temp dir, not in
    ``reports/`` — it is transient coordination state between two hooks, not an
    artifact worth keeping or committing. ``stop-kb-lint.py`` unlinks it on
    read, so a crashed session leaves at most one stale file that the OS
    reclaims.

    Args:
        record: A built activity record. Only records whose ``file`` is a
            markdown file under ``knowledge/`` or ``daily/`` are accumulated;
            everything else is ignored.
    """
    path = record.get("file")
    if not isinstance(path, str) or not path.endswith(".md"):
        return
    if not (path.startswith("knowledge/") or path.startswith("daily/")):
        return
    try:
        with accumulator_path(record.get("session") or "unknown").open(
            "a", encoding="utf-8"
        ) as f:
            # One path per line, append-only: concurrent hook processes can
            # each append without a lock, which a read-modify-write would need.
            f.write(path + "\n")
    except OSError:
        # Coordination is best-effort; a failure here must not affect the edit.
        return


def main() -> int:
    """Read stdin, build a record, append it to the JSONL log.

    Returns:
        Exit code (always 0 — this hook never blocks).
    """
    payload = _read_payload()
    record = _build_record(payload)
    if record is None:
        return 0

    _accumulate_kb_edit(record)

    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Logging is best-effort; never block the agent on a disk error.
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
