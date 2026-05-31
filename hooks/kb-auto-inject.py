"""UserPromptSubmit hook: inject relevant KB excerpts before each prompt.

Reads `{ "prompt": "..." }` from stdin (the Claude Code hook payload).
Runs BM25 search over `knowledge/` + `daily/` via scripts/search.py. If
>=1 hit clears the min-score threshold, emits a `<kb-context>` block to
stdout, which Claude Code prepends to the user's prompt.

Always exits 0. A search failure must never block a user prompt; on any
exception we fall through to "no injection" silently.

Kill switches:
    - Env var KB_AUTO_INJECT=0 disables injection entirely.
    - Env var CLAUDE_INVOKED_BY=<anything> disables (prevents recursion
      when this hook fires inside a nested Claude call).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Import the search function directly to avoid a second uv subprocess
# spawn per prompt. Adding scripts/ to sys.path is the lightest way to
# do this without restructuring the existing flat module layout.
HOOK_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = HOOK_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(HOOK_DIR))

from _profile_gate import check_enabled  # noqa: E402

check_enabled("kb-auto-inject", min_profile="minimal")

from search import search  # noqa: E402

MIN_PROMPT_LEN = 15
ACKNOWLEDGMENTS = frozenset({
    "ok", "okay", "yes", "no", "y", "n", "go", "continue",
    "thanks", "thank you", "sure", "alright", "yep", "nope",
})
MIN_SCORE = 5.0
TOP_K = 3
EXCERPT_CHARS = 160


def should_skip(prompt: str, env: dict[str, str]) -> bool:
    """Decide whether to skip injection for this prompt.

    Args:
        prompt: The raw user prompt text.
        env: Mapping of environment variables to check (typically os.environ).

    Returns:
        True if KB injection should be skipped, False if it should proceed.

    Why each rule:
      - KB_AUTO_INJECT=0 / CLAUDE_INVOKED_BY: explicit kill switches.
      - <15 chars: too short to encode a useful BM25 query.
      - starts with `/`: a slash command has its own handler.
      - pure acknowledgment: would force noise into every "ok"/"yes" turn.
    """
    if env.get("KB_AUTO_INJECT") == "0":
        return True
    if env.get("CLAUDE_INVOKED_BY"):
        return True
    stripped = prompt.strip()
    if len(stripped) < MIN_PROMPT_LEN:
        return True
    if stripped.startswith("/"):
        return True
    if stripped.lower() in ACKNOWLEDGMENTS:
        return True
    return False


def format_context(hits: list[dict]) -> str:
    """Render top-K hits as a `<kb-context>` block.

    Why an XML-ish wrapper: makes it visually obvious to the agent (and to
    a human reading the transcript) that this content was injected by a
    hook, not typed by the user. Inside the wrapper we keep each hit
    short — Claude can `Read(path, offset=start, limit=end-start+1)` to
    pull the full section if needed.
    """
    if not hits:
        return ""
    lines = [
        "<kb-context>",
        "## Relevant prior knowledge for this prompt:",
        "",
    ]
    for i, h in enumerate(hits, 1):
        excerpt = h["body"].replace("\n", " ")
        if len(excerpt) > EXCERPT_CHARS:
            excerpt = excerpt[:EXCERPT_CHARS].rstrip() + "..."
        lines.append(
            f"{i}. {h['path']}:{h['start_line']}-{h['end_line']} — score {h['score']:.2f}"
        )
        lines.append(f"   ## {h['section']}")
        lines.append(f"   {excerpt}")
        lines.append("")
    lines.append("</kb-context>")
    return "\n".join(lines)


def run(payload: dict, env: dict[str, str]) -> int:
    """Execute the hook against a parsed payload + env snapshot.

    Why split from main(): keeps stdin parsing and process-level concerns
    out of the unit-testable core. Tests inject payload+env directly.
    """
    prompt = payload.get("prompt", "") or ""
    if should_skip(prompt, env):
        return 0

    try:
        hits = search(prompt, k=TOP_K, min_score=MIN_SCORE)
    except Exception:
        return 0  # never block the user prompt

    block = format_context(hits)
    if block:
        print(block)
    return 0


def main() -> int:
    """Entry point: parse stdin JSON, hand to run(), always exit 0."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    return run(payload, env=dict(os.environ))


if __name__ == "__main__":
    sys.exit(main())
