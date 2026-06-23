# Typeset Studio — Roadmap & Build Reference

Reference doc for working on this codebase (e.g. with Claude Code). It captures the
current architecture, the data model, the non-obvious gotchas, and a prioritized
feature backlog with concrete touch points. Read the "Architecture" and "Gotchas"
sections before changing the engine.

---

## What this app is

A local, single-user Flask web app that turns a manuscript + a reusable **style**
(preset) into a print-ready interior PDF with embedded fonts. Runs on the author's
own machine; not a public service. Styles are JSON files meant to be cloned and
tweaked per customer.

---

## Architecture snapshot

```
app.py            Flask routes + preset CRUD + form parsing. Entry point (port 5050).
engine.py         The typesetting engine (ReportLab). Builds the PDF.
manuscript.py     Parses Markdown / imports .docx -> a chapters/blocks structure.
templates/        Jinja2 UI: base, index (styles), editor (preset form), generate, result.
presets/*.json    One file per style. Cloneable per customer.
fonts/*.ttf       Embeddable static TrueType faces (family "Book").
sample/sample.md  Demo manuscript.
out/              Composed PDFs land here (also served for download).
uploads/          User-uploaded manuscripts / cover art (created at runtime).
```

Data flow for a compose:
`generate.html` (POST) → `app.generate()` builds a **meta** dict + loads the chosen
**preset** + parses the manuscript via `manuscript.parse_markdown()` →
`engine.build_pdf(manuscript, preset, out_path, meta)` → PDF in `out/` → `result.html`.

---

## Data model

### Preset (presets/*.json) — the per-book typographic recipe
```
name, description
trim:        {w, h}                      inches
margins:     {top, bottom, inside, outside}   inches (inside = gutter/spine side)
font_family: str                          registered family name
font_files:  {regular, bold, italic}      .ttf filename (looked up in fonts/) OR abs path
body:        {size, leading, indent, justify, hyphenate}   pts/pts/inches/bool/bool
chapter:     {start, sink, show_number, number_format, number_size, title_size,
              after_title, open_style, leadin_words, dropcap_lines}
             start: "recto" | "any"
             open_style: "none" | "raised_initial" | "smallcaps_leadin" | "dropcap"
             number_format uses "{n}", e.g. "Chapter {n}"
scene_break: {glyph, size, gap}           glyph is plain text; keep it font-safe
running_head:{show, caps, size, gap}      gap in inches
folio:       {show, position, size, gap, hide_on_opener}   position: "outer" | "center"
```
`app.DEFAULTS` is the canonical default preset and `app.parse_preset_form()` maps the
editor form fields to this schema. **If you add a preset field, update all three:**
`DEFAULTS`, `parse_preset_form()`, and `templates/editor.html`.

### meta dict (per-book, assembled in app.generate())
```
title, subtitle, author, year, publisher
copyright            optional override string; else engine._default_copyright(meta)
front_matter         "full" | "title" | "copyright" | "none"
right_hand_starts    bool — insert blank pages so sections open on a recto
cover_image          path to uploaded art ('' if none)
cover_overlay        bool — print title/author over the art
cover_color          "light" | "dark"   (overlay text colour)
```

### Parsed manuscript (manuscript.parse_markdown)
```
{ "chapters": [ { "title": str|None, "blocks": [ block, ... ] }, ... ] }
block = ("para", html_text) | ("subhead", html_text) | ("scene", None)
```
Inline emphasis is converted to ReportLab markup (`<b>`, `<i>`). Markup conventions:
`# ` chapter, `## ` subhead, `* * *` / `***` / `---` scene break, blank line = para.
`.docx` import (`manuscript.import_docx`) maps Heading 1 → chapter.

---

## Gotchas (read before touching the engine)

- **Folio numbering is body-start tracked, not a fixed front-matter count.** The first
  chapter opener page defines folio 1 (`BookDoc._furniture` sets `self._body_start` on
  the first page where `canv._is_opener`). Anything before it gets no running head/folio.
  Do **not** reintroduce a hardcoded `fm_pages` count — variable front matter + cover
  would break it.
