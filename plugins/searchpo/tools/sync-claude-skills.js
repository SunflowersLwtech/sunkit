#!/usr/bin/env node
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const result = spawnSync(
  process.execPath,
  [path.join(toolDir, 'sync-agent-skills.js'), 'claude', ...process.argv.slice(2)],
  {stdio: 'inherit'}
);

process.exit(result.status ?? 1);
