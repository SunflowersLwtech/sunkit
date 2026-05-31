#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROFILE="${SEARCHPO_E2E_PROFILE:-contract}"
EXECUTION_PROFILE="$PROFILE"
case "$PROFILE" in
  contract)
    export SEARCHPO_AGENT_MODE="${SEARCHPO_AGENT_MODE:-contract}"
    export SEARCHPO_REMOTION_RENDER_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-local}"
    export SEARCHPO_DOUYIN_CHECK_LEVEL="${SEARCHPO_DOUYIN_CHECK_LEVEL:-manifest}"
    EFFECTIVE_RENDER_MODE="none"
    PUBLISH_MODE="none"
    ;;
  provider)
    export SEARCHPO_AGENT_MODE="${SEARCHPO_AGENT_MODE:-provider}"
    export SEARCHPO_REMOTION_RENDER_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-local}"
    export SEARCHPO_DOUYIN_CHECK_LEVEL="${SEARCHPO_DOUYIN_CHECK_LEVEL:-adapter}"
    EFFECTIVE_RENDER_MODE="local"
    PUBLISH_MODE="contract-check"
    ;;
  lambda)
    export SEARCHPO_AGENT_MODE="${SEARCHPO_AGENT_MODE:-provider}"
    export SEARCHPO_REMOTION_RENDER_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-lambda}"
    export SEARCHPO_DOUYIN_CHECK_LEVEL="${SEARCHPO_DOUYIN_CHECK_LEVEL:-adapter}"
    EFFECTIVE_RENDER_MODE="lambda"
    PUBLISH_MODE="contract-check"
    ;;
  live)
    export SEARCHPO_AGENT_MODE="${SEARCHPO_AGENT_MODE:-provider}"
    export SEARCHPO_REMOTION_RENDER_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-lambda}"
    export SEARCHPO_DOUYIN_CHECK_LEVEL="${SEARCHPO_DOUYIN_CHECK_LEVEL:-adapter}"
    export SEARCHPO_DOUYIN_LIVE="${SEARCHPO_DOUYIN_LIVE:-1}"
    EFFECTIVE_RENDER_MODE="lambda"
    PUBLISH_MODE="live"
    ;;
  *)
    echo "Unsupported SEARCHPO_E2E_PROFILE: $PROFILE (expected contract, provider, lambda, or live)" >&2
    exit 2
    ;;
esac

if [[ "${SEARCHPO_DOUYIN_LIVE:-0}" == "1" && "$PROFILE" != "live" ]]; then
  echo "SEARCHPO_DOUYIN_LIVE=1 is only allowed with SEARCHPO_E2E_PROFILE=live" >&2
  exit 2
fi
export SEARCHPO_EXECUTION_PROFILE="$EXECUTION_PROFILE"
export SEARCHPO_EFFECTIVE_RENDER_MODE="$EFFECTIVE_RENDER_MODE"
export SEARCHPO_PUBLISH_MODE="$PUBLISH_MODE"

finalize_and_exit_fail() {
  local msg="$1"
  if [[ -n "${RUN_DIR:-}" && -f "$RUN_DIR/agent_run.json" ]]; then
    python3 scripts/finalize_run.py "$RUN_DIR" --execution-profile "$EXECUTION_PROFILE" --publish-mode "$PUBLISH_MODE" >/dev/null 2>&1 || true
  fi
  echo "$msg" >&2
  exit 1
}

python3 scripts/check_env.py --env-file .env --profile "$PROFILE"

if [[ -n "${SEARCHPO_LINK:-}" && -n "${SEARCHPO_TOPIC_URL:-}" && "${SEARCHPO_LINK}" != "${SEARCHPO_TOPIC_URL}" ]]; then
  echo "SEARCHPO_LINK and SEARCHPO_TOPIC_URL both set but point to different URLs; pass only one canonical source boundary." >&2
  exit 2
fi

