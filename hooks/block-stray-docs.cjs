#!/usr/bin/env node
'use strict';
/**
 * PreToolUse hook — blocks Write / Edit / MultiEdit calls that would create
 * ad-hoc Markdown / plain-text files outside the monorepo's structured
 * documentation surfaces.
 *
 * Why this hook exists:
 *   CLAUDE.md (project root) states "NEVER create documentation files (*.md)
 *   or README files unless explicitly requested by the User." Without
 *   enforcement, that rule degrades into best-effort and is silently violated
 *   by the agent during long sessions. This hook converts the rule into a hard
 *   stop.
 *
 * How it decides whether to block:
 *   1. Only inspect ``.md`` and ``.txt`` files. Other writes pass through.
 *   2. Only inspect ``Write`` and ``MultiEdit`` create-style ops, plus the rare
 *      ``Edit`` that targets a path that does not yet exist (``Edit`` typically
 *      modifies existing files, which is fine).
 *   3. Paths inside the structured documentation surfaces are always allowed:
 *        - ``knowledge/``, ``daily/``, ``reports/`` (PKB layers)
 *        - ``docs/`` (per-project documentation)
 *        - ``.claude/`` (skills, agents, commands)
 *        - ``.github/`` (issue/PR templates)
 *        - ``.githooks/`` (hook scripts often ship a README)
 *        - ``commands/``, ``skills/``, ``agents/`` (matching ECC's "structured
 *          surfaces" denylist origin)
 *   4. Canonical top-level docs are always allowed by basename:
 *      README.md, CLAUDE.md, AGENTS.md, CONTRIBUTING.md, CHANGELOG.md, LICENSE,
 *      SECURITY.md, CODE_OF_CONDUCT.md, SKILL.md, NOTES intentionally NOT here.
 *   5. Otherwise: block, with a message naming the specific path and the
 *      structured directory the agent should use instead.
 *
 * Exit codes:
 *   0 — allowed, hook passes through.
 *   2 — hard block; reason written to stderr is shown to the model.
 *
 * Borrowed from ECC's ``doc-file-warning.js`` pattern, but inverted from
 * advisory to blocking, and tuned to match the user's specific structured
 * surfaces (PKB + per-project docs).
 */

const fs = require('fs');
const path = require('path');

require(path.join(__dirname, '_profile_gate.cjs')).checkEnabled(
  'block-stray-docs',
  'standard'
);

/** Filenames that are always legitimate at any depth. */
const ALLOWED_BASENAMES = new Set([
  'README.md',
  'CLAUDE.md',
  'AGENTS.md',
  'CONTRIBUTING.md',
  'CHANGELOG.md',
  'LICENSE',
  'LICENSE.md',
  'LICENSE.txt',
  'SECURITY.md',
  'CODE_OF_CONDUCT.md',
  'SKILL.md',
  'GEMINI.md',
  'program.md',
]);

/**
 * Top-level directories where new docs are intentional and welcome.
 * The check is anchored to a forward-slash separator so partial prefix matches
 * (e.g. ``docs-old/``) do not slip through.
 */
const ALLOWED_DIR_PREFIXES = [
  'knowledge/',
  'daily/',
  'reports/',
  'docs/',
  '.claude/',
  '.github/',
  '.githooks/',
  'commands/',
  'skills/',
  'agents/',
  // Per-project doc surfaces: anything matching projects/<name>/docs/ or
  // projects/<name>/README.md is handled below in isAllowedPath.
];

/**
 * Read the hook payload from stdin without crashing on bad JSON. A malformed
 * payload returns ``{}`` so the hook errs on the permissive side rather than
 * mass-blocking the model.
 *
 * @returns {object} Parsed JSON payload, or empty object on any parse failure.
 */
function readInput() {
  try {
    return JSON.parse(fs.readFileSync(0, 'utf-8'));
  } catch {
    return {};
  }
}

/**
 * Decide whether ``filePath`` (already normalized to forward slashes) is one
 * of the allowed documentation locations.
 *
 * @param {string} filePath - Repo-relative or absolute path with ``/`` separators.
 * @returns {boolean} True when the path is allowed and the hook should pass.
 */
function isAllowedPath(filePath) {
  // Normalize away absolute prefixes to repo-relative form when possible so
  // both Windows and POSIX paths land in the same comparison space.
  const repoRoot = path.resolve(__dirname, '..').replace(/\\/g, '/');
  let rel = filePath;
  if (rel.startsWith(repoRoot + '/')) {
    rel = rel.slice(repoRoot.length + 1);
  }

  const base = path.posix.basename(rel);

  if (ALLOWED_BASENAMES.has(base)) {
    return true;
  }

  for (const prefix of ALLOWED_DIR_PREFIXES) {
    if (rel.startsWith(prefix)) {
      return true;
    }
  }

  // Per-project docs and READMEs: projects/<name>/(docs/|README.md|CLAUDE.md|*.md)
  // Project subdirs are allowed to host their own docs; only block stray .md
  // files at the project root level that are not README/CLAUDE/AGENTS.
  const projectMatch = rel.match(/^projects\/[^/]+\/(.+)$/);
  if (projectMatch) {
    const remainder = projectMatch[1];
    if (remainder.startsWith('docs/')) return true;
    // Inside any nested directory under a project, .md files are fine
    // (component docs, route docs, etc.). Only flag files at the project root.
    if (remainder.includes('/')) return true;
  }

  return false;
}

/**
 * Test whether the tool call would create a NEW file (vs. editing an existing
 * one). ``Write`` and ``MultiEdit`` always create-or-overwrite; ``Edit`` only
 * counts as "create" if the target does not already exist on disk.
 *
 * @param {string} toolName - Name of the Claude Code tool being invoked.
 * @param {string} filePath - Resolved file path for the call.
 * @returns {boolean} True when the call should be subject to the doc guard.
 */
function isCreation(toolName, filePath) {
  if (toolName === 'Write' || toolName === 'MultiEdit') return true;
  if (toolName === 'Edit') {
    try {
      return !fs.existsSync(filePath);
    } catch {
      return false;
    }
  }
  return false;
}

const event = readInput();
const toolName = event?.tool_name || '';
const rawPath = (event?.tool_input?.file_path || '').replace(/\\/g, '/');

if (!rawPath) {
  process.exit(0);
}

// Only .md and .txt are documentation surfaces; everything else passes.
const isDoc = /\.(md|txt)$/i.test(path.posix.basename(rawPath));
if (!isDoc) {
  process.exit(0);
}

if (!isCreation(toolName, rawPath)) {
  process.exit(0);
}

if (isAllowedPath(rawPath)) {
  process.exit(0);
}

process.stderr.write(
  `Blocked: creating "${rawPath}" violates CLAUDE.md "never create documentation files unless explicitly requested".\n` +
    `Use one of the structured surfaces instead:\n` +
    `  - knowledge/   PKB articles (narrative layer)\n` +
    `  - daily/       PKB daily logs\n` +
    `  - docs/        repo-wide docs\n` +
    `  - projects/<name>/docs/   per-project docs\n` +
    `  - .claude/skills/<name>/SKILL.md   skill definitions\n` +
    `If the user explicitly asked for this file, set DISABLED_HOOKS=block-stray-docs in the shell.\n`
);
process.exit(2);
