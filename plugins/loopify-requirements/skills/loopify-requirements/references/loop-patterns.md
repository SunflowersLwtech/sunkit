# Loop Patterns

Use these patterns to convert requests into reliable loops.

## Maintenance Loop

Use for PR babysitting, CI fixes, dependency checks, docs drift, cleanup passes.

- Trigger: schedule or PR event.
- State: branch status, CI logs, review comments, changed files.
- Safe first action: summarize and propose.
- Verification: tests pass, diff is minimal, review threads addressed.
- Stop: no pending work, repeated same failure, permission boundary reached.

## Monitor Loop

Use for metrics, alerts, competitor/source watching, inbox triage, uptime, regressions.

- Trigger: schedule, webhook, threshold, or manual wakeup.
- State: latest metric/log/source compared with prior snapshot.
- Safe first action: report change with evidence.
- Verification: source timestamp, threshold math, deduplicated alert.
- Stop: condition cleared, source unavailable repeatedly, alert acknowledged.

## Research Loop

Use for papers, repos, docs, market scans, evidence gathering.

- Trigger: manual start or schedule.
- State: source list, claim ledger, unknowns, checked artifacts.
- Safe first action: collect sources and separate facts from inference.
- Verification: every public claim has source evidence.
- Stop: sources exhausted, evidence insufficient, claim unsafe.

## Build Loop

Use for coding tasks, feature implementation, bug fixing, refactors.

- Trigger: issue, PR, schedule, or user request.
- State: repo status, tests, task list, failing logs, branch.
- Safe first action: inspect, plan, implement smallest slice.
- Verification: relevant tests, lint, build, screenshot or manual check.
- Stop: tests fail repeatedly for same reason, scope expands, destructive action needed.

## Publishing Loop

Use for X/thread/blog/email/content workflows.

- Trigger: approved posting pack, schedule, or source update.
- State: source evidence, copy, media, claim review, publish credentials.
- Safe first action: dry run and preflight.
- Verification: claim gate, image gate, dry-run plan, explicit approval.
- Stop: credentials invalid, claim unsafe, media missing, live post partially fails.

## Failure Modes

- **Runaway scope**: loop starts new initiatives outside the contract.
- **Permission drift**: read-only loop quietly becomes write-capable.
- **False success**: green infrastructure status is mistaken for task success.
- **Repeated bad fix**: loop retries the same wrong action without new evidence.
- **Missing audit**: no record of inputs, changes, or why it stopped.
- **Human bypass**: escalation rules exist in prose but are not checked in the loop.