DIRECT_LINK="${SEARCHPO_LINK:-${SEARCHPO_TOPIC_URL:-}}"
if [[ -n "$DIRECT_LINK" && ! "$DIRECT_LINK" =~ ^https?:// ]]; then
  echo "SEARCHPO_LINK/SEARCHPO_TOPIC_URL must be an http(s) URL: $DIRECT_LINK" >&2
  exit 2
fi
if [[ -n "${SEARCHPO_TOPIC:-}" || -n "$DIRECT_LINK" ]]; then
  TOPIC_VALUE="${SEARCHPO_TOPIC:-$DIRECT_LINK}"
  TOPIC_ARGS=(--topic "$TOPIC_VALUE")
  if [[ -n "${SEARCHPO_TOPIC_SUMMARY:-}" ]]; then
    TOPIC_ARGS+=(--topic-summary "$SEARCHPO_TOPIC_SUMMARY")
  fi
  if [[ -n "$DIRECT_LINK" ]]; then
    TOPIC_ARGS+=(--topic-url "$DIRECT_LINK")
  fi
  if [[ -n "${SEARCHPO_TOPIC_SOURCE:-}" ]]; then
    TOPIC_ARGS+=(--topic-source "$SEARCHPO_TOPIC_SOURCE")
  fi
  python3 agent_harness/run_agent_loop.py "${TOPIC_ARGS[@]}"
  RUN_DIR="$(cat runtime/latest_run.txt)"
else
  if [[ "${SEARCHPO_ENABLE_DAILY_RADAR:-0}" != "1" ]]; then
    cat >&2 <<'EOF'
Searchpo now expects an operator-supplied topic or link.
Pass SEARCHPO_TOPIC="..." for widesearch from a topic, or SEARCHPO_LINK="https://..." / SEARCHPO_TOPIC_URL="https://..." for a canonical source boundary.
Set SEARCHPO_ENABLE_DAILY_RADAR=1 only when you explicitly want the legacy source-registry candidate sweep.
EOF
    exit 2
  fi
  python3 data_prep/scripts/probe_sources.py --timeout 10 --min-ok-sources 4 --min-ok-p0 3 --allow-transient-statuses 429,500,502,503,504 --allow-transient-timeouts
  python3 data_prep/scripts/run_pipeline.py --limit-per-source "${SEARCHPO_LIMIT_PER_SOURCE:-10}" --shortlist-size 10 --timeout 15
  RUN_DIR="$(cat runtime/latest_run.txt)"
  python3 agent_harness/run_agent_loop.py "$RUN_DIR"
fi
if [[ "$PROFILE" == "contract" ]]; then
  if find "$RUN_DIR" \( \
    -path '*/video/final.mp4' \
    -o -path '*/cover/final.jpg' \
    -o -name 'render_payload.json' \
    -o -name 'artifact_manifest.json' \
    -o -name 'douyin_upload_check.json' \
    -o -name 'run_final.json' \
  \) -print -quit | grep -q .; then
    echo "Contract profile must not create media, render, publish-check, or final-run artifacts: $RUN_DIR" >&2
    exit 1
  fi
  echo "Contract preflight passed without provider media or live publish: $RUN_DIR"
  exit 0
fi
REMOTION_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-local}"
FINAL_VIDEO="$RUN_DIR/video/final.mp4"
FINAL_COVER="$RUN_DIR/cover/final.jpg"

case "$REMOTION_MODE" in
  lambda|local)
    if ! python3 scripts/video_quality_loop.py "$RUN_DIR" \
      --execution-profile "$EXECUTION_PROFILE" \
      --render-mode "$REMOTION_MODE" \
      --publish-mode "$PUBLISH_MODE"; then
      finalize_and_exit_fail "Video quality loop failed: $RUN_DIR"
    fi
    ;;
  *)
    echo "Unsupported SEARCHPO_REMOTION_RENDER_MODE: $REMOTION_MODE (expected lambda or local)" >&2
    exit 2
    ;;
esac

if [[ ! -f "$FINAL_VIDEO" || ! -f "$FINAL_COVER" ]]; then
  finalize_and_exit_fail "Video quality loop did not produce final media: $RUN_DIR"
fi

if SEARCHPO_RENDERED_VIDEO="$FINAL_VIDEO" SEARCHPO_RENDERED_COVER="$FINAL_COVER" bash scripts/douyin_upload_check.sh "$RUN_DIR"; then
  :
else
  echo "Douyin upload/check reported failure; recording final gates." >&2
fi
DOUYIN_CHECK_JSON="$RUN_DIR/post/douyin_upload_check.json"
if [[ -f "$DOUYIN_CHECK_JSON" ]] && python3 -c "import json,sys;d=json.load(open(sys.argv[1]));sys.exit(0 if d.get('status')=='pass' else 1)" "$DOUYIN_CHECK_JSON" 2>/dev/null; then
  DOUYIN_STATUS="pass"
else
  DOUYIN_STATUS="fail"
fi
if [[ "${SEARCHPO_DOUYIN_LIVE:-0}" == "1" ]]; then
  if [[ "$DOUYIN_STATUS" == "pass" ]]; then
    DOUYIN_GATE="douyin_live_publish_gate:pass:Douyin live upload verified against remote identity"
  else
    DOUYIN_GATE="douyin_live_publish_gate:fail:Douyin live upload failed or remote identity was not verified"
  fi
else
  if [[ "$DOUYIN_STATUS" == "pass" ]]; then
    DOUYIN_GATE="douyin_contract_gate:pass:Douyin manifest check passed without live upload"
  else
    DOUYIN_GATE="douyin_contract_gate:fail:Douyin manifest check failed"
  fi
fi
DOUYIN_STAGE_STATUS="completed"
if [[ "$DOUYIN_STATUS" != "pass" ]]; then
  DOUYIN_STAGE_STATUS="failed"
fi
python3 agent_harness/record_runtime_stage.py "$RUN_DIR" \
  --name douyin_publish \
  --title "Douyin publish adapter" \
  --owner claude_impl_agent \
  --status "$DOUYIN_STAGE_STATUS" \
  --artifact douyin_upload_check="$RUN_DIR/post/douyin_upload_check.json" \
  --gate "$DOUYIN_GATE"

if python3 scripts/finalize_run.py "$RUN_DIR" --execution-profile "$EXECUTION_PROFILE" --publish-mode "$PUBLISH_MODE"; then
  FINAL_STATUS="pass"
else
  FINAL_STATUS="fail"
fi

_notify() {
  local status="$1" msg="$2"
  if [[ -n "${SEARCHPO_SLACK_WEBHOOK:-}" ]]; then
    curl -sf -X POST -H 'Content-Type: application/json' \
      -d "{\"text\":\"searchpo $status: $msg\"}" "$SEARCHPO_SLACK_WEBHOOK" >/dev/null 2>&1 || true
  fi
  if [[ -n "${SEARCHPO_BARK_URL:-}" ]]; then
    curl -sf "$SEARCHPO_BARK_URL/searchpo%20$status/$msg" >/dev/null 2>&1 || true
  fi
}

if [[ "$FINAL_STATUS" != "pass" ]]; then
  _notify "FAIL" "Final release gate failed for run $RUN_DIR"
  echo "E2E completed with final release gate failure: $RUN_DIR" >&2
  exit 1
fi

_notify "OK" "$(basename "$RUN_DIR")"
echo "E2E passed: $RUN_DIR"
