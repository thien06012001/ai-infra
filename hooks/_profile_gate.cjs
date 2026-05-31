'use strict';
/**
 * Shared profile-gate module for Claude Code hooks (Node twin).
 *
 * Mirrors ``hooks/_profile_gate.py``: every .cjs hook calls ``checkEnabled``
 * early; if the active ``HOOK_PROFILE`` is too low or the hook ID is
 * named in ``DISABLED_HOOKS``, the process exits with status 0 and
 * the hook body never runs.
 *
 * Why a Node twin instead of shelling out to Python: hook gating must be
 * cheap (<5ms). A node require() of a local file is essentially free, while
 * spawning ``uv run python`` would dominate the hook's runtime.
 *
 * The two implementations share env-var names and the same profile ladder
 * so an operator only ever has to remember one set of toggles.
 *
 * @module hooks/_profile_gate
 */

// Profile ladder. Order matters — index serves as the comparison level.
// minimal keeps only critical safety + KB hooks. standard layers in
// convention enforcement and metrics. strict adds noisier advisory hooks.
const PROFILE_LEVELS = Object.freeze({
  minimal: 0,
  standard: 1,
  strict: 2,
});

const DEFAULT_PROFILE = 'standard';

/**
 * Return the active profile name, or the default if the env var is missing or
 * contains an unrecognized value.
 *
 * Falling back silently (rather than throwing) keeps a typo from bricking the
 * entire hook layer — the operator's worst case is "hooks ran at standard
 * instead of strict," not "no hooks fired at all."
 *
 * @returns {string} One of the keys in ``PROFILE_LEVELS``.
 */
function activeProfile() {
  const raw = String(process.env.HOOK_PROFILE || DEFAULT_PROFILE)
    .trim()
    .toLowerCase();
  return Object.prototype.hasOwnProperty.call(PROFILE_LEVELS, raw) ? raw : DEFAULT_PROFILE;
}

/**
 * Parse ``DISABLED_HOOKS`` into a Set of hook IDs.
 *
 * Empty entries are dropped so an unset / blank env var doesn't accidentally
 * match every hook ID.
 *
 * @returns {Set<string>} Set of disabled hook identifiers.
 */
function disabledHookIds() {
  const raw = String(process.env.DISABLED_HOOKS || '');
  return new Set(
    raw
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)
  );
}

/**
 * Exit the calling hook with status 0 if it is gated off by env vars.
 *
 * Gating order (first match wins):
 *   1. DISABLED_HOOKS lists this hookId -> disabled.
 *   2. HOOK_PROFILE is below minProfile -> disabled.
 *   3. Otherwise -> enabled, return.
 *
 * Returns normally when the hook should proceed. Calls ``process.exit(0)``
 * (a deliberate no-op exit) when the hook should be skipped.
 *
 * @param {string} hookId - Stable identifier matching what an operator would
 *   put in DISABLED_HOOKS (e.g. "warn-debug-statements").
 * @param {('minimal'|'standard'|'strict')} [minProfile='standard'] - Minimum
 *   profile at which this hook should run.
 * @returns {void}
 */
function checkEnabled(hookId, minProfile = 'standard') {
  if (disabledHookIds().has(hookId)) {
    process.exit(0);
  }
  const active = activeProfile();
  const required = PROFILE_LEVELS[minProfile] ?? PROFILE_LEVELS[DEFAULT_PROFILE];
  if (PROFILE_LEVELS[active] < required) {
    process.exit(0);
  }
}

module.exports = {
  PROFILE_LEVELS,
  DEFAULT_PROFILE,
  checkEnabled,
};
