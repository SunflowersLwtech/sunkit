#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(toolDir, '..');
const pluginPath = path.join(repoRoot, 'openclaw.plugin.json');
const packagePath = path.join(repoRoot, 'package.json');
const bridgeMapPath = path.join(toolDir, 'skill-bridge-map.json');

function fail(message) {
  console.error(`agent plugin check: ${message}`);
  process.exit(1);
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    fail(`Invalid JSON in ${path.relative(repoRoot, filePath)}: ${error.message}`);
  }
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

function normalizeSkillPath(skillPath) {
  return skillPath.replace(/^\.?\//, '').replace(/\/$/, '');
}

function skillNameFromPath(skillPath) {
  return path.basename(normalizeSkillPath(skillPath));
}

function assertSameSet(label, actual, expected) {
  const actualSet = new Set(actual);
  const expectedSet = new Set(expected);
  const missing = [...expectedSet].filter((item) => !actualSet.has(item));
  const extra = [...actualSet].filter((item) => !expectedSet.has(item));
  if (missing.length || extra.length) {
    fail(`${label} mismatch. missing=[${missing.join(', ')}] extra=[${extra.join(', ')}]`);
  }
}

const plugin = readJson(pluginPath);
const pkg = readJson(packagePath);
const bridgeMap = readJson(bridgeMapPath);

if (plugin.name !== pkg.name) {
  fail(`Plugin name ${plugin.name} does not match package name ${pkg.name}`);
}
if (plugin.version !== pkg.version) {
  fail(`Plugin version ${plugin.version} does not match package version ${pkg.version}`);
}
if (plugin.family !== 'bundle-plugin') {
  fail('openclaw.plugin.json family must be bundle-plugin');
}
if (!Array.isArray(plugin.skills) || plugin.skills.length === 0) {
  fail('openclaw.plugin.json must list at least one skill');
}
if (!Array.isArray(plugin.shared_deps)) {
  fail('openclaw.plugin.json must include shared_deps');
}

const pluginSkillNames = plugin.skills.map(skillNameFromPath);
const bridgeSkillNames = (bridgeMap.skills ?? []).map((entry) => entry.name);
assertSameSet('plugin skills vs bridge map skills', pluginSkillNames, bridgeSkillNames);

const normalizedMapSharedDeps = (bridgeMap.sharedDeps ?? []).map((item) => normalizeSkillPath(path.join('skills', item)));
const normalizedPluginSharedDeps = plugin.shared_deps.map(normalizeSkillPath);
assertSameSet('plugin shared_deps vs bridge map sharedDeps', normalizedPluginSharedDeps, normalizedMapSharedDeps);

for (const skillPath of plugin.skills) {
  const normalized = normalizeSkillPath(skillPath);
  const absoluteSkillDir = path.join(repoRoot, normalized);
  const skillFile = path.join(absoluteSkillDir, 'SKILL.md');
  if (!fs.existsSync(skillFile)) {
    fail(`Missing plugin skill file: ${path.relative(repoRoot, skillFile)}`);
  }

  const name = skillNameFromPath(skillPath);
  const frontmatter = frontmatterFor(readText(skillFile), skillFile);
  if (!new RegExp(`(^|\\n)name:\\s*${escapeRegex(name)}\\s*(\\n|$)`).test(frontmatter)) {
    fail(`Frontmatter name does not match ${name}: ${path.relative(repoRoot, skillFile)}`);
  }
  for (const field of ['description', 'triggers', 'tools', 'mutating']) {
    assertFrontmatterField(frontmatter, skillFile, field);
  }
}

for (const sharedDep of plugin.shared_deps) {
  const absolutePath = path.join(repoRoot, normalizeSkillPath(sharedDep));
  if (!fs.existsSync(absolutePath)) {
    fail(`Missing plugin shared dependency: ${path.relative(repoRoot, absolutePath)}`);
  }
}

console.log(`agent plugin check passed: ${plugin.skills.length} skills, ${plugin.shared_deps.length} shared deps`);
