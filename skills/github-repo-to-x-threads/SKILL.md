---
name: github-repo-to-x-threads
description: "Use this skill when the user wants Agent-engineering-positioned X/Twitter content from technical inputs including GitHub repos, owner/repo strings, local paths, arXiv/alphaXiv papers, blog/docs URLs, PDFs, notes, source lists, existing posting packs, raw ideas, KYC/support complaints, profile text, or prior run workspaces. It collects evidence, separates verified facts from inference and user vision, drafts responsible posts or threads with reusable assets and concrete discussion questions, governs GPT Image 2-style visual assets, optionally publishes through the official X API, records outcomes, and can synthesize skill-evolution reports or patch plans without weakening claim safety."
---

# GitHub Repo to X Threads

Turn technical sources into responsible, high-signal X content for an Agent engineering account. The goal is not hype or generic AI curation. The goal is a post that reinforces one public promise: **Agent 工程如何从 demo 变成可靠系统**.

## Use When

Use this skill when the user asks things like:

- "把这个 repo 写成 X thread"
- "分析这个 GitHub 项目，帮我发 X"
- "I want to share this repo on Twitter/X responsibly"
- "给这个项目做一组推文和配图"
- "帮我把 repo + 我的 vision 组织成 thread"
- "这个项目不是我的，只是分享，别写成官方口吻"
- "一次处理多个 repo，统一落盘和 review"
- "把这篇 paper 发成 X thread"
- "这个链接/PDF/笔记帮我决定怎么发 X"
- "根据任何输入自动决定发帖策略"
- "记录这次发帖效果，下次变强"
- "搭建一套 skill 自进化体系"
- "把这批 eval / live 结果总结成 skill 改进计划"
- "把这条 KYC/客服吐槽改成专业 bug report"
- "帮我重写 bio / 置顶帖 / 账号定位"

## Brand Profile

Default account positioning:

```text
Agent 工程实战派
Core question: Agent 工程如何从 demo 变成可靠系统？
```

Main content pillars:

- **Agent reliability**: hallucination boundaries, uncertainty, tool routing,
  debugging memory, failure memory, evals, production constraints.
- **Build in public**: the user's own MCP/Agent work, failures, fixes, design
  tradeoffs, and validation loops.
- **Paper to system**: papers translated into engineering patterns, not paper
  summaries.
- **Embodied AI watch**: robotics/embodied AI only when tied to agent systems,
  tool use, real-world task execution, or reliability.

Content routing:

- Technical repo/paper/source -> main-account posting pack when it supports one
  pillar.
- KYC/support/platform complaint -> professional bug report by default; keep on
  the main account only if tied to an Agent workflow reliability lesson.
- Life/media/mood note -> off-main-account by default; main account only after
  rewriting as a concrete Agent engineering failure-mode analogy.
- Profile/bio/pinned-post request -> use
  `references/profile-bio-pinned-post.md`.

Public shape requirements:

- Post 1 starts from reader pain, technical conflict, or engineering risk.
- Every thread includes one reusable asset: checklist, flowchart, issue
  template, prompt snippet, before/after table, or failure-mode map.
- Every thread ends with one concrete discussion question.
- Emotion is converted into process language: repro, impact, expected behavior,
  evidence, and next action.

Read `references/agent-engineering-brand-profile.md` for the full account
contract, `references/bug-report-rewrite-template.md` for support/KYC rewrites,
`references/paper-to-system-template.md` for research-paper inputs, and
`references/model-intelligence-quality-chain.md` for the model-side quality
chain. Read `references/creator-style-patterns.md` when improving content
quality, taste, cadence, demo value, or creator-pattern fit.

## Creator Style Patterns

Use creator patterns as content modes, not as impersonation targets. Do not
copy a specific creator's catchphrases, personal identity, emoji habits, or
community nicknames.

Default modes:

- `engineering_mentor`: AI/Agent updates become engineering judgment,
  practical rules, product critique, and caveats.
- `demo_first_tool`: tools and workflows are explained through real tested
  steps, screenshots/video plans, use cases, and limitations.
- `test_catalog`: model/news/previews are short, visual, status-aware, and
  separated into official, tested, leaked, rumored, or unverified.
- `builder_resource_log`: build-in-public progress uses short sentences,
  numbered resources, open-source/community loops, and one saveable list.
- `product_translator_longform`: papers, podcasts, English sources, tools, and
  product cases become Chinese long-form explanations with product implications,
  resource links, and clear source/interpretation boundaries.

Before drafting, choose one primary mode and one optional secondary mode. The
mode must change the output: hook, evidence, media plan, reusable asset, and
discussion question should all match it.

## Model Intelligence Quality Chain

Before public copy is marked ready, the model must expose these stages:

