# Searchpo Production Structure

`searchpo` is a single-machine content pipeline with explicit gates. It is not an agent fleet and it should not hide side effects behind the default E2E command.

## Runtime Boundary

```text
data_prep -> agent_harness -> render/Remotion -> visual audit -> Douyin contract/live gate
```

Default local operation is `npm run e2e`:

- fetch public sources and write ignored `runtime/artifacts/...` evidence;
- run the harness in `contract` mode without DeepSeek, Gemini, AWS, or live Douyin calls;
- render locally with Remotion using run-scoped props;
- validate the Douyin upload manifest without calling the uploader adapter.

External side effects are explicit:

- `npm run e2e:provider`: DeepSeek/Gemini provider calls, local render, adapter preflight.
- `npm run e2e:lambda`: provider calls plus S3/Lambda render.
- `npm run e2e:live`: provider calls plus Lambda render plus live Douyin upload.
- `npm run lambda:*`: AWS/S3/Lambda only.
- `npm run douyin:upload`: live Douyin upload only.

## Directory Ownership

| Path | Ownership | Notes |
| --- | --- | --- |
| `data_prep/` | Source collection and candidate contracts | Live public-source reads, ignored runtime writes. |
| `agent_harness/` | Task board, gates, and deterministic/provider stage orchestration | `SEARCHPO_AGENT_MODE=contract` is default. |
| `render/` | Run-scoped Remotion input preparation | Writes `runtime/.../remotion_input_props.json`; does not edit tracked `public/searchpo-content.json`. |
| `src/` | Remotion vertical video app | Uses tracked fixture defaults plus run props. |
| `scripts/` | Thin operational entrypoints and CI guards | Side-effecting scripts must be explicit in name or profile. |
| `docs/` | Human operating contracts | Governance, runbooks, retention, env ownership. |
| `.claude/` | Project agent instructions | Mirrors command tiers and live-publish guard. |
| `runtime/`, `out/`, `public/generated/` | Ignored generated state | Do not commit. |

## Compatibility Rule

Existing CLI paths stay stable until tests cover a package move. If Python source is later moved under `src/searchpo/`, keep thin wrappers at the old paths for `package.json`, Claude commands, and local operator muscle memory.
