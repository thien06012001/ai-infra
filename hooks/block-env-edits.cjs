#!/usr/bin/env node
/**
 * PreToolUse hook — blocks Edit/Write calls targeting .env files.
 *
 * Allows: .env.example, .env.local.example (template files are safe to edit)
 * Blocks: .env, .env.local, .env.production, etc. (real secret files)
 *
 * Exit 2 = hard block with reason shown to the model.
 */
'use strict';

const fs = require('fs');
const path = require('path');

require(path.join(__dirname, '_profile_gate.cjs')).checkEnabled(
  'block-env-edits',
  'minimal'
);

function readInput() {
  try {
    return JSON.parse(fs.readFileSync(0, 'utf-8'));
  } catch {
    return {};
  }
}

const event = readInput();
const filePath = (event?.tool_input?.file_path || '').replace(/\\/g, '/');

// Only check Edit and Write tool calls
const toolName = event?.tool_name || '';
if (toolName !== 'Edit' && toolName !== 'Write') {
  process.exit(0);
}

// Match .env files: .env, .env.local, .env.production, etc.
// Allow template files: .env.example, .env.local.example
const isEnvFile = /\.env(\.[^/]*)?$/.test(filePath);
const isTemplate = filePath.endsWith('.example');

if (isEnvFile && !isTemplate) {
  process.stderr.write(
    `Blocked: direct edit of "${filePath}" risks overwriting secrets.\n` +
      `Edit the corresponding .env.example template instead, or open the file manually.\n`
  );
  process.exit(2);
}

process.exit(0);
