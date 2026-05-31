#!/usr/bin/env bash
# linux-setup — Claude Code PreToolUse guardrail hook.
# Reads the hook JSON on stdin; denies a tool call whose command matches a
# catastrophic-shell-command pattern. jq does the JSON in/out; the rules
# live in a sibling pure script so they are unit-testable.
set -eu

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=guardrail-rules.sh
. "$here/guardrail-rules.sh"

if ! command -v jq >/dev/null 2>&1; then
    # jq missing means the hook can't parse the payload at all. Pass through
    # silently rather than blocking every command.
    exit 0
fi

raw="$(cat || true)"
if [ -z "$raw" ]; then exit 0; fi

cmd="$(printf '%s' "$raw" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
if [ -z "$cmd" ]; then exit 0; fi

if [ "$(is_dangerous_command "$cmd")" = '1' ]; then
    jq -nc '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked by the linux-setup guardrail: the command matches a destructive pattern (recursive delete of root/home, raw-device write, fork bomb, or wipe operation)."
      }
    }'
fi
exit 0
