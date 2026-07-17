# searchpo Agent Runtime

Use the project-level Searchpo skills when operating this repo. Durable skill logic lives in `skills/`; `.claude/skills/` is a generated Claude Code bridge kept in sync with `npm run skills:sync`.

## Architecture

- Main agent owns task-plan state, release gates, and final publish decision evidence.
- Implementation agent runs scripts and Remotion commands; do not invent provider output or hand-edit runtime artifacts.
- Board truth is `runtime/artifacts/YYYY-MM-DD/<run_id>/harness_board.sqlite3` plus `agent_run.json`.
- Default publish is Douyin through `runtime/social-auto-upload`; live upload requires explicit `SEARCHPO_DOUYIN_LIVE=1`.
- `.env` contains secrets. Do not print secret values.

## Provider Stack

| Role | Model | Script |
|------|-------|--------|
| 口播润色 | DeepSeek V4 Pro (`deepseek-v4-pro`) | `scripts/deepseek_polish.py` |
| 内容评分 | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/content_scorer.py` |
| 语音合成 | Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) | `scripts/gemini_tts.py` |
| 视频审核 | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/gemini_visual_audit.py` |
| 视频合成 | Remotion 4.0 (1080×1920, CRF 18, 动态字幕) | `src/Composition.tsx` |
| 发布 | social-auto-upload | `scripts/douyin_upload_check.sh` |

## Commands

Safe default flow:

```bash
npm run e2e
```

Provider/Lambda/live flows are explicit:

```bash
npm run e2e:provider
npm run e2e:lambda
npm run e2e:live
```

Resume from failure:

```bash
python3 agent_harness/run_agent_loop.py --mode provider --resume-from N
```
