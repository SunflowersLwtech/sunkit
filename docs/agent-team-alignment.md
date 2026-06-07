# Searchpo Agent Team Alignment

This repo supports Claude Code and Codex directly. It does not maintain an OpenClaw manifest.

## Runtime Model

Searchpo has exactly three project agents:

| Agent | Runtime Role | Owns |
| --- | --- | --- |
| `searchpo-main-agent` | Team lead / orchestrator | Task assignment, release gates, final publish decision |
| `searchpo-research-agent` | Research teammate | AnySearch enrichment, DeepWiki repo context, FactBank, TopicBrief, source cross-check evidence |
| `searchpo-impl-agent` | Implementation teammate | Scripts, DeepSeek, Remotion, Gemini, Douyin check/upload execution |

AnySearch, DeepWiki MCP repo context, and source evidence belong to `searchpo-research-agent`. The main agent may verify `fact_bank.json`, `research_brief.json`, and `cross_check_review.json`, but it should not claim the research execution role. AnySearch search/extract must start before DeepWiki can be treated as useful support; DeepWiki-only notes are not a completed research task.
DeepSeek belongs to `searchpo-impl-agent`. The main agent may verify `deepseek_polish.json`, but it should not claim the provider execution role.

The team order is sequential, not parallel: research agent first, main-agent research barrier verification second, implementation agent third, main-agent release verification last. The main agent does not run implementation commands when `searchpo-impl-agent` is available.

Project MCP config lives in `.mcp.json`; DeepWiki is a supporting repo-intelligence surface and does not replace canonical URL/API/README evidence or the independent-source cross-check. Redacted credential/capability routing lives in `config/agent_capabilities.json` and is inspected through `scripts/agent_capabilities.py`.

## Claude Code Alignment

Claude has two related but different mechanisms:

- Custom subagents are reusable role definitions in `.claude/agents/*.md` or `~/.claude/agents/*.md`. They use Markdown plus YAML frontmatter with `name`, `description`, and optional `tools`.
- Agent teams are runtime sessions. A team lead creates teammates, assigns or lets them claim tasks, and uses a shared task list plus mailbox. Claude stores generated runtime state under `~/.claude/teams/{team-name}/` and `~/.claude/tasks/{team-name}/`; do not pre-author that state in this repo.

Searchpo therefore stores reusable roles in `agents/*.md` and syncs them to `.claude/agents/*.md`. The main agent source grants `Agent(searchpo-research-agent)` and `Agent(searchpo-impl-agent)` so Claude can delegate research and execution to the right teammates when an agent-team or subagent runtime is available.

## Codex Alignment

Codex custom agents are standalone TOML files in `.codex/agents/*.toml` for project scope or `~/.codex/agents/*.toml` for user scope. Each file must include:

- `name`
- `description`
- `developer_instructions`

Searchpo generates Codex TOML from the same `agents/*.md` source. The generated files are mirrors, not source:

- `.codex/agents/searchpo-main-agent.toml`
- `.codex/agents/searchpo-research-agent.toml`
- `.codex/agents/searchpo-impl-agent.toml`
- `~/.codex/agents/searchpo-main-agent.toml`
- `~/.codex/agents/searchpo-research-agent.toml`
- `~/.codex/agents/searchpo-impl-agent.toml`

Codex only spawns subagents when explicitly asked. The Searchpo full-flow skill and slash command must explicitly ask for the team shape before provider/live execution:

```text
Use the searchpo-main-agent as lead. Do not run research and implementation in parallel. First spawn or assign only searchpo-research-agent for AnySearch-first source discovery/extraction, GitHub API/README evidence, FactBank/TopicBrief, cross-check tasks, and only supporting DeepWiki repo context when useful. Wait until the main agent verifies cross_check_review.status == pass and research_sufficient == true, then spawn or assign searchpo-impl-agent for provider, render, audit, and Douyin tasks. The main agent must not run implementation commands itself; it verifies artifacts and makes the final release decision.
```

Do not count `main_task_plan.json` owner labels alone as proof that Codex actually spawned teammates. If the current Codex host does not expose subagent tools, the run may proceed as a manual fallback with the same ownership split, but the final report must say `manual fallback`.

The repo runtime now exposes a phase seam for real host-side delegation. A spawned team run records proof in `agent_run.json.delegation`; `spawned_subagents` requires a host subagent/thread id, while the synchronous wrapper remains `single_harness` unless explicitly marked `manual_fallback`.

```bash
python3 agent_harness/run_agent_loop.py --topic "topic" --mode provider --stop-after research_enrichment --delegation-mode spawned_subagents --delegation-agent searchpo-research-agent --delegation-proof "<host-subagent-id>"
python3 agent_harness/run_agent_loop.py "<run_dir>" --mode provider --resume-from 4 --stop-after main_task_plan --delegation-mode spawned_subagents --delegation-agent searchpo-main-agent --delegation-proof "<host-subagent-id>"
python3 agent_harness/run_agent_loop.py "<run_dir>" --mode provider --resume-from 5 --delegation-mode spawned_subagents --delegation-agent searchpo-impl-agent --delegation-proof "<host-subagent-id>"
```

## Source And Sync Contract

Source files:

- `agents/searchpo-main-agent.md`
- `agents/searchpo-research-agent.md`
- `agents/searchpo-impl-agent.md`
- `.mcp.json`
- `config/agent_capabilities.json`
- `scripts/agent_capabilities.py`
- `skills/searchpo-agent-capabilities/SKILL.md`
- `skills/searchpo-deepwiki-research/SKILL.md`
- `tools/skill-bridge-map.json`

Generated files:

- `.claude/agents/*.md`
- `.codex/agents/*.toml`
- `~/.codex/agents/searchpo-*.toml`

Validation:

```bash
PATH="/opt/homebrew/bin:$PATH" npm run skills:sync
PATH="/opt/homebrew/bin:$PATH" npm run agent-plugin:check
PATH="/opt/homebrew/bin:$PATH" npm run skills:check
PATH="/opt/homebrew/bin:$PATH" npm run ci:static
```

`tools/skill-bridge-map.json` records the intended three-agent ownership model, but it is not a Claude runtime team config. Claude team config is generated by Claude Code at runtime.