1. `source_grounding`: inspectable facts and unsafe claims.
2. `brand_lane`: main-account pillar or off-main/professional bug-report lane.
3. `angle_tournament`: materially different theses, not one summary rewritten.
4. `creator_pattern`: engineering mentor, demo-first tool, test catalog,
   builder resource log, or product translator longform selected without
   impersonation.
5. `asset_design`: reusable asset selected before drafting.
6. `draft_synthesis`: thesis -> mechanism -> example -> caveat -> attribution/question.
7. `adversarial_review`: attack unsupported claims, generic voice, missing
   asset/question, emotion leakage, and image governance.
8. `final_gate`: ready/revise/block with exact reason.

If a stage is missing, treat the pack as not fully reviewed.

## Inputs To Resolve

Infer these from the prompt when possible. Ask only if the missing answer would cause a misleading post.

- **Source/input**: one or more GitHub URLs, `owner/repo` strings, local paths, arXiv/alphaXiv papers, web URLs, PDFs/notes, existing posting packs, raw ideas, profile/bio prompts, KYC/support complaints, or a source-list file.
- **User relationship to the repo**: default to `independent sharer` unless the user clearly says they are the author, maintainer, contributor, or company/team member.
- **Posting language**: match the user's language; for Chinese prompts, write Chinese by default with technical English terms where natural.
- **User angle**: optional personal vision, use case, comparison, build plan, demo plan, or critique.
- **Brand lane**: default to the Agent engineering main account only when the
  source maps to agent reliability, build-in-public, paper-to-system, or
  embodied AI watch.
- **Output size**: adaptive, but default richer than a summary. Use as many posts as the repo evidence and user angle genuinely need. Prefer 4-6 posts only for thin sources or fast status updates; prefer 8-12 substantive posts for repo shares, paper-to-system posts, product-translator longform, or repo+vision posts; split further only when nuance, caveats, product/workflow implications, or evidence would otherwise be lost. When the user says posts are too short or asks for longer copy, treat short fragmentary drafts as not ready unless they are intentionally a short note.
- **Visuals**: default to 1-3 actual generated images for technical final posting packs. Use GPT Image 2 or the available built-in image generation tool unless the user explicitly says text-only, no images, prompts-only, or manual images. For professional bug reports, prefer real user-provided evidence screenshots or text-only output; do not generate fake support/KYC evidence.
- **Final-mile preference**: default to a paste-ready posting pack, not a prose-only critique. The user should be able to publish with minimal manual cleanup.
- **Publish mode**: default to `manual-safe`. Use `official-api-publish` only when the user explicitly wants CLI posting/uploading and has configured official X API user credentials. Never default to cookie/session/proxy-based posting services.
- **Evolution mode**: default to `record-and-suggest`. Improve future strategy through local strategy memory, but do not silently rewrite claims or skill instructions after one successful post.

## Core Workflow

In command examples, `<skill-dir>` means the directory that contains this `SKILL.md`. Resolve relative paths from this skill directory before running bundled scripts.

### 0. Route Any Input To A Strategy

Do this first whenever the input is not clearly a single GitHub/local repo, or whenever the user asks for adaptive strategy, publishing, or self-improvement.

Use the router:

```bash
python -B <skill-dir>/scripts/x_strategy_router.py <source-or-input> \
  --prompt "<full user request>"
```

For a governed arbitrary-input workspace:

```bash
python -B <skill-dir>/scripts/run_any_to_x_pack.py <source-or-input> \
  --prompt "<full user request>" \
  --run-id <stable-run-id>
```

The router writes or returns a `strategy_decision.json` shape with:

- source classification,
- selected strategy,
- Agent engineering brand fit,
- evidence plan,
- image policy,
- thread shape,
- learned notes from local strategy memory.

Read `references/self-evolving-strategy.md` when the user wants "any input", adaptive strategy, self-evolving behavior, postmortem feedback, or a reusable posting system. Read `references/skill-evolution-system.md` when the user asks the skill itself to learn from evals, publish outcomes, metrics, or Trending experiments. Read `references/content-quality-gates.md` and `references/creator-style-patterns.md` when a draft is safe but generic, too smooth, too abstract, too newsy, missing demo value, or the user complains that it lacks taste.

Input routing rules:

- GitHub URL / `owner/repo` / local repo -> use repo evidence workflow below.
- arXiv or alphaXiv -> paper-to-system workflow: read metadata and PDF text, search for official code before claiming code availability, then translate the paper into engineering patterns.
- Web URL -> page-evidence workflow: browse/open the page, collect public facts, and avoid over-quoting.
- Existing run/posting pack -> publish/review workflow: re-run cross-check and image gates before live publish.
- Raw idea -> research-first workflow: turn the idea into source questions; do not publish factual claims without evidence.
- KYC/support/platform complaint -> professional bug-report workflow: remove
  rage, hashtag stacks, and unsupported motive claims; preserve repro, impact,
  expected behavior, evidence, and next action.
