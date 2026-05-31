# Self-Evolving X Strategy

This skill can accept more than GitHub repositories. The durable loop is:

```text
any input -> strategy_decision.json -> governed evidence pack -> publish/review -> post_outcome.json -> local strategy memory -> better next decision
```

The loop is intentionally auditable. It improves strategy recommendations from local outcomes, but it does not silently rewrite public claims or mutate canonical skill instructions after a post performs well.

## Input Router

Start arbitrary-input runs with:

```bash
python -B <skill-dir>/scripts/x_strategy_router.py <source-or-input> \
  --prompt "<full user request>"
```

For a governed workspace, use:

```bash
python -B <skill-dir>/scripts/run_any_to_x_pack.py <source-or-input> \
  --prompt "<full user request>" \
  --run-id <stable-run-id>
```

The router classifies inputs into:

- `github_repo`: GitHub URL or `owner/repo`.
- `local_repo`: local repo/source tree.
- `paper`: arXiv or alphaXiv URL.
- `web_url`: blog, docs, product page, or general URL.
- `local_file`: PDF, markdown, transcript, notes, source list, or other file.
- `existing_posting_pack`: a governed run directory containing `posting_pack.md` and `images_manifest.json`.
- `raw_idea`: a free-form idea with no direct source yet.

## Strategy IDs

- `independent_technical_share`: default for repos/projects the user does not own.
- `launch_thread`: when the user owns the project or explicitly says they built/released it.
- `paper_to_system`: for arXiv/alphaXiv/research-paper inputs translated into engineering patterns.
- `professional_bug_report`: for KYC/support/platform complaint rewrites.
- `off_main_filter`: for life/media/mood inputs that should not enter the main account unless rewritten around Agent engineering.
- `profile_positioning`: for bio, profile, and pinned-post positioning.
- `comparison_or_roundup`: for multiple sources, comparisons, or candidate pools.
- `builder_notes`: when the user tested/built/demoed something and wants practical notes.
- `x_article`: when the target is a native X Article or long-form post.
- `research_then_post`: for raw ideas or weakly sourced prompts.
- `publish_existing_pack`: for already-reviewed governed packs.

## Strategy Decision Contract

Every durable run should write `strategy_decision.json` at run root. It should include:

- input classification,
- selected strategy,
- evidence plan,
- image policy,
- thread shape,
- publish mode,
- learned notes from local strategy memory.

If a strategy decision conflicts with evidence, evidence wins. The router chooses how to approach the post; it does not authorize unsupported claims.

## Self-Evolution Memory

After a review or live post, record the outcome:

```bash
python -B <skill-dir>/scripts/record_post_outcome.py <repo-run-dir> \
  --manual-quality 0.8 \
  --lesson "Paper-to-system posts work better when the hook states the engineering caveat directly."
```

When X metrics are available, prefer actual metrics:

```bash
python -B <skill-dir>/scripts/record_post_outcome.py <repo-run-dir> \
  --impressions 10000 \
  --likes 120 \
  --reposts 18 \
  --replies 9 \
  --bookmarks 35 \
  --lesson "Architecture image on post 1 increased saves."
```

This appends to:

```text
repo-to-x-workspace/strategy-memory/outcomes.jsonl
repo-to-x-workspace/strategy-memory/strategy_profile.json
```

These files are intentionally local and ignored by git.

## Skill Evolution Report

When the question is not just "which strategy should this one post use" but
"how should the skill improve after a batch of runs", run:

```bash
python -B <skill-dir>/scripts/x_skill_evolution.py \
  --runs-root repo-to-x-workspace/runs \
  --memory-root repo-to-x-workspace/strategy-memory
```

This produces an auditable signal ledger, aggregate report, and patch plan under
`repo-to-x-workspace/skill-evolution/<run-id>/`. Add `--apply-profile` only to
store proposed local routing rules in `strategy_profile.json`; do not use it as
permission to auto-edit canonical skill files.

## What The Agent Should Learn

Use the profile as a bias, not a law:

- If a strategy has better average scores, prefer its thread shape when the new input is similar.
- Reuse lessons that match the same strategy and source kind.
- Do not reuse performance lessons that would weaken claim safety.
- If metrics are missing, use a manual-quality score from review instead of pretending engagement data exists.
- Keep a short human-readable lesson after every meaningful run; the lesson is more reusable than the raw metric.

## Gates

Before live publish:

- `strategy_decision.json` exists.
- `claims_ledger.json` maps public claims to sources.
- `cross_check_review.md` is `pass`.
- `images_manifest.json` contains governed GPT Image 2 assets unless the user opted out.
- `check_image_assets.py` passes.
- User explicitly approves live publishing or requested upload/publish.

After live publish:

- `x_publish_log.json` contains posted tweet ids.
- `record_post_outcome.py` has been run with either manual-quality feedback or real metrics.
- Any new durable lesson is added as a lesson in local strategy memory, not silently inserted into public copy.
