#!/usr/bin/env bash
# Shared secret-redaction filter for the Claude Code bash hooks.
#
# WHAT: `redact` reads text on stdin and writes it back with credential VALUES
# replaced by a `<REDACTED>` marker, while preserving the surrounding command
# shape so the audit log stays useful for debugging. `audit_append` wraps that
# with safe log handling (mode 600, size-capped rotation).
#
# WHY: audit.sh and pre-bash-guard.sh append every Bash tool call to
# ~/.claude/hooks/audit.log. Without filtering, any command carrying a
# credential — `curl -H "Authorization: Bearer ..."`, `gh auth login
# --with-token`, `export API_KEY=...` — writes that secret in cleartext to a
# file that was never rotated and defaulted to mode 644. A 2026-07-18 audit of
# that log found real bearer tokens dating back to 2026-05-25.
#
# HOW: a single GNU-sed pass with an ordered denylist of credential shapes.
# Value characters are matched with `\x22`/`\x27` escapes rather than literal
# quotes so the expressions survive shell quoting without escaping gymnastics.
#
# This is best-effort defense in depth, NOT a guarantee. A novel credential
# format will pass through, so the log must still be treated as sensitive.

# Maximum audit-log size before rotation, in bytes. One rotation generation is
# kept (.1); older history is intentionally dropped rather than accumulating
# credential-bearing lines indefinitely.
AUDIT_MAX_BYTES=${AUDIT_MAX_BYTES:-5242880}

# redact: filter stdin -> stdout, replacing credential values with <REDACTED>.
#
# Rule order matters. The more specific vendor prefixes (github_pat_, gh?_,
# AKIA) run before the generic `key=value` sweep so that the vendor prefix is
# preserved in the output — knowing a GitHub token was used is useful; knowing
# its value is not.
redact() {
  sed -E \
    -e 's/(github_pat_)[A-Za-z0-9_]{10,}/\1<REDACTED>/g' \
    -e 's/(gh[pousr]_)[A-Za-z0-9]{10,}/\1<REDACTED>/g' \
    -e 's/(A[KS]IA)[0-9A-Z]{12,}/\1<REDACTED>/g' \
    -e 's/([Aa]uthorization:[[:space:]]*[A-Za-z]+[[:space:]]+)[^\x22\x27\x5C[:space:]]+/\1<REDACTED>/g' \
    -e 's/([Bb]earer[[:space:]]+)[^\x22\x27\x5C[:space:]]+/\1<REDACTED>/g' \
    -e 's/(sk-ant-)[A-Za-z0-9_-]{8,}/\1<REDACTED>/g' \
    -e 's/(sk-)[A-Za-z0-9]{20,}/\1<REDACTED>/g' \
    -e 's/(xox[baprs]-)[A-Za-z0-9-]{8,}/\1<REDACTED>/g' \
    -e 's/(AIza)[A-Za-z0-9_-]{30,}/\1<REDACTED>/g' \
    -e 's/eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]+/<REDACTED-JWT>/g' \
    -e 's/(-----BEGIN[A-Z ]*PRIVATE KEY-----).*/\1<REDACTED>/g' \
    -e 's/(--(token|password|passwd)[= ])[^\x22\x27\x5C[:space:]]+/\1<REDACTED>/g' \
    -e 's/([Aa][Pp][Ii][_-]?[Kk][Ee][Yy]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Tt][Oo][Kk][Ee][Nn]|[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd])([\x22\x27]?[[:space:]]*[:=][[:space:]]*[\x22\x27]?)[^\x22\x27\x5C[:space:]\&;|]+/\1\2<REDACTED>/g'
}

# audit_append: write one already-composed log line through `redact`.
#
# Creates the log with mode 600 before the first write — chmod after the fact
# would leave a window where a fresh log is world-readable. Rotates once the
# file exceeds AUDIT_MAX_BYTES so a long-lived log cannot grow unbounded.
#
# Args:
#   $1 — path to the audit log
#   $2 — the raw line to append (redacted before it touches disk)
audit_append() {
  local log="$1" line="$2"
  mkdir -p "$(dirname "$log")"
  if [ ! -e "$log" ]; then
    install -m 600 /dev/null "$log" 2>/dev/null || { : >"$log"; chmod 600 "$log"; }
  fi
  # stat -c is GNU/Linux; a missing or unreadable size simply skips rotation.
  local size
  size=$(stat -c %s "$log" 2>/dev/null || echo 0)
  if [ "$size" -gt "$AUDIT_MAX_BYTES" ] 2>/dev/null; then
    mv -f "$log" "$log.1" 2>/dev/null || true
    # `mv` preserves the old file's mode, so a log that predates mode-600
    # creation stays world-readable under its new name. Rotation must reduce
    # exposure, not relocate it — this was found the hard way when the first
    # rotation moved 6.18 MB of unredacted history into a 644 archive.
    chmod 600 "$log.1" 2>/dev/null || true
    install -m 600 /dev/null "$log" 2>/dev/null || { : >"$log"; chmod 600 "$log"; }
  fi
  printf '%s\n' "$line" | redact >>"$log"
}