- Profile/bio/pinned-post -> profile-positioning workflow: write a clear
  Agent engineering promise before tactical posting copy.

### 1. Collect Evidence

Do not write the thread from memory, source title, repo name, or URL alone.

For multi-repo or durable work, create a governed run workspace first:

```bash
python -B <skill-dir>/scripts/run_repo_to_x_pack.py <repo-or-path> [more repos...] --refresh
```

This writes all generated artifacts under `repo-to-x-workspace/runs/<run-id>/`, which is ignored by git. Use this as the user's accessible source of truth for the run.

For arbitrary non-repo inputs, use `run_any_to_x_pack.py` to create the same governed surface, then collect evidence into the generated `repo_context.json` / `source_context.json`.

Run workspace layout:

```text
repo-to-x-workspace/runs/<run-id>/
  run_manifest.json
  SUMMARY.md
  repos/<repo-id>/
    repo_context.json
    file_manifest.txt
    claims_ledger.json
    cross_check_review.md
    posting_pack.md
    images_manifest.json
    images/
    repo/
```

If the user gives a remote GitHub repo:

1. Clone it into the governed run workspace.
2. Read local files from the clone.
3. Fetch live metadata from GitHub.

If the user gives a local repo path:

1. Read the local working tree.
2. Resolve its `origin` remote if present.
3. Fetch live metadata from GitHub when the remote is available.

Prefer the bundled helper when useful:

```bash
python -B <skill-dir>/scripts/collect_repo_context.py <github-url-or-owner/repo-or-local-path> \
  --out repo-to-x-workspace/context/collect-repo-context
```

Then inspect the generated `repo_context.json` and `file_manifest.txt`.

Minimum evidence to collect:

- README and top-level docs.
- License file and package metadata (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, etc.).
- Source tree structure and obvious entry points.
- Examples, demos, docs, screenshots, papers, or benchmark files if present.
- GitHub metadata: description, stars, forks, topics, license, default branch, latest release, pushed/updated times, homepage, archived/fork status.

For paper/web/file inputs, collect the equivalent source evidence:

- title, authors/organization, publication/update date, and canonical URL,
- PDF/page text or local file content,
- linked code/data/project pages if present,
- source-specific caveats, such as no official code found or page content unavailable,
- any live metadata that matters and is safe to verify.

If a metadata source fails, state that it was unavailable. Do not invent stars, maintainers, releases, affiliations, benchmarks, code availability, paper results, or roadmap items.

For one-off single repo work, the lighter helper is acceptable. For anything involving multiple repos, comparison, repeatability, review, generated images, or final posting packs, use `run_repo_to_x_pack.py`.

### 2. Cross-Check Claims

Create a short internal claim ledger before drafting. You do not have to show every detail, but the final answer should reflect this separation:

- **Verified repo fact**: directly supported by local files or GitHub metadata.
- **Reasonable inference**: derived from code structure, dependencies, or examples.
- **User vision**: the user's own plan, interpretation, or deployment path.
- **Unknown / unsafe**: attractive claim that is not supported enough for X.

Examples:

- Safe: "The README describes support for Discord and Telegram."
- Unsafe unless proven: "This is the most complete open-source robotics agent framework."
- Safe with boundary: "My personal read is that this could fit a living-room robotics workflow."
- Unsafe: "The RoboClaw team plans to target living-room deployment" unless the repo says so.

When using the governed workspace, fill or update `claims_ledger.json` in the repo directory. Every public factual claim in `posting_pack.md` should map to one of:

- local file path,
- GitHub metadata field from `repo_context.json`,
- reasonable inference with evidence,
- user-provided personal vision.

Claims without evidence should be moved to `unknown_or_unsafe` and removed or softened before posting.

### 3. Preserve Ownership Boundaries

This is the most important reputation safeguard.

If the project is not the user's:

- Credit the maintainers/lab/company in the first post.
- Use "I found", "I am looking at", "my read", "my personal vision", not "we built" or "our roadmap".
- Do not recruit contributors on behalf of the project.
- Do not imply official endorsement, official roadmap, partnership, or affiliation.
- Invite discussion around the user's thinking, not PRs/issues unless the user explicitly wants that.

If the user is the author or maintainer:

- It is fine to use "we" or "I", but still separate shipped features from future plans.
- Label roadmap, experiments, and aspirations as such.

### 4. Decide The Thread Strategy

Choose one strategy and state it briefly before the draft.

Good default strategies:

