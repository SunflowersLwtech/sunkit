# X Eval Rubric

This rubric scores a posting pack before publishing and calibrates the strategy after publishing. It is not a real X ranking oracle. It is a local approximation that combines:

- public X recommendation-system signals,
- posting-pack safety gates,
- Grok semantic judgment,
- the user's own historical outcomes.

## Pre-Publish Scores

Use 0.0-1.0 scores.

| Score | Meaning |
| --- | --- |
| `claim_safety` | Public claims are sourced, ownership is clear, no fake metrics or unsupported superlatives. |
| `hook_strength` | The first post gives a concrete reason to stop scrolling within the first sentence. |
| `angle_freshness` | The thread has a sharp, repeatable thesis instead of a generic summary opener. |
| `specificity_density` | The post contains concrete technical details, examples, names, or mechanisms without becoming cluttered. |
| `audience_fit` | The thread matches the intended technical audience and avoids generic AI slop. |
| `bookmark_value` | Readers can save the post for a concrete technical idea, tool, repo, paper, or workflow. |
| `reply_potential` | The post invites useful discussion without baiting low-quality controversy. |
| `media_quality` | Images are governed, high-quality, relevant, accessible, and clearly conceptual when generated. |
| `structure_fit` | Thread length, sequencing, links, caveats, and post lengths fit X ergonomics. |
| `voice_authenticity` | The copy sounds like a real technical reader with taste, not a rigid generated template. |
| `risk_control` | Low spam/template/link/controversy/downranking risk. |
| `brand_clarity` | The copy clearly supports the Agent engineering positioning rather than a generic AI/news/life stream. |
| `cta_specificity` | The ending asks a concrete technical question that can trigger useful replies. |
| `asset_value` | The thread gives readers a reusable asset such as a checklist, template, flow, prompt, or failure map. |
| `emotion_control` | Emotional or complaint-like input is converted into process, repro, impact, and expected behavior. |
| `account_fit` | The post belongs on the main account; off-topic support/life/media material is filtered or rewritten. |
| `creator_pattern_fit` | The draft uses one coherent content mode: engineering mentor, demo-first tool, test catalog, builder resource log, or product translator longform, without impersonation. |

Additional content-quality checks:

- `source_material_density`: the draft contains enough material to justify a hook: concrete artifacts, sourced numbers, before/after contrast, reader pain, and a caveat.
- `hook_independence`: post 1 works without the link card, image, or title and makes topic + reason to read + evidence credibility legible.
- `plain_language_conversion`: high-level concepts are translated into concrete mechanisms or workflows.
- `anti_smoothness`: the copy avoids over-polished AI patterns, repeated balanced turns, ritual transitions, and fake certainty.
- `demo_or_test_evidence`: tool/testing claims include real test details,
  screenshot/video plans, or a clear not-tested boundary.
- `practical_next_action`: the reader can try, inspect, compare, save, or adapt
  something after reading.
- `community_loop`: the final question invites useful test results, workflow
  comparisons, design tradeoffs, or beta feedback.
- `translation_value`: complex sources become clear Chinese product/workflow
  decisions while preserving source, interpretation, and user-vision boundaries.
- `explainer_depth`: rich paper-to-system, product-translator, and repo+vision
  drafts use enough space for a real explanation arc instead of passing as short
  checklist fragments.

Default weighted score:

```text
final_score =
  0.15 * claim_safety
+ 0.10 * hook_strength
+ 0.09 * angle_freshness
+ 0.08 * specificity_density
+ 0.05 * audience_fit
+ 0.07 * bookmark_value
+ 0.04 * reply_potential
+ 0.05 * media_quality
+ 0.04 * structure_fit
+ 0.04 * voice_authenticity
+ 0.03 * risk_control
+ 0.07 * brand_clarity
+ 0.04 * cta_specificity
+ 0.05 * asset_value
+ 0.03 * emotion_control
+ 0.02 * account_fit
+ 0.05 * creator_pattern_fit
```

Recommended gates:

