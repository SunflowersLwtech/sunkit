# Environment Ownership

Secrets live in `.env` or the operator's shell, never in tracked files or CI logs. `scripts/check_env.py` audits presence only and intentionally omits values.

| Group | Variables | Owner | Scope |
| --- | --- | --- | --- |
| Data source quota | `GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_PERSONAL_ACCESS_TOKEN`, `HUGGINGFACE_TOKEN` | Operator | Optional read-only source expansion. |
| Provider generation | `DEEPSEEK_API_KEY`, `GOOGLE_AGENT_PLATFORM_API`, `GOOGLE_API_KEY` | Operator | Required for `e2e:provider`, `e2e:lambda`, and `e2e:live`. |
| Remotion Lambda | `REMOTION_AWS_ACCESS_KEY_ID`, `REMOTION_AWS_SECRET_ACCESS_KEY`, `REMOTION_*` | Infrastructure owner | Required only for Lambda commands and live/prod E2E. |
| Douyin adapter | `SOCIAL_AUTO_UPLOAD_ROOT`, `SOCIAL_AUTO_UPLOAD_CLI`, `DOUYIN_ACCOUNT_NAME` | Publishing operator | Required for adapter preflight and live upload. |
| Live gate | `SEARCHPO_DOUYIN_LIVE` | Human approver | Must be `0` except during intentional live publish. |

## Rotation Notes

- AWS keys should be least-privilege for Remotion Lambda/S3 in the active region.
- Google and DeepSeek keys should be separate from unrelated products when possible.
- Douyin cookies under `runtime/social-auto-upload` are local operational state and must not be committed.
- CI may run only `contract` profile and must never contain live publishing credentials.
