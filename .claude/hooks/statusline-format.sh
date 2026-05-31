#!/usr/bin/env bash
# linux-setup — pure statusline formatter. Reads the Claude Code payload from
# argument $1 (as JSON string), an optional git branch from $2, prints a single
# status line. Kept pure so it is unit-testable in isolation.

format_status_line() {
    local payload="$1" git_branch="${2:-}"
    local model dir leaf ctx cost line

    model="$(printf '%s' "$payload" | jq -r '.model.display_name // "Claude"')"
    dir="$(printf '%s' "$payload" | jq -r '.workspace.current_dir // .cwd // ""')"
    if [ -n "$dir" ]; then
        leaf="$(basename "$dir")"
    else
        leaf='?'
    fi
    ctx="$(printf '%s' "$payload" | jq -r '.context_window.used_percentage // empty')"
    cost="$(printf '%s' "$payload" | jq -r '.cost.total_cost_usd // empty')"

    line="[$model]  $leaf"
    [ -n "$git_branch" ] && line="$line  git:$git_branch"
    [ -n "$ctx" ]        && line="$line  ctx:${ctx}%"
    if [ -n "$cost" ]; then
        # Two-decimal dollar amount; printf rounds half-even, matching the PS version.
        line="$(printf '%s  $%.2f' "$line" "$cost")"
    fi
    printf '%s\n' "$line"
}
