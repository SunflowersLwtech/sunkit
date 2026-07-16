#!/usr/bin/env python3
"""Get an official X OAuth2 user token for publishing posts from the CLI.

This is a one-time local setup helper. It opens the X consent page, receives the
OAuth callback on localhost, exchanges the code, and writes only secret values to
the chosen local .env file. Never commit that .env file.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

DEFAULT_SCOPES = "tweet.read users.read tweet.write media.write offline.access"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"


def utc_expiry(expires_in: int | str | None) -> str:
    try:
        seconds = int(expires_in or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return ""
    return datetime.fromtimestamp(time.time() + seconds, tz=timezone.utc).replace(microsecond=0).isoformat()


def load_env(path: Path) -> dict[str, str]:
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


def upsert_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
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
    if out and out[-1].strip():
        out.append("")
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def make_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(client_id: str, redirect_uri: str, scope: str, state: str, challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


class CallbackState:
    def __init__(self, expected_state: str) -> None:
        self.expected_state = expected_state
        self.code = ""
        self.error = ""
        self.event = threading.Event()


def make_handler(callback: CallbackState, callback_path: str) -> type[BaseHTTPRequestHandler]:
    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            status = 200
            body = "X OAuth setup complete. You can close this tab and return to the terminal."
            if parsed.path != callback_path:
                status = 404
                body = "Unexpected OAuth callback path."
            elif query.get("state", [""])[0] != callback.expected_state:
                status = 400
                body = "OAuth state mismatch. Do not use this token response."
                callback.error = body
                callback.event.set()
            elif "error" in query:
                status = 400
                body = f"OAuth error: {query.get('error', ['unknown'])[0]}"
                callback.error = body
                callback.event.set()
            else:
                callback.code = query.get("code", [""])[0]
                callback.event.set()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return OAuthCallbackHandler


def exchange_code(
    *,
    code: str,
    verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict[str, Any]:
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
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
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"X token exchange failed: HTTP {exc.code}: {detail}") from exc
    return json.loads(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="Local env file to read/update")
    parser.add_argument("--client-id", help="X OAuth2 Client ID; defaults to X_CLIENT_ID in env")
    parser.add_argument("--client-secret", help="Optional X OAuth2 Client Secret; defaults to X_CLIENT_SECRET in env")
    parser.add_argument("--redirect-uri", help="Callback URL registered in X Developer Portal")
    parser.add_argument("--scope", default=DEFAULT_SCOPES, help="Space-separated OAuth2 scopes")
    parser.add_argument("--no-open", action="store_true", help="Print the URL instead of opening the browser")
    args = parser.parse_args()

    env_path = Path(args.env_file).expanduser().resolve()
    env = load_env(env_path)
    client_id = args.client_id or env.get("X_CLIENT_ID", "")
    client_secret = args.client_secret or env.get("X_CLIENT_SECRET", "")
    redirect_uri = args.redirect_uri or env.get("X_REDIRECT_URI", "http://127.0.0.1:8765/callback")

    if not client_id:
        raise SystemExit(
            "Missing X_CLIENT_ID. Create an X Developer App, enable OAuth2, register "
            "the callback URL, then put X_CLIENT_ID in your local .env."
        )

    parsed_redirect = urllib.parse.urlparse(redirect_uri)
    if parsed_redirect.scheme != "http" or parsed_redirect.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("This helper only accepts localhost HTTP redirect URIs, e.g. http://127.0.0.1:8765/callback")
    if not parsed_redirect.port:
        raise SystemExit("Redirect URI must include a port, e.g. http://127.0.0.1:8765/callback")

    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    callback = CallbackState(state)
    handler = make_handler(callback, parsed_redirect.path or "/callback")
    server = HTTPServer((parsed_redirect.hostname, parsed_redirect.port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = build_authorize_url(client_id, redirect_uri, args.scope, state, challenge)
    print("Open this X authorization URL and approve posting permissions:")
    print(url)
    if not args.no_open:
        webbrowser.open(url)
    print(f"Waiting for callback on {redirect_uri} ...")

    try:
        if not callback.event.wait(timeout=300):
            raise SystemExit("Timed out waiting for OAuth callback.")
    finally:
        server.shutdown()

    if callback.error:
        raise SystemExit(callback.error)
    if not callback.code:
        raise SystemExit("OAuth callback did not include a code.")

    token = exchange_code(
        code=callback.code,
        verifier=verifier,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    access_token = str(token.get("access_token", ""))
    refresh_token = str(token.get("refresh_token", ""))
    if not access_token:
        raise SystemExit("Token response did not include access_token.")

    updates = {
        "X_CLIENT_ID": client_id,
        "X_REDIRECT_URI": redirect_uri,
        "X_OAUTH2_ACCESS_TOKEN": access_token,
        "X_OAUTH2_TOKEN_EXPIRES_AT": utc_expiry(token.get("expires_in")),
        "X_OAUTH2_SCOPES": args.scope,
    }
    if client_secret:
        updates["X_CLIENT_SECRET"] = client_secret
    if refresh_token:
        updates["X_OAUTH2_REFRESH_TOKEN"] = refresh_token
    upsert_env(env_path, updates)

    print(f"Updated local env file: {env_path}")
    print("Wrote keys: " + ", ".join(sorted(updates)))
    print("Do not commit this env file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