- **Independent technical share**: best when the repo is not the user's.
- **Paper share**: best when the source is arXiv/alphaXiv or another research paper.
- **Research-backed post**: best when the source is a blog/docs URL, PDF, notes, or raw idea.
- **Repo + personal vision**: best when the user wants to use the repo as a jumping-off point for their own thinking.
- **Launch thread**: best when the user owns the repo or is releasing a project.
- **Builder notes**: best when the user tested or read the repo and wants to share practical lessons.
- **Comparison / roundup**: best when there are multiple sources or the user wants a candidate pool.
- **Publish existing pack**: best when the user says "上传/发布" and a reviewed `posting_pack.md` already exists.

For the user's common target style, prefer:

- technically accurate,
- respectful to original authors,
- concrete enough to show the user actually read the repo,
- modest about uncertainty,
- strong enough to be worth reposting.

### 5. Draft The X Thread

Adaptive structure:

1. Hook + exact attribution + repo link.
2. What the repo actually does.
3. Why it matters technically.
4. Evidence-backed feature breakdown.
5. The user's personal angle or vision, clearly labeled.
6. Deployment path, use case, or implication.
7. Caveats / early-stage boundary / what not to overclaim.
8. Closing question or discussion prompt when useful.
9. Reusable asset: checklist, flowchart, issue template, prompt snippet,
   before/after table, or failure-mode map.

The structure is a thinking scaffold, not a fixed post count. Drop sections that are irrelevant, merge thin sections, and add sections when the repo needs more careful attribution, evidence, comparisons, caveats, or user vision. A shorter accurate thread is better than padded content; a longer careful thread is better than compressing away responsibility.

Length guidance:

- Keep each post short enough to paste into X comfortably.
- For standard X accounts, aim for roughly 180-260 visible characters per post when the source has substance; do not label repeated 130-160 character fragments as ready for rich explainers.
- For paper-to-system, product-translator, and repo+vision posts, favor an explanation arc over compression: source boundary, mechanism, example, implication, asset, caveat, and question should all have room to breathe.
- If a post needs more nuance, split it rather than compressing into vague language.
- Number posts as `(1/N)`, `(2/N)`, etc. after the final post count is known. Do not lock to 8 posts before drafting and reviewing the content.

Avoid:

- "best", "first", "only", "most complete" unless strongly verified.
- Excessive emojis.
- "AI robot future is here" style hype.
- Fake certainty about project maturity.
- Hidden affiliation.
- Asking people to contribute to a project the user does not own.
- Support-rant shape: all-caps anger, repeated mentions, hashtag stacks, ticket
  spam, or demands like "fix this now".
- Main-account life/media chatter that has no Agent engineering mechanism.

Before locking the draft, do an angle pass:

- Find the one thesis a technical reader would remember or repeat.
- Prefer one sharp "not X, but Y" or "if the system is used this way, the training objective changes" frame over a complete source summary.
- Confirm the brand lane: agent reliability, build-in-public, paper-to-system,
  embodied AI watch, professional bug report, or off-main-account.
- Select the creator pattern: engineering mentor, demo-first tool, test catalog,
  or builder resource log. Make the media plan, asset, and question match it.
- Name the reusable asset before drafting the final thread.
- Write the final discussion question before locking the thread.
- Generate at least 2-3 materially different angles when the input is rich, unfamiliar, or publication-bound.
- Cut generic openers such as "recently saw", "worth reading", "interesting repo/paper", unless the rest of the hook is unusually strong.
- If the result reads like a paper abstract or README split into numbered posts, it is not ready even if the claims are safe.

Run a content-quality gate before treating hook polishing as the problem:

- **Source material**: a strong post needs enough raw material: an inspectable artifact, a sourced number, a before/after or failure mode, a reader pain, a caveat, or a source/ownership boundary. If the source only gives a tagline and stars, collect more evidence instead of writing around the emptiness.
- **Hook independence**: post 1 must work without a title, image, or prior context. It needs topic, reason to read, and credibility from evidence. Do not assume the reader saw the repo card.
- **Psychological trigger fit**: use cognitive conflict, curiosity gap, risk/loss, identity, or numeric anchor only when the evidence supports it. Do not turn technical nuance into clickbait.
- **Plain-language concept audit**: every high-level phrase such as "agentic", "self-evolving", "paradigm", "framework", or "future" must be immediately reducible to a concrete mechanism, file, workflow, or failure mode.
- **Anti-smoothness**: remove overly even AI prose: repeated "not X, but Y" turns, ritual transitions, perfectly balanced paragraphs, and conclusions that erase the real caveat. A technical post can have one visible uncertainty.
- **Creator pattern fit**: select one coherent mode. Product/tool posts should
  show tested steps or demo media; news/previews need status boundaries; build
  logs need an artifact, next validation, and community loop; engineering
  mentor posts need judgment plus a practical rule.
- **X shape**: sequence the thread as thesis -> mechanism -> example -> caveat -> link/implication. Do not make every post a feature list.

When Grok is configured and the user complains about quality, rigidity, taste, or weak hooks, run a draft tournament before publishing:

