# Post Artifact Contract

Each run writes a post package under:

```text
runtime/artifacts/YYYY-MM-DD/<run_id>/post/
```

## Required Files

| File | Purpose |
| --- | --- |
| `posting_pack.md` | Human-readable package and command preview. |
| `claims_ledger.json` | Structured claim evidence and unsafe-claim notes. |
| `cross_check_review.json` | Structured source-bound cross-check copied from run root. |
| `cross_check_review.md` | Human-readable review status, source facts, caveats, and constructive angles. |
| `douyin_upload_manifest.json` | Adapter-neutral upload package. |
| `douyin_upload_check.json` | Provider/lambda/live publish check result after artifact binding. |
| `post_publish_verification.json` | Live-only remote identity evidence. `submitted` is not final success. |
| `douyin_title.txt`, `douyin_desc.txt`, `douyin_tags.txt` | Exact platform copy. |

## Status Rules

- Contract profile may produce `contract-check-pass` for text/package preflight, but it does not create final media or publish-check artifacts.
- Provider profile requires DeepSeek/Gemini artifacts before publish readiness.
- Lambda profile must render the same run props recorded in `render_input_manifest.json`.
- Live profile must record `live_upload_enabled: true`, adapter submit result, and remote identity verification.
- Runtime JSON records `execution_profile`, `render_mode`, and `publish_mode` separately. Contract package manifests use `render_mode=none` and `publish_mode=none` until media is explicitly rendered and bound in a higher tier.
- `douyin_upload_manifest.json` starts as `pending-artifact-binding`; it is not publishable until `scripts/finalize_artifacts.py` rewrites it with `expected_video_sha256`, `cover_sha256`, and `render_props_sha256`.
- Upload checks reject generic `out/` paths. The adapter must upload `runtime/artifacts/<date>/<run_id>/video/final.mp4`.

## Compatibility

The post package is generated from `agent_harness/stages.py`. Do not hand-edit runtime artifacts to force a gate; fix the generator or rerun the stage.
