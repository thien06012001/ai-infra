# `.claude/` — project-scope Claude Code config (the only scope)

Everything here is active when this repo is the open project in Claude Code.
Nothing is installed to `~/.claude`; ai-infra never mutates your global setup.

- **`settings.json`** — the full project config: every hook (KB lifecycle +
  guardrail / pre-bash-guard / audit / notify / post-fetch-injection-scan / rtk
  passthrough), the statusline, `skipDangerousModePermissionPrompt`, and the
  enabled plugins + marketplaces. All hook paths are `$CLAUDE_PROJECT_DIR`-relative.
- **`hooks/`** — the shell guard/utility hooks referenced above: `guardrail`
  (+ `guardrail-rules`), `pre-bash-guard`, `audit`, `notify`, `statusline`
  (+ `statusline-format`), `post-fetch-injection-scan`. (The PKB lifecycle hooks
  live in the repo-root `hooks/`.)
- **`skills/`** — `best-practices`, `find-skills`.
- **`commands/kb-search.md`** — the `/kb-search` slash command.

External CLIs (`graphify`, `rtk`) are not vendored here — `../setup.sh` installs
them to the latest version.