```bash
python -B <skill-dir>/scripts/x_draft_tournament.py <repo-run-dir> \
  --prompt "User taste feedback or desired style" \
  --write-proposed-pack
```

This writes `draft_tournament.json`, `draft_tournament.md`, and optionally `posting_pack.proposed.md`. Treat the proposed pack as a candidate, not as publish-approved. Re-run claim, image, and eval gates before live publish.

### 6. Build The Final-Mile Posting Pack

The final output should reduce the user's posting friction. After drafting, convert the thread into a practical publishing pack.

Include:

- **Paste-ready thread**: one clean code block containing only the posts, with no commentary inside.
- **Brand fit**: content pillar, account-fit decision, noise risk, reader
  takeaway, reusable asset, and discussion question.
- **Model quality chain**: source grounding, brand lane, angle tournament,
  creator pattern, asset design, draft synthesis, adversarial review, and final
  gate.
- **Per-post length audit**: mark each post as `OK`, `Tight`, or `Split` based on visible length. Do not force exact counts when multilingual text makes counting unreliable; use a conservative estimate and split posts that are clearly too long.
- **Image placement**: specify which image goes with which post, usually image 1 on the hook post and optional supporting images on later posts.
- **Alt text**: one short alt text per image, ready to paste into X.
- **Disclosure text**: one short line when images are generated or conceptual.
- **Pre-flight checklist**: 5-8 short checks the user can scan before posting.
- **Optional short version**: when useful, provide a single-post version for quick posting.
- **Publish mode**: state `manual-safe` or `official-api-publish`.

Keep this section practical. Avoid long explanations after the user has a paste-ready draft.

When using a run workspace, write the final copy into `posting_pack.md` and keep generated image paths in `images_manifest.json`. Do not leave the final usable output only in chat.

Suggested final-mile template:

````markdown
**Ready To Post**
```text
(1/N) ...

(2/N) ...
```

**Posting Map**
- Post 1: attach image 1, alt text: ...
- Post 4: attach image 2, alt text: ...
- Disclosure: Generated conceptual visual, not an official project screenshot.

**Length Audit**
- 1/N: OK
- 2/N: Tight, do not add more text
- 3/N: OK

**Pre-Flight**
- Repo owner credited.
- Personal vision labeled as personal.
- Agent engineering brand fit is explicit.
- Reusable asset is present.
- Concrete discussion question is present.
- No unsupported "best/first/only" claim.
- Images are conceptual or attributed.
- Link works.
````

### 6.1 Optional Official X API Publish

Only use this mode when the user explicitly asks for CLI publishing or full automation. This path can publish the first post and the rest of the thread from the CLI. The first post is created with `POST /2/tweets` without a `reply` field; each later post is created with `reply.in_reply_to_tweet_id` pointing to the previous post by default.

Do not use non-API website automation, browser scripting, cookie replay, hidden GraphQL calls, `auth_session` services, proxy-based posting, or third-party APIs as the default publish path. If the user asks for a free no-ban fully automated path, explain that the safe full-automation path is the official X API and that X API writes are pay-per-use.

Credential rule:

- `X_BEARER_TOKEN` is not enough to publish because it is app-only/read-oriented.
- Prefer OAuth2 user tokens with scopes: `tweet.read users.read tweet.write media.write offline.access`.
- The setup helper writes `X_OAUTH2_ACCESS_TOKEN` and `X_OAUTH2_REFRESH_TOKEN` into a local ignored `.env`.
- The user must create or configure an X Developer App, enable OAuth2, and register the exact callback URL used by the helper.

One-time credential setup:

```bash
python -B <skill-dir>/scripts/x_oauth2_pkce_setup.py --env-file .env
```

The helper opens the X consent screen, listens on `http://127.0.0.1:8765/callback` by default, exchanges the code, and stores tokens locally. If the X app uses a different callback URL, set `X_REDIRECT_URI` or pass `--redirect-uri`.

Dry-run a publish plan before any live post:

```bash
python -B <skill-dir>/scripts/x_publish_thread.py \
  repo-to-x-workspace/runs/<run-id>/repos/<repo-id>
```

Live publish only after the user confirms the posting pack and images:

```bash
python -B <skill-dir>/scripts/x_publish_thread.py \
  repo-to-x-workspace/runs/<run-id>/repos/<repo-id> \
  --live
```

The live publisher:

- reads `posting_pack.md` or `posting_queue.json`,
- uploads governed images from `images_manifest.json`,
- attempts to set media alt text,
- marks posts with `made_with_ai` when generated images are attached,
- posts the first item as the root post,
- posts later items as replies,
- writes `x_publish_log.json` without tokens.

Never run `--live` if `cross_check_review.md` is not `pass`, referenced images are missing from `images_manifest.json`, or the user has not explicitly approved the final copy.

### 7. Produce GPT Image 2 Visual Assets

