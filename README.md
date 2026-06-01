# github-repo-to-x-threads

Agent Skills plugin for turning technical inputs into responsible
Agent-engineering-positioned X/Twitter content systems: posting packs, paper-to-system
threads, build-in-public notes, professional bug-report rewrites, profile
positioning, image assets, and optional official X API publishing.

## Agent/Plugin/Skills Shape

This project is organized as an agent-first skillpack, similar in spirit to
`garrytan/gbrain`: agents start from root protocol files, route through
`skills/RESOLVER.md`, and execute the canonical skill under `skills/`.

```text
AGENTS.md                      # repo operating rules for coding agents
llms.txt                       # compact documentation map for LLMs
INSTALL_FOR_AGENTS.md          # install + verification protocol
CLAUDE.md                      # Claude Code entrypoint
skillpack.json                 # agent skillpack manifest
openclaw.plugin.json           # OpenClaw/Hermes-style bundle manifest
skills/
  _AGENT_README.md             # cold-start contract for scaffolded skills
  RESOLVER.md                  # routing table
  manifest.json                # machine-readable skill index
  github-repo-to-x-threads/    # canonical reusable skill
.codex-plugin/plugin.json      # Codex adapter manifest
.claude-plugin/plugin.json     # Claude plugin adapter manifest
commands/                      # command source: Claude slash; packaged in Codex adapters
runbooks/bootstrap.md          # post-scaffold runbook
plugins/github-repo-to-x-threads/ # generated local Codex plugin adapter, ignored
```

The important boundary: `skills/github-repo-to-x-threads/` is the canonical
implementation. Everything else is a manifest, router, runbook, or generated
install surface.

The canonical skill is agent-neutral:

```text
skills/github-repo-to-x-threads/
  SKILL.md
  scripts/
  references/
```

Adapter metadata is thin and separate:

```text
.codex-plugin/plugin.json      # Codex plugin manifest
.claude-plugin/plugin.json     # Claude Code plugin manifest
commands/                      # command source: Claude slash; packaged in Codex adapters
.claude/                       # generated local Claude adapter, ignored
.agents/                       # generated local Codex adapter, ignored
plugins/                       # generated local Codex marketplace plugin root, ignored
```

Do not install this project by copying the whole repository into `.claude/skills`. The reusable skill lives under `skills/`; installers and plugin manifests adapt that folder for each agent surface.

## Coding Agent One-Line Config

Coding agents should treat `AGENTS.md` plus `skills/github-repo-to-x-threads/SKILL.md` as the source of truth, keep generated runs/images/env files out of git, and use `scripts/install_skill_bundle.sh /Volumes/T7/media/X` only to sync local install surfaces on this machine.

For a cold start, read:

1. `AGENTS.md`
2. `INSTALL_FOR_AGENTS.md`
3. `skills/_AGENT_README.md`
4. `skills/RESOLVER.md`
5. `skills/github-repo-to-x-threads/SKILL.md`

## What It Does

Given one or more GitHub repos, owner/repo strings, local paths, arXiv/alphaXiv papers, web URLs, PDFs/notes, existing posting packs, profile prompts, KYC/support complaints, or raw ideas, the skill guides an agent to:

1. classify the input through the Agent engineering brand gate,
2. clone/read repos or collect source-specific evidence for papers, pages, files, and ideas,
3. cross-check evidence against live metadata when available,
4. separate verified facts, reasonable inference, and user vision,
5. route KYC/support/life/media noise into bug-report, off-main-account, or Agent failure-mode drafts,
6. draft paste-ready X content with attribution, caveats, source-material richness, hook independence, reusable assets, concrete discussion questions, and anti-template voice checks,
7. expose the model quality chain: source grounding, brand lane, angle tournament, asset design, draft synthesis, adversarial review, and final gate,
8. create a final-mile posting pack with Brand Fit, image placement, and alt text,
9. generate and govern GPT Image 2-style assets through a local image registry by default,
10. optionally publish the approved pack through the official X API from the CLI,
11. record outcomes into local strategy memory so later posts can improve,
12. synthesize eval/publish/experiment signals into an auditable skill-evolution report and patch plan.

## Agent Engineering Brand Contract

Default positioning:

```text
Agent 工程实战派
Core question: Agent 工程如何从 demo 变成可靠系统？
```

Main-account content must map to one of:

- `agent_reliability`
- `build_in_public`
- `paper_to_system`
- `embodied_ai_watch`

