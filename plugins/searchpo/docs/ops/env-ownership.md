# Environment Ownership

Secrets live in `.env` or the operator's shell, never in tracked files or CI logs. `scripts/check_env.py` audits presence only and intentionally omits values.

| Group | Variables | Owner | Scope |
| --- | --- | --- | --- |
| Data source quota | `GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_PERSONAL_ACCESS_TOKEN`, `HUGGINGFACE_TOKEN` | Operator | Optional read-only source expansion. |
| Provider generation | `DEEPSEEK_API_KEY`, `GOOGLE_AGENT_PLATFORM_API`, `GOOGLE_API_KEY` | Operator | Required for `e2e:provider`, `e2e:lambda`, and `e2e:live`. |
| Remotion Lambda | `REMOTION_AWS_ACCESS_KEY_ID`, `REMOTION_AWS_SECRET_ACCESS_KEY`, `REMOTION_*` | Infrastructure owner | Required only for Lambda commands and live/prod E2E. |
| Douyin adapter | `SOCIAL_AUTO_UPLOAD_ROOT`, `SOCIAL_AUTO_UPLOAD_CLI`, `DOUYIN_ACCOUNT_NAME` | Publishing operator | Required for adapter preflight and live upload. |
| Live gate | `SEARCHPO_DOUYIN_LIVE` | Human approver | Must be `0` except during intentional live publish. |
| Text-model gateway | `SEARCHPO_LLM_URL`, `SEARCHPO_LLM_API_KEY`, `SEARCHPO_LLM_MODEL`, `SEARCHPO_LLM_SCORER_MODEL` | Operator | Optional. When `SEARCHPO_LLM_URL` (full chat/completions URL) is set, polish and scoring use it in OpenAI format and `DEEPSEEK_API_KEY` is not needed. |
| Voiceover provider | `SEARCHPO_TTS_PROVIDER`, `CARTESIA_API_KEY`, `SEARCHPO_CARTESIA_VOICE`, `SEARCHPO_CARTESIA_MODEL`, `SEARCHPO_TTS_DAILY_CHARS`, `SEARCHPO_TTS_LEDGER` | Operator | Optional. `cartesia` replaces Gemini TTS; the daily character cap (default `20000`) is enforced before any request. |
| Visual gate | `SEARCHPO_VISUAL_AUDIT` | Operator | Optional. `deterministic` lets the deterministic audit decide; Gemini audits are recorded as `not-used`, never `pass`. |
| Douyin browser publisher | `SEARCHPO_DOUYIN_UPLOADER`, `SEARCHPO_EGO_PUBLISHER`, `SEARCHPO_DOUYIN_VISIBILITY` | Publishing operator | Optional. `ego` publishes through a signed-in browser profile instead of social-auto-upload; visibility defaults to `self_only`. |

## Rotation Notes

- AWS keys should be least-privilege for Remotion Lambda/S3 in the active region.
- Google and DeepSeek keys should be separate from unrelated products when possible.
- Google keys are needed only while Gemini still scores (no gateway), speaks (`SEARCHPO_TTS_PROVIDER` unset or `gemini`), or audits video (`SEARCHPO_VISUAL_AUDIT` unset or `gemini`); `scripts/check_env.py` reports which keys the selected switches require.
- The Cartesia ledger lives at `~/.local/state/cartesia-daily-chars.json` unless `SEARCHPO_TTS_LEDGER` points somewhere else. It is one file for the machine, so the daily cap covers every tool that speaks with the same provider here. Do not delete it to get more characters; raise `SEARCHPO_TTS_DAILY_CHARS` deliberately instead.
- Douyin cookies under `runtime/social-auto-upload` are local operational state and must not be committed.
- CI may run only `contract` profile and must never contain live publishing credentials.
