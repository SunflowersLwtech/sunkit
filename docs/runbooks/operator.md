# Operator Runbook

## Daily Contract Check

```bash
npm install
npm run e2e
```

This is the safe default. It fetches public sources, runs the local contract harness, renders locally, and validates the Douyin manifest without provider, AWS, or live upload side effects.

## Provider Review

```bash
npm run e2e:provider
```

Use when DeepSeek copy, Gemini TTS, and Gemini visual audit should run. Missing provider keys are hard failures in this profile.

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

- `gemini_visual_audit.json` status is `pass`;
- `claims_ledger.json` contains no unsupported claim;
- the account cookie check passes;
- a human approved the exact post package.

## Failure Handling

- Source probe failure: rerun later if transient; do not lower source thresholds without noting the reason.
- Provider failure: preserve the provider error; do not replace it with fabricated copy or audio.
- Visual audit failure: fix the render payload or CSS and rerender; do not override the gate.
- Lambda failure: run `npm run lambda:check`, inspect AWS region/function/bucket values, then retry `e2e:lambda`.
- Douyin risk prompt: keep live upload headed, complete the prompt manually, and preserve the run artifacts.
- Accidental publish: capture `post/douyin_upload_check.json`, platform URL/evidence, and deletion/rollback steps in the incident notes.