Every thread should include one reusable asset and one concrete discussion
question. KYC/support/platform complaints are rewritten as cold PRD-style bug
reports by default; life/media/mood notes move off the main account unless they
become concrete Agent engineering failure-mode notes.

## Install For Local Use

The helper installs the canonical skill plus local adapters without committing generated outputs:

```bash
scripts/install_skill_bundle.sh /Volumes/T7/media/X
```

It writes:

```text
/Volumes/T7/media/X/
  AGENTS.md
  INSTALL_FOR_AGENTS.md
  CLAUDE.md
  llms.txt
  skillpack.json
  openclaw.plugin.json
  runbooks/bootstrap.md
  skills/_AGENT_README.md
  skills/RESOLVER.md
  skills/manifest.json
  skills/github-repo-to-x-threads/      # canonical plugin skill
  .codex-plugin/plugin.json             # Codex plugin manifest
  .claude-plugin/plugin.json            # Claude plugin manifest
  commands/github-repo-to-x-threads.md  # Claude plugin command
  .agents/plugins/marketplace.json      # Codex project marketplace
  plugins/github-repo-to-x-threads/     # Codex project plugin adapter, including command source
  .claude/skills/github-repo-to-x-threads/  # Claude project adapter
```

It also installs one user-level Codex skill copy to:

```text
~/.agents/skills/github-repo-to-x-threads/
```

And one user-level Claude Code skill plus slash command copy to:

```text
~/.claude/skills/github-repo-to-x-threads/
~/.claude/commands/github-repo-to-x-threads.md
```

Do not also keep this skill under `~/.codex/skills/` or the bundle's `.agents/skills/`; Codex will show duplicate entries if the same skill is present in multiple scanned locations.

## Manual Install

Codex official user skill location:

```bash
mkdir -p ~/.agents/skills
cp -R skills/github-repo-to-x-threads ~/.agents/skills/
```

Claude Code personal skill location:

```bash
mkdir -p ~/.claude/skills
cp -R skills/github-repo-to-x-threads ~/.claude/skills/
mkdir -p ~/.claude/commands
cp commands/github-repo-to-x-threads.md ~/.claude/commands/
```

For Codex plugin distribution, use the project marketplace adapter generated by
the installer. Codex requires a real plugin root under
`plugins/github-repo-to-x-threads/`; a symlink-only adapter installs as an empty
cache.

Current Codex Desktop exposes installed plugins and skills to the model, but its
slash-command picker only lists built-in commands and model service-tier
commands. The packaged `commands/` file is kept for adapter parity; it is not a
guarantee that `/github-repo-to-x-threads` appears in the Codex slash menu.
Invoke the workflow in Codex with natural language, or name the skill explicitly
as `$github-repo-to-x-threads`.

```bash
CODEX_CLI="${CODEX_CLI_PATH:-/Applications/Codex.app/Contents/Resources/codex}"
"$CODEX_CLI" plugin marketplace list
"$CODEX_CLI" plugin marketplace add /Volumes/T7/media/X   # only if media-x-local is absent
"$CODEX_CLI" plugin add github-repo-to-x-threads@media-x-local
scripts/verify_codex_project_plugin.sh .
```

After editing the plugin manifest or skill, refresh the cachebuster, sync the
adapter, and reinstall:

```bash
python3 /Users/chenyu/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py .
scripts/install_skill_bundle.sh /Volumes/T7/media/X
CODEX_CLI="${CODEX_CLI_PATH:-/Applications/Codex.app/Contents/Resources/codex}"
"$CODEX_CLI" plugin add github-repo-to-x-threads@media-x-local
scripts/verify_codex_project_plugin.sh .
```

Claude Code reads `.claude-plugin/plugin.json` and the root `skills/` directory.

For agent-first installation, point the agent at:

```text
https://raw.githubusercontent.com/SunflowersLwtech/github-repo-to-x-threads/main/INSTALL_FOR_AGENTS.md
```

The agent should read the install protocol, scaffold the bundle, then route
tasks through `skills/RESOLVER.md`.

## Governed Multi-Repo Runs

Use the run-pack script when you want one governed workspace for one or more repos:

```bash
python -B skills/github-repo-to-x-threads/scripts/run_repo_to_x_pack.py \
  https://github.com/owner/repo owner2/repo2 --refresh
```

Or use a source list:

```bash
python -B skills/github-repo-to-x-threads/scripts/run_repo_to_x_pack.py \
  --source-file repos.txt --refresh
```

Outputs are written under:

```text
repo-to-x-workspace/runs/<run-id>/
```