- **Furniture is drawn at page END** (`onPageEnd=self._furniture`) so opener/blank status
  is known without a pre-pass. Opener/blank state is flagged by zero-size marker flowables
  `OpenerMarker` / `BlankMarker` whose `draw()` sets `canv._is_opener` / `canv._is_blank`.
- **Recto forcing** is handled in `BookDoc.handle_flowable` via the `RectoBreak` flowable,
  branching on `self.frame._atTop` × current-page parity (`self.page`, which ReportLab has
  already incremented for the composing page — do not use `self.page+1`). It inserts a
  counted blank verso when needed.
- **Mirrored margins / parity:** recto pages use the `recto` frame (left = inside margin),
  verso pages the `verso` frame. Body pages alternate correctly; front-matter pages render
  in the recto frame (fine, they're centered). Verify parity after engine changes by
  measuring text `x0` on odd vs even pages (recto≈inside, verso≈outside).
- **Cover** is a full-bleed page-1 template (`id='cover'`, `onPage=_draw_cover`). When a
  cover exists it is inserted at template index 0 so page 1 paints the art; the story then
  switches to a normal template. Art is pre-cropped to trim @300dpi with Pillow
  (`_prepare_cover`) and the temp file is deleted after build.
- **Scene-break glyphs must exist in the body font.** Libre Baskerville ("Book") lacks many
  ornaments (e.g. U+2766 renders as tofu). Presets ship with font-safe marks (`* * *`,
  em-dashes, middots). A custom-ornament feature should validate or fall back.
- **Fonts:** `register_fonts` resolves bare filenames against `fonts/`, accepts absolute
  paths, and falls back to Times if a file is missing — so a build never hard-fails, but
  type may silently change. Surface this in any preflight feature.
- **Paragraph-after-scene/subhead** is set flush (no indent) via the `flush_next` flag in
  `_build_story`; the chapter's first paragraph gets the `open_style` once via `opened`.

---

## Feature backlog (prioritized)

Effort key: **S** ≈ hours, **M** ≈ half-day–day, **L** ≈ multi-day.

### Tier 1 — do first (client-readiness + biggest time savers)

**1. Projects: save & re-generate a book — M**
Currently every compose is one-shot. Persist a "book" = manuscript ref + preset id +
meta so it can be regenerated after edits without re-entering everything.
- Touch: new `projects/*.json` store; `app.py` routes (`/projects`, `/project/<id>`,
  save-from-generate); store uploaded manuscript alongside; new `projects.html` + link
  from generate/result ("Save as project").
- Acceptance: edit manuscript file, hit regenerate, get an updated PDF with same settings.

**2. Spine & margin calculator — S**
After a build the page count is known. Report KDP/IngramSpark minimum inside margin for
that page count and the cover spine width (page count × paper-thickness factor; expose a
paper-type selector: white/cream/color). Pure information, high trust value.
- Touch: compute in `app.generate()` post-build (read final page count from the PDF or
  return it from `engine.build_pdf`); show on `result.html`. Add paper-type constants.
- Acceptance: 300-page 6×9 shows correct min gutter + spine inches for chosen paper.

**3. Preflight report — S/M**
Post-build checklist surfaced on result page: fonts embedded ✓, requested fonts actually
used (not silently Times-fallback) ✓, trim matches preset ✓, inside margin adequate for
page count ✓, flag any missing-glyph / overset characters. A confidence artifact to hand
clients.
- Touch: `engine.build_pdf` returns a report dict (font fallback already detectable in
  `register_fonts`; check embedded fonts via pdf inspection); render on `result.html`.
- Acceptance: a preset pointing at a missing font shows a clear "fell back to Times" warning.

**4. Letter / document / field-log block style — M** *(the differentiator)*
A dedicated block format for epistolary content (letters, journal entries, field logs):
distinct indent/measure, optional alternate face or monospaced treatment, optional ruled
or boxed framing. This is the "complex literary interior" niche the whole positioning
rests on (cf. "Correspondence").
- Touch: extend the manuscript convention with a block marker (e.g. fenced
  `~~~letter … ~~~` or a `> ` document block); add block kind in `manuscript.py`; add a
  `document_block` style group to the preset + editor + `_build_story` rendering.
- Acceptance: a letter block renders visually distinct from body prose and survives page
  breaks.

### Tier 2 — craft & polish

**5. Typographic cleanup (smart punctuation) — S**
Straight→curly quotes, `--`→em dash, `...`→ellipsis, collapse double spaces. On by default,
toggle per book. Apply in `manuscript._inline` (careful: do it before/around the existing
escape + emphasis regexes; don't curl quotes inside markup).
- Acceptance: `"He said--wait..."` renders with curly quotes, em dash, ellipsis.

**6. Real hyphenation for justified text — M**
Reduce rivers/loose lines in justified literary setting. Integrate a hyphenation dict
(e.g. `pyphen`) and feed soft hyphens into paragraphs when `body.hyphenate` is on.
- Touch: `engine._styles`/paragraph construction; new dep; respect the existing
  `hyphenate` preset flag (currently parsed but unused).
- Acceptance: justified text with hyphenation shows tighter spacing vs off.

**7. Parts / section dividers — M**
"Part One" divider pages above chapters. Add a manuscript marker (e.g. `# #` or a
`=== Part: Title` line) and a `part` style group (divider page, sink, recto-forced).
- Touch: `manuscript.py` (new top-level structure or a `part` block), `_build_story`.
- Acceptance: a part divider gets its own recto page and doesn't carry a chapter folio.

**8. Front/back matter blocks — M**
Dedication, epigraph, also-by, about-the-author, acknowledgments. Either dedicated meta
fields or recognized manuscript sections, rendered with appropriate (often centered,
unnumbered) styling.
- Touch: meta + `generate.html` (or manuscript markers); `_build_story` front/back sections.

**9. Custom scene-break ornament (image) — S**
Allow a small image as the scene break instead of a text glyph, with size control. Keep
the text-glyph path as default and font-safe.
- Touch: `scene_break` preset (`type: glyph|image`, `image` path); `SceneBreak` flowable
  to draw an image; editor field.

### Tier 3 — usability

**10. Live page preview — M**
Render a few representative pages (chapter opener, a facing-page spread, a scene break) to
PNG thumbnails shown in the browser when editing a style — no full PDF download per tweak.
- Touch: build a tiny sample doc with the in-progress preset; rasterize with
  `pdftoppm`/PyMuPDF; new endpoint returning images; editor.html preview panel.
- Note: needs a PDF→image rasterizer available at runtime (document the dependency).

**11. Auto table of contents — S/M**
Generate a TOC page from chapter titles (+ part titles). Page numbers require knowing
final folios — either a two-pass build or capture opener page numbers during build and
emit the TOC in front matter on a second pass.
- Touch: `engine` (capture chapter→folio map), front-matter assembly.

### Tier 4 — bigger bets

**12. EPUB export — L**
Many clients want ebook + print. Separate output path: generate semantic HTML/EPUB from
the already-parsed manuscript structure (reuse `manuscript.parse_markdown` output; ignore
print-only preset fields; map styles to CSS). Roughly doubles sellable output per book.
- Touch: new `epub.py` builder consuming the chapters/blocks structure; output `.epub`;
  generate-page format toggle (PDF / EPUB / both).
- Acceptance: produces a valid EPUB (passes epubcheck) with chapters, scene breaks,
  italics/bold, and front matter.

---

## Conventions for contributions

- Keep the engine **single-pass** unless a feature genuinely needs two (TOC, cross-refs);
  if so, isolate the measuring pass.
- New preset fields: update `DEFAULTS`, `parse_preset_form`, `editor.html` together, and
  keep defaults backward-compatible with existing `presets/*.json` (use `.get(...)`).
- New per-book options go on the **generate** page + `meta`, not the preset, when they vary
  per book (cover, front matter, TOC) rather than per style.
- Preserve offline operation: no CDN assets in templates; system-font stacks only.
- After any imposition change, re-verify: folio starts at 1 on the first story page; blanks
  appear only where intended; recto/verso text margins alternate correctly.
