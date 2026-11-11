# Block vocabulary (from the template's `<head>` CSS) and what fits on one page

All measurements are from the template and the build script's probe. Page = A4,
210×297 mm, white header, `--page-ground` (default `#edf2f8`) body.
The layout math assumes the type sizes shipped in the template; rebrand via the
`:root` tokens, not by retyping sizes.

## Page frame — every page has all three

```html
<div class="page">
  <div class="hd"><div class="brand"><span class="ring"></span><b>Acme</b><span>/ Company</span></div>
                  <div class="sect">Section Name&nbsp;&nbsp;&nbsp;/02</div></div>
  <div class="bd"> …blocks… </div>
  <div class="ft"><span><b>Acme</b> — Topic brief</span><span>Month YYYY</span><span><b>02 / 04</b></span></div>
</div>
```

Cover page uses `<div class="ft coverft">` (gradient footer) with the entity line
and "Prepared for X". `.bd` always opens with `.eyebrow` (uppercase label + `/0N`),
then `h1`, then `p.lede`.

## Blocks

| Class | Use | Capacity on one page (with eyebrow + h1 + lede) |
|---|---|---|
| `.rows > .row` (`.k` + `small`, `.v`, `.idx`) | ruled fact rows — cover facts, timeline | 4 rows + one block below, or 5 rows alone |
| `.rows.compact` | product list | 8 rows + one `.band` |
| `.duo > .panel.light / .panel.dark` | contrast pair (where we are / what changes) | 3 `li` each, after 3 rows; 4 `li` each only with 2 rows |
| `.stats > .st` (`.t`, `.d`) | 3-column strip of short facts | 1 strip + 4–5 rows + `.note` + `.band` is the limit |
| `.band` / `.band.plain` | one-sentence closing statement, arrow at right | one per page |
| `.note` | orange-edged caveat / evidence note | one per page |

## Page archetypes

- **Cover**: 4 `.row` (entity, method, footprint, funding) + `ft.coverft`.
- **Portfolio**: 8 `.rows.compact` + `.band`.
- **Contrast**: 3 `.row` + `.duo` + `.band.plain`.
- **Projection / timeline**: `.stats` ×3 + 4 `.row` + `.note` + `.band` (this is the
  fullest page that still fits; a 5th row or a 3-line `h1` overflows by ~75 px).

Overflow shows up in `bash scripts/build.sh` as `page4:+77px`; trim words until it is 0.
