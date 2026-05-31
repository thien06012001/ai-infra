#!/usr/bin/env bash
# Generic audit logger. Records every tool invocation timestamped.
# Receives JSON on stdin: { tool_name, tool_input }
set -euo pipefail
LOG=~/.claude/hooks/audit.log
mkdir -p "$(dirname "$LOG")"

INPUT=$(cat)
TOOL=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')
# Summarize tool_input compactly; truncate to keep the log readable.
SUMMARY=$(printf '%s' "$INPUT" | jq -c '.tool_input // {}' | cut -c1-400)
echo "$(date -Iseconds) $TOOL $SUMMARY" >> "$LOG"
exit 0
