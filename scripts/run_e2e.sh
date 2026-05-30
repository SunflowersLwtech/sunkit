#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROFILE="${SEARCHPO_E2E_PROFILE:-contract}"
case "$PROFILE" in
  contract)
    export SEARCHPO_AGENT_MODE="${SEARCHPO_AGENT_MODE:-contract}"
    export SEARCHPO_REMOTION_RENDER_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-local}"
    export SEARCHPO_DOUYIN_CHECK_LEVEL="${SEARCHPO_DOUYIN_CHECK_LEVEL:-manifest}"
    ;;
  provider)
    export SEARCHPO_AGENT_MODE="${SEARCHPO_AGENT_MODE:-provider}"
    export SEARCHPO_REMOTION_RENDER_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-local}"
    export SEARCHPO_DOUYIN_CHECK_LEVEL="${SEARCHPO_DOUYIN_CHECK_LEVEL:-adapter}"
    ;;
  lambda)
    export SEARCHPO_AGENT_MODE="${SEARCHPO_AGENT_MODE:-provider}"
    export SEARCHPO_REMOTION_RENDER_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-lambda}"
    export SEARCHPO_DOUYIN_CHECK_LEVEL="${SEARCHPO_DOUYIN_CHECK_LEVEL:-adapter}"
    ;;
  live)
    export SEARCHPO_AGENT_MODE="${SEARCHPO_AGENT_MODE:-provider}"
    export SEARCHPO_REMOTION_RENDER_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-lambda}"
    export SEARCHPO_DOUYIN_CHECK_LEVEL="${SEARCHPO_DOUYIN_CHECK_LEVEL:-adapter}"
    export SEARCHPO_DOUYIN_LIVE="${SEARCHPO_DOUYIN_LIVE:-1}"
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

python3 scripts/check_env.py --env-file .env --profile "$PROFILE"

if [[ -n "${SEARCHPO_TOPIC:-}" ]]; then
  TOPIC_ARGS=(--topic "$SEARCHPO_TOPIC")
  if [[ -n "${SEARCHPO_TOPIC_SUMMARY:-}" ]]; then
    TOPIC_ARGS+=(--topic-summary "$SEARCHPO_TOPIC_SUMMARY")
  fi
  if [[ -n "${SEARCHPO_TOPIC_URL:-}" ]]; then
    TOPIC_ARGS+=(--topic-url "$SEARCHPO_TOPIC_URL")
  fi
  if [[ -n "${SEARCHPO_TOPIC_SOURCE:-}" ]]; then
    TOPIC_ARGS+=(--topic-source "$SEARCHPO_TOPIC_SOURCE")
  fi
  python3 agent_harness/run_agent_loop.py "${TOPIC_ARGS[@]}"
  RUN_DIR="$(cat runtime/latest_run.txt)"
else
  python3 data_prep/scripts/probe_sources.py --timeout 10 --min-ok-sources 4 --min-ok-p0 3 --allow-transient-statuses 429,500,502,503,504 --allow-transient-timeouts
  python3 data_prep/scripts/run_pipeline.py --limit-per-source "${SEARCHPO_LIMIT_PER_SOURCE:-10}" --shortlist-size 10 --timeout 15
  RUN_DIR="$(cat runtime/latest_run.txt)"
  python3 agent_harness/run_agent_loop.py "$RUN_DIR"
fi
python3 render/prepare_remotion_input.py "$RUN_DIR"
python3 agent_harness/record_runtime_stage.py "$RUN_DIR" \
  --name remotion_input \
  --title "Prepare Remotion run props" \
  --owner claude_impl_agent \
  --artifact render_input_manifest="$RUN_DIR/render_input_manifest.json" \
  --gate remotion_input_prepared:pass:"Remotion props and optional voiceover assets are ready"

REMOTION_MODE="${SEARCHPO_REMOTION_RENDER_MODE:-local}"
case "$REMOTION_MODE" in
  lambda)
    bash scripts/lambda_render.sh site
    bash scripts/lambda_render.sh render
    RENDERED_VIDEO="out/searchpo-radar-lambda.mp4"
    ;;
  local)
    bash scripts/remotion_render.sh local
    RENDERED_VIDEO="out/searchpo-radar.mp4"
    ;;
  *)
    echo "Unsupported SEARCHPO_REMOTION_RENDER_MODE: $REMOTION_MODE (expected lambda or local)" >&2
    exit 2
    ;;
