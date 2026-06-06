---
name: loopify-requirements
description: Convert prompts, vague tasks, product requirements, coding requests, research plans, monitors, reminders, and agent workflows into repeatable, verifiable loops. Use when the user asks to "loopify" a requirement, turn a prompt into an agent loop, design unattended or recurring work, define /loop or routine instructions, create guardrails for autonomous agents, convert one-shot tasks into monitored workflows, or make future prompts more reliable through goal/scope/verification/escalation/stop conditions.
---

# Loopify Requirements

Turn a request into a loop contract: a bounded process that can wake up, inspect state, act, verify, report, and stop. Optimize for reliability before autonomy.

## Core Rule

A requirement is not loop-ready until it answers:

1. **Goal**: what outcome should repeatedly become true?
2. **Trigger**: what starts or wakes the loop?
3. **State**: what evidence does each iteration inspect?
4. **Scope**: what may the agent read, change, or call?
5. **Verification**: how does the loop know the work is correct?
6. **Escalation**: when must it ask a human?
7. **Stop**: when should it end, pause, or refuse to continue?
8. **Audit**: what should be logged for later review?

If any answer is missing, produce a `Not Loop-Ready` section and fill the smallest safe next step.

## Workflow

1. **Classify the request**
   - `one_shot`: solve once; loopification should produce a checklist or reusable prompt.
   - `scheduled`: run on a cadence such as hourly, daily, weekly.
   - `event_driven`: run on PR, alert, webhook, email, file change, or user message.
   - `monitor`: watch for a condition and report or act.
   - `long_horizon`: split work into iterations with state carryover.

2. **Pick the autonomy level**
   - `L0`: human-run checklist.
   - `L1`: reusable prompt for manual runs.
   - `L2`: supervised loop that proposes actions.
   - `L3`: scheduled loop with read-only or low-risk writes.
   - `L4`: event/API/GitHub-triggered routine with bounded writes.
   - `L5`: autonomous write/merge/publish. Use only when verification, rollback, and escalation are explicit.

   Default to the lowest level that solves the user’s problem.

3. **Write the Loop Contract**
   Use the user’s words, but convert vague wishes into observable state, allowed actions, and success checks. Separate facts, assumptions, open questions, and unsafe automation.

4. **Rewrite the prompt**
   Produce instructions an agent can run repeatedly. Include:
   - role and goal,
   - inputs to inspect,
   - allowed tools and forbidden actions,
   - step-by-step iteration,
   - verification command or review check,
   - report format,
   - escalation and stop rules.

5. **Design rollout**
   Start with a small supervised loop. Promote only after the loop has clean logs, stable verification, and no unresolved high-risk failures.

## Output Format

Use this structure unless the user asks for code or implementation:

````markdown
## Loopified Requirement
- Goal:
- Trigger:
- State:
- Scope:
- Autonomy level:

## Loop Contract
- Allowed actions:
- Forbidden actions:
- Verification:
- Escalation:
- Stop conditions:
- Audit log:

## Loop Prompt
```text
...
```

## Rollout
- First safe run:
- Promotion gate:
- Failure drill:
````

For implementation work, add the actual automation artifact after the contract: cron command, Claude Code `/loop` prompt, routine prompt, GitHub Action, monitor config, or script.

## Safety Defaults

- Do not grant write, delete, merge, publish, payment, credential, or production access by default.
- Treat repeated work as risk amplification: a small wrong action can become large when scheduled.
- Prefer read-only triage before writes.
- Prefer reversible changes before irreversible actions.
- Require human escalation for ambiguous ownership, destructive changes, credentials, legal/financial/medical decisions, and public publishing.
- Do not use prompt-only plans as proof that a real loop was installed, scheduled, or validated.

## Resources

- Read `references/loop-patterns.md` when choosing loop types, guardrails, or failure modes.
- Use `scripts/loopify.py` for a deterministic scaffold from a raw prompt before refining it with task-specific evidence.
