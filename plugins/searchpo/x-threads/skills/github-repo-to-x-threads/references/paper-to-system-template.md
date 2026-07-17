# Paper-To-System Thread Template

Use this for arXiv/alphaXiv/paper inputs. The goal is not a paper summary. The
goal is an engineering pattern a builder can reuse.

## Structure

```text
(1/N) <reader pain or engineering conflict>.

This paper is useful because it turns <research idea> into <system design
question>. I care less about the slogan and more about the mechanism:
<mechanism 1>, <mechanism 2>, <mechanism 3>.

(2/N) Source boundary:
<paper title/authors/link>. I am not affiliated. My read is about engineering
translation, not an official claim.

(3/N) Pattern:
<research concept> -> <system component>
<research concept> -> <runtime policy>
<research concept> -> <eval or failure gate>

(4/N) Reusable asset:
Checklist / flow / prompt / issue template.

(5/N) Caveat:
<what the paper does not prove, what needs code/data/eval, or where the
engineering translation can fail>.

(N/N) Question:
<specific technical tradeoff question>
```

## Hook Rules

Do not open with:

- `最近看了这篇 paper`;
- `这篇论文很有意思`;
- `quick thread`;
- a title-only intro.

Open with:

- a failure mode;
- a tradeoff;
- a surprising system-design implication;
- a reader pain that the paper helps frame.

## Asset Examples

- `answer/search/hedge/stop` routing policy.
- `failure memory` issue template.
- `uncertainty boundary` checklist.
- `shared state vs isolated agent` before/after table.
