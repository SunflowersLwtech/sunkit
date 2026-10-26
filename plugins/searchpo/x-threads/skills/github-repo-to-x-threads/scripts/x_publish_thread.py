#!/usr/bin/env python3
"""Publish a governed posting pack as an X thread using the official X API.

The script defaults to dry-run. Use --live to create real posts. It supports the
first post and subsequent thread replies from the CLI, including image upload and
best-effort alt text metadata.
"""

from __future__ import annotations

import argparse
import base64
import os
import hashlib
import hmac
import json
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_BASE = "https://api.x.com"
TOKEN_URL = f"{API_BASE}/2/oauth2/token"
OAUTH1_MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
OAUTH1_MEDIA_METADATA_URL = "https://upload.twitter.com/1.1/media/metadata/create.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def load_env(paths: list[Path]) -> tuple[dict[str, str], Path | None]:
    merged: dict[str, str] = {}
    highest_precedence_existing: Path | None = None
    for path in paths:
        expanded = path.expanduser().resolve()
        values = load_env_file(expanded)
        if values:
            highest_precedence_existing = expanded
        merged.update(values)
    return merged, highest_precedence_existing


def upsert_env(path: Path, values: dict[str, str]) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                out.append(f"{key}={values[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


VK_FIELDS = (
    "X_CLIENT_ID",
    "X_CLIENT_SECRET",
    "X_OAUTH2_ACCESS_TOKEN",
    "X_OAUTH2_REFRESH_TOKEN",
    "X_OAUTH2_TOKEN_EXPIRES_AT",
)


def load_env_vk(entry: str) -> dict[str, str]:
    """The X tokens straight from Vaultwarden (`vk render` into a 0600 file in the temp dir, read, deleted at once).

    Vaultwarden rotates nothing on its own, but X rotates the refresh token on every use and other pipelines share
    the same entry: what this script reads at the start is what every other caller reads after it writes back.
    """
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory(prefix="r2x-vk-") as tmp:
        template = Path(tmp) / "t"
        out = Path(tmp) / "o"
        template.write_text("".join(f"{k}=vk://{entry}/{k}\n" for k in VK_FIELDS), encoding="utf-8")
        result = subprocess.run(["vk", "render", "-f", str(template), "-o", str(out)], capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(f"vk render failed for {entry}: {result.stderr[-200:]}")
        return load_env_file(out)


def save_env_vk(entry: str, values: dict[str, str]) -> None:
    """Write the rotated tokens back to Vaultwarden, on stdin, before they are used anywhere."""
    import subprocess

    for key, value in values.items():
        if not value:
            continue
        result = subprocess.run(["vk", "set", entry, key], input=value, capture_output=True, text=True)
        if result.returncode != 0 or value in (result.stdout + result.stderr):
            raise SystemExit(f"vk set {key} failed")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_ready_to_post(markdown: str) -> list[str]:
    match = re.search(r"(?is)##\s+Ready\s+To\s+Post.*?```(?:text)?\s*(.*?)```", markdown)
    if not match:
        return []
    block = match.group(1).strip()
    starts = list(re.finditer(r"(?m)^\(\d+/\d+\)", block))
    if starts:
        posts: list[str] = []
        for index, start in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(block)
            posts.append(block[start.start() : end].strip())
        return posts
    return [part.strip() for part in re.split(r"\n\s*\n", block) if part.strip()]


def post_index_from_label(label: str, default: int) -> int:
    match = re.match(r"\s*(?:Post\s*)?(\d+)\s*/", str(label), flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.match(r"\s*(?:Post\s*)?(\d+)\b", str(label), flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return default


def build_queue(repo_run_dir: Path) -> dict[str, Any]:
    posting_pack = repo_run_dir / "posting_pack.md"
    if not posting_pack.exists():
        raise SystemExit(f"posting_pack.md not found: {posting_pack}")
    posts = extract_ready_to_post(posting_pack.read_text(encoding="utf-8"))
    if not posts:
        raise SystemExit("Could not find a Ready To Post text block in posting_pack.md")

    images_by_post: dict[int, list[str]] = {}
    manifest_path = repo_run_dir / "images_manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        for image in manifest.get("images", []):
            image_id = str(image.get("id", ""))
            if not image_id:
                continue
            index = post_index_from_label(str(image.get("post", "")), 1)
            if image.get("path"):
                images_by_post.setdefault(index, []).append(image_id)

    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "reply_mode": "previous",
        "posts": [
            {
                "index": index,
                "text": text,
                "image_ids": images_by_post.get(index, []),
            }
            for index, text in enumerate(posts, start=1)
        ],
    }


def load_or_create_queue(repo_run_dir: Path, queue_path: Path | None) -> tuple[dict[str, Any], Path]:
    target = queue_path or (repo_run_dir / "posting_queue.json")
    if target.exists():
        return read_json(target), target
    queue = build_queue(repo_run_dir)
    write_json(target, queue)
    return queue, target


def image_lookup(repo_run_dir: Path) -> dict[str, dict[str, Any]]:
    manifest_path = repo_run_dir / "images_manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = read_json(manifest_path)
    return {str(image.get("id")): image for image in manifest.get("images", []) if image.get("id")}


def make_multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"----repo-to-x-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for key, (filename, content, content_type) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def api_json(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def api_multipart(url: str, token: str, fields: dict[str, str], file_path: Path) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body, content_type = make_multipart(
        fields,
        {"media": (file_path.name, file_path.read_bytes(), mime_type)},
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def api_media_upload_json(url: str, token: str, fields: dict[str, str], file_path: Path) -> dict[str, Any]:
    payload = {
        **fields,
        "media": base64.b64encode(file_path.read_bytes()).decode("ascii"),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def oauth1_credentials(env: dict[str, str]) -> dict[str, str]:
    creds = {
        "consumer_key": env.get("X_CONSUMER_KEY") or env.get("TWITTER_CONSUMER_KEY") or "",
        "consumer_secret": env.get("X_CONSUMER_SECRET") or env.get("TWITTER_CONSUMER_SECRET") or "",
        "access_token": env.get("X_ACCESS_TOKEN") or env.get("TWITTER_ACCESS_TOKEN") or "",
        "access_token_secret": env.get("X_ACCESS_TOKEN_SECRET") or env.get("TWITTER_ACCESS_TOKEN_SECRET") or "",
    }
    return creds if all(creds.values()) else {}


def pct(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~")


def oauth1_authorization(
    method: str,
    url: str,
    env: dict[str, str],
    params: dict[str, str] | None = None,
) -> str:
    creds = oauth1_credentials(env)
    if not creds:
        raise RuntimeError("missing OAuth1 user credentials for media upload path")
    oauth_params = {
        "oauth_consumer_key": creds["consumer_key"],
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    signature_params = {**oauth_params, **(params or {})}
    normalized = "&".join(f"{pct(key)}={pct(value)}" for key, value in sorted(signature_params.items()))
    base = "&".join([method.upper(), pct(url), pct(normalized)])
    signing_key = f"{pct(creds['consumer_secret'])}&{pct(creds['access_token_secret'])}"
    signature = base64.b64encode(hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()).decode("ascii")
    oauth_params["oauth_signature"] = signature
    return "OAuth " + ", ".join(f'{pct(key)}="{pct(value)}"' for key, value in sorted(oauth_params.items()))


def api_multipart_oauth1(url: str, env: dict[str, str], fields: dict[str, str], file_path: Path) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body, content_type = make_multipart(
        fields,
        {"media": (file_path.name, file_path.read_bytes(), mime_type)},
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": oauth1_authorization("POST", url, env, fields),
            "Content-Type": content_type,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def api_json_oauth1(method: str, url: str, env: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": oauth1_authorization(method, url, env),
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def refresh_access_token(env: dict[str, str], env_path: Path | None, vk_entry: str = "") -> str:
    refresh_token = env.get("X_OAUTH2_REFRESH_TOKEN") or env.get("X_REFRESH_TOKEN", "")
    client_id = env.get("X_CLIENT_ID", "")
    client_secret = env.get("X_CLIENT_SECRET", "")
    if not refresh_token or not client_id:
        return ""

    data: dict[str, str] = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if client_secret:
        raw = f"{client_id}:{client_secret}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    else:
        data["client_id"] = client_id

    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"refresh token failed: HTTP {exc.code}: {detail}") from exc

    access = str(payload.get("access_token", ""))
    if not access:
        return ""
    env["X_OAUTH2_ACCESS_TOKEN"] = access
    if payload.get("refresh_token"):
        env["X_OAUTH2_REFRESH_TOKEN"] = str(payload["refresh_token"])
    if vk_entry:
        # The refresh token is written first: the old one is already dead, so losing the new one means a new sign-in.
        updates = {"X_OAUTH2_REFRESH_TOKEN": env.get("X_OAUTH2_REFRESH_TOKEN", ""),
                   "X_OAUTH2_ACCESS_TOKEN": env["X_OAUTH2_ACCESS_TOKEN"]}
        if payload.get("expires_in"):
            updates["X_OAUTH2_TOKEN_EXPIRES_AT"] = datetime.fromtimestamp(
                time.time() + int(payload["expires_in"]), timezone.utc
            ).isoformat()
        save_env_vk(vk_entry, updates)
    elif env_path:
        updates = {
            "X_OAUTH2_ACCESS_TOKEN": env["X_OAUTH2_ACCESS_TOKEN"],
            "X_OAUTH2_REFRESH_TOKEN": env.get("X_OAUTH2_REFRESH_TOKEN", ""),
        }
        upsert_env(env_path, {key: value for key, value in updates.items() if value})
    return access


def resolve_image_file(repo_run_dir: Path, image: dict[str, Any]) -> Path:
    relative = str(image.get("path", ""))
    if not relative:
        raise SystemExit(f"image {image.get('id')} has no governed local path")
    path = (repo_run_dir / relative).resolve()
    if not path.exists() or not path.is_file():
        raise SystemExit(f"image file missing: {path}")
    return path


def upload_image(token: str, env: dict[str, str], repo_run_dir: Path, image: dict[str, Any]) -> str:
    path = resolve_image_file(repo_run_dir, image)
    mime_type = str(image.get("mime_type") or mimetypes.guess_type(path.name)[0] or "image/png")
    used_oauth1 = False
    fields = {"media_category": "tweet_image", "media_type": mime_type}
    try:
        response = api_multipart(
            f"{API_BASE}/2/media/upload",
            token,
            fields,
            path,
        )
    except RuntimeError as exc:
        if "HTTP 401" not in str(exc):
            raise
        try:
            response = api_media_upload_json(f"{API_BASE}/2/media/upload", token, fields, path)
        except RuntimeError:
            if not oauth1_credentials(env):
                raise
            response = api_multipart_oauth1(
                OAUTH1_MEDIA_UPLOAD_URL,
                env,
                {"media_category": "tweet_image"},
                path,
            )
            used_oauth1 = True
    media_id = str(response.get("data", {}).get("id") or response.get("media_id") or "")
    if not media_id:
        raise RuntimeError(f"media upload did not return id for {path}: {response}")
    alt_text = str(image.get("alt_text") or "").strip()
    if alt_text:
        try:
            api_json(
                "POST",
                f"{API_BASE}/2/media/metadata",
                token,
                {"id": media_id, "metadata": {"alt_text": {"text": alt_text}}},
            )
        except RuntimeError as exc:
            if used_oauth1:
                try:
                    api_json_oauth1(
                        "POST",
                        OAUTH1_MEDIA_METADATA_URL,
                        env,
                        {"media_id": media_id, "alt_text": {"text": alt_text}},
                    )
                except RuntimeError as oauth1_exc:
                    print(f"Warning: alt text metadata failed for {image.get('id')}: {oauth1_exc}", file=sys.stderr)
            else:
                print(f"Warning: alt text metadata failed for {image.get('id')}: {exc}", file=sys.stderr)
    return media_id


def post_tweet(token: str, text: str, media_ids: list[str], reply_to: str | None, made_with_ai: bool) -> str:
    payload: dict[str, Any] = {"text": text}
    if media_ids:
        payload["media"] = {"media_ids": media_ids}
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to}
    if made_with_ai:
        payload["made_with_ai"] = True
    response = api_json("POST", f"{API_BASE}/2/tweets", token, payload)
    tweet_id = str(response.get("data", {}).get("id") or "")
    if not tweet_id:
        raise RuntimeError(f"post response did not include id: {response}")
    return tweet_id


def generated_image(image: dict[str, Any]) -> bool:
    source = str(image.get("source_type", ""))
    model = str(image.get("model", ""))
    return source.startswith("gpt_") or "gpt-image" in model


def publish(args: argparse.Namespace) -> int:
    repo_run_dir = Path(args.repo_run_dir).expanduser().resolve()
    if not repo_run_dir.exists():
        raise SystemExit(f"repo_run_dir does not exist: {repo_run_dir}")
    queue, queue_path = load_or_create_queue(repo_run_dir, Path(args.queue).expanduser().resolve() if args.queue else None)
    images = image_lookup(repo_run_dir)
    log: dict[str, Any] = {
        "schema_version": 1,
        "created_at": utc_now(),
        "dry_run": not args.live,
        "repo_run_dir": str(repo_run_dir),
        "queue": str(queue_path),
        "posts": [],
    }

    vk_entry = args.vk_entry or os.environ.get("REPO2X_VK_ENTRY", "")
    if vk_entry:
        env, env_path = load_env_vk(vk_entry), None
    else:
        env, env_path = load_env([repo_run_dir / ".env", Path.cwd() / ".env", Path(args.env_file)])
    token = env.get("X_OAUTH2_ACCESS_TOKEN") or env.get("X_USER_ACCESS_TOKEN", "")
    if args.live and not token:
        token = refresh_access_token(env, env_path, vk_entry)
    if args.live and not token:
        raise SystemExit(
            "Missing X_OAUTH2_ACCESS_TOKEN. Run x_oauth2_pkce_setup.py first, or provide an env file with a user token."
        )

    root_tweet_id = ""
    previous_tweet_id = ""
    reply_mode = args.reply_mode or str(queue.get("reply_mode") or "previous")
    for default_index, post in enumerate(queue.get("posts", []), start=1):
        index = int(post.get("index") or default_index)
        text = str(post.get("text", "")).strip()
        if not text:
            raise SystemExit(f"post {index} has empty text")
        image_ids = [str(image_id) for image_id in post.get("image_ids", [])]
        post_images = [images[image_id] for image_id in image_ids if image_id in images]
        missing = [image_id for image_id in image_ids if image_id not in images]
        if missing:
            raise SystemExit(f"post {index} references missing image ids: {', '.join(missing)}")
        if len(post_images) > 4:
            raise SystemExit(f"post {index} has {len(post_images)} images; X supports up to 4 images per post")

        reply_to = None
        planned_reply_to = ""
        if index > 1:
            planned_reply_to = "root post" if reply_mode == "root" else "previous post"
            reply_to = root_tweet_id if reply_mode == "root" else previous_tweet_id
            if args.live and not reply_to:
                raise SystemExit(f"post {index} has no previous tweet id to reply to")

        entry: dict[str, Any] = {
            "index": index,
            "text_chars": len(text),
            "image_ids": image_ids,
            "reply_to": reply_to or "",
            "planned_reply_to": planned_reply_to,
            "made_with_ai": any(generated_image(image) for image in post_images),
            "image_warnings": [],
            "status": "planned",
        }
        if not args.live:
            for image in post_images:
                if not image.get("path"):
                    raise SystemExit(f"post {index} references image {image.get('id')} with no governed local path")
                resolve_image_file(repo_run_dir, image)
        if args.live:
            media_ids = [upload_image(token, env, repo_run_dir, image) for image in post_images]
            try:
                tweet_id = post_tweet(token, text, media_ids, reply_to, bool(entry["made_with_ai"]))
            except RuntimeError as exc:
                if "401" in str(exc):
                    token = refresh_access_token(env, env_path, vk_entry)
                    if not token:
                        raise
                    tweet_id = post_tweet(token, text, media_ids, reply_to, bool(entry["made_with_ai"]))
                else:
                    raise
            entry["status"] = "posted"
            entry["tweet_id"] = tweet_id
            entry["media_ids"] = media_ids
            if index == 1:
                root_tweet_id = tweet_id
            previous_tweet_id = tweet_id
            print(f"Posted {index}: {tweet_id}")
            time.sleep(args.delay_seconds)
        else:
            entry["status"] = "dry_run"
            print(
                f"[dry-run] post {index}: {len(text)} chars, images={image_ids}, "
                f"reply_to={reply_to or planned_reply_to or 'none'}"
            )
        log["posts"].append(entry)

    log["updated_at"] = utc_now()
    write_json(repo_run_dir / "x_publish_log.json", log)
    print(f"Wrote publish log: {repo_run_dir / 'x_publish_log.json'}")
    if not args.live:
        print("Dry run only. Re-run with --live to publish through the official X API.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_run_dir", help="Repo directory under repo-to-x-workspace/runs/<run-id>/repos/<repo-id>")
    parser.add_argument("--queue", help="posting_queue.json path; generated from posting_pack.md when absent")
    parser.add_argument("--env-file", default=".env", help="Local env file containing X OAuth2 user tokens")
    parser.add_argument("--reply-mode", choices=["previous", "root"], help="Thread replies target previous post or root post")
    parser.add_argument("--delay-seconds", type=float, default=1.0, help="Delay between live posts")
    parser.add_argument("--live", action="store_true", help="Actually publish posts. Default is dry-run.")
    parser.add_argument("--vk-entry", default="",
                        help="Read and write the X tokens in this Vaultwarden entry instead of an env file "
                        "(also REPO2X_VK_ENTRY). When set, .env files are not read and refreshes are written "
                        "back to Vaultwarden before they are used.")
    args = parser.parse_args()
    return publish(args)


if __name__ == "__main__":
    sys.exit(main())
