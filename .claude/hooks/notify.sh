#!/usr/bin/env bash
# linux-setup — Claude Code Stop/Notification hook. Shows a desktop notification
# via notify-send. Mirrors the Windows BurntToast hook. Fails silent — the
# notification is a nice-to-have, never a reason to block Claude.
#
# Usage: notify.sh --kind Done    (Stop hook)
#        notify.sh --kind Input   (Notification hook)
set -u

# Drain stdin so Claude Code's pipe does not block.
cat >/dev/null 2>&1 || true

kind='Done'
while [ $# -gt 0 ]; do
    case "$1" in
        --kind) kind="${2:-Done}"; shift ;;
        --kind=*) kind="${1#*=}" ;;
        *) ;;
    esac
    shift || true
done

if ! command -v notify-send >/dev/null 2>&1; then
    exit 0
fi

case "$kind" in
    Input) line='Needs your input' ;;
    *)     line='Finished' ;;
esac

notify-send 'Claude Code' "$line" 2>/dev/null || true
exit 0