- `final_score >= 0.80`: ready if cross-check and image gates pass.
- `0.65 <= final_score < 0.80`: revise before publishing.
- `< 0.65`: block or rewrite.
- Any `claim_safety < 0.75`: revise, regardless of final score.
- Any `angle_freshness < 0.62`: revise, even if the thread is accurate.
- Any `specificity_density < 0.65`: revise.
- Any `voice_authenticity < 0.58`: revise.
- Any `brand_clarity < 0.58`: revise.
- Any `cta_specificity < 0.55`: revise.
- Any `asset_value < 0.55`: revise.
- Any `emotion_control < 0.60`: revise.
- Any `account_fit < 0.55`: revise.
- Any `creator_pattern_fit < 0.58`: revise.
- Any `media_quality < 0.65` when images are required: regenerate or remove image references.
- Rich explainers with many short posts, average post length below the source
  complexity, or no mechanism/example/implication arc should revise even when
  claim safety and hook strength are high.

The harsh rule: a safe, accurate summary is not automatically ready. If it reads like a paper abstract split into numbered tweets, if the hook needs the link card to make sense, if the draft has no inspectable example, or if a complex source is compressed into skinny checklist posts, it should go through draft tournament or rewrite.

## Grok Evaluation Role

Use Grok for semantic judgment:

- Is the hook specific and non-generic?
- Does the thread sound like a real technical reader wrote it?
- Does it overclaim?
- Is the caveat visible enough?
- Which post is most likely to create bookmark/reply value?
- Which line should be cut before publishing?
- What is the one thesis a reader would remember or repost?
- Is there enough source material to justify the hook, or is the copy writing around an empty thesis?
- Which high-level concept should be translated into concrete workflow language?
- Does this belong on the Agent engineering main account?
- What reusable asset does the reader save?
- Is the discussion question specific enough to answer?
- If the source is a complaint, has emotion been converted into a bug report?
- Which creator pattern is the draft using, and does the hook/media/asset/question match that pattern?
- Are "tested", "demo", "preview", "leak", "rumor", and "official release" boundaries truthful?
- If the post translates a paper/podcast/English source, are original facts,
  product interpretation, and trend prediction separated?

Grok should return JSON. Treat it as a reviewer, not as evidence. If Grok says a factual claim is true, still require the claim ledger or source context.

## Draft Tournament

When the user says the post feels weak, rigid, generic, or not worth publishing, run:

```bash
python -B scripts/x_draft_tournament.py <repo-run-dir> \
  --prompt "Short description of the user's taste feedback" \
  --write-proposed-pack
```

This writes:

```text
draft_tournament.json
draft_tournament.md
posting_pack.proposed.md
```

The tournament should produce multiple angles first, then thread variants. The winning version still needs the normal claim, image, and publish gates.

## Text-Only Early Screening

For GitHub Trending or large-scale experiments, run copy quality before media quality:

```bash
python -B scripts/x_eval_post.py <repo-run-dir> --text-only-eval
```

In text-only mode:

- ignore image/media suggestions,
- focus on hook, angle, specificity, caveats, claim safety, and voice,
- accept a rewrite only if the score improves,
- deep clone, image generation, alt text, and media gates happen only after a candidate survives the screen.

If repeated rounds do not cross the ready threshold, do not publish. Convert the common fixes into strategy rules.

## Post-Publish Metrics

Collect metrics from X API when possible, then aggregate:

- impressions,
- likes,
- reposts / retweets / quotes,
- replies,
- bookmarks,
- profile clicks,
- URL clicks when available.

Outcome score can use:

```text
outcome_score =
  (likes + 2*reposts + 1.5*replies + 1.5*bookmarks + profile_clicks) / max(impressions, 1)
```

Use outcome scores to calibrate strategy memory. Do not use performance as proof that a public claim was accurate.

## Report Files

Pre-publish eval:

```text
post_eval.json
x_eval_report.md
```

Post-publish metrics:

```text
x_metrics_snapshot.json
post_outcome.json
```

Calibration:

```text
repo-to-x-workspace/strategy-memory/outcomes.jsonl
repo-to-x-workspace/strategy-memory/strategy_profile.json
```
