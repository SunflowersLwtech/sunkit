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
| `cross_check_review.md` | Human-readable review status. |
| `douyin_upload_manifest.json` | Adapter-neutral upload package. |
| `douyin_upload_check.json` | Manifest, adapter, account, and live-upload execution result. |
| `douyin_title.txt`, `douyin_desc.txt`, `douyin_tags.txt` | Exact platform copy. |

## Status Rules

- Contract profile may produce `contract-check-pass`, but this is not live publish approval.
- Provider profile requires DeepSeek/Gemini artifacts before publish readiness.
- Lambda profile must render the same run props recorded in `render_input_manifest.json`.
- Live profile must record `live_upload_enabled: true` and the adapter result.

## Compatibility

The post package is generated from `agent_harness/stages.py`. Do not hand-edit runtime artifacts to force a gate; fix the generator or rerun the stage.
