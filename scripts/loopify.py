#!/usr/bin/env python3
"""Create a deterministic loop-readiness scaffold from a raw request."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


def infer_loop_type(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ["daily", "weekly", "hourly", "schedule", "cron", "每天", "每周", "定时"]):
        return "scheduled"
    if any(word in lowered for word in ["monitor", "watch", "alert", "check if", "跟踪", "监控"]):
        return "monitor"
    if any(word in lowered for word in ["webhook", "event", "pr ", "pull request", "github", "alert"]):
        return "event_driven"
    if any(word in lowered for word in ["research", "scan", "collect", "paper", "repo", "调研", "收集"]):
        return "long_horizon"
    return "one_shot"


def infer_autonomy(loop_type: str) -> str:
    if loop_type in {"scheduled", "monitor"}:
        return "L2 supervised loop"
    if loop_type == "event_driven":
        return "L2 supervised loop; promote to L4 only after verification passes"
    if loop_type == "long_horizon":
        return "L1 reusable prompt or L2 supervised loop"
    return "L1 reusable prompt"


def build_contract(text: str) -> dict[str, object]:
    loop_type = infer_loop_type(text)
    return {
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "raw_request": text,
        "classification": loop_type,
        "autonomy_level": infer_autonomy(loop_type),
        "loopified_requirement": {
            "goal": "Make the requested outcome repeatedly true; replace this with a measurable outcome.",
            "trigger": "Manual start unless the request names a schedule, event, or monitor condition.",
            "state": "List the files, logs, sources, metrics, tickets, PRs, or messages to inspect each iteration.",
            "scope": "Start read-only. Add write permissions only after verification and rollback are explicit.",
        },
        "loop_contract": {
            "allowed_actions": [
                "inspect current state",
                "summarize evidence",
                "propose next action",
            ],
            "forbidden_actions": [
                "delete data",
                "merge/publish/deploy",
                "change credentials or payment settings",
                "expand scope without approval",
            ],
            "verification": [
                "define at least one objective check",
                "record command, source, or reviewer evidence",
            ],
            "escalation": [
                "ambiguous ownership",
                "destructive or public action",
                "same failure repeats twice",
                "missing required evidence",
            ],
            "stop_conditions": [
                "goal reached",
                "verification fails repeatedly",
                "permission boundary reached",
                "source unavailable",
            ],
            "audit_log": [
                "iteration timestamp",
                "state inspected",
                "action taken or proposed",
                "verification result",
                "reason for stop/escalation",
            ],
        },
    }


def to_markdown(contract: dict[str, object]) -> str:
    req = contract["loopified_requirement"]
    loop = contract["loop_contract"]
    assert isinstance(req, dict)
    assert isinstance(loop, dict)

    def bullets(values: object) -> str:
        if isinstance(values, list):
            return "\n".join(f"- {value}" for value in values)
        return f"- {values}"

    return f"""## Loopified Requirement
- Goal: {req["goal"]}
- Trigger: {req["trigger"]}
- State: {req["state"]}
- Scope: {req["scope"]}
- Classification: {contract["classification"]}
- Autonomy level: {contract["autonomy_level"]}

## Loop Contract
Allowed actions:
{bullets(loop["allowed_actions"])}

Forbidden actions:
{bullets(loop["forbidden_actions"])}

Verification:
{bullets(loop["verification"])}

Escalation:
{bullets(loop["escalation"])}

Stop conditions:
{bullets(loop["stop_conditions"])}

Audit log:
{bullets(loop["audit_log"])}

## Loop Prompt
```text
You are running a bounded loop for this request:
{contract["raw_request"]}

On each iteration:
1. Inspect only the defined state.
2. Compare current state with the goal.
3. Take only allowed actions.
4. Run or describe the verification check.
5. Report result, uncertainty, and next wakeup/stop reason.
6. Escalate instead of acting when an escalation rule matches.
```

## Rollout
- First safe run: execute manually in read-only mode.
- Promotion gate: verification passes on repeated runs and audit logs are clean.
- Failure drill: force a bad input and confirm the loop stops or escalates.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="*", help="Raw request to loopify. Reads stdin when omitted.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    args = parser.parse_args()

    text = " ".join(args.request).strip() or sys.stdin.read().strip()
    if not text:
        raise SystemExit("Provide a request as arguments or stdin.")
    contract = build_contract(text)
    if args.json:
        print(json.dumps(contract, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(contract))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
