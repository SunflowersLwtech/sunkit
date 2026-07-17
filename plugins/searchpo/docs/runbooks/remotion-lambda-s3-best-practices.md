# Remotion Lambda S3 Best Practices

Last verified: 2026-06-04

This runbook is for agents operating Searchpo's Remotion Lambda render path. It covers the local environment, AWS/Remotion setup, `.env` variables, API/CLI surfaces, test commands, and success criteria.

## Agent Contract

- Do not print `.env` values or AWS credentials. Report variable names only.
- Treat Remotion S3 as the Lambda render workspace, not as Searchpo's final release truth.
- Treat `runtime/artifacts/YYYY-MM-DD/<run_id>/video/final.mp4` and `cover/final.jpg` as the publishable Searchpo media after finalization.
- Treat `out/` as preview/download scratch. Never use `out/` directly as the publish input.
- Do not use mock audio, silent video, skipped checks, or upload-path fallback to make a Lambda run pass.
- Prefer explicit `SEARCHPO_RUN_DIR=...` over `runtime/latest_run.txt` when reviewing or repairing a specific run.

## Short Answer

Yes: with `render_mode=lambda`, the video is rendered by AWS Lambda and uploaded to the configured Remotion S3 bucket first. Searchpo's wrapper then downloads the rendered object to a local `out/...` file. The video quality loop copies that local attempt into the run's optimization evidence and only a passing attempt is promoted into `runtime/artifacts/.../video/final.mp4`.

The important split is:

| Layer | Purpose | Default location |
| --- | --- | --- |
| Remotion Lambda S3 | Site bundle, progress, Lambda render output, still output | `s3://<REMOTION_LAMBDA_BUCKET_NAME>/sites/...` and `renders/<renderId>/...` |
| Local scratch | CLI-downloaded preview of the Lambda result | `out/<run_id>-searchpo-radar-lambda-attempt-XX.mp4` |
| Searchpo final truth | SHA-bound publishable media | `runtime/artifacts/YYYY-MM-DD/<run_id>/video/final.mp4` and `cover/final.jpg` |

## Official Model

Remotion Lambda renders in AWS and uploads the final media to S3. By default, the media is saved in the same bucket as the Remotion site under `renders/${renderId}/out.{extension}`.

Useful official docs:

- Remotion `renderMediaOnLambda()`: https://www.remotion.dev/docs/lambda/rendermediaonlambda
- Remotion custom output destination: https://www.remotion.dev/docs/lambda/custom-destination
- Remotion auto-delete renders: https://www.remotion.dev/docs/lambda/autodelete
- Remotion multiple buckets: https://www.remotion.dev/docs/lambda/multiple-buckets
- Remotion bucket security: https://www.remotion.dev/docs/lambda/bucket-security
- Remotion data transfer cost: https://www.remotion.dev/docs/lambda/data-transfer-cost
- AWS S3 lifecycle rules: https://docs.aws.amazon.com/AmazonS3/latest/userguide/intro-lifecycle-rules.html
- AWS S3 presigned URLs: https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html
- AWS S3 Block Public Access: https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html

## Searchpo Render Path

Package scripts:

```bash
npm run e2e:lambda      # provider + Remotion Lambda/S3 render + contract-check publish mode
npm run e2e:live        # provider + Remotion Lambda/S3 render + real Douyin live publish
npm run lambda:check    # list Lambda functions in the configured region
npm run lambda:site     # deploy/update Remotion site into S3 with folder expiry enabled
npm run lambda:render   # render SearchpoRadar through Lambda for the selected run
bash scripts/lambda_render.sh still  # render SearchpoCover through Lambda
```

Current wrapper:

- `scripts/lambda_render.sh` loads `.env`, maps `REMOTION_AWS_*` into `AWS_*`, and invokes `npx remotion lambda ...`.
- `scripts/lambda_render.sh site` calls `remotion lambda sites create` with `--enable-folder-expiry`.
- `scripts/lambda_render.sh render` calls `remotion lambda render`, passes `--privacy`, `--out-name`, render quality flags, and optional `--delete-after`.
- `scripts/video_quality_loop.py` sets per-attempt output overrides, runs the Lambda render/still commands, copies the downloaded files into `optimization/video/attempt-XX/`, audits them, and only promotes a passing attempt.

