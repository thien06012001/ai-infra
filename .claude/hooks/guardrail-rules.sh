#!/usr/bin/env bash
# linux-setup — pure rules for the Claude Code PreToolUse guardrail.
# is_dangerous_command echoes "1" for a small heuristic denylist of catastrophic
# commands. It is a safety net, not a sandbox — it does not aim to be exhaustive.
#
# Rules are tuned for POSIX shells (bash / sh / zsh). Mirrors the PowerShell
# guardrail-rules.ps1 in spirit, replacing the Windows-specific patterns with
# their Unix analogues.

# Extended POSIX regex patterns (bash =~).
_DANGEROUS_PATTERNS=(
    # rm with a recursive flag targeting the filesystem ROOT or HOME ROOT
    # itself (not subdirectories — `rm -rf ~/projects/x` is allowed).
    'rm[[:space:]]+(-[^[:space:]]+[[:space:]]+)*-[^[:space:]]*r[^[:space:]]*[[:space:]]+(-[^[:space:]]+[[:space:]]+)*(/\*|/|~/\*|~|\$HOME/\*|\$HOME)([[:space:]]|$)'
    # `dd` writing to a raw block device under /dev/sd*, /dev/nvme*, /dev/hd*
    '\bdd[[:space:]]+[^|;&]*\bof=/dev/(sd|nvme|hd|mmcblk)'
    # mkfs.* targeting a real device
    '\bmkfs(\.[a-z0-9]+)?[[:space:]]+[^|;&]*/dev/(sd|nvme|hd|mmcblk)'
    # classic fork bomb
    ':\(\)[[:space:]]*\{[[:space:]]*:[[:space:]]*\|[[:space:]]*:[[:space:]]*&[[:space:]]*\}[[:space:]]*;[[:space:]]*:'
    # `chmod` / `chown` recursively on a root or home-root path
    '\b(chmod|chown)[[:space:]]+(-[^[:space:]]+[[:space:]]+)*-[^[:space:]]*R[^[:space:]]*[[:space:]]+(-[^[:space:]]+[[:space:]]+)*(/|~|\$HOME)([[:space:]]|$)'
    # `shred -fz` of a device or root path
    '\bshred[[:space:]]+[^|;&]*-[^[:space:]]*[fz][^[:space:]]*[[:space:]]+(/dev/|/|~|\$HOME)'
)

is_dangerous_command() {
    local cmd="$1" pattern
    for pattern in "${_DANGEROUS_PATTERNS[@]}"; do
        if [[ "$cmd" =~ $pattern ]]; then
            echo 1
            return 0
        fi
    done
    echo 0
}
