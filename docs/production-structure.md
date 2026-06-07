# Searchpo Production Structure

`searchpo` is a single-machine content pipeline with explicit gates. It is not an agent fleet and it should not hide side effects behind the default E2E command.

## Runtime Boundary

```text
intent intake -> evidence fetch -> TopicBrief/FactBank -> research_barrier.json -> runtime_contract.json -> Script/ScenePlan -> VideoSpec -> implementation_loop.json -> render/Remotion -> artifact binding -> QA -> Douyin contract/live gate -> release_gate.json -> DeliveryPackage -> run_final.json
```

Default local operation is `npm run e2e`:

- fetch public sources and write ignored `runtime/artifacts/...` evidence;
- run the harness in `contract` mode without DeepSeek, Gemini, AWS, or live Douyin calls;
- fetch canonical URL details and write `evidence_bundle.json` plus `cross_check_review.json`;
- stop after text preflight and post-package structure checks;
- never create mock audio, silent media, placeholder captions, or skipped audit evidence.

External side effects are explicit:

- `npm run e2e:provider`: DeepSeek/Gemini provider calls, local render, adapter preflight.
- `npm run e2e:lambda`: provider calls plus S3/Lambda render.
- `npm run e2e:live`: provider calls plus Lambda render plus live Douyin upload.
- `npm run lambda:*`: AWS/S3/Lambda only.
- `npm run douyin:upload`: live Douyin upload only.

The runtime records three separate axes:

| execution_profile | render_mode | publish_mode | Meaning |
| --- | --- | --- | --- |
| `contract` | `none` | `none` | Evidence and text/package preflight only. |
| `provider` | `local` | `contract-check` | Provider APIs plus local publishable media, no live upload. |
| `lambda` | `lambda` | `contract-check` | Provider APIs plus AWS Lambda/S3 render, no live upload. |
| `live` | `lambda` | `live` | Full production path with remote Douyin identity verification. |

## Directory Ownership

| Path | Ownership | Notes |
| --- | --- | --- |
| `data_prep/` | Source collection and candidate contracts | Live public-source reads, ignored runtime writes. |
| `agent_harness/` | Task board, gates, deterministic/provider stage orchestration, service artifacts, and storyboard validation | `SEARCHPO_AGENT_MODE=contract` is default; `agent_harness/service_artifacts.py` owns local service contracts and `agent_harness/storyboard.py` bounds scene graphs. |
| `render/` | Run-scoped Remotion input preparation | Writes `runtime/.../remotion_input_props.json`; validates or synthesizes `storyboard`; does not edit tracked `public/searchpo-content.json`. |
| `src/` | Remotion vertical video app | `SearchpoRadar` renders a validated storyboard with vetted scene blocks and compatibility card fallback. |
| `scripts/` | Thin operational entrypoints and CI guards | Side-effecting scripts must be explicit in name or profile. |
| `docs/` | Human operating contracts | Governance, runbooks, retention, env ownership. |
| `.claude/` | Project agent instructions | Mirrors command tiers and live-publish guard. |
| `runtime/artifacts/YYYY-MM-DD/<run_id>/` | Run-scoped truth | Board DB, evidence, contracts, final media, gates, and `RUN.md`. |
| `out/previews/YYYY-MM-DD/<run_id>/...` | Render preview scratch | Attempt/manual local/lambda renders only; never publish from here. |
| `runtime/`, `out/`, `public/generated/` | Ignored generated state | Do not commit. |

## Final Truth

`agent_run.json` is the harness loop summary. It is not the final production truth.

Every provider/lambda/live E2E run that reaches final verification writes:

- `runtime_contract.json`: planning, delegation, verification, and recovery contracts for the run.
- `research_barrier.json`: main-agent decision that implementation may start only after source artifacts prove sufficiency.
- `implementation_loop.json`: implementation-agent evidence for provider, media-contract, render/audit, and delivery phases.
- `release_gate.json`: main-agent release/no-release verdict from final artifact and publish evidence.
- `artifact_manifest.json`: selected subject, render props hash, final MP4 hash, cover hash, execution profile, render mode, and publish mode.
- `run_final.json`: final board snapshot plus artifact, audit, execution profile, render mode, and publish status.
- `video/final.mp4` and `cover/final.jpg`: the only files allowed as publish input.
- `delivery_package.json`: delivery-facing package that binds final media, cover, captions, source map, metadata, render log, and artifact hashes.
- `RUN.md`: human-readable index of the final decision, key evidence, media, audits, and preview scratch paths.

`out/` files are preview outputs only. New renders use `out/previews/YYYY-MM-DD/<run_id>/attempt-XX/<backend>/` or `manual/<backend>/` so scratch media stays grouped by run. A publish adapter must reject `out/` even if the filename looks current.

No production gate may pass by substituting mock provider output, silent audio, skipped ffmpeg/tesseract checks, manual env-based remote identity, or stale/generic media paths.

No content-quality gate may pass without detailed source evidence. Operator-supplied link runs use `SEARCHPO_LINK` or `SEARCHPO_TOPIC_URL`; open-source project links require GitHub repo API and README evidence before DeepSeek/Gemini copy generation.

## Video Storyboard Contract

Render payloads now carry an additive `storyboard` object. Contract mode synthesizes the default `statement -> context -> card(s) -> cta` storyboard from profile data. Provider mode lets DeepSeek choose bounded scene blocks and brand-safe style tokens from `config/searchpo_policy.json`; `agent_harness/storyboard.py`, `render/prepare_remotion_input.py`, and `src/storyboard.ts` validate the same shape.

The canonical planning chain is `topic_brief.json -> fact_bank.json -> script.json -> scene_plan.json -> video_spec.json`. `video_spec.json` is renderer-neutral; `render_payload.json` is the Remotion adapter output consumed by `render/prepare_remotion_input.py`.

`cards` remains a compatibility field for cover, claims, and older tooling, but it no longer dictates the video layout. Claims ledger and content preflight scan storyboard scene text as public visible copy.

## Compatibility Rule

Existing CLI paths stay stable until tests cover a package move. If Python source is later moved under `src/searchpo/`, keep thin wrappers at the old paths for `package.json`, Claude commands, and local operator muscle memory.
