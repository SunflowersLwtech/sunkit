#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(toolDir, '..');
const bridgeMapPath = path.join(toolDir, 'skill-bridge-map.json');

function fail(message) {
  console.error(`agent bridge check: ${message}`);
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

function normalizePath(input) {
  return input.replace(/^\.?\//, '').replace(/\/$/, '');
}

function sourcePath(root, ...segments) {
  return path.join(repoRoot, normalizePath(root), ...segments);
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

function assertFrontmatterName(frontmatter, filePath, name) {
  const pattern = new RegExp(`(^|\\n)name:\\s*${escapeRegex(name)}\\s*(\\n|$)`);
  if (!pattern.test(frontmatter)) {
    fail(`Frontmatter name does not match ${name}: ${path.relative(repoRoot, filePath)}`);
  }
}

function assertUniqueNames(label, entries) {
  const names = entries.map((entry) => entry.name);
  const seen = new Set();
  const duplicates = new Set();
  for (const name of names) {
    if (seen.has(name)) {
      duplicates.add(name);
    }
    seen.add(name);
  }
  if (duplicates.size) {
    fail(`${label} contains duplicate names: ${[...duplicates].join(', ')}`);
  }
}

function assertValidEntryName(label, entry) {
  if (!entry.name || !/^[a-z0-9][a-z0-9-]*$/.test(entry.name)) {
    fail(`Invalid ${label} name: ${entry.name ?? '<missing>'}`);
  }
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

function assertSkill(entry, map) {
  assertValidEntryName('skill', entry);
  const skillFile = sourcePath(map.sourceRoot, entry.name, 'SKILL.md');
  if (!fs.existsSync(skillFile)) {
    fail(`Missing source skill file: ${path.relative(repoRoot, skillFile)}`);
  }
  const frontmatter = frontmatterFor(readText(skillFile), skillFile);
  assertFrontmatterName(frontmatter, skillFile, entry.name);
  for (const field of ['description', 'triggers', 'tools', 'mutating']) {
    assertFrontmatterField(frontmatter, skillFile, field);
  }
}

function assertSharedDep(relativePath, map) {
  const depPath = sourcePath(map.sourceRoot, relativePath);
  if (!fs.existsSync(depPath)) {
    fail(`Missing shared dependency: ${path.relative(repoRoot, depPath)}`);
  }
}

function assertCommand(entry, map) {
  assertValidEntryName('command', entry);
  const commandRoot = map.commandSourceRoot ?? 'commands';
  const commandFile = sourcePath(commandRoot, `${entry.name}.md`);
  if (!fs.existsSync(commandFile)) {
    fail(`Missing source command file: ${path.relative(repoRoot, commandFile)}`);
  }
  const commandText = readText(commandFile);
  if (!commandText.trim()) {
    fail(`Empty source command file: ${path.relative(repoRoot, commandFile)}`);
  }
  const frontmatter = frontmatterFor(commandText, commandFile);
  assertFrontmatterField(frontmatter, commandFile, 'description');
  for (const heading of ['Preflight', 'Verification']) {
    const pattern = new RegExp(`^#{2,3}\\s+${escapeRegex(heading)}\\s*$`, 'im');
    if (!pattern.test(commandText)) {
      fail(`Missing ${heading} section in source command file: ${path.relative(repoRoot, commandFile)}`);
    }
  }
}

function assertAgent(entry, map) {
  assertValidEntryName('agent', entry);
  const agentRoot = map.agentSourceRoot ?? 'agents';
  const agentFile = sourcePath(agentRoot, `${entry.name}.md`);
  if (!fs.existsSync(agentFile)) {
    fail(`Missing source agent file: ${path.relative(repoRoot, agentFile)}`);
  }
  const text = readText(agentFile);
  const frontmatter = frontmatterFor(text, agentFile);
  assertFrontmatterName(frontmatter, agentFile, entry.name);
  for (const field of ['description', 'tools']) {
    assertFrontmatterField(frontmatter, agentFile, field);
  }
  if (!text.replace(/^---\n[\s\S]*?\n---/, '').trim()) {
    fail(`Empty source agent body: ${path.relative(repoRoot, agentFile)}`);
  }
}

function assertAgentTeam(map) {
  const entries = map.agents ?? [];
  const names = entries.map((entry) => entry.name);
  const team = map.agentTeam;
  if (!team) {
    fail('tools/skill-bridge-map.json must include agentTeam');
  }
  if (!team.lead) {
    fail('agentTeam.lead is required');
  }
  if (!Array.isArray(team.teammates)) {
    fail('agentTeam.teammates must be an array');
  }
  assertSameSet('agentTeam members vs agents', [team.lead, ...team.teammates], names);
  if (team.lead !== 'searchpo-main-agent') {
    fail('agentTeam.lead must be searchpo-main-agent');
  }
  if (!team.teammates.includes('searchpo-impl-agent')) {
    fail('agentTeam.teammates must include searchpo-impl-agent');
  }
  if (!team.teammates.includes('searchpo-research-agent')) {
    fail('agentTeam.teammates must include searchpo-research-agent');
  }
  if (team.researchOwnership?.anysearch !== 'searchpo-research-agent') {
    fail('agentTeam.researchOwnership.anysearch must be searchpo-research-agent');
  }
  if (team.researchOwnership?.evidence !== 'searchpo-research-agent') {
    fail('agentTeam.researchOwnership.evidence must be searchpo-research-agent');
  }
  if (team.providerOwnership?.deepseek !== 'searchpo-impl-agent') {
    fail('agentTeam.providerOwnership.deepseek must be searchpo-impl-agent');
  }
}

function assertGeneratedCodexAgent(root, entry, agent) {
  const destination = sourcePath(root, `${entry.name}.toml`);
  if (!fs.existsSync(destination)) {
    return;
  }
  const generatedText = readText(destination);
  if (!new RegExp(`(^|\\n)name\\s*=\\s*"${escapeRegex(entry.name)}"(\\n|$)`).test(generatedText)) {
    fail(`Generated Codex agent must include name: ${path.relative(repoRoot, destination)}`);
  }
  if (!generatedText.includes('developer_instructions = ')) {
    fail(`Generated Codex agent must include developer_instructions: ${path.relative(repoRoot, destination)}`);
  }
  if (!generatedText.includes(agent.description)) {
    fail(`Generated Codex agent description drifted from source: ${path.relative(repoRoot, destination)}`);
  }
}

const bridgeMap = readJson(bridgeMapPath);

if (!Array.isArray(bridgeMap.skills) || bridgeMap.skills.length === 0) {
  fail('tools/skill-bridge-map.json must list skills');
}
if (!Array.isArray(bridgeMap.sharedDeps)) {
  fail('tools/skill-bridge-map.json must list sharedDeps');
}
if (!Array.isArray(bridgeMap.commands)) {
  fail('tools/skill-bridge-map.json must list commands');
}
if (!Array.isArray(bridgeMap.agents) || bridgeMap.agents.length !== 3) {
  fail('tools/skill-bridge-map.json must list exactly three agents');
}

assertUniqueNames('skills', bridgeMap.skills);
assertUniqueNames('commands', bridgeMap.commands);
assertUniqueNames('agents', bridgeMap.agents);

for (const entry of bridgeMap.skills) {
  assertSkill(entry, bridgeMap);
}
for (const sharedDep of bridgeMap.sharedDeps) {
  assertSharedDep(sharedDep, bridgeMap);
}
for (const entry of bridgeMap.commands) {
  assertCommand(entry, bridgeMap);
}
for (const entry of bridgeMap.agents) {
  assertAgent(entry, bridgeMap);
}
assertAgentTeam(bridgeMap);

for (const entry of bridgeMap.agents) {
  const agentRoot = bridgeMap.agentSourceRoot ?? 'agents';
  const agentFile = sourcePath(agentRoot, `${entry.name}.md`);
  const text = readText(agentFile);
  const frontmatter = frontmatterFor(text, agentFile);
  assertGeneratedCodexAgent(bridgeMap.codexProjectAgentRoot ?? '.codex/agents', entry, {
    description: /^description:\s*(.*)$/m.exec(frontmatter)?.[1]?.trim() ?? '',
  });
}

console.log(
  `agent bridge check passed: ${bridgeMap.skills.length} skills, ${bridgeMap.sharedDeps.length} shared deps, ${bridgeMap.commands.length} commands, ${bridgeMap.agents.length} agents`
);