esac

python3 agent_harness/record_runtime_stage.py "$RUN_DIR" \
  --name remotion_render \
  --title "Render MP4 with Remotion" \
  --owner claude_impl_agent \
  --artifact rendered_video="$ROOT/$RENDERED_VIDEO" \
  --gate remotion_rendered:pass:"Rendered MP4 exists"

# Render the Douyin cover still. Non-fatal: a missing cover warns, never blocks the publish gate.
COVER_OUTPUT="out/searchpo-cover.jpg"
if SEARCHPO_RUN_DIR="$RUN_DIR" bash scripts/remotion_render.sh cover; then
  COVER_STATUS="pass"
else
  COVER_STATUS="warn"
  echo "Cover render failed; continuing without a cover." >&2
fi
python3 agent_harness/record_runtime_stage.py "$RUN_DIR" \
  --name remotion_cover \
  --title "Render Douyin cover still" \
  --owner claude_impl_agent \
  --artifact rendered_cover="$ROOT/$COVER_OUTPUT" \
  --gate "cover_rendered:${COVER_STATUS}:Cover still rendered for Douyin"

if [[ "$SEARCHPO_AGENT_MODE" == "provider" ]]; then
  python3 scripts/gemini_visual_audit.py "$RUN_DIR" --video "$RENDERED_VIDEO"
  python3 agent_harness/record_runtime_stage.py "$RUN_DIR" \
    --name gemini_visual_audit \
    --title "Gemini video visual audit" \
    --owner claude_impl_agent \
    --artifact gemini_visual_audit="$RUN_DIR/gemini_visual_audit.json" \
    --gate visual_audit_passed:pass:"Gemini visual audit passed before publish"
else
  python3 - "$RUN_DIR" "$ROOT/$RENDERED_VIDEO" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

run_dir = Path(sys.argv[1])
video = Path(sys.argv[2])
payload = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "status": "pass" if video.is_file() else "fail",
    "mode": "contract_local",
    "video_path": str(video),
    "checks": {"rendered_video_exists": video.is_file()},
    "note": "Provider visual audit skipped in contract profile.",
}
(run_dir / "contract_visual_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
raise SystemExit(0 if video.is_file() else 1)
PY
  python3 agent_harness/record_runtime_stage.py "$RUN_DIR" \
    --name contract_visual_audit \
    --title "Contract render artifact audit" \
    --owner claude_impl_agent \
    --artifact contract_visual_audit="$RUN_DIR/contract_visual_audit.json" \
    --gate contract_visual_audit_passed:pass:"Rendered MP4 exists; provider audit is skipped in contract profile"
fi

SEARCHPO_RENDERED_VIDEO="$RENDERED_VIDEO" bash scripts/douyin_upload_check.sh "$RUN_DIR"
DOUYIN_CHECK_JSON="$RUN_DIR/post/douyin_upload_check.json"
if [[ "${SEARCHPO_DOUYIN_LIVE:-0}" == "1" ]]; then
  if [[ -f "$DOUYIN_CHECK_JSON" ]] && python3 -c "import json,sys;d=json.load(open(sys.argv[1]));sys.exit(0 if d.get('status')=='pass' else 1)" "$DOUYIN_CHECK_JSON" 2>/dev/null; then
    DOUYIN_GATE="explicit_live_publish_gate:pass:Douyin live upload verified pass"
  else
    DOUYIN_GATE="explicit_live_publish_gate:fail:Douyin live upload failed or status not pass"
  fi
else
  DOUYIN_GATE="douyin_contract_check_passed:pass:Douyin adapter completed without live upload"
fi
python3 agent_harness/record_runtime_stage.py "$RUN_DIR" \
  --name douyin_publish \
  --title "Douyin publish adapter" \
  --owner claude_impl_agent \
  --artifact douyin_upload_check="$RUN_DIR/post/douyin_upload_check.json" \
  --gate "$DOUYIN_GATE"

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

if echo "$DOUYIN_GATE" | grep -q ":fail:"; then
  _notify "FAIL" "Douyin gate failed for run $RUN_DIR"
  echo "E2E completed with publish gate failure: $RUN_DIR" >&2
  exit 1
fi

_notify "OK" "$(basename "$RUN_DIR")"
echo "E2E passed: $RUN_DIR"
