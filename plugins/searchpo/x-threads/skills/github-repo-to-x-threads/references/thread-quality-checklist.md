# Thread Quality Checklist

Use this when the repo facts are collected but before final output.

## Reputation Safety

- The post fits the `Agent 工程实战派` promise or is explicitly routed off-main-account.
- KYC/support/platform complaints are rewritten as cold bug reports unless they teach an Agent reliability lesson.
- Life/media/mood notes are tied to a concrete Agent engineering mechanism or moved off the main account.
- The repo owner is credited early enough to avoid hidden affiliation, usually by post 2 or the final attribution/link post.
- The user relationship is clear: author, contributor, or independent sharer.
- The post does not imply endorsement, official roadmap, or affiliation unless verified.
- The post does not ask for contributors unless the user owns the project or explicitly wants to promote contribution.
- Any user's own vision is labeled as personal thinking.

## Evidence Safety

- Stars, forks, releases, dates, and license come from live metadata or are omitted.
- Capabilities come from README/docs/code, not repo name vibes.
- Benchmarks, production readiness, and hardware support are stated only if directly supported.
- "Best", "first", "only", and "most complete" are avoided unless there is strong evidence.
- Missing or failed metadata is disclosed briefly when relevant.

## Thread Shape

- Post 1 starts from reader pain, technical conflict, or engineering risk.
- The hook is specific and not clickbait.
- Each post adds a new reason to care.
- The thread count is adaptive to the evidence and user angle; it is not forced to exactly 8 posts.
- Thin/fast updates can be 4-6 posts, but paper-to-system, product-translator, and rich repo+vision drafts should usually be 8-12 substantive posts.
- If several posts are under 150 characters in a rich explainer, merge or expand them with mechanism, example, implication, resource value, or caveat before marking the pack ready.
- Thin sections are merged or dropped; complex evidence, caveats, or user vision can add posts.
- Technical terms are concrete enough for developers but not written like README paste.
- Caveats make the post more credible, not weaker.
- The thread includes one reusable asset: checklist, flowchart, issue template, prompt snippet, before/after table, or failure-mode map.
- The ending asks one concrete technical question, not blind hype or a vague CTA.

## Creator Pattern Fit

- One primary creator mode is selected: `engineering_mentor`, `demo_first_tool`, `test_catalog`, `builder_resource_log`, or `product_translator_longform`.
- The hook matches the mode: conflict/rule, pain/demo result, newly available status, or build artifact.
- Tool/demo posts include real tested steps, real screenshots/video when available, or an explicit not-tested boundary.
- News/preview/leak posts separate official release, tested result, leak, rumor, and inference.
- Build-in-public posts include a concrete artifact, current status, next validation, and one community loop.
- Product-translator posts separate original source facts, interpretation, product implication, and user vision.
- Product-translator posts include resource links, a reading path, command/repo/paper/case artifact, or a saveable summary.
- Engineering-mentor posts include a practical rule or product judgment, not only a feature summary.
- The draft does not copy any creator's catchphrases, personal identity, or community nickname.

## Final-Mile Posting

- The user has a single clean copy-paste block with only the posts.
- Every post has a rough length status: OK, Tight, or Split.
- The thread includes a posting map for image placement.
- Alt text is ready to paste into X.
- Generated-image disclosure is ready when needed.
- A one-post short version is included when it would materially reduce publishing friction.
- Publish mode is explicit: `manual-safe` or `official-api-publish`.
- `official-api-publish` is not used unless the user explicitly approved live CLI posting.
- `official-api-publish` uses official X OAuth2 user credentials, not app-only `X_BEARER_TOKEN` and not cookie/session/proxy automation.

## Visual Safety

- Generated visuals are labeled as conceptual.
- No fake UI screenshots, fake robot evidence, fake benchmark charts, or fake GitHub metrics.
- Alt text is included.
- Official assets are used only when actually present and attributed.
- Every image referenced in the posting map has a matching `images_manifest.json` entry.
- Generated image files live under `images/` with `sha256` and `mime_type`.

## GPT Image 2 Quality

- Image generation is the default for technical final posting packs unless the user explicitly says text-only, no images, prompts-only, or manual images.
- Professional bug reports use real evidence screenshots or text-only output, not generated fake evidence.
- If image generation is available, the agent generates images rather than only writing prompts.
- If the user says GPT Image 2, image2, generated images, actual images, or 配图, the agent treats this as a hard trigger to use the native `imagegen` / built-in image generation path.
- Script-drawn cards, SVG placeholders, browser screenshots, HTML/CSS, canvas, or Python charts are not acceptable substitutes for GPT Image-style generated assets unless the user explicitly requested deterministic code-native visuals.
- Prompts specify aspect ratio, composition, and the post where the image will be used.
- Prompts explicitly avoid fake screenshots, fake GitHub metrics, and fake benchmark tables when relevant.
- The first image supports the hook; later images explain architecture, workflow, or personal vision.
- `scripts/check_image_assets.py <repo-run-dir>` passes before the pack is described as ready.
- If the image tool cannot expose a file path for an actual-image pack, the image gate is blocked. Do not replace it with `prompt_only`.