Critical distinction:

| Field | Meaning | Example |
| --- | --- | --- |
| Positional local output path | Where the Remotion CLI downloads the finished media on this machine | `out/topic-...-searchpo-radar-lambda-attempt-01.mp4` |
| `--out-name` / `SEARCHPO_LAMBDA_RENDER_OUT_NAME` | The media filename/key inside the S3 render folder | `<run_id>/attempt-01/searchpo-radar.mp4` |
| Remotion S3 object path | Effective S3 key created by Remotion | `renders/<renderId>/<run_id>/attempt-01/searchpo-radar.mp4` |

If `REMOTION_LAMBDA_DELETE_AFTER=7-days`, Remotion prefixes the render folder so the lifecycle rule can expire it, for example under `renders/7-days-*`.

## Local Environment

Required local tools:

```bash
node --version
npm --version
npx remotion --version
python3 --version
ffmpeg -version
ffprobe -version
jq --version
```

On this Mac, prefer this PATH if tools are not resolving:

```bash
export PATH=/opt/homebrew/bin:/opt/anaconda3/bin:$PATH
```

Install project dependencies:

```bash
npm install
```

The Remotion package versions must stay aligned. This repo pins:

```text
remotion=4.0.468
@remotion/cli=4.0.468
@remotion/lambda=4.0.468
```

If Python tests fail because Homebrew Python cannot import a package that exists in conda, retry with:

```bash
/opt/anaconda3/bin/python3 -m unittest discover -s tests
```

## AWS And Remotion Setup

One-time AWS setup, following Remotion's official model:

1. Create or choose an AWS account and region. Searchpo currently defaults to `ap-southeast-1`.
2. Create the Remotion Lambda IAM role policy from the CLI output:

```bash
npx remotion lambda policies role
```

3. Create the Remotion Lambda IAM user policy from the CLI output:

```bash
npx remotion lambda policies user
```

4. Validate permissions without exposing secrets:

```bash
npx remotion lambda policies validate
```

5. Deploy a Remotion Lambda function using the Remotion CLI or API:

```bash
npx remotion lambda functions deploy
```

Record the resulting function name in `REMOTION_LAMBDA_FUNCTION_NAME`.

6. Create or reuse one Remotion Lambda bucket for the active AWS account and region. Remotion recommends one bucket per account + region unless compliance requirements force a split.
7. Put the bucket name in `REMOTION_LAMBDA_BUCKET_NAME`.
8. Deploy the Searchpo Remotion site and enable folder expiry:

```bash
npm run lambda:site
```

This uses:

```bash
npx remotion lambda sites create src/index.ts \
  --site-name "$REMOTION_LAMBDA_SITE_NAME" \
  --region "$REMOTION_LAMBDA_REGION" \
  --force-bucket-name "$REMOTION_LAMBDA_BUCKET_NAME" \
  --enable-folder-expiry
```

The current render wrapper assumes the Lambda function already exists. `REMOTION_LAMBDA_MEMORY_MB`, `REMOTION_LAMBDA_TIMEOUT_SEC`, and `REMOTION_LAMBDA_DISK_MB` are environment inventory/deploy knobs, but `scripts/lambda_render.sh` does not deploy or resize the function.

## `.env` Variables

Never print values. Agents may report set/missing status only.

Required for any Lambda render:

| Variable | Purpose |
| --- | --- |
| `REMOTION_AWS_ACCESS_KEY_ID` | AWS access key used by the wrapper |
| `REMOTION_AWS_SECRET_ACCESS_KEY` | AWS secret key used by the wrapper |
| `REMOTION_AWS_REGION` | Fallback AWS region |
| `REMOTION_LAMBDA_REGION` | Active Lambda/S3 region |
| `REMOTION_LAMBDA_FUNCTION_NAME` | Existing Remotion Lambda function name |
| `REMOTION_LAMBDA_BUCKET_NAME` | Remotion S3 bucket used for site/render artifacts |

Recommended defaults:

| Variable | Recommended value | Notes |
| --- | --- | --- |
| `REMOTION_LAMBDA_SITE_NAME` | `searchpo-radar` | Used as the Remotion site name / serve target |
| `REMOTION_LAMBDA_PRIVACY` | `private` | Prefer private output and signed access |
| `REMOTION_LAMBDA_DELETE_AFTER` | `7-days` | Valid values: `1-day`, `3-days`, `7-days`, `30-days` |
| `REMOTION_LAMBDA_CONCURRENCY` | `4` | Used when `SEARCHPO_LAMBDA_FRAMES_PER_LAMBDA` is unset |
| `SEARCHPO_LAMBDA_CONCURRENCY_PER_LAMBDA` | `1` | Keep conservative unless measured |
| `SEARCHPO_RENDER_CRF` | `18` | High-quality H.264 output |
| `SEARCHPO_RENDER_AUDIO_BITRATE` | `192K` | Current Searchpo default |
| `SEARCHPO_RENDER_IMAGE_FORMAT` | `jpeg` | Current Lambda render default |
| `SEARCHPO_RENDER_JPEG_QUALITY` | `95` | Current Lambda render default |

Per-attempt overrides normally set by `scripts/video_quality_loop.py`:

| Variable | Purpose |
| --- | --- |
| `SEARCHPO_RUN_DIR` | Explicit run directory to render |
| `SEARCHPO_REMOTION_PROPS` | Override props file path |
| `SEARCHPO_LAMBDA_RENDER_OUTPUT` | Local video download path |
| `SEARCHPO_LAMBDA_RENDER_OUT_NAME` | S3 output name inside the render folder |
| `SEARCHPO_LAMBDA_COVER_OUTPUT` | Local still download path |
| `SEARCHPO_LAMBDA_COVER_OUT_NAME` | S3 still name inside the render folder |
| `SEARCHPO_LAMBDA_FRAMES_PER_LAMBDA` | Explicit chunk size; mutually preferred over concurrency when set |
| `SEARCHPO_LAMBDA_CONCURRENCY` | Direct concurrency override |

Full `npm run e2e:lambda` also needs provider/research keys because the Lambda profile includes evidence, DeepSeek, Gemini TTS, render, and visual audit:

| Group | Variables |
| --- | --- |
| Research | `ANYSEARCH_API_KEY` |
| Copy | `DEEPSEEK_API_KEY` |
| Gemini | `GOOGLE_AGENT_PLATFORM_API` or `GOOGLE_API_KEY` |
| Optional Douyin account for live only | `DOUYIN_ACCOUNT_NAME` or `SOCIAL_UPLOAD_ACCOUNT_NAME` |

Use the built-in redacted checker:

```bash
python3 scripts/check_env.py --profile lambda
python3 scripts/agent_capabilities.py --profile lambda --format text
```

## API And CLI Surface

Remotion official APIs most relevant to Searchpo:

| API | Purpose |
| --- | --- |
| `deployFunction()` | Deploy a Remotion Lambda function |
| `deploySite()` | Upload the Remotion site bundle into S3 |
| `getOrCreateBucket()` | Create/reuse a Remotion bucket; can enable folder expiry |
| `renderMediaOnLambda()` | Start a video/audio render |
| `renderStillOnLambda()` | Start a still render |
| `getRenderProgress()` | Poll render progress from S3 `progress.json` |
| `downloadMedia()` | Download final media from S3 |
| `presignUrl()` | Generate time-limited access to private media |
| `deleteRender()` | Delete a render folder |

Remotion CLI commands used or expected:

```bash
npx remotion lambda policies role
npx remotion lambda policies user
npx remotion lambda policies validate
npx remotion lambda functions ls --region "$REMOTION_LAMBDA_REGION"
npx remotion lambda functions deploy
npx remotion lambda sites create src/index.ts --site-name "$REMOTION_LAMBDA_SITE_NAME" --enable-folder-expiry
npx remotion lambda render "$REMOTION_LAMBDA_SITE_NAME" SearchpoRadar out/test.mp4 --out-name "<run_id>/searchpo-radar.mp4"
npx remotion lambda still "$REMOTION_LAMBDA_SITE_NAME" SearchpoCover out/test.jpg --out-name "<run_id>/searchpo-cover.jpg"
```