Each repo gets:

- `repo_context.json`
- `file_manifest.txt`
- `claims_ledger.json`
- `cross_check_review.md`
- `posting_pack.md`
- `images_manifest.json`
- `images/`
- `repo/` when the source is remote

`repo-to-x-workspace/` is ignored by git. It is the local, accessible place for cloned repos, generated images, drafts, review notes, and final posting packs.

## Any Input Strategy Runs

For non-repo or strategy-first inputs, start with the router:

```bash
python -B skills/github-repo-to-x-threads/scripts/x_strategy_router.py \
  "https://www.alphaxiv.org/abs/2605.22817" \
  --prompt "帮我决定策略并发成中文 X thread"
```

For a governed workspace:

```bash
python -B skills/github-repo-to-x-threads/scripts/run_any_to_x_pack.py \
  "https://www.alphaxiv.org/abs/2605.22817" \
  --prompt "帮我决定策略并发成中文 X thread" \
  --run-id vpo-paper-to-system
```

This creates:

```text
repo-to-x-workspace/runs/<run-id>/
  strategy_decision.json
  run_manifest.json
  SUMMARY.md
  repos/<source-id>/
    repo_context.json
    source_context.json
    claims_ledger.json
    cross_check_review.md
    posting_pack.md
    images_manifest.json
    images/
```

Use `run_repo_to_x_pack.py` for deep GitHub repo collection. Use `run_any_to_x_pack.py` when the source can be a paper, web URL, PDF, existing pack, or raw idea.

## Content Quality Gates

When a draft is safe but feels generic, use:

```text
skills/github-repo-to-x-threads/references/content-quality-gates.md
```

The quality gate checks whether the source has enough material to justify a hook, whether post 1 works without a link card, whether the psychological trigger fits the evidence, whether high-level concepts are translated into concrete mechanisms, whether the copy is too smooth or template-like, and whether the draft fits the Agent engineering account instead of becoming generic AI/life/support noise.

`references/model-intelligence-quality-chain.md` defines the model-side quality
chain. Generated packs should show the chain status; missing stages are treated
as a quality failure rather than hidden reasoning.

## Self-Evolving Strategy Memory

After review or live publish, record the result:

```bash
python -B skills/github-repo-to-x-threads/scripts/record_post_outcome.py \
  repo-to-x-workspace/runs/<run-id>/repos/<source-id> \
  --manual-quality 0.8 \
  --lesson "The strongest posts used a direct caveat in the hook."
```

When real X metrics are available:

```bash
python -B skills/github-repo-to-x-threads/scripts/record_post_outcome.py \
  repo-to-x-workspace/runs/<run-id>/repos/<source-id> \
  --impressions 10000 \
  --likes 120 \
  --reposts 18 \
  --replies 9 \
  --bookmarks 35 \
  --lesson "Architecture images worked better than generic hero images."
```

This writes ignored local memory:

```text
repo-to-x-workspace/strategy-memory/outcomes.jsonl
repo-to-x-workspace/strategy-memory/strategy_profile.json
```

Future `x_strategy_router.py` runs read this profile and surface learned notes. The memory biases strategy selection; it does not replace evidence checks or authorize unsupported public claims.

For a broader self-evolution pass across evals, live publish logs, recorded
outcomes, and Trending experiments:

```bash
python -B skills/github-repo-to-x-threads/scripts/x_skill_evolution.py \
  --runs-root repo-to-x-workspace/runs \
  --memory-root repo-to-x-workspace/strategy-memory \
  --run-id review_latest
```

This writes:

```text
repo-to-x-workspace/skill-evolution/<run-id>/
  signal_ledger.json
  skill_evolution_summary.json
  skill_evolution_report.md
  skill_patch_plan.md
```

Add `--apply-profile` only when you want the proposed rules stored in ignored
local `strategy_profile.json` as routing guidance. The script never edits
`SKILL.md` or public claims automatically; turn `skill_patch_plan.md` into a
reviewed code/doc change with a regression eval.

## X Eval Agent

Use Grok plus deterministic checks to score a posting pack before publishing:

```bash
python -B skills/github-repo-to-x-threads/scripts/x_eval_post.py \
  repo-to-x-workspace/runs/<run-id>/repos/<source-id>
```

It writes:

```text
post_eval.json
x_eval_report.md
```

If `GROK_API_KEY` is present in the local ignored `.env`, Grok provides semantic scores and suggestions. Without Grok, the script falls back to deterministic rubric checks.

The evaluator is intentionally strict on editorial quality. It now scores:

