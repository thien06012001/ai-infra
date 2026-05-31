#!/usr/bin/env bash
# linux-setup — Claude Code statusline. Reads payload JSON on stdin, resolves
# the current-dir git branch, prints one status line via format_status_line.
set -eu

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=statusline-format.sh
. "$here/statusline-format.sh"

if ! command -v jq >/dev/null 2>&1; then
    echo 'Claude'
    exit 0
fi

raw="$(cat || true)"
if [ -z "$raw" ]; then echo 'Claude'; exit 0; fi

dir="$(printf '%s' "$raw" | jq -r '.workspace.current_dir // .cwd // ""')"
branch=''
if [ -n "$dir" ] && [ -d "$dir" ]; then
    branch="$(git -C "$dir" branch --show-current 2>/dev/null | head -n1 || true)"
fi

format_status_line "$raw" "$branch"
