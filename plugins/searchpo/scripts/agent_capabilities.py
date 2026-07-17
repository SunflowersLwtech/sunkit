#!/usr/bin/env python3
"""Report Searchpo agent capabilities without exposing secret values."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "config" / "agent_capabilities.json"
DEFAULT_ENV = ROOT / ".env"
DEFAULT_MCP = ROOT / ".mcp.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def effective_env(env_file: Path) -> dict[str, str]:
    values = parse_env(env_file)
    for key in set(values) | set(os.environ):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def capability_status(capability: dict[str, Any], values: dict[str, str]) -> str:
    required_all = capability.get("required_all", [])
    required_any = capability.get("required_any", [])
    env_keys = capability.get("env", [])
    if capability.get("kind") == "mcp":
        return "available"
    if required_all and any(not values.get(key) for key in required_all):
        return "unavailable"
    if required_any and not any(values.get(key) for key in required_any):
        return "unavailable"
    if any(values.get(key) for key in env_keys):
        return "available"
    return "configured"


def select_capabilities(catalog: dict[str, Any], profile: str) -> list[dict[str, Any]]:
    capabilities = catalog.get("capabilities", [])
    if profile == "all":
        return capabilities
    return [
        capability
        for capability in capabilities
        if profile in capability.get("profiles", [])
    ]


def mcp_status(mcp_file: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    expected = catalog.get("mcp_servers", {}).get("deepwiki", {})
    expected_url = expected.get("url")
    exists = mcp_file.exists()
    configured = False
    if exists:
        try:
            data = load_json(mcp_file)
            server = data.get("mcpServers", {}).get("deepwiki", {})
            configured = server.get("url") == expected_url and server.get("type") == expected.get("type")
        except json.JSONDecodeError:
            configured = False
    return {
        "config_file": str(mcp_file),
        "exists": exists,
        "deepwiki_configured": configured,
        "server": "deepwiki",
        "url": expected_url,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    catalog_path = Path(args.catalog).expanduser().resolve()
    env_path = Path(args.env_file).expanduser().resolve()
    mcp_path = Path(args.mcp_file).expanduser().resolve()
    catalog = load_json(catalog_path)
    values = effective_env(env_path)
    selected = select_capabilities(catalog, args.profile)
    capability_reports = []
    for capability in selected:
        env_keys = capability.get("env", [])
        present = [key for key in env_keys if values.get(key)]
        missing = [key for key in env_keys if not values.get(key)]
        capability_reports.append(
            {
                "id": capability["id"],
                "owner_agent": capability["owner_agent"],
                "kind": capability["kind"],
                "status": capability_status(capability, values),
                "present_env": present,
                "missing_env": missing,
                "required_all": capability.get("required_all", []),
                "required_any": capability.get("required_any", []),
                "mcp_server": capability.get("mcp_server"),
                "purpose": capability.get("purpose", ""),
            }
        )
    return {
        "catalog": str(catalog_path),
        "env_file": str(env_path),
        "env_file_exists": env_path.exists(),
        "profile": args.profile,
        "secrets_omitted": True,
        "mcp": mcp_status(mcp_path, catalog),
        "capabilities": capability_reports,
        "notes": [
            "Only environment variable names and availability are reported.",
            "Do not print or persist .env values in agent logs.",
            "DeepWiki MCP is supporting repo context; publishable claims still require canonical evidence and cross-check artifacts.",
            "Live publishing remains gated by an explicit current-run user request plus the Searchpo live profile.",
        ],
    }


def check_catalog(args: argparse.Namespace, report: dict[str, Any]) -> list[str]:
    catalog = load_json(Path(args.catalog).expanduser().resolve())
    declared = catalog.get("declared_env", [])
    errors: list[str] = []
    if len(declared) != len(set(declared)):
        errors.append("declared_env contains duplicate keys")
    capability_env = {
        key
        for capability in catalog.get("capabilities", [])
        for key in capability.get("env", [])
    }
    unused_declared = sorted(set(declared) - capability_env)
    undeclared_used = sorted(capability_env - set(declared))
    if unused_declared:
        errors.append(f"declared_env keys are not routed by any capability: {', '.join(unused_declared)}")
    if undeclared_used:
        errors.append(f"capability keys are missing from declared_env: {', '.join(undeclared_used)}")
    for env_file in [Path(args.env_file).expanduser().resolve(), ROOT / ".env.example"]:
        values = parse_env(env_file)
        if values:
            unknown = sorted(set(values) - set(declared))
            if unknown:
                errors.append(f"{env_file} contains undeclared keys: {', '.join(unknown)}")
    if not report["mcp"]["deepwiki_configured"]:
        errors.append(".mcp.json does not contain the expected deepwiki HTTP server")
    return errors


def print_text(report: dict[str, Any]) -> None:
    print(f"Searchpo agent capability profile: {report['profile']}")
    print(f"env_file_exists={report['env_file_exists']} secrets_omitted=true")
    print(
        "mcp.deepwiki="
        + ("configured" if report["mcp"]["deepwiki_configured"] else "missing")
        + f" url={report['mcp']['url']}"
    )
    for capability in report["capabilities"]:
        present = ",".join(capability["present_env"]) or "-"
        missing_required = [
            key
            for key in capability["required_all"]
            if key not in capability["present_env"]
        ]
        if capability["required_any"] and not any(key in capability["present_env"] for key in capability["required_any"]):
            missing_required.append("one of " + "/".join(capability["required_any"]))
        missing = ",".join(missing_required) or "-"
        print(
            f"- {capability['id']} owner={capability['owner_agent']} "
            f"kind={capability['kind']} status={capability['status']} "
            f"present_env={present} missing_required={missing}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--env-file", default=str(DEFAULT_ENV))
    parser.add_argument("--mcp-file", default=str(DEFAULT_MCP))
    parser.add_argument(
        "--profile",
        default="all",
        choices=[
            "all",
            "main",
            "research",
            "repo",
            "paper",
            "topic",
            "review",
            "implementation",
            "provider",
            "render",
            "lambda",
            "publish",
            "live",
            "social",
            "notify",
        ],
    )
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--check", action="store_true", help="Validate catalog coverage and MCP config.")
    args = parser.parse_args()

    report = build_report(args)
    if args.format == "text":
        print_text(report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.check:
        errors = check_catalog(args, report)
        if errors:
            for error in errors:
                print(f"agent capability check: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