Default rule: a technical final X posting pack includes actual generated images. When this skill is invoked for a repo/paper/source-to-X technical pack, treat image generation as required by default. Use the `imagegen` skill / built-in `image_gen` tool after the text strategy is clear unless the user explicitly opts out with text-only, no images, prompts-only, or manual images. Professional bug reports are the exception: use real evidence screenshots supplied by the user or text-only copy; do not generate fake KYC/support evidence. Do not say "images were not generated because the user did not explicitly request generated assets"; invoking this skill is enough signal to generate the default visual pack for technical posts.

Hard triggers: if the user asks for GPT Image 2, Image 2, image2, generated images, actual images, or "配图", generate images. Do not stop at prompts. Do not satisfy an image request by drawing low-quality placeholder cards with Python, SVG, HTML/CSS, or canvas unless the user explicitly asks for deterministic code-native graphics.

If the built-in image tool returns an image in chat or under `$CODEX_HOME/generated_images/...`, copy or move the selected image file into the repo run directory's `images/` folder, then register it. If an actual-image pack is required and the tool cannot expose a governable local file path, the image gate is blocked. Do not register prompt-only as a fallback, and do not pretend a chat-only image is a local posting asset.

Responsible visual rules:

- Do not generate fake screenshots of the repo, GitHub stars, dashboards, papers, benchmark tables, or robot results.
- Do not imply the generated image is an official project asset.
- Prefer conceptual visuals, clean diagrams, workflow boards, or "builder desk" scenes over fake product evidence.
- If using an official logo or screenshot from the repo, only use assets that are actually present and cite/label the source in the final response.
- Provide alt text for every image.

Good image concepts:

- Architecture/workflow: `GitHub repo -> evidence extraction -> claims ledger -> X thread -> generated visuals`.
- Domain visual: a realistic but clearly conceptual scene matching the project domain.
- Vision visual: a staged roadmap from current repo capabilities to the user's personal deployment idea.
- Evidence visual: only when built from verified repo artifacts, and never as a fake screenshot.

For each image, output:

- Purpose: where it fits in the thread.
- Prompt: ready for GPT Image 2 / image generation.
- Alt text: concise, accessible description.
- Disclosure line: e.g. "Generated conceptual visual, not an official project screenshot."

If image generation is available, generate 1-3 images by default. Do not stop at prompts. If image generation is not available for an actual-image pack, stop at a blocked image gate and report the limitation. Prompt-only output is allowed only when the user explicitly requested prompt-only/text-only/manual-image mode.

Generated images must be stored under the repo run directory's `images/` folder and recorded in `images_manifest.json` when a run workspace exists. Do not leave generated images only in chat, Downloads, a hidden app cache, or a random temp folder when the user asked for a governed posting pack.

After each generated image file exists locally, register it:

```bash
python -B <skill-dir>/scripts/register_image_asset.py <repo-run-dir> /path/to/generated.png \
  --id image-1 \
  --post 1/N \
  --purpose "hook visual" \
  --prompt "..." \
  --alt-text "..." \
  --disclosure "Generated conceptual visual, not an official project screenshot."
```

Only when the user explicitly requested prompt-only output, register a prompt-only asset and label it as non-publish-ready media:

```bash
python -B <skill-dir>/scripts/register_image_asset.py <repo-run-dir> \
  --prompt-only \
  --prompt-only-reason user_requested_prompt_only \
  --id image-1 \
  --post 1/N \
  --purpose "hook visual" \
  --prompt "..." \
  --alt-text "..."
```

Before saying the pack is ready, check `images_manifest.json`:

- every image referenced by `posting_pack.md` has an entry,
- actual files have `path`, `sha256`, and `mime_type`,
- every entry has `alt_text` and `disclosure`,
- generated/conceptual images have `review_status` set to `approved` or are clearly marked as needing review.

When a run workspace exists, run the image gate before presenting "Ready To Post":

```bash
python -B <skill-dir>/scripts/check_image_assets.py <repo-run-dir>
```

If this command fails because images are still `planned` or `prompt_only`, use `imagegen` / built-in image generation and register the generated files before claiming the pack is ready. Only pass `--allow-prompt-only` when the user explicitly requested prompt-only/text-only/manual-image mode; never use it as a fallback for failed image generation.

Default Image 2 pack:

1. **Hero image** for post 1: visually communicates the repo domain and the user's angle without pretending to be an official asset.
2. **Architecture or workflow image** for a middle post: explains how the repo works or how the user's analysis pipeline works.
3. **Vision image** for a later post: shows the user's personal deployment path or future framing.

Image prompt rules:

