#!/usr/bin/env python3
"""Record or execute a Douyin rollback action for a mismatched live publish."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--remote-id", help="Remote post/item id. Defaults to post_publish_verification.json.")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--status", default="manual-action-required", choices=["manual-action-required", "deleted", "unpublished", "failed"])
    parser.add_argument("--operator", default="local_operator")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    verification = read_json(run_dir / "post" / "post_publish_verification.json")
    remote = verification.get("remote") if isinstance(verification.get("remote"), dict) else {}
    remote_id = args.remote_id or str(remote.get("remote_post_id") or "")
    if not remote_id:
        raise SystemExit("remote id required; pass --remote-id or create post_publish_verification.json first")
    path = run_dir / "post" / "rollback_ledger.json"
    ledger = read_json(path) or {"schema_version": 1, "entries": []}
    ledger.setdefault("entries", []).append(
        {
            "created_at": utc_now(),
            "remote_post_id": remote_id,
            "permalink": remote.get("permalink"),
            "operator": args.operator,
            "reason": args.reason,
            "status": args.status,
        }
    )
    ledger["updated_at"] = utc_now()
    write_json(path, ledger)
    print(json.dumps({"rollback_ledger": str(path), "remote_post_id": remote_id, "status": args.status}, ensure_ascii=False, indent=2))
    return 0 if args.status in {"deleted", "unpublished", "manual-action-required"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
