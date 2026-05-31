# Git hooks

Repository-tracked git hooks that enforce the project's commit-message
convention and run unit tests before push.

## One-time setup

From the repo root, point git at this directory:

```bash
git config core.hooksPath .githooks
```

On Unix-like systems (including Git Bash on Windows) the hook files must be
executable. If you cloned on Linux/macOS:

```bash
chmod +x .githooks/commit-msg .githooks/pre-push
```

On Windows, Git Bash runs the hooks through `bash` regardless of the executable
bit, so no `chmod` is needed.

> Branch naming is intentionally **not** enforced — each project that uses this
> setup can adopt its own branch convention.

## Conventions enforced

### Commit messages — `commit-msg`

```
[<TASK-ID>] <message content>
```

Example:

```
[TASK-5] scaffold the app
```

Exempt: merge commits, revert commits, and `fixup!` / `squash!` commits produced
by `git commit --fixup` / `--squash`.

### Unit tests — `pre-push`

Before pushing, the hook detects which projects have changed in the commits
being pushed and runs their unit tests. The hook ships as a no-op template —
adapt one block per project (see the commented example inside the hook file).