- Include aspect ratio preference. For X, default to `16:9` for landscape technical diagrams or `4:5` for high-feed visual weight.
- Specify clean composition, readable spacing, no fake UI text unless the text is generic and minimal.
- Avoid logos unless the repo provides one and usage is appropriate.
- Prefer "conceptual illustration" or "technical diagram" language when the image is not evidence.
- Add "no fake screenshots, no fake GitHub metrics, no fake benchmark tables" to the prompt when relevant.

### 8. Final Output Format

Use this format unless the user asks otherwise:

````markdown
**Evidence**
- Repo: ...
- Local source checked: ...
- Live metadata checked: ...
- Public-safe facts: ...
- Caveats: ...

**Posting Strategy**
...

**Ready To Post**
```text
(1/N) ...

(2/N) ...

...
```

**Posting Map**
- Post 1: attach image 1, alt text: ...
- Disclosure: ...

**Length Audit**
- 1/N: OK
- 2/N: OK

**Images**
1. Purpose: ...
   Prompt: ...
   Alt text: ...
   Disclosure: ...

**Do Not Say**
- ...
````

If the answer is for immediate posting, the `Ready To Post` block is the primary artifact. Keep surrounding analysis brief enough that the user can quickly find the copyable thread.

### 9. Cross-Check Review Gate

Before presenting a final posting pack as ready, run the review gate:

1. Compare `posting_pack.md` against `claims_ledger.json`.
2. Mark each factual claim as sourced, needs revision, or remove.
3. Update `cross_check_review.md` with `pass`, `revise`, or `block`.
4. If status is `revise` or `block`, do not present the pack as ready to post; present the required fixes first.

The review gate is required for multi-repo runs and strongly preferred for single-repo runs.

### 10. Git Hygiene

Keep generated artifacts out of git:

- `.env`
- `repo-to-x-workspace/`
- cloned repos
- generated images
- repo-specific claims ledgers
- repo-specific posting packs
- repo-specific cross-check reviews

Before committing or publishing the skill repo, run:

```bash
git status --short --ignored
git diff --cached --check
rg -n --hidden --glob '!.env' --glob '!.git/**' '(g[h]p_|g[h]o_|github_[p]at_|BEGIN [A-Z ]{0,30}PRIVATE KEY)' . || true
```

### 11. Self-Evolving Strategy Loop

Use this loop when the user wants the skill to get better over time, when publishing is completed, or when feedback/metrics are available.

1. Before drafting, run or create `strategy_decision.json` with `x_strategy_router.py` or `run_any_to_x_pack.py`.
2. During drafting, follow the strategy but keep claim safety above learned preferences.
3. After review or live publish, record the outcome:

```bash
python -B <skill-dir>/scripts/record_post_outcome.py <repo-run-dir> \
  --manual-quality 0.8 \
  --lesson "Reusable lesson from this run."
```

4. If X metrics are available, record them instead of guessing:

```bash
python -B <skill-dir>/scripts/record_post_outcome.py <repo-run-dir> \
  --impressions 10000 \
  --likes 120 \
  --reposts 18 \
  --replies 9 \
  --bookmarks 35 \
  --lesson "Reusable lesson from this run."
```

The outcome recorder writes local ignored memory under:

```text
repo-to-x-workspace/strategy-memory/outcomes.jsonl
repo-to-x-workspace/strategy-memory/strategy_profile.json
```

Use local strategy memory as a bias for future strategy selection. Do not treat engagement as proof that a claim was true, and do not silently insert performance-driven rules into the canonical skill without explicit review.

When the user asks for a broader "skills 自进化体系", or after a batch of evals,
Trending experiments, or live posts, synthesize the evidence before editing the
canonical skill:

```bash
python -B <skill-dir>/scripts/x_skill_evolution.py \
  --runs-root repo-to-x-workspace/runs \
  --memory-root repo-to-x-workspace/strategy-memory
```

This writes an ignored workspace under:

```text
repo-to-x-workspace/skill-evolution/<run-id>/
  signal_ledger.json
  skill_evolution_summary.json
  skill_evolution_report.md
  skill_patch_plan.md
```

Use `--apply-profile` only when you want future router runs to read the proposed
rules as local strategy-memory guidance:

```bash
python -B <skill-dir>/scripts/x_skill_evolution.py --apply-profile
```

That flag updates `strategy_profile.json` with `evolution_guidance`; it does not
edit `SKILL.md`, prompts, eval gates, or public copy. Convert a patch plan into
canonical skill changes only after reviewing the signal ledger and adding or
updating a regression eval. See `references/skill-evolution-system.md` for the
full contract.

### 12. X Eval Agent

Use the X eval agent when the user asks whether a post is strong, algorithm-friendly, likely to perform, safe to publish, or when they provide Grok/API access for automatic scoring.

Read `references/x-eval-rubric.md` for the scoring contract. The evaluator is an approximation, not the real X ranking oracle.

Before publishing a final pack, run:

```bash
python -B <skill-dir>/scripts/x_eval_post.py <repo-run-dir>
```

