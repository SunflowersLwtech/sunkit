# brief-pdf

Build polished A4 brief PDFs — company/product briefs, program applications,
proposals, one-pagers — from a plain HTML source, using headless Chrome.

The interesting part is not the markup, it is the proof: each `.page` is a fixed
297 mm flex column with `overflow: hidden`, so a hand-run Chrome silently clips
the footer while the PDF still looks fine. The build script **measures every
page and refuses to write on overflow**, checks the page count against the
number of `.page` divs, and renders through never-fetched scratch URLs so
Chrome's `file://` cache can never print yesterday's draft.

## Install

```
/plugin marketplace add SunflowersLwtech/sunkit
/plugin install brief-pdf@sunkit
```

## Needs

- A Chrome/Chromium binary. `CHROME_BIN` wins; otherwise the script probes the
  platform browser and the Playwright cache (`npx playwright install chromium`).
- `poppler-utils` (`pdfinfo`, `pdftoppm`) for the page-count check and previews.
- `python3`, `jq`-free — just bash + python3 stdlib.

## Use

Rebrand once in `assets/template.src.html` (`:root` color tokens, brand name,
logo, footer/contact lines), then:

```bash
bash scripts/build.sh My_Topic_Brief.src.html
```

See `skills/brief-pdf/SKILL.md` for the workflow and `references/blocks.md`
for what fits on one page.
