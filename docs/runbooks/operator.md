# Operator Runbook

## Daily Contract Check

```bash
npm install
npm run e2e
```

This is the safe default for wiring checks only. It fetches public sources and runs the no-provider harness without provider, AWS, or live upload side effects. It must not fabricate audio, captions, visual evidence, or publish success.

## Side-Effect Matrix

| Tier | Command | execution_profile | render_mode | publish_mode | Success condition |
| --- | --- | --- | --- | --- | --- |
| Contract | `npm run e2e` | `contract` | `none` | `none` | Evidence, cross-check, claims ledger, and preflight pass; no final media or publish artifacts. |
| Provider | `npm run e2e:provider` | `provider` | `local` | `contract-check` | Provider output, local MP4/cover, audits, artifact binding, and adapter preflight pass. |
| Lambda | `npm run e2e:lambda` | `lambda` | `lambda` | `contract-check` | Provider path plus fresh Remotion Lambda/S3 render pass; no live upload. |
| Live | `npm run e2e:live` | `live` | `lambda` | `live` | All media gates pass and Douyin remote identity is verified after upload. |

Contract still reads public sources and writes ignored `runtime/artifacts/...` evidence. It must not call DeepSeek/Gemini, render media, touch AWS/S3, or upload to Douyin.

Every run now requires detailed source evidence:

- automatic radar: the selected candidate's `canonical_url` is fetched before content planning;
- direct link: set `SEARCHPO_LINK="https://..."`;
- topic mode: set `SEARCHPO_TOPIC_URL="https://..."`; a topic without a source URL fails before copy generation.

For GitHub repositories, the evidence gate requires the repo API and README in addition to the public page.

## Provider Review

```bash
npm run e2e:provider
```

Use when DeepSeek copy, Gemini TTS, deterministic media audit, and Gemini visual audit should run. Missing provider keys, media tools, TTS audio, captions, ffmpeg, or tesseract are hard failures in this profile.

Direct-link provider run:

```bash
SEARCHPO_LINK=https://github.com/owner/repo npm run e2e:provider
```

## Lambda Render

```bash
npm run e2e:lambda
```

Use after provider review when the Lambda/S3 path needs verification. This uploads/updates the Remotion site and invokes the configured Lambda function.

## Live Publish

```bash
DOUYIN_ACCOUNT_NAME=<account_name> npm run e2e:live
```

Before live publish:

- `artifact_manifest.json` binds `video/final.mp4` and `cover/final.jpg` by SHA256;
- `content_optimization_loop.json` and `video_optimization_loop.json` status are `pass`;
- `visual_audit_deterministic.json` and `gemini_visual_audit.json` status are `pass`;
- `claims_ledger.json` contains no unsupported claim;
- the account cookie check passes;
- a human approved the exact post package.
- after submit, `post/post_publish_verification.json` must prove remote item identity; `submitted` alone is failure.

## Failure Handling

- Source probe failure: rerun later if transient; do not lower source thresholds without noting the reason.
- Provider failure: preserve the provider error; do not replace it with fabricated copy, audio, captions, or media.
- Visual audit failure: inspect `optimization/video/attempt-XX/video_revision_decision.json`; let repairable layout issues rerender, but do not override or skip the gate.
- Lambda failure: run `npm run lambda:check`, inspect AWS region/function/bucket values, then retry `e2e:lambda`.
- Douyin risk prompt: keep live upload headed, complete the prompt manually, and preserve the run artifacts.
- Accidental publish: capture `post/douyin_upload_check.json`, `post/post_publish_verification.json`, platform URL/evidence, and deletion/rollback steps in `post/rollback_ledger.json`.