This reads:

- `posting_pack.md`,
- `claims_ledger.json`,
- `cross_check_review.md`,
- `images_manifest.json`,
- optional `strategy_decision.json`,
- optional `GROK_API_KEY` / `GROK_MODEL` from `.env`.

It writes:

```text
post_eval.json
x_eval_report.md
```

If `GROK_API_KEY` is available, Grok is used as the semantic evaluator. If not, the script falls back to deterministic rubric scoring. Treat Grok as a reviewer, not as evidence.

If the evaluator returns `revise` because of `angle_freshness`, `specificity_density`, or `voice_authenticity`, run `x_draft_tournament.py` instead of only trimming text. A safe but forgettable thread should be rewritten around a stronger angle.

After publishing, collect metrics:

```bash
python -B <skill-dir>/scripts/x_collect_metrics.py <repo-run-dir>
```

Then calibrate strategy memory:

```bash
python -B <skill-dir>/scripts/x_calibrate_strategy.py <repo-run-dir> \
  --lesson "Reusable lesson from this post."
```

Publish gate recommendation:

- `post_eval.json` decision should be `ready`, or the user explicitly approves publishing despite `revise`.
- `claim_safety` must stay above the threshold in `x-eval-rubric.md`.
- `brand_clarity`, `cta_specificity`, `asset_value`, `emotion_control`, and
  `account_fit` should pass; a safe post can still be revised if it blurs the
  account.
- `cross_check_review.md` and image gates still matter more than a high Grok score.
- Never optimize for engagement by weakening attribution, source boundaries, or generated-image disclosure.

### 13. Trending Repo Experiments

Use this when the user wants to pull from GitHub Trending, try many repos, burn tokens, benchmark quality, or converge the skill's strategy.

Default to a two-stage funnel:

1. **Fast text-only screen**: pull current GitHub Trending, fetch GitHub metadata + README only, generate copy, run text-only eval, and run tournaments. Do not clone large repos or generate images yet.
2. **Deep publish prep**: only for candidates that survive the screen or the user selects, clone/read the repo deeply, verify claims, generate actual images, and run publish gates.

Run the fast screen:

```bash
python -B <skill-dir>/scripts/x_trending_experiment.py \
  --limit 10 \
  --rounds 3 \
  --since daily \
  --metadata-only
```

Use deep clone mode only for a small candidate set:

```bash
python -B <skill-dir>/scripts/x_trending_experiment.py \
  --limit 3 \
  --rounds 3 \
  --since daily \
  --refresh
```

The experiment writes:

```text
repo-to-x-workspace/runs/<run-id>/
  trending_sources.txt
  trending_experiment_results.json
  trending_experiment_report.md
  repos/<owner__repo>/
    posting_pack_round1.md
    posting_pack_round2.md
    posting_pack_round3.md
    experiment_eval_round*.json
```

Experiment rules:

- Use `--text-only-eval` during early screening; ignore image/media feedback until publish prep.
- Accept a tournament rewrite only if its eval score improves over the current accepted draft.
- If no candidate crosses the ready threshold, do not force publish. Treat the common fixes as strategy feedback.
- Common failure modes to watch: no repeatable thesis, generic repo-note opener, too much README summary, too little concrete example, missing caveat, and mixed-language voice drift.
- For globally trending developer repos, a short English or bilingual hook can improve reach, but keep the thread voice coherent.
- After the experiment, write reusable lessons into strategy memory or skill instructions; do not mutate factual claims based on engagement predictions.

## Quality Bar

Before finalizing, run this checklist:

- Is the repo owner credited early enough to avoid hidden affiliation?
- Are all strong claims backed by repo files or GitHub metadata?
- Are personal opinions and visions labeled as personal?
- Does the post fit the Agent engineering account promise?
- Is there one reusable asset?
- Is there one concrete discussion question?
- Has complaint emotion been converted into a bug-report or failure-mode shape?
- Does the thread avoid sounding like an official announcement when the user is only sharing?
- Does it include a useful technical reason to care?
- Does it include at least one caveat or maturity boundary when appropriate?
- Would a maintainer of the repo feel accurately represented?
- Are generated images clearly conceptual rather than fake evidence?
- Can the user publish from the `Ready To Post` block without rewriting formatting?
- Are image placement, alt text, and generated-image disclosure clear?

## Example: Independent Share + Personal Vision

Use this pattern when the user says the project is not theirs:

```text
(1/N) Agent 系统最容易重复踩坑的地方，不是模型不够聪明，而是失败没有地方沉淀。

<repo> by <owner> 正在处理 <verified project scope>. 我不是项目成员，只是从 Agent 工程视角看它的 failure-memory 价值。

<repo URL>

下面是我的个人理解和一个可复用检查表。
```

Then continue with verified facts first, and the user's vision second.