Searchpo wrapper commands should be preferred during normal operation:

```bash
npm run lambda:check
npm run lambda:site
SEARCHPO_RUN_DIR="/absolute/path/to/runtime/artifacts/YYYY-MM-DD/<run_id>" npm run lambda:render
SEARCHPO_RUN_DIR="/absolute/path/to/runtime/artifacts/YYYY-MM-DD/<run_id>" bash scripts/lambda_render.sh still
```

## Test Ladder

### 1. Static/local readiness

```bash
npm install
python3 scripts/check_env.py --profile lambda
npm run lint
```

If this fails, fix local dependencies or missing variable names before touching AWS.

### 2. AWS permission and function discovery

```bash
npm run lambda:check
```

Pass condition:

- command exits `0`;
- the expected function exists in the configured region;
- no credential values are printed.

Typical failures:

- missing `REMOTION_AWS_ACCESS_KEY_ID`;
- missing `REMOTION_AWS_SECRET_ACCESS_KEY`;
- wrong `REMOTION_LAMBDA_REGION`;
- IAM policy does not allow Lambda/S3 discovery.

### 3. Site deploy and lifecycle setup

```bash
npm run lambda:site
```

Pass condition:

- command exits `0`;
- Remotion site exists under `REMOTION_LAMBDA_SITE_NAME`;
- S3 bucket has folder expiry lifecycle rules;
- site bucket and function are in the same region.

### 4. Render an existing run through Lambda

Use an explicit run directory with `render_payload.json` and `remotion_input_props.json` support:

```bash
export SEARCHPO_RUN_DIR="/absolute/path/to/runtime/artifacts/YYYY-MM-DD/<run_id>"
python3 render/prepare_remotion_input.py "$SEARCHPO_RUN_DIR"
npm run lambda:render
bash scripts/lambda_render.sh still
```

Pass condition:

- video is uploaded to S3 by Remotion;
- video is downloaded to the configured local `out/...mp4`;
- cover is uploaded to S3 by Remotion;
- cover is downloaded to the configured local `out/...jpg`;
- local files are non-empty.

Quick local checks:

```bash
VIDEO="out/<run_id>-searchpo-radar-lambda.mp4"
COVER="out/<run_id>-searchpo-cover-lambda.jpg"
test -s "$VIDEO"
test -s "$COVER"
ffprobe -v error -show_format -show_streams -of json "$VIDEO" | jq '{format: .format.format_name, duration: .format.duration, streams: [.streams[] | {codec_type, codec_name, width, height}]}'
shasum -a 256 "$VIDEO" "$COVER"
```

### 5. Full governed Lambda run

Use a real source URL. A topic without canonical URL is not enough for current governed provider flow.

```bash
SEARCHPO_TOPIC="topic to investigate" \
SEARCHPO_TOPIC_URL="https://canonical-source.example/path" \
npm run e2e:lambda
```

Pass condition:

- `cross_check_review.json` passes before copy generation;
- provider copy, TTS, captions, render payload, and audits are real;
- Lambda render produces the media attempts;
- deterministic and Gemini visual audits pass;
- `artifact_manifest.json` binds `video/final.mp4` and `cover/final.jpg` by SHA256;
- `run_final.json` is written last and reports `render_mode=lambda`;
- no live upload occurs unless `npm run e2e:live` was explicitly requested.

Suggested verification:

```bash
RUN_DIR="$(cat runtime/latest_run.txt)"
jq '{status, execution_profile, render_mode, publish_mode}' "$RUN_DIR/run_final.json"
jq '{video, cover}' "$RUN_DIR/artifact_manifest.json"
test -s "$RUN_DIR/video/final.mp4"
test -s "$RUN_DIR/cover/final.jpg"
ffprobe -v error -show_format -show_streams -of json "$RUN_DIR/video/final.mp4" | jq '.format.duration'
```

## Storage Best Practices

