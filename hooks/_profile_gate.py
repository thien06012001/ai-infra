"""Shared profile-gate module for Claude Code hooks.

Provides a single ``check_enabled(hook_id, min_profile)`` entry point that every
hook script calls early. The function exits the calling process with status 0
when the hook is disabled by the active profile or by an explicit
``DISABLED_HOOKS`` opt-out, so the caller never needs to reason about
gating logic itself.

Why a shared module rather than per-hook env-var checks:
    - Single source of truth for the profile ladder (``minimal`` < ``standard``
      < ``strict``). Adding a new gating tier means editing one constant here.
    - Consistent behavior across Python hooks. The .cjs hooks have a sibling
      twin in ``_profile_gate.cjs`` that exposes the same contract.
    - Lets us turn down hook intensity for triage (``HOOK_PROFILE=
      minimal``) without editing or removing hook files.

How callers wire it in (must run before any heavy work in the hook):

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from _profile_gate import check_enabled
    check_enabled("session-activity-tracker", min_profile="standard")

The ``sys.path`` shim is needed because hooks run via
``uv run --directory $ROOT python hooks/<name>.py`` which puts the repo root on
the path, not ``hooks/``. Bumping ``hooks/`` to the front of ``sys.path`` keeps
the module flat and avoids restructuring into a package.
"""

from __future__ import annotations

import os
import sys
from typing import Final

# Profile ladder. ``minimal`` keeps only critical-safety + KB hooks (never
# disable .env block, KB context, KB compile, worktree management). ``standard``
# layers convention enforcement and metrics. ``strict`` adds noisier warnings
# that some sessions may want suppressed (e.g. console.log warnings).
PROFILE_LEVELS: Final[dict[str, int]] = {
    "minimal": 0,
    "standard": 1,
    "strict": 2,
}

DEFAULT_PROFILE: Final[str] = "standard"


def _active_profile() -> str:
    """Return the active profile name, falling back to the default on bad input.

    Reading from ``HOOK_PROFILE`` keeps profile selection out of band
    from the hook file itself — the operator can change profile per-shell
    without touching ``.claude/settings.json`` or any script.
    """
    profile = os.environ.get("HOOK_PROFILE", DEFAULT_PROFILE).strip().lower()
    if profile not in PROFILE_LEVELS:
        return DEFAULT_PROFILE
    return profile


def _disabled_hook_ids() -> set[str]:
    """Parse ``DISABLED_HOOKS`` into a set of hook IDs.

    Format is comma-separated, whitespace-tolerant. Empty IDs are dropped to
    avoid an empty string matching every hook by accident.
    """
    raw = os.environ.get("DISABLED_HOOKS", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def check_enabled(hook_id: str, min_profile: str = "standard") -> None:
    """Exit the calling hook process with status 0 if it is gated off.

    The function is fire-and-forget: it either returns silently (hook proceeds)
    or calls ``sys.exit(0)`` so the hook never executes its main body.

    Gating order (first match wins):
        1. ``DISABLED_HOOKS`` lists this ``hook_id`` -> disabled.
        2. Active ``HOOK_PROFILE`` is below ``min_profile`` -> disabled.
        3. Otherwise -> enabled, return.

    Args:
        hook_id: Stable identifier for this hook (e.g. "session-activity-tracker").
            Should match the value the operator types into DISABLED_HOOKS.
        min_profile: Minimum profile at which this hook should run. Hooks that
            are critical safety (e.g. .env block, KB plumbing) should pass
            "minimal"; convention-enforcement hooks should pass "standard";
            noisy advisory hooks should pass "strict".

    Raises:
        SystemExit: With status 0 when the hook is gated off. The exit code is
            zero by design — a gated hook is not a failure, it is a no-op.
    """
    if hook_id in _disabled_hook_ids():
        sys.exit(0)

    active = _active_profile()
    required = PROFILE_LEVELS.get(min_profile, PROFILE_LEVELS[DEFAULT_PROFILE])
    if PROFILE_LEVELS[active] < required:
        sys.exit(0)
