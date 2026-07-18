#!/usr/bin/env bash
# Pre-tool-use guard for the Bash tool.
# Receives JSON on stdin: { tool_name, tool_input: { command, description } }
# Exit 0 = allow.
# Exit 2 with reason on stderr = block (Claude sees the reason).
# Logs every invocation to ~/.claude/hooks/audit.log regardless.

set -euo pipefail
# shellcheck source=redact.sh
. "$(dirname "${BASH_SOURCE[0]}")/redact.sh"

LOG=~/.claude/hooks/audit.log

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)

ts=$(date -Iseconds)
audit_append "$LOG" "$ts BASH $CMD"

block() {
  echo "BLOCKED by pre-bash-guard.sh: $1" >&2
  audit_append "$LOG" "$ts BLOCK ($1): $CMD"
  exit 2
}

# Empty / non-string command — let Claude Code handle it
[ -z "$CMD" ] && exit 0

# --- Patterns that are nearly always destructive ---

# Recursive deletes against system or home roots
if echo "$CMD" | grep -Eq 'rm[[:space:]]+(-[a-zA-Z]*[rf][a-zA-Z]*[[:space:]]+|--recursive[[:space:]]+--force[[:space:]]+|-rf[[:space:]]+|-fr[[:space:]]+)(/|/\*|\$HOME|~|~/$|/etc|/usr|/var|/boot|/bin|/sbin|/lib|/opt)([[:space:]]|$)'; then
  block "rm -rf against a protected path"
fi

# Fork bomb
if echo "$CMD" | grep -qE ':\(\)[[:space:]]*\{[[:space:]]*:\|:'; then
  block "fork bomb pattern"
fi

# Disk wipes
if echo "$CMD" | grep -qE 'dd[[:space:]]+.*of=/dev/(sd[a-z]|nvme|hd[a-z]|vd[a-z])'; then
  block "dd writing to a raw block device"
fi
if echo "$CMD" | grep -qE 'mkfs(\.[a-z0-9]+)?[[:space:]]+/dev/'; then
  block "mkfs on a block device"
fi
if echo "$CMD" | grep -qE '(shred|wipe)[[:space:]]+.*/dev/'; then
  block "shred/wipe on a device"
fi

# curl | bash family
if echo "$CMD" | grep -qE '(curl|wget)[[:space:]]+[^|]*\|[[:space:]]*(bash|sh|zsh|fish)([[:space:]]|$)'; then
  block "remote-script-piped-to-shell pattern (curl|bash). Download to a file and review first."
fi

# Edits to /etc/passwd /etc/shadow
if echo "$CMD" | grep -qE '(tee|>|>>)[[:space:]]+/etc/(passwd|shadow|sudoers)'; then
  block "writing to a credential file"
fi

# Sensitive read/write on the SSH key itself
if echo "$CMD" | grep -qE '~/\.ssh/id_(ed25519|rsa|ecdsa)([^.]|$)' \
   && ! echo "$CMD" | grep -qE '^\s*(ls|stat|file|ssh-keygen[[:space:]]+-l)'; then
  block "operation touches ~/.ssh private key — manual review required"
fi
if echo "$CMD" | grep -qE 'cat[[:space:]]+~?/\.claude/\.credentials\.json|cat[[:space:]]+~?/\.config/gh/hosts\.yml'; then
  block "attempt to read Claude / gh credential file via cat"
fi

# Force-push to main/master/release
if echo "$CMD" | grep -qE 'git[[:space:]]+push[[:space:]]+.*(--force|--force-with-lease|[[:space:]]-f([[:space:]]|$))' \
   && echo "$CMD" | grep -qE '(main|master|release|prod|production)([[:space:]]|$)'; then
  block "force-push to a protected branch"
fi

# sudo userdel / passwd / chsh of root
if echo "$CMD" | grep -qE 'sudo[[:space:]]+(userdel|usermod[[:space:]]+--?L|passwd[[:space:]]+root|chpasswd)'; then
  block "user-management operation that could lock you out"
fi

# WSL teardown (would kill our environment)
if echo "$CMD" | grep -qE 'wsl(\.exe)?[[:space:]]+--(unregister|terminate|shutdown)'; then
  block "wsl unregister/terminate/shutdown — would lose state, do manually"
fi

# Default: allow
exit 0
