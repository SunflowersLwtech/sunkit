# Claim Governance

Searchpo publishes candidate radar content, not verified market conclusions. Every post must keep the source boundary visible.

## Claim Types

| Type | Allowed Source | Public Wording |
| --- | --- | --- |
| Pipeline fact | Local run artifacts such as `candidate_shortlist.json` | "selected by searchpo" or "entered the candidate pool" |
| Source-reported fact | Original URL in candidate evidence | "appeared on GitHub Trending" or "source page reports..." |
| Metric fact | Source-native metric captured in artifacts | Include timestamp/source; avoid ranking unless source provides it. |
| Inference | Operator or model interpretation | Phrase as "may indicate", "worth checking", or "candidate signal". |
| Manual-review claim | Funding, customers, benchmark, production maturity | Requires official source plus independent corroboration before use. |
| Prohibited claim | Best, first, only, market leader, guaranteed outcome | Block unless explicitly proven and approved outside the default flow. |

## Required Evidence

Generated post artifacts must retain:

- selected candidate ID and canonical URL;
- source IDs and source URLs;
- collected timestamp;
- claim role for each evidence item;
- caveats for unsupported or manually reviewed claims.

`claims_ledger.json` is the review source of truth. `posting_pack.md` is a human-readable package, not a substitute for structured evidence.

## Review Checklist

- The first hook names the evidence boundary, not hype.
- No unsupported `best`, `first`, `only`, `首个`, `唯一`, `最强`, or benchmark claim appears.
- Community-only signals are labeled as discussion signals.
- Funding, customer, and market-size claims are either removed or backed by official sources.
- Live publishing is authorized only through `SEARCHPO_E2E_PROFILE=live` and `SEARCHPO_DOUYIN_LIVE=1`.