- `angle_freshness`
- `specificity_density`
- `voice_authenticity`
- `brand_clarity`
- `cta_specificity`
- `asset_value`
- `emotion_control`
- `account_fit`

A safe summary can still be marked `revise` if it feels rigid, generic, off-brand, assetless, or emotionally noisy.

When a draft feels weak, run a Grok draft tournament:

```bash
python -B skills/github-repo-to-x-threads/scripts/x_draft_tournament.py \
  repo-to-x-workspace/runs/<run-id>/repos/<source-id> \
  --prompt "User says the current skill is too rigid and quality is not good" \
  --write-proposed-pack
```

It writes:

```text
draft_tournament.json
draft_tournament.md
posting_pack.proposed.md
```

Use the proposed pack as a candidate, then re-run claim/image/eval gates before publishing.

After publishing, collect X metrics and calibrate strategy memory:

```bash
python -B skills/github-repo-to-x-threads/scripts/x_collect_metrics.py \
  repo-to-x-workspace/runs/<run-id>/repos/<source-id>

python -B skills/github-repo-to-x-threads/scripts/x_calibrate_strategy.py \
  repo-to-x-workspace/runs/<run-id>/repos/<source-id> \
  --lesson "Architecture images beat generic hero images for this audience."
```

## Trending Experiments

For broad testing, pull current GitHub Trending and run multi-round text-only evals before spending time on deep clones or images:

```bash
python -B skills/github-repo-to-x-threads/scripts/x_trending_experiment.py \
  --limit 10 \
  --rounds 3 \
  --since daily \
  --metadata-only \
  --run-id trending_daily_metadata
```

This writes `trending_experiment_results.json` and `trending_experiment_report.md` under the run directory. The script only accepts a tournament rewrite when it scores better than the current draft.

Use deep clone mode only after a repo survives the fast screen:

```bash
python -B skills/github-repo-to-x-threads/scripts/x_trending_experiment.py \
  --limit 3 \
  --rounds 3 \
  --since daily \
  --refresh
```

The evaluator is not a real X ranking oracle. It combines local posting-pack gates, approximate recommendation-system heuristics, Grok semantic review, and the user's own historical outcomes.

## Image Governance

Technical final posting packs should generate actual images by default. Use text-only, no-images, prompts-only, or manual-image mode only when the user explicitly asks for that output mode. If actual images are required and the image tool cannot produce a governable file, block the image gate. Professional bug reports are the exception: prefer real evidence screenshots supplied by the user or text-only copy, and never generate fake KYC/support evidence.

Generated image files must be copied into the repo run directory and registered:

```bash
python -B skills/github-repo-to-x-threads/scripts/register_image_asset.py \
  repo-to-x-workspace/runs/<run-id>/repos/<repo-id> /path/to/generated.png \
  --id image-1 \
  --post 1/N \
  --purpose "hook visual" \
  --prompt "..." \
  --alt-text "..." \
  --disclosure "Generated conceptual visual, not an official project screenshot."
```

The registry writes `images_manifest.json` with:

- stable image id,
- post placement,
- source type,
- model,
- governed local path,
- `sha256`,
- MIME type,
- prompt,
- alt text,
- disclosure,
- review status.

Prompt-only entries are not a fallback for failed image generation. Register
`--prompt-only` only when the user explicitly asked for prompts as the
deliverable, and include a prompt-only reason. If an actual-image pack is
required and no governable image file exists, the image gate is blocked.

When an agent is asked for actual images, it should use its native image generation capability first, such as Codex `imagegen` / built-in image generation. Script-drawn cards, SVG placeholders, browser screenshots, or canvas diagrams are not substitutes for GPT Image-style assets unless the user explicitly asked for deterministic code-native graphics.

Before a pack is presented as ready, run:

```bash
python -B skills/github-repo-to-x-threads/scripts/check_image_assets.py \
  repo-to-x-workspace/runs/<run-id>/repos/<repo-id>
```

Only pass `--allow-prompt-only` when the user explicitly requested prompt-only,
text-only, or manual-image mode. Do not pass it because image generation failed.

## Adaptive Threads

The skill does not force exactly 8 posts. It uses the repo evidence and the user's angle to choose the length: short repos can be 4-6 posts, richer repo+vision posts can be 8-12, and longer threads are acceptable when needed for attribution, evidence, caveats, or practical use.

## Official X API CLI Publishing

Full automation is supported only through official X API user credentials. The first post is created by the CLI as a normal root post; each later thread item is created as a reply to the previous post by default.

