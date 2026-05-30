#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(toolDir, '..');
const mapPath = path.join(toolDir, 'skill-bridge-map.json');
const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));

const args = process.argv.slice(2);
const command = args.find((arg) => !arg.startsWith('--')) ?? 'all';
const checkOnly = args.includes('--check') || command === 'check';
const projectOnly = args.includes('--project-only');

const allowedCommands = new Set(['all', 'claude', 'codex', 'check']);
if (!allowedCommands.has(command)) {
  fail(`Unknown command: ${command}. Use one of: ${[...allowedCommands].join(', ')}`);
}

function fail(message) {
  console.error(`skills sync: ${message}`);
  process.exit(1);
}

function expandRoot(input) {
  if (input === '~') {
    return os.homedir();
  }
  if (input.startsWith('~/')) {
    return path.join(os.homedir(), input.slice(2));
  }
  return path.resolve(repoRoot, input);
}

function skillPath(root, skillName) {
  return path.join(expandRoot(root), skillName);
}

function readText(filePath) {
  return fs.readFileSync(filePath, 'utf8');
}

function escapeRegex(input) {
  return input.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function frontmatterFor(text, filePath) {
  const match = /^---\n([\s\S]*?)\n---/.exec(text);
  if (!match) {
    fail(`Missing YAML frontmatter: ${path.relative(repoRoot, filePath)}`);
  }
  return match[1];
}

function assertFrontmatterField(frontmatter, filePath, field) {
  const pattern = new RegExp(`(^|\\n)${escapeRegex(field)}:`);
  if (!pattern.test(frontmatter)) {
    fail(`Missing frontmatter ${field}: ${path.relative(repoRoot, filePath)}`);
  }
}

function assertSkillSource(entry) {
  const source = skillPath(map.sourceRoot, entry.name);
  const skillFile = path.join(source, 'SKILL.md');
  if (!fs.existsSync(skillFile)) {
    fail(`Missing source skill file: ${path.relative(repoRoot, skillFile)}`);
  }
  const text = readText(skillFile);
  const frontmatter = frontmatterFor(text, skillFile);
  if (!new RegExp(`(^|\\n)name:\\s*${escapeRegex(entry.name)}\\s*(\\n|$)`).test(frontmatter)) {
    fail(`Frontmatter name does not match ${entry.name}: ${path.relative(repoRoot, skillFile)}`);
  }
  for (const field of ['description', 'triggers', 'tools', 'mutating']) {
    assertFrontmatterField(frontmatter, skillFile, field);
  }
  return source;
}

function removeDestination(destination) {
  if (!fs.existsSync(destination) && !fs.lstatSync(path.dirname(destination), {throwIfNoEntry: false})) {
    fs.mkdirSync(path.dirname(destination), {recursive: true});
    return;
  }
  fs.mkdirSync(path.dirname(destination), {recursive: true});
  if (fs.existsSync(destination) || fs.lstatSync(destination, {throwIfNoEntry: false})) {
    fs.rmSync(destination, {recursive: true, force: true});
  }
}

function copySkill(source, destination, label) {
  if (checkOnly) {
    const sourceSkill = path.join(source, 'SKILL.md');
    const destinationSkill = path.join(destination, 'SKILL.md');
    if (!fs.existsSync(destinationSkill)) {
      fail(`Missing ${label} bridge: ${destinationSkill}`);
    }
    if (readText(sourceSkill) !== readText(destinationSkill)) {
      fail(`Out-of-sync ${label} bridge: ${destinationSkill}`);
    }
    return;
  }

  removeDestination(destination);
  fs.cpSync(source, destination, {recursive: true});
  console.log(`synced ${label}: ${path.relative(repoRoot, destination)}`);
}

function copySharedDep(relativePath, root, label) {
  const source = path.join(expandRoot(map.sourceRoot), relativePath);
  const destination = path.join(expandRoot(root), relativePath);
  if (!fs.existsSync(source)) {
    fail(`Missing shared dependency: ${path.relative(repoRoot, source)}`);
  }

  if (checkOnly) {
    if (!fs.existsSync(destination)) {
      fail(`Missing ${label} shared dependency: ${destination}`);
    }
    if (readText(source) !== readText(destination)) {
      fail(`Out-of-sync ${label} shared dependency: ${destination}`);
    }
    return;
  }

  fs.mkdirSync(path.dirname(destination), {recursive: true});
  fs.cpSync(source, destination, {force: true});
  console.log(`synced ${label} shared dependency: ${path.relative(repoRoot, destination)}`);
}

function ensureSymlink(source, destination) {
  const parent = path.dirname(destination);
  if (checkOnly) {
    const stat = fs.lstatSync(destination, {throwIfNoEntry: false});
    if (!stat?.isSymbolicLink()) {
      fail(`Missing Codex user skill symlink: ${destination}`);
    }
    const target = fs.readlinkSync(destination);
    const resolvedTarget = path.resolve(parent, target);
    if (path.resolve(resolvedTarget) !== path.resolve(source)) {
      fail(`Codex user skill symlink points at ${resolvedTarget}, expected ${source}`);
    }
    return;
  }

  fs.mkdirSync(parent, {recursive: true});
  const stat = fs.lstatSync(destination, {throwIfNoEntry: false});
  if (stat?.isSymbolicLink()) {
    const target = fs.readlinkSync(destination);
    const resolvedTarget = path.resolve(parent, target);
    if (path.resolve(resolvedTarget) === path.resolve(source)) {
      console.log(`kept codex user link: ${destination}`);
      return;
    }
    fs.unlinkSync(destination);
  } else if (stat) {
    fail(`Refusing to replace non-symlink Codex user skill: ${destination}`);
  }

  fs.symlinkSync(source, destination, 'dir');
  console.log(`linked codex user skill: ${destination} -> ${source}`);
}

function syncClaude(entry, source) {
  copySkill(source, skillPath(map.claudeProjectRoot, entry.name), 'claude project skill');
}

function syncCodex(entry, source) {
  copySkill(source, skillPath(map.codexProjectRoot, entry.name), 'codex project skill');
  if (!projectOnly) {
    ensureSymlink(source, skillPath(map.codexUserRoot, entry.name));
  }
}

function syncSharedDeps(root, label) {
  for (const relativePath of map.sharedDeps ?? []) {
    copySharedDep(relativePath, root, label);
  }
}

for (const entry of map.skills) {
  const source = assertSkillSource(entry);
  if (command === 'all' || command === 'claude' || command === 'check') {
    syncClaude(entry, source);
  }
  if (command === 'all' || command === 'codex' || command === 'check') {
    syncCodex(entry, source);
  }
}

if (command === 'all' || command === 'claude' || command === 'check') {
  syncSharedDeps(map.claudeProjectRoot, 'claude project skill');
}
if (command === 'all' || command === 'codex' || command === 'check') {
  syncSharedDeps(map.codexProjectRoot, 'codex project skill');
}

console.log(checkOnly ? 'skills bridge check passed' : 'skills bridge sync complete');
