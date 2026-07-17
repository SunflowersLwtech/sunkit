# Model Intelligence Quality Chain

This chain is the model-side thinking contract before any X copy is treated as
publishable. It is not decorative documentation: generated packs should expose
the chain status so reviewers can see where quality came from.

## Stages

1. `source_grounding`: extract inspectable facts first; remove or caveat claims
   without evidence.
2. `brand_lane`: choose main-account pillar, professional bug report, or
   off-main route before writing.
3. `angle_tournament`: generate materially different theses, not minor rewrites
   of one summary.
4. `creator_pattern`: select a coherent creator mode such as engineering
   mentor, demo-first tool, test catalog, builder resource log, or product
   translator longform without impersonation.
5. `asset_design`: choose the reusable asset before drafting.
6. `draft_synthesis`: write thesis -> mechanism -> example -> caveat ->
   attribution/question.
7. `adversarial_review`: attack the draft for unsupported claims, weak hook,
   generic voice, emotion leakage, missing asset, missing question, and image
   governance.
8. `final_gate`: mark ready only when claim, brand, asset, CTA, image, and
   publish gates pass.

## Required Output

`posting_pack.md`, `draft_tournament.md`, or generated JSON should include a
`Model Quality Chain` section or `model_quality_chain` object with:

- `status`: `pass`, `revise`, or `block`;
- `evidence`: concrete support for the status;
- `decision`: what changed because of that stage.

If a stage is missing, the draft is not considered fully reviewed.

## No Escape Rule

Do not replace a failed quality stage with generic copy, prompt-only media,
temporary install output, mocked metrics, or a disposable artifact. A failed
stage should remain failed until the real evidence or artifact exists.
