---
name: verbatim-fetch
description: "Detail doc assigned by the `search` router — which retrieval rung returns a page's actual words (WebFetch summarizes), what each rung drops, x.com handling."
disable-model-invocation: true
user-invocable: false
---

# verbatim-fetch

## The rule that costs most

**`WebFetch` never returns original text.** It pipes the page through a small
model and returns that model's answer to your prompt. Writing "verbatim" or
"do not summarize" in the prompt does not change this — the summarization has
already happened by the time your prompt is applied.

So: **never quote `WebFetch` output as the source's words**, and never treat its
structure as the source's structure. Measured on a real article: a fetched
six-part argument came back as a flat six-item list and dropped the three-axis
test the whole piece was built on. Nothing errored. The output read like a
competent summary, because it was one — of something whose shape was the point.

That is the failure mode: not "I couldn't get it", but **"I got a summary and
used it as the original."**

## The ladder

Climb only as far as the task needs.

| # | Route | Returns | Cost |
|---|---|---|---|
| 1 | `WebFetch <url>` | LLM summary. Facts survive, wording and structure do not | fast, cheap |
| 2 | `anysearch extract <url>` | Verbatim prose | seconds, ~free |
| 2b | `mcp__exa__web_fetch_exa` (`maxCharacters` ≫ page size) | Verbatim prose **with code fences kept**; drops link URLs and `<angle-bracket>` placeholders | seconds; default cap 3000 chars truncates silently |
| 3 | A web-capable CLI coding agent run as a fetch tool (any one you have installed) | Prose + code blocks + image positions | ~1–2 min, see cost below |
| 4 | A real browser session (your browser-automation skill) | Anything, incl. logged-in pages | slow, needs a browser |

**Default to rung 2 the moment you might quote or restate an argument.** It is
nearly as cheap as rung 1 and it is actually the text.

Rung 2b, measured against the raw `.md` of a docs site, kept sentences identical
and fences intact, but returned a path like `~/.claude/skills/<skill-name>/SKILL.md`
as `~/.claude/skills/ /SKILL.md` and a relative markdown link as bare text.
Prefer 2b when the page's code matters (rung 2 loses fencing, see ① below);
prefer 2 or a raw `.md`/source URL when paths, placeholders or links are what
you quote.

### x.com / twitter.com specifically

`WebFetch` on a bare `x.com` status URL returns **HTTP 402 Payment Required** —
loud, so you will not mistake it for content. Two ways through: `anysearch
extract` on the original URL works (rung 2), and
`WebFetch https://api.fxtwitter.com/<user>/status/<id>` also reaches it — but
fxtwitter is still rung 1, so it is still a summary. Do not let "I had to work
around a paywall" make the result feel more authentic than it is.

A CLI coding agent whose vendor operates X can also fetch X content directly
(rung 3). That is a data-access difference, not a smarter model — do not
generalize "that CLI fetched it" into "that CLI fetches better".

## Rung 2's two silent failures

Measured across several pages. Both failures are silent: no error, no warning,
no truncation marker.

**① Code never keeps its fencing, and sometimes vanishes.** Rung 2 emitted
**zero** ``` fences on every page tested. Two different outcomes:

- A documentation page — code text survived but **flattened to one inline-code
  line**, every newline gone: `` `<form toolname="..."> <label ...> <input ...>` ``.
  Usable if you only need the attribute names; useless if you need the layout.
- An article — the two code samples were **absent entirely**, leaving prose
  pointing at nothing ("Two attributes. The browser reads the form…").

So: for indentation-significant code (Python, YAML) or anything you will paste,
rung 2 is not sufficient even when the code appears to be there.

**② The extractor can follow locale and hand you a translation.** One page came
back **in the wrong language** — auto-localized. A "verbatim" quote taken from
that is not the author's words in any language. If the source should be English
and the output is not, you are holding a translation; refetch with an explicit
locale-pinned URL or go to rung 3.

The detection check, which covers both and survives tool improvements:

> After a rung-2 fetch: (a) scan for prose pointing at artifacts you cannot see
> — "as shown below", "this example", "the diagram", "two attributes";
> (b) confirm the output language is the source's language; (c) if you intend to
> paste code, confirm it has line structure, not one flattened line.
> **Any of the three failing → escalate to rung 3.**

## Rung 3 as a fetch tool

Any web-capable CLI coding agent can serve as rung 3. A worked prompt shape that
produced a complete article — state the prohibition and give images somewhere to
go, or it narrates them away:

> Output the FULL article body VERBATIM as markdown. Do not summarize or
> paraphrase. Preserve headings, lists and code blocks. Mark images you cannot
> read as [IMAGE: <position>]. Output nothing but the article markdown.

**It has no cheap call.** These CLIs carry a large system prompt in every
invocation — in the tens of thousands of tokens when measured, several seconds
and a nonzero model cost per call. Never use one for a fetch rung 2 handles. And
when scripting a CLI agent, pass its explicit approval/permission flag rather
than depending on whatever a local config file happens to say.

## Before you call code "verbatim", diff it

The one place the ladder does **not** save you: on a paste-this-form task, an
answer that reached rung 3 still flattened the source's 4-space indentation to
1 space and inserted blank lines the source lacks — and still called it
「逐字照抄」. Reaching a better rung does not make your output verbatim; only
comparing does.

> Before writing "verbatim" / "逐字" / "原样" about any code you reproduce, pick
> one indented line in the source and check its exact leading-space count against
> yours. If you did not compare, write "reformatted" instead. The claim is what
> the user relies on; getting it from a better source does not license it.

## What to tell the user

When you relay fetched content, the rung is part of the claim:

- Rung 2 or 3, checked → quote freely.
- **Rung 1 → say it is a summary.** Do not put its wording in quotation marks
  and do not attribute its structure to the author.
- If you quoted something earlier from rung 1 and later fetch the real text,
  **say which way the correction went** — whether the quote held up or not. A
  quote that turns out accurate is worth one clause; one that did not is worth
  a correction.

## Boundary with neighbouring skills

- **`anysearch`** owns search and the `extract` command itself. This skill does
  not duplicate its CLI reference — it only says when verbatim matters enough to
  reach for `extract` instead of `WebFetch`, and how to detect a lossy extract.
- A **real browser session** (via your browser-automation skill, if any) owns
  anything needing a login: paywalls that survive rung 3, clicking. It is rung 4
  here. If rungs 1–3 all fail on a page, that is the signal to go there, not to
  retry rung 3 harder.
