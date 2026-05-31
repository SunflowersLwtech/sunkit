---
description: Analyze repos, papers, URLs, files, ideas, profile prompts, or support complaints and create Agent-engineering-positioned X content packs with strategy routing, evidence review, reusable assets, images, and optional publish.
argument-hint: '<repo-url|owner/repo|local-path|paper-url|web-url|file|idea> [...] [--source-file sources.txt] [--run-id id] [--refresh]'
allowed-tools: Bash(python:*), Bash(git:*), Bash(gh:*), Bash(rg:*), Bash(jq:*), Read, Write, Edit, Grep, Glob
---

# GitHub Repo to X Threads

Use the `github-repo-to-x-threads` skill from this plugin/project. If the skill body is not already loaded, read:

`$CLAUDE_PLUGIN_ROOT/skills/RESOLVER.md`

Then read:

`$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/SKILL.md`

If `$CLAUDE_PLUGIN_ROOT` is not available, read:

`skills/RESOLVER.md`

Then read:

`skills/github-repo-to-x-threads/SKILL.md`

## Task

Analyze the sources provided in `$ARGUMENTS`, choose a posting strategy, run the Agent engineering brand gate, create a governed local run workspace, cross-check public claims, and produce a final X posting pack.

Default positioning: `Agent 工程实战派` / `Agent 工程如何从 demo 变成可靠系统`.

Main-account content must map to agent reliability, build-in-public,
paper-to-system, or embodied AI watch. KYC/support/platform complaints should be
rewritten as cold bug reports or tied to an Agent reliability failure mode.
Life/media/mood notes should move off-main-account unless they have a concrete
Agent engineering mechanism.

Thread length is adaptive. Do not force exactly 8 posts; use the number of posts the repo evidence and user angle justify.

Every final thread needs one reusable asset and one concrete discussion question.

Actual generated images are part of the default technical posting pack. Use native image generation when available, then register the files in `images_manifest.json`. For professional bug reports, prefer real evidence screenshots or text-only output; do not generate fake support/KYC evidence. Prompt-only entries are allowed only when the user explicitly chose text-only/prompts-only/manual images; they are not a fallback when image generation fails.

First route the input when it is not clearly a single GitHub/local repo, or when the user asks for strategy/self-evolution:

```bash
python -B "$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/scripts/x_strategy_router.py" $ARGUMENTS
```

For arbitrary-input durable work, run:

```bash
python -B "$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/scripts/run_any_to_x_pack.py" $ARGUMENTS
```

For multi-repo or deep GitHub repo work, run:

```bash
python -B "$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/scripts/run_repo_to_x_pack.py" $ARGUMENTS
```

If using the repository skill path instead:

```bash
python -B "skills/github-repo-to-x-threads/scripts/run_repo_to_x_pack.py" $ARGUMENTS
```

Then read the generated `SUMMARY.md`, each `repo_context.json`, `claims_ledger.json`, `cross_check_review.md`, `posting_pack.md`, and `images_manifest.json`.

If a `strategy_decision.json` exists, read it before drafting. After review or publish, record outcomes with `record_post_outcome.py` when the user provides metrics or qualitative feedback.

If the draft feels rigid, generic, or not worth publishing, run an angle-first tournament before trying to publish:

```bash
python -B "$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/scripts/x_draft_tournament.py" <repo-run-dir> \
  --prompt "User taste feedback" \
  --write-proposed-pack
```

Before rewriting, use `references/content-quality-gates.md` to check source-material richness, hook independence, psychological-trigger fit, plain-language concept conversion, and over-smooth AI prose. Treat `posting_pack.proposed.md` as a candidate. Re-run claim, image, and eval gates before live publishing.

Before live publishing, prefer running:

```bash
python -B "$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/scripts/x_eval_post.py" <repo-run-dir>
```

After live publishing, prefer:

```bash
python -B "$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/scripts/x_collect_metrics.py" <repo-run-dir>
python -B "$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/scripts/x_calibrate_strategy.py" <repo-run-dir>
```

If the user asks to evolve the skill from a batch of evals, publish logs,
metrics, or Trending experiments, synthesize the evidence first:

```bash
python -B "$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/scripts/x_skill_evolution.py" \
  --runs-root repo-to-x-workspace/runs \
  --memory-root repo-to-x-workspace/strategy-memory
```

Use `--apply-profile` only to write proposed local routing guidance into ignored
strategy memory. Do not silently edit the canonical skill from the generated
patch plan.

Do not present a pack as ready until `cross_check_review.md` is `pass`, Brand Fit is explicit, the reusable asset and discussion question are present, and the relevant image gate passes. Keep generated outputs in the local ignored workspace and do not commit `.env`, cloned repos, generated images, or repo-specific run artifacts.

Before presenting "Ready To Post", run:

```bash
python -B "$CLAUDE_PLUGIN_ROOT/skills/github-repo-to-x-threads/scripts/check_image_assets.py" <repo-run-dir>
```

If using the repository skill path instead:

```bash
python -B "skills/github-repo-to-x-threads/scripts/check_image_assets.py" <repo-run-dir>
```
