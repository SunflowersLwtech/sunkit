#!/usr/bin/env bash
# render.sh — drive Render web services that deploy from GHCR images, without
# Render's GitHub connection. CI (an image workflow per repo) is the primary
# deploy path; this script is the fallback when CI or local Docker is unavailable.
# services.json (beside this file's parent) holds one block per service.
#
# usage: render.sh <build|create|deploy|release|env|status|domain|logs> <service> [args]
#
# Credentials/ids come from the environment — never argv, never committed:
#   RENDER_API_KEY        Render API key (Dashboard → Team Settings → API Keys)
#   RENDER_OWNER_ID       Render owner/team id (tea-…)
#   RENDER_REGISTRY_CRED  registry credential id (rgc-…) pointing at the GHCR pull PAT
#   RENDER_REGION         region (default oregon)
#   GHCR_USER             account name that `gh auth token` belongs to (remote build)
#   REMOTE_BUILD_HOST     user@host for native x86_64 fallback builds
#   REMOTE_BUILD_KEY      optional ssh key for REMOTE_BUILD_HOST
#   DOCKER_CMD            docker command on the remote host (default: docker)
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REG="$SKILL_DIR/services.json"
API=https://api.render.com/v1
KEY="${RENDER_API_KEY:?set RENDER_API_KEY in the environment}"
OWNER_ID="${RENDER_OWNER_ID:?set RENDER_OWNER_ID in the environment (tea-…)}"
REGISTRY_CRED="${RENDER_REGISTRY_CRED:?set RENDER_REGISTRY_CRED in the environment (rgc-…)}"
REGION="${RENDER_REGION:-oregon}"
cmd=${1:?usage: render.sh <cmd> <service>}; svc=${2:?service name}
cfg() { jq -r ".\"$svc\".$1" "$REG"; }
# The token never reaches argv: curl reads the Authorization header off stdin (-H @-).
api() {
  local m=$1 path=$2; shift 2
  printf 'Authorization: Bearer %s\n' "$KEY" | \
    curl -sf -X "$m" "$API$path" -H @- -H 'Content-Type: application/json' "$@"
}
sid() {
  local id; id=$(cfg serviceId)
  [ -n "$id" ] && [ "$id" != "null" ] || { echo "serviceId empty — run create first" >&2; exit 1; }
  [[ "$id" == srv-* && "$id" != "srv-REPLACE"* ]] || { echo "serviceId is still the placeholder in services.json" >&2; exit 1; }
  echo "$id"
}
# envFile is a JSON array of {key, value, type} — secrets must not sit in a committed file.
case "$cmd" in
  build)
    dir=$(cfg repoDir); ctx=$(cfg context); img=$(cfg image)
    df=$(cfg dockerfile); [ "$df" = "null" ] && df="Dockerfile"
    sha=$(git -C "$dir" rev-parse --short HEAD); full_sha=$(git -C "$dir" rev-parse HEAD)
    # An image tagged with a commit must contain that commit, so refuse to build
    # a dirty tree — otherwise :$sha is a lie and /healthz/ reports a commit that
    # never matched what is running.
    [ -z "$(git -C "$dir" status --porcelain)" ] || { echo "$dir is dirty — commit or stash before building $img:$sha" >&2; exit 1; }
    if [ -n "${REMOTE_BUILD_HOST:-}" ]; then
      # Fallback for when the local Docker daemon is unusable: build natively on an
      # x86_64 host over SSH — no QEMU emulation — then push to GHCR from there and
      # clean up after itself on every exit path. Use a host you own for builds,
      # not a production server.
      key="${REMOTE_BUILD_KEY:-}"; ssh_opts=(-o BatchMode=yes)
      [ -n "$key" ] && ssh_opts+=(-i "$key")
      docker="${DOCKER_CMD:-docker}"
      ghcr_user="${GHCR_USER:?set GHCR_USER (the account `gh auth token` belongs to)}"
      remote_dir="~/.render-build-$svc"
      echo "building $img:$sha on $REMOTE_BUILD_HOST (local docker unavailable)"
      arch=$(ssh "${ssh_opts[@]}" "$REMOTE_BUILD_HOST" 'uname -m')
      [ "$arch" = "x86_64" ] || { echo "remote host is $arch, need x86_64 for a native linux/amd64 build" >&2; exit 1; }
      ssh "${ssh_opts[@]}" "$REMOTE_BUILD_HOST" "rm -rf $remote_dir && mkdir -p $remote_dir"
      rsync -az -e "ssh ${ssh_opts[*]}" --exclude '.venv' --exclude '__pycache__' \
        --exclude '*.pyc' --exclude 'staticfiles' --exclude '.env' --exclude 'db.sqlite3*' \
        "$dir/$ctx/" "$REMOTE_BUILD_HOST:$remote_dir/"
      gh auth token | ssh "${ssh_opts[@]}" "$REMOTE_BUILD_HOST" \
        "$docker login ghcr.io -u $ghcr_user --password-stdin >/dev/null 2>&1 \
         && cd $remote_dir \
         && $docker build -q --build-arg RELEASE_SHA=$full_sha -f $df -t $img:$sha -t $img:latest . \
         && $docker push -q $img:$sha && $docker push -q $img:latest \
         && $docker inspect $img:$sha --format '{{.Architecture}}/{{.Os}}' \
         ; code=\$?; rm -rf $remote_dir; $docker rmi $img:$sha $img:latest >/dev/null 2>&1; \
           $docker image prune -f >/dev/null 2>&1; $docker logout ghcr.io >/dev/null 2>&1; exit \$code"
    else
      ( cd "$dir/$ctx" && docker buildx build --platform linux/amd64 -f "$df" \
          --build-arg "RELEASE_SHA=$full_sha" -t "$img:$sha" -t "$img:latest" --push . )
    fi
    echo "pushed $img:$sha (+latest)" ;;
  create)
    img=$(cfg image); envfile=$(eval echo "$(cfg envFile)")
    # The payload carries the env var values, so go through a 0600 temp file,
    # never an argv — the process table can read those.
    tmp=$(mktemp --tmpdir "$svc-create-XXXXXX.json"); chmod 600 "$tmp"
    trap 'rm -f "$tmp"' EXIT
    jq -n --slurpfile ev "$envfile" \
      --arg name "$svc" --arg owner "$OWNER_ID" --arg img "$img:latest" --arg cred "$REGISTRY_CRED" \
      --arg plan "$(cfg plan)" --arg hc "$(cfg healthCheckPath)" --arg region "$REGION" \
      '{type:"web_service", name:$name, ownerId:$owner,
        image:{ownerId:$owner, imagePath:$img, registryCredentialId:$cred},
        envVars:$ev[0],
        serviceDetails:{env:"image", region:$region, plan:$plan, healthCheckPath:$hc}}' > "$tmp"
    resp=$(api POST /services --data-binary @"$tmp")
    id=$(echo "$resp" | jq -r .service.id); url=$(echo "$resp" | jq -r .service.serviceDetails.url)
    jq ".\"$svc\".serviceId = \"$id\"" "$REG" > "$REG.tmp" && mv "$REG.tmp" "$REG"
    echo "created $id → $url" ;;
  deploy)
    tag=${3:-latest}; img=$(cfg image)
    api POST "/services/$(sid)/deploys" -d "{\"imageUrl\":\"$img:$tag\"}" | jq -r '"deploy " + .id + " → " + .status' ;;
  release)
    # Deploy the commit-tagged image, not :latest — :latest moves under you and
    # makes "which commit is live?" unanswerable from the Render side.
    "$0" build "$svc" && "$0" deploy "$svc" "$(git -C "$(cfg repoDir)" rev-parse --short HEAD)" ;;
  env)
    # Upsert per key: PUT updates one key in place (404 → POST creates it).
    # Never use the bulk PUT on /env-vars: it REPLACES the service's entire env
    # var list, so every key absent from the file would be deleted.
    envfile=$(eval echo "$(cfg envFile)")
    jq -r '.[] | "\(.key)\t\(.value|tojson)"' "$envfile" | while IFS=$'\t' read -r k v; do
      [ -n "$k" ] || continue
      body=$(mktemp --tmpdir "$svc-env-XXXXXX.json"); chmod 600 "$body"
      printf '{"value":%s}' "$v" > "$body"
      code=$(printf 'Authorization: Bearer %s\n' "$KEY" | \
        curl -s -o /dev/null -w '%{http_code}' -X PUT "$API/services/$(sid)/env-vars/$k" \
        -H @- -H 'Content-Type: application/json' --data-binary @"$body") || code=000
      if [ "$code" != "200" ]; then
        jq -cn --arg k "$k" --argjson v "$v" '{key:$k, value:$v}' > "$body"
        api POST "/services/$(sid)/env-vars" --data-binary @"$body" >/dev/null
      fi
      echo "upserted $k ($code)"
      rm -f "$body"
    done ;;
  status)
    api GET "/services/$(sid)" | jq '{name:.name, suspended:.suspended, url:.serviceDetails.url}'
    api GET "/services/$(sid)/deploys?limit=1" | jq -r '.[0].deploy | "latest deploy: \(.id) \(.status) (\(.createdAt))"' ;;
  domain)
    domain=${3:-$(cfg customDomain)}
    api POST "/services/$(sid)/custom-domains" -d "{\"name\":\"$domain\"}"; echo ;;
  logs)
    api GET "/services/$(sid)/deploys?limit=5" | jq -r '.[].deploy | .id + " " + .status + " " + .createdAt' ;;
  *) echo "unknown cmd: $cmd" >&2; exit 1;;
esac
