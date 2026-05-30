# searchpo Agent Runtime

Codex, Claude Code, and plugin-style agent hosts use the same project skills in this repo.

## Skill Source Of Truth

Installable bundle metadata lives at `openclaw.plugin.json`.

Long-lived skill logic lives under `skills/`:

- `skills/RESOLVER.md`: routes user requests to the right Searchpo skill.
- `skills/_AGENT_README.md`: explains the local skill directory contract.
- `skills/searchpo-main-agent/`: orchestrates source selection, task-plan state, release gates, and final publish decisions.
- `skills/searchpo-impl-agent/`: runs scripts, Remotion commands, Gemini audit, and Douyin publish/check commands.
- `skills/remotion-best-practices/`: guides edits to the Remotion video composition and render path.
- `skills/searchpo-plugin-check/`: validates plugin manifest, skill metadata, resolver deps, and bridge sync.

Generated bridges live outside the source of truth:

- `.claude/skills/`: Claude Code project skill mirror.
- `.codex/skills/`: Codex project skill mirror for local inspection.
- `/Users/sunfl/.codex/skills/searchpo-*`: Codex user-level symlinks installed by `npm run skills:sync:codex`.

When a task matches a Searchpo skill but the skill is not listed in the active Codex skill registry for the current session, read `skills/RESOLVER.md`, open the matching `skills/*/SKILL.md` file manually, and follow it.

## Operating Rules

- The main agent owns task-plan state, release gate checks, and final publish decision evidence.
- The implementation agent runs scripts and Remotion commands; do not invent provider output or hand-edit runtime artifacts.
- Board truth is `runtime/artifacts/YYYY-MM-DD/<run_id>/harness_board.sqlite3` plus `agent_run.json`.
- Default publish is Douyin through `runtime/social-auto-upload`; live upload requires explicit `SEARCHPO_DOUYIN_LIVE=1` and the user must request live publishing for the current run.
- `.env` contains secrets. Do not print secret values.

## Provider Stack

| Role | Model | Script |
| --- | --- | --- |
| Copy polish | DeepSeek V4 Pro (`deepseek-v4-pro`) | `scripts/deepseek_polish.py` |
| Content scoring | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/content_scorer.py` |
| Text-to-speech | Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) | `scripts/gemini_tts.py` |
| Video audit | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/gemini_visual_audit.py` |
| Video render | Remotion 4.0 (1080x1920, CRF 18, dynamic captions) | `src/Composition.tsx` |
| Publish | social-auto-upload | `scripts/douyin_upload_check.sh` |

## Commands

Safe default flow:

```bash
npm run e2e
```

Provider, Lambda, and live flows are explicit:

```bash
npm run e2e:provider
npm run e2e:lambda
npm run e2e:live
```

Resume from failure:

```bash
python3 agent_harness/run_agent_loop.py --mode provider --resume-from N
```

Sync skill bridges after editing `skills/`:

```bash
npm run skills:sync
npm run agent-plugin:check
npm run skills:check
```
