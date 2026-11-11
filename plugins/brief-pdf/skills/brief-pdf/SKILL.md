---
name: brief-pdf
description: Build a polished A4 brief PDF — company/product brief, program application, proposal, one-pager — from an HTML source via headless Chrome. Fires on 「做个 PDF」「公司介绍/方案做成 PDF」「申请材料排版」, "prepare a brief / one-pager / proposal", "print this HTML to PDF", or any polished PDF someone outside the team will read. Measures every page for overflow and never re-renders a cached file:// URL, so the PDF always contains what was measured. Not for reading PDFs, printing markdown notes, or slide decks.
---

# brief-pdf — A4 brief from HTML, proven not to clip

A house style for one-page-per-topic briefs: white header, ruled fact rows,
one idea per page, everything a reviewer can check. The template and the build
script enforce the two things hand-built PDFs get wrong — a footer silently
clipped by page overflow, and a stale cached render.

## What's here

| Thing | Path |
|---|---|
| Skeleton with every block type | `assets/template.src.html` |
| Build + proof | `bash scripts/build.sh <X.src.html> [out.pdf]` |
| Block vocabulary and per-page capacity | `references/blocks.md` — read when composing a page you have not built before |

## Configuration (do this once per brand)

Everything brand-specific is a token in the template's `<head>`:

- **Palette** — the `:root` block (`--brand-*`, `--page-ground`, `--note-accent`, …).
  Change these; do not restyle individual rules, the layout math below assumes the
  current type sizes and spacing.
- **Brand name + logo** — the `<b>` wordmark wherever the header/footer/cover print
  it. The `.ring` logo is pure CSS; swap `<span class="ring"></span>` for a small
  `<img>` if you have a mark (keep it ~3.4 mm so the header height does not move).
- **Footer entity line and contact line** — placeholders in the template footer
  (`Reg. No. …`) and the cover/contact band; put your real registration text and
  contact details there once.

## Workflow

1. **Source of truth is `<Name>.src.html`, never the PDF.** New brief: copy
   `assets/template.src.html` (or, for a second brief in the same style, the
   `<head>` of the nearest existing brief verbatim — the head *is* the style;
   do not restyle). Name it `<Topic>_Brief.src.html` next to where the PDF will live.
2. **Every fact traceable.** Entity/registration/domains from your own records,
   stack facts from the repo or docs, dates from `git log`. Mark each claim
   *running* or *planned* — the "stated honestly" framing survives review, and a
   reviewer can check the running ones. Prices/quotas carry a month. Before
   printing a contact name or email, check whose it actually is.
3. **Build with the script, not with Chrome by hand.** Two failures make a hand-run
   Chrome print a wrong PDF that looks right. Each `.page` is a fixed 297 mm flex column
   with `overflow:hidden`, so too much content pushes the footer off the page while the
   PDF still renders with the right page count and reads fine at a glance; the script
   measures every page and refuses to write on overflow (fix by trimming words or
   dropping a row, never by shrinking type). And Chrome caches `file://` URLs, so
   re-rendering the same path after an edit can print the *previous* draft — exit 0, a
   fresh file, last draft's words. The script renders every pass through a URL that has
   never been fetched, so the page it measured and the page it printed are the same bytes.
4. **Look at every preview PNG the script prints.** What the probe cannot see: an `h1`
   wrapping to three lines, a long ID or URL breaking mid-token, a row with one orphan
   word. Then read the PDF back with `pdftotext -layout` once — the last line of each
   page should be its footer.
5. **Decide delivery before writing "see attached".** Application forms often have no
   upload field — know where the PDF will actually go before you reference it. Hosting
   the PDF on a public site is a deploy and outward-facing — the owner decides. If it
   goes out by email, use your own mail tooling and **write the letter** — a brief
   arriving with no covering text is half a delivery, and mail automation has reported
   `sent` on exactly that. Verify by reading the sent copy back (body length,
   attachment name + byte count), never by trusting the `sent` line.

## Stop conditions

- No invented numbers, customers or dates; if a figure cannot be traced, write the
  mechanism ("sized from current repo count") or leave it out.
- Do not push/host/publish the PDF, and do not submit the form it accompanies, without
  the owner saying so in this conversation.
