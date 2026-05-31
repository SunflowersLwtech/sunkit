# searchpo Agent Runtime

Codex and Claude Code use the same project skills, slash commands, and agent-team definitions in this repo.

## Skill Source Of Truth

Bridge metadata lives at `tools/skill-bridge-map.json`.

Long-lived skill logic lives under `skills/`:

- `skills/RESOLVER.md`: routes user requests to the right Searchpo skill.
- `skills/_AGENT_README.md`: explains the local skill directory contract.
- `skills/searchpo-main-agent/`: orchestrates source selection, task-plan state, release gates, and final publish decisions.
- `skills/searchpo-research-agent/`: runs AnySearch enrichment, FactBank/TopicBrief generation, and strengthened cross-check.
- `skills/searchpo-impl-agent/`: runs scripts, Remotion commands, Gemini audit, and Douyin publish/check commands.
- `skills/remotion-best-practices/`: guides edits to the Remotion video composition and render path.
- `skills/searchpo-plugin-check/`: validates Claude/Codex bridge metadata, skill/command/agent metadata, resolver deps, and bridge sync.

Slash command source lives under `commands/`:

- `commands/searchpo-full-flow.md`: shared Claude Code/Codex `/searchpo-full-flow` entrypoint.

Agent-team source lives under `agents/`:

- `agents/searchpo-main-agent.md`: team lead; owns task assignment, release gates, and publish decisions.
- `agents/searchpo-research-agent.md`: teammate; owns AnySearch enrichment, FactBank, TopicBrief, and source cross-check evidence.
- `agents/searchpo-impl-agent.md`: teammate; owns scripts, DeepSeek provider polish, Remotion, Gemini audit, and Douyin check/upload execution.

Generated bridges live outside the source of truth:

- `.claude/skills/`: Claude Code project skill mirror.
- `.claude/commands/`: Claude Code project slash-command mirror.
- `.claude/agents/`: Claude Code project subagent mirror.
- `.codex/skills/`: Codex project skill mirror for local inspection.
- `.codex/commands/`: Codex project slash-command mirror.
- `.codex/agents/`: Codex project agent TOML mirror.
- `/Users/sunfl/.codex/skills/searchpo-*`: Codex user-level symlinks installed by `npm run skills:sync:codex`.
- `/Users/sunfl/.codex/agents/searchpo-*.toml`: Codex user-level agent definitions installed by `npm run skills:sync:codex`.

When a task matches a Searchpo skill but the skill is not listed in the active Codex skill registry for the current session, read `skills/RESOLVER.md`, open the matching `skills/*/SKILL.md` file manually, and follow it.

## Operating Rules

- The main agent owns task-plan state, release gate checks, and final publish decision evidence.
- When an agent-team runtime is available, the main agent assigns research tasks to the research agent and execution tasks to the implementation agent.
- The research agent runs AnySearch from `vendor/anysearch-skill` and must produce `anysearch_research.json`, `fact_bank.json`, `research_brief.json`, and enriched cross-check artifacts before copy generation.
- The implementation agent runs scripts, DeepSeek, Remotion, Gemini audit, and Douyin commands; do not invent provider output or hand-edit runtime artifacts.
- Every automatic or operator-supplied subject must fetch canonical URL detail, collect at least two independent supplemental AnySearch extracts, and pass `cross_check_review.json` before copy generation. Use `SEARCHPO_LINK` for direct links and `SEARCHPO_TOPIC_URL` for topic runs.
- Full-service run trace is `topic_brief.json -> fact_bank.json -> script.json -> scene_plan.json -> video_spec.json -> render_payload.json -> delivery_package.json`; `research_brief.json` is a compatibility view of `topic_brief.json`.
- Video layout is storyboard-driven: provider mode may author bounded scene graphs, contract mode synthesizes the default statement/context/card/cta storyboard, `video_spec.json` is the renderer-neutral contract, and `cards` remains only a compatibility field.
- Board truth is `runtime/artifacts/YYYY-MM-DD/<run_id>/harness_board.sqlite3`; final release truth is `run_final.json` plus `artifact_manifest.json`. `agent_run.json` is only the harness loop summary.
- Default publish is Douyin through `runtime/social-auto-upload`; live upload requires explicit `SEARCHPO_DOUYIN_LIVE=1`, the user must request live publishing for the current run, and `submitted` does not count as success without remote identity verification.
- Do not use mock audio, silent media, placeholder provider output, skipped visual checks, or upload-path fallbacks to make a run pass.
- `.env` contains secrets. Do not print secret values.

## Provider Stack

| Role | Model | Script |
| --- | --- | --- |
| Research | AnySearch vendored CLI | `vendor/anysearch-skill/scripts/anysearch_cli.py` |
| Copy polish | DeepSeek V4 Pro (`deepseek-v4-pro`) | `scripts/deepseek_polish.py` |
| Content scoring | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/content_scorer.py` |
| Text-to-speech | Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) | `scripts/gemini_tts.py` |
| Video audit | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/gemini_visual_audit.py` |
| Video render | Remotion 4.0 (1080x1920, CRF 18, dynamic captions, storyboard scenes) | `src/Composition.tsx` |
| Publish | social-auto-upload | `scripts/douyin_upload_check.sh` |

## Commands

Safe default flow:

```bash
npm run e2e
```

Provider, Lambda, and live flows are explicit:

```bash
npm run e2e:provider
SEARCHPO_LINK="https://github.com/owner/repo" npm run e2e:link
npm run e2e:lambda
npm run e2e:live
```

Resume from failure:

```bash
python3 agent_harness/run_agent_loop.py --mode provider --resume-from N
```

Sync skill/command/agent bridges after editing `skills/`, `commands/`, or `agents/`:

```bash
npm run skills:sync
npm run agent-plugin:check
npm run skills:check
```