1. Use one Remotion bucket per AWS account + region unless compliance requires multiple buckets.
2. Keep Lambda function, site bucket, and render bucket in the same region.
3. Keep `REMOTION_LAMBDA_PRIVACY=private`.
4. Use presigned URLs or a controlled API for temporary access. Do not expose raw private media URLs in logs.
5. Enable folder expiry with `npm run lambda:site` and set `REMOTION_LAMBDA_DELETE_AFTER`.
6. Keep Searchpo's final run artifacts separate from Remotion's expiring render folder.
7. For long-term cloud retention, add a separate archive bucket such as `searchpo-media-prod` or an R2 bucket. Copy `video/final.mp4`, `cover/final.jpg`, `artifact_manifest.json`, `run_final.json`, and required evidence JSONs together. Do not rely on the expiring Remotion render bucket for reviewed or published media.
8. For public video distribution or external downloads, prefer a dedicated distribution layer such as S3 + CloudFront or R2 + custom domain/CDN. Do not expose raw Remotion S3 object URLs as the public product URL.
9. For large input assets, consider CDN/R2-style storage and `@remotion/media` tags where appropriate to reduce repeated full downloads by Lambda chunks.
10. Keep object keys run-scoped and attempt-scoped. Do not use a single stable `latest.mp4` key for governed output.

## Security Practices

- Do not put AWS credentials, provider keys, or Douyin cookies in Remotion props.
- Do not commit `.env`, `runtime/social-auto-upload`, `out/`, or generated Remotion runtime media.
- Keep AWS IAM least-privilege for the active Remotion region and bucket.
- Prefer S3 Block Public Access for non-public buckets.
- Use `REMOTION_LAMBDA_PRIVACY=private` unless a deliberate public distribution layer has been designed.
- Remember that a presigned URL is a bearer token. Treat it as sensitive until it expires.
- Scan before exporting traces:

```bash
npm run trace:scan
```

## Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `Missing required env var: REGION` | Region variables unset | Set `REMOTION_LAMBDA_REGION` and `REMOTION_AWS_REGION` |
| `Missing required env var: BUCKET_NAME` | Bucket variable unset | Set `REMOTION_LAMBDA_BUCKET_NAME` |
| `Missing Remotion props file` | Run directory not selected or props not prepared | Set `SEARCHPO_RUN_DIR` and run `python3 render/prepare_remotion_input.py "$SEARCHPO_RUN_DIR"` |
| Lambda function not listed | Wrong region or credentials | Run `npm run lambda:check`; verify region/function/account |
| S3 AccessDenied | IAM policy does not cover bucket/function | Re-run Remotion policy generation and validate |
| Render succeeds but local file missing | CLI download path failed or local output path wrong | Inspect positional output path and `SEARCHPO_LAMBDA_RENDER_OUTPUT` |
| S3 file exists but final artifact missing | Searchpo audit/finalization did not promote attempt | Inspect `optimization/video/attempt-XX/`, audit JSONs, and `scripts/finalize_artifacts.py` output |
| `runtime/latest_run.txt` points to the wrong run | Another run started later | Use explicit `SEARCHPO_RUN_DIR` |
| Old S3 renders accumulating | Folder expiry missing or `deleteAfter` unset | Run `npm run lambda:site`; set `REMOTION_LAMBDA_DELETE_AFTER=7-days` |
| Public access concern | Bucket ACL/policy too open | Review Remotion bucket security and AWS Block Public Access |

## Completion Checklist

For an agent to report "Remotion Lambda/S3 is working" in Searchpo, all of these must be true:

- `.env` has required Lambda variable names set, without exposing values.
- `python3 scripts/check_env.py --profile lambda` passes for the intended flow.
- `npm run lambda:check` sees the configured function.
- `npm run lambda:site` has deployed the current Remotion site with folder expiry.
- A Lambda render has uploaded media to S3 and downloaded a local preview.
- The full governed flow has promoted a passing media attempt to `runtime/artifacts/.../video/final.mp4`.
- `artifact_manifest.json` records SHA256-bound final media.
- `run_final.json` records the final execution/render/publish modes.
- Remotion S3 outputs have an explicit retention policy; reviewed/published Searchpo artifacts are preserved separately.
