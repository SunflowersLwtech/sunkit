# Skill Evolution System

Use this when the user wants the skill itself to improve from runs, feedback,
metrics, or experiments. The system is deliberately auditable:

```text
run artifacts -> signal ledger -> evolution report -> patch plan -> reviewed skill change
```

The script may update local ignored strategy memory, but it must not silently
edit canonical skill instructions or public claims.

## Signals

`x_skill_evolution.py` reads these local artifacts when present:

- `post_eval.json`: final score, score dimensions, top fixes, text features.
- `x_publish_log.json`: posted tweet ids and whether image ids were attached.
- `post_outcome.json`: manual-quality or metric-derived score plus lessons.
- `strategy-memory/outcomes.jsonl`: durable postmortem rows.
- `strategy-memory/strategy_profile.json`: strategy-level score/lesson profile.
- `trending_experiment_results.json`: multi-repo screening results, common fixes,
  converged rules, and tournament rewrite acceptance/rejection.

## Run It

Default local run:

```bash
python -B <skill-dir>/scripts/x_skill_evolution.py
```

Use another run workspace:

```bash
python -B <skill-dir>/scripts/x_skill_evolution.py \
  --runs-root /path/to/repo-to-x-workspace/runs \
  --memory-root /path/to/repo-to-x-workspace/strategy-memory \
  --run-id review-2026-05-27
```

Write proposed guidance into ignored local strategy memory:

```bash
python -B <skill-dir>/scripts/x_skill_evolution.py --apply-profile
```

`--apply-profile` only writes `evolution_guidance` into
`strategy_profile.json`. `x_strategy_router.py` can read those rules as routing
bias. Evidence collection, claim safety, image gates, and user approval still
win over learned guidance.

## Outputs

The script writes under `repo-to-x-workspace/skill-evolution/<run-id>/`:

- `signal_ledger.json`: raw normalized signals from evals, outcomes, and
  experiments.
- `skill_evolution_summary.json`: aggregate counts, weak dimensions, common
  fixes, strategy scores, and proposed active rules.
- `skill_evolution_report.md`: human-readable diagnosis.
- `skill_patch_plan.md`: reviewed patch plan with suggested target surfaces.

These files are local evidence, not committed product artifacts by default.

## Guardrails

- Do not treat engagement as proof that a factual claim was true.
- Do not weaken attribution, claim safety, generated-image disclosure, or
  official X API publishing rules to improve engagement.
- Do not apply a rule from one source kind to another unless the report evidence
  shows the same failure mode.
- Do not edit `SKILL.md` automatically from this script. Convert a patch plan
  into code/doc changes only after reviewing the evidence.
- Keep broad candidate search text-only until a candidate survives angle
  screening; generate images during publish prep.

## Review Checklist

Before turning a proposed rule into a canonical skill change:

- The rule is supported by at least one concrete eval/outcome/experiment signal.
- The rule improves angle, specificity, caveat, voice, or workflow efficiency.
- The rule does not authorize unsupported claims or hidden affiliation.
- There is a regression eval or smoke command that would catch the old failure.
- The change is scoped to the canonical skill or scripts, not generated adapters.