Existing app-only keys such as `X_BEARER_TOKEN` are not enough to publish. For the bundled publisher, configure OAuth2 user credentials with these scopes:

```text
tweet.read users.read tweet.write media.write offline.access
```

One-time setup:

1. Create or open your app in the X Developer Portal.
2. Enable OAuth2 user authentication for the app.
3. Add this callback URL exactly, or set your own and use it consistently:

```text
http://127.0.0.1:8765/callback
```

4. Put the app's OAuth2 Client ID in your local ignored `.env`:

```bash
cp skills/github-repo-to-x-threads/.env.example .env
# edit .env and set X_CLIENT_ID, optionally X_CLIENT_SECRET
python -B skills/github-repo-to-x-threads/scripts/x_oauth2_pkce_setup.py --env-file .env
```

Dry-run the generated posting pack:

```bash
python -B skills/github-repo-to-x-threads/scripts/x_publish_thread.py \
  repo-to-x-workspace/runs/<run-id>/repos/<repo-id>
```

Publish after review:

```bash
python -B skills/github-repo-to-x-threads/scripts/x_publish_thread.py \
  repo-to-x-workspace/runs/<run-id>/repos/<repo-id> \
  --live
```

The publisher uploads registered images, attempts to set alt text, marks generated-image posts with `made_with_ai`, posts the first thread item, then replies with the rest. It writes `x_publish_log.json` in the ignored run directory and never logs tokens.

Do not use cookie replay, website automation, hidden GraphQL calls, `auth_session` services, or proxy-based third-party posting as this project's default path.

When using an external bundle such as `/Volumes/T7/media/X`, you may keep local user-governed artifacts at the bundle root:

- `/Volumes/T7/media/X/.env`
- `/Volumes/T7/media/X/repo-to-x-workspace/`

The installer preserves these bundle-root paths. Do not commit `.env`, and do not place real env files or generated run workspaces under `skills/`.

## Local Env

Create a local `.env` when you want live GitHub metadata or official X API publishing:

```bash
cp skills/github-repo-to-x-threads/.env.example .env
```

Set one of:

- `GH_TOKEN`
- `GITHUB_TOKEN`
- `GITHUB_PERSONAL_ACCESS_TOKEN`

For official X API publishing, set `X_CLIENT_ID` first and then run `x_oauth2_pkce_setup.py` to populate `X_OAUTH2_ACCESS_TOKEN` and `X_OAUTH2_REFRESH_TOKEN`.

For Grok-based pre-publish evaluation, set:

- `GROK_API_KEY`
- `GROK_MODEL` (defaults to `grok-4.3`)

`.env` files are ignored by git. Do not commit real tokens.

## Git Hygiene

Tracked:

- `skills/github-repo-to-x-threads/`
- `skills/RESOLVER.md`
- `skills/_AGENT_README.md`
- `skills/manifest.json`
- `.codex-plugin/plugin.json`
- `.claude-plugin/plugin.json`
- `skillpack.json`
- `openclaw.plugin.json`
- `INSTALL_FOR_AGENTS.md`
- `CLAUDE.md`
- `llms.txt`
- `runbooks/`
- `commands/`
- root installer scripts

## Project-Level Codex Registration

The project-level Codex plugin registration is:

```text
.agents/plugins/marketplace.json
.codex-plugin/plugin.json
plugins/github-repo-to-x-threads/.codex-plugin/plugin.json
plugins/github-repo-to-x-threads/skills/github-repo-to-x-threads/SKILL.md
skills/github-repo-to-x-threads/SKILL.md
```

Verify it with:

```bash
scripts/verify_codex_project_plugin.sh .
```

This check requires the real project files to exist and does not use temporary
registration targets. It also checks `codex plugin list` and the installed
Codex cache when the Codex CLI is available.
- `README.md`
- `AGENTS.md`
- `evals/`

Ignored:

- `.env`
- `.claude/` generated local adapters
- `.agents/` duplicate local adapters
- `plugins/` generated local Codex marketplace adapter
- `repo-to-x-workspace/`
- cloned third-party repos
- generated images
- repo-specific claims ledgers and posting packs
- `.DS_Store`, `._*`, `__pycache__`

Before publishing changes:

```bash
git status --short --ignored
git diff --check
rg -n --hidden --glob '!.env' --glob '!.git/**' '(g[h]p_|g[h]o_|github_[p]at_|BEGIN [A-Z ]{0,30}PRIVATE KEY)' . || true
```
