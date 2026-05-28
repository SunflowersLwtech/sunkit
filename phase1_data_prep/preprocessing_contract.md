# Preprocessing Contract

The preprocessing pipeline converts source-specific records into score-ready candidates. It must preserve source evidence and avoid early LLM calls.

## Pipeline

```text
raw fetch
-> raw JSONL per source
-> timestamp and URL normalization
-> entity extraction
-> exact dedupe
-> fuzzy dedupe
-> cheap enrichment
-> Stage 1 heuristic filter
-> score-ready candidate shortlist
```

## Artifact Layout

```text
runtime/artifacts/YYYY-MM-DD/<run_id>/
  raw/
    github_trending.jsonl
    hacker_news_algolia.jsonl
    product_hunt_feed.jsonl
    huggingface_models.jsonl
    arxiv_ai_ml_cl.jsonl
    v2ex_hot.jsonl
    kr36_feed.jsonl
  normalized_candidates.jsonl
  dedupe_clusters.json
  stage1_filter_report.json
  candidate_shortlist.json
```

## Raw Ingest Rules

- Write raw payloads before transformation.
- Add `source`, `source_item_id`, `collected_at`, and `raw_sha256` to every raw item.
- Do not discard source-native fields in raw storage.
- Record fetch errors as events, not as empty successful files.

## Normalization Rules

Required normalized fields:

- `candidate_id`: stable hash from canonical entity or canonical URL.
- `source_ids`: source item references included in this candidate.
- `canonical_url`: clean URL without tracking params.
- `entity_type`: one of `repo`, `product`, `model`, `paper`, `discussion`, `article`, `unknown`.
- `entity_key`: repo full name, model ID, arXiv ID, product domain, or title hash.
- `title`, `summary`, `published_at`, `collected_at`.
- `metrics`: source-specific metrics normalized into numeric fields.
- `evidence`: source URL list with reliability weights.
- `signals`: cheap boolean or numeric indicators used before LLM scoring.
- `risk_flags`: reasons a candidate may be unsafe or weak.

## URL Canonicalization

Strip:

- `utm_*`;
- `ref`;
- `source`;
- `spm`;
- `from`;
- `trk`;
- Product Hunt redirect wrappers when target URL is available.

Normalize:

- GitHub repo URLs to `https://github.com/{owner}/{repo}`;
- Hugging Face model URLs to `https://huggingface.co/{author}/{model}`;
- arXiv URLs to `https://arxiv.org/abs/{id}`;
- remove trailing slashes unless source-native identity requires them.

## Entity Extraction

Use deterministic extraction first:

- GitHub URL -> `repo:{owner}/{repo}`;
- Hugging Face URL -> `model:{author}/{model}`;
- arXiv ID -> `paper:arxiv:{id}`;
- Product domain -> `product:{domain}`;
- HN/V2EX/36Kr external URL domain -> `web:{domain}:{title_hash}`.

Only use LLM extraction later for candidates that survive Stage 1.

## Dedupe Rules

Exact merge if any of these match:

- same canonical URL;
- same GitHub `owner/repo`;
- same Hugging Face `author/model`;
- same arXiv ID;
- same source-native stable ID in the same source.

Fuzzy merge if:

- normalized title token Jaccard >= 0.82; or
- character 3-gram Jaccard >= 0.78; or
- title similarity >= 0.72 and canonical domains match.

Do not merge if two items share only generic terms like `AI agent`, `LLM`, `RAG`, `automation`, or `open source`.

## Cheap Signal Extraction

Compute these without LLM:

| Signal | Rule |
| --- | --- |
| `freshness_hours` | `collected_at - published_at` when available |
| `has_demo_keyword` | title/summary/readme contains demo, playground, try, live, video, screenshot, examples, gradio |
| `has_code_signal` | GitHub URL, arXiv code link, Hugging Face model card, package link |
| `has_buyer_keyword` | contains workflow, team, support, sales, ops, devtools, enterprise, API, pricing |
| `has_pain_keyword` | contains automate, replace, faster, reduce cost, bottleneck, privacy, self-hosted, error-prone |
| `ad_language_density` | ratio of promo terms to total tokens |
| `source_count` | number of independent sources in a dedupe cluster |
| `metric_strength` | source-relative normalized engagement |

Chinese keyword equivalents should be included for CN sources.

## Stage 1 Filter

Reject before LLM scoring when:

- no URL;
- published more than 30 days ago unless it is cross-source validated today;
- title is too generic after stopword removal;
- content is pure job listing, coupon, press release, or ad copy;
- no demo, code, product, model, paper, or discussion artifact can be found;
- source fetch succeeded but required fields are empty.

Keep but flag when:

- strong metrics but no demo signal;
- strong launch copy but no independent discussion;
- funding or customer claims appear;
- source is community-only and not confirmed by official page;
- item requires manual login to view.

## Stage 1 Output

`candidate_shortlist.json` should contain no more than 20 items:

```json
{
  "run_id": "2026-05-28-daily-001",
  "generated_at": "2026-05-28T12:30:00+08:00",
  "candidates": [
    {
      "candidate_id": "repo:owner/name",
      "title": "Example Repo",
      "entity_type": "repo",
      "canonical_url": "https://github.com/owner/name",
      "stage1_score": 7.4,
      "stage1_reasons": [
        "fresh within 48h",
        "demo keyword in README",
        "GitHub and HN evidence"
      ],
      "risk_flags": [
        "metrics_unverified"
      ],
      "next_actions": [
        "fetch README",
        "cross-check HN discussion",
        "run five-dimensional scoring"
      ]
    }
  ]
}
```

## Stage 1 Heuristic Weights

These are temporary pre-LLM weights. They only decide what enters five-dimensional scoring.

| Dimension | Weight |
| --- | ---: |
| Freshness | 0.25 |
| Demo signal | 0.25 |
| Engagement strength | 0.15 |
| Buyer/pain keyword signal | 0.20 |
| Source reliability and source count | 0.15 |

Items below `stage1_score < 5.8` should not enter LLM scoring unless manually selected.
