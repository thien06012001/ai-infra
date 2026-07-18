#!/usr/bin/env bash
# Generic audit logger. Records every tool invocation timestamped.
# Receives JSON on stdin: { tool_name, tool_input }
set -euo pipefail
# shellcheck source=redact.sh
. "$(dirname "${BASH_SOURCE[0]}")/redact.sh"

LOG=~/.claude/hooks/audit.log

INPUT=$(cat)
TOOL=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')
# Summarize tool_input compactly, then truncate to keep the log readable.
# Redaction runs BEFORE the cut so a secret can never be sliced in half and
# leave a usable prefix on disk.
SUMMARY=$(printf '%s' "$INPUT" | jq -c '.tool_input // {}' | redact | cut -c1-400)
audit_append "$LOG" "$(date -Iseconds) $TOOL $SUMMARY"
exit 0
