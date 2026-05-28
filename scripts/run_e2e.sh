#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 scripts/check_env.py --env-file .env
python3 data_prep/scripts/probe_sources.py --timeout 10 --min-ok-sources 4 --min-ok-p0 3 --allow-transient-statuses 429,500,502,503,504 --allow-transient-timeouts
python3 data_prep/scripts/run_pipeline.py --limit-per-source "${SEARCHPO_LIMIT_PER_SOURCE:-10}" --shortlist-size 10 --timeout 15
RUN_DIR="$(cat runtime/latest_run.txt)"
python3 agent_harness/run_agent_loop.py "$RUN_DIR"
python3 render/prepare_remotion_input.py "$RUN_DIR"

REMOTION_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-lambda}"
case "$REMOTION_MODE" in
  lambda)
    bash scripts/lambda_render.sh site
    bash scripts/lambda_render.sh render
    SEARCHPO_RENDERED_VIDEO=out/searchpo-radar-lambda.mp4 bash scripts/douyin_upload_check.sh "$RUN_DIR"
    ;;
  local)
    npm run render
    SEARCHPO_RENDERED_VIDEO=out/searchpo-radar.mp4 bash scripts/douyin_upload_check.sh "$RUN_DIR"
    ;;
  *)
    echo "Unsupported SEARCHPO_REMOTION_RENDER_MODE: $REMOTION_MODE (expected lambda or local)" >&2
    exit 2
    ;;
esac

echo "E2E passed: $RUN_DIR"
