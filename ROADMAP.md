# Typeset Studio — Roadmap & Build Reference

Reference doc for working on this codebase (e.g. with Claude Code). It captures the
current architecture, the data model, the non-obvious gotchas, and a prioritized
feature backlog with concrete touch points. Read the "Architecture" and "Gotchas"
sections before changing the engine.

---

## What this app is

A local, single-user Flask web app that turns a manuscript + a reusable **style**
(preset) into a print-ready interior PDF with embedded fonts, and optionally an EPUB.
Runs on the author's own machine; not a public service. Styles are JSON files meant
to be cloned and tweaked per customer. Books (manuscript + meta + preset) can be saved
as **projects** for one-click regeneration.

---

## Architecture snapshot

```
app.py            Flask routes + preset/project CRUD + form parsing. Entry point (port 5050).
engine.py         The typesetting engine (ReportLab). Builds the PDF. Two-pass when TOC enabled.
manuscript.py     Parses Markdown / imports .docx → a chapters/blocks structure.
epub.py           EPUB 3 builder — consumes the same parsed structure as engine.py.
checker.py        Continuity checker: tier-1 rule checks + tier-2 Claude Haiku analysis.
templates/        Jinja2 UI: base, index (styles), editor (preset form + live preview),
                  generate, result, projects, project_edit, continuity_result.
presets/*.json    One file per style. Cloneable per customer. Seven presets ship by default.
covers/*.json     One file per designed cover template (text-driven page-1 layout). Cloneable per line.
                  Edited in the browser via the Cover Studio (no hand-editing needed).
fonts/*.ttf       Embeddable TrueType faces (family "Book"). Also stores scene-break ornament images.
sample/sample.md  Demo manuscript (3 chapters; Chapter 3 exercises all 5 epistolary block types).
out/              Composed PDFs / EPUBs land here (also served for download).
uploads/          User-uploaded manuscripts / cover art (created at runtime).
projects/         One .json per saved project.
projects/manuscripts/   Stored manuscript + cover copies (one per project).
```

Data flow for a compose:
`generate.html` (POST) → `app.generate()` builds a **meta** dict + loads the chosen
**preset** + parses the manuscript via `manuscript.parse_markdown()` →
`engine.build_pdf(manuscript, preset, out_path, meta)` (two-pass if TOC enabled) →
PDF in `out/` → `result.html`. If format includes EPUB, `epub.build_epub()` runs too.

---

## Data model

### Preset (presets/*.json) — the per-book typographic recipe
```
name, description
trim:          {w, h}                       inches
margins:       {top, bottom, inside, outside}   inches (inside = gutter/spine side)
font_family:   str                           registered family name
font_files:    {regular, bold, italic}       .ttf filename (looked up in fonts/) OR abs path
body:          {size, leading, indent, justify, hyphenate}   pts/pts/inches/bool/bool
chapter:       {start, sink, show_number, number_format, number_size, title_size,
               after_title, open_style, leadin_words, dropcap_lines}
               start: "recto" | "any"
               open_style: "none" | "raised_initial" | "smallcaps_leadin" | "dropcap"
               number_format uses "{n}", e.g. "Chapter {n}"
part_divider:  {show_number, number_format, number_size, title_size, sink}
               sink is a 0–1 fraction of the text-area height
scene_break:   {type, glyph, size, gap, image}
               type: "glyph" | "image"; image is a filename in fonts/ or absolute path
document_block:{frame, indent, font_size, first_indent, space_around,
               header_size, dateline_style}
               frame: "none" | "ruled" | "box"
               dateline_style: "italic" | "bold" | "smallcaps"
running_head:  {show, caps, size, gap}       gap in inches
folio:         {show, position, size, gap, hide_on_opener}   position: "outer" | "center"
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
cover_mode           "none" | "image" | "designed"   (page-1 cover style)
cover_image          path to uploaded art ('' if none; image mode)
cover_overlay        bool — print title/author over the art (image mode)
cover_color          "light" | "dark"   (overlay text colour; image mode)
cover_template       id of a covers/*.json template (designed mode)
cover_template_data  the loaded template dict (designed mode; app.py injects it)
cover_collection     top+bottom letterspaced line, e.g. "Edenfall Collection" (designed)
cover_kicker         italic line under the collection, e.g. "player options" (designed)
cover_accent         teal line under the title; falls back to `author`; override e.g. "& Feats" (designed)
cover_epigraph       italic cover passage; falls back to `epigraph` (designed)
cover_studio         footer line; falls back to `publisher` (designed)
include_toc          bool — generate a Contents page (triggers two-pass build)
smartquotes          bool — apply curly quotes / em dashes / ellipsis (default True)
format               "pdf" | "epub" | "both"
dedication           plain text ('' = no page)
epigraph             plain text; last line starting with — is styled as attribution
acknowledgments      plain text ('' = no page)
about_author         plain text ('' = no page)
also_by              plain text, one title per line ('' = no page)
```

### Parsed manuscript (manuscript.parse_markdown)
```
{
  "chapters": [
    {
      "title":  str | None,
      "part":   {"title": str | None, "number": int} | None,
      "blocks": [ block, ... ]
    },
    ...
  ]
}
block = ("para", html_text)
      | ("subhead", html_text)
      | ("scene", None)
      | ("doc_block", [("para", html_text), ...])
      | ("doc_block", [("para", html_text), ...], {"_type": str, attr: str, ...})
```

Inline emphasis is converted to ReportLab markup (`<b>`, `<i>`), with optional smart
punctuation applied first. Markup conventions:

| You write          | You get                        |
|--------------------|--------------------------------|
| `=== Part title`   | a part divider page            |
| `# Chapter title`  | starts a new chapter           |
| `## Subhead`       | a centered section subhead     |
| `* * *` (own line) | a scene break                  |
| `~~~` … `~~~`      | plain document block (indented / ruled / boxed per preset) |
| `~~~ letter from="X" to="Y" date="Z"` | typed epistolary block (see below) |
| `*italic*`         | *italic*                       |
| `**bold**`         | **bold**                       |
| blank line         | new paragraph                  |

Typed epistolary block types (opening fence declares type + attributes):
```
~~~ letter    from="…" to="…" date="…"
~~~ journal   date="…" author="…"
~~~ telegram  to="…"
~~~ newspaper headline="…" date="…" source="…"
~~~ redacted  classification="…"
```
Each type has a distinct visual signature in PDF (header between rules, italic body,
Courier uppercase, bold headline, classification banner) and semantic CSS classes in
EPUB (`doc-block-letter`, etc.). Plain `~~~` with no type is unchanged.

`.docx` import (`manuscript.import_docx`) maps Heading 1 → chapter, runs → bold/italic.

### Project (projects/*.json) — a saved book
```
name, preset (preset id), title, subtitle, author, year, publisher
front_matter, right_hand_starts, include_toc, smartquotes, format
dedication, epigraph, acknowledgments, about_author, also_by
cover_overlay, cover_color
manuscript_file     filename inside projects/manuscripts/
manuscript_type     "file" | "pasted" | "sample"
cover_file          filename inside projects/manuscripts/ ('' if none)
last_pdf, last_epub
created, updated    ISO 8601 datetime strings
```

---

## Gotchas (read before touching the engine)

- **Folio numbering is body-start tracked, not a fixed front-matter count.** The first
  chapter opener page defines folio 1 (`BookDoc._furniture` sets `self._body_start` on
  the first page where `canv._is_opener`). Anything before it gets no running head/folio.
  Do **not** reintroduce a hardcoded `fm_pages` count — variable front matter + cover
  would break it.

- **Furniture is drawn at page END** (`onPageEnd=self._furniture`) so opener/blank status
  is known without a pre-pass. Opener/blank state is flagged by zero-size marker flowables:
  `TocMarker` sets `_is_opener` AND records the chapter page for TOC generation;
  `BlankMarker.draw()` sets `canv._is_blank` (part dividers, blank versos, TOC pages).
  `OpenerMarker` is kept for part dividers that don't need TOC recording.

- **Recto forcing** is handled in `BookDoc.handle_flowable` via the `RectoBreak` flowable,
  branching on `self.frame._atTop` × current-page parity (`self.page`, which ReportLab has
  already incremented for the composing page — do not use `self.page+1`). It inserts a
  counted blank verso when needed.

- **Mirrored margins / parity:** recto pages use the `recto` frame (left = inside margin),
  verso pages the `verso` frame. Body pages alternate correctly; front-matter pages render
  in the recto frame (fine, they're centered). Verify parity after engine changes by
  measuring text `x0` on odd vs even pages (recto≈inside, verso≈outside).

- **Cover** is a full-bleed page-1 template (`id='cover'`, `onPage=_draw_cover`). When a
  cover exists it is inserted at template index 0 so page 1 paints it; the story then
  switches to a normal template. Two modes, chosen by `meta['cover_mode']`:
  - **image** — uploaded art, pre-cropped to trim @300dpi with Pillow (`_prepare_cover`);
    the temp file is deleted after build. Optional title/author overlay.
  - **designed** — `_draw_designed_cover` renders a text-driven layout from a `covers/*.json`
    template (palette, double-rule border + corner brackets, letterspaced lines, wrapped
    display title with **shrink-to-fit**, teal accent, vector-diamond ornament, italic
    epigraph, studio footer). Cover fonts register separately via `_register_cover_fonts`
    (prefix `Cover-`) so they can differ from the interior family; missing faces fall back
    to the interior fonts, then Times. Text is drawn with `_tracked_centre` (letterspacing
    via a text object's `setCharSpace` — the canvas has no `setCharSpace` in this ReportLab).
  Designed covers are **PDF-only** (EPUB stays image-only) and are **not yet persisted in
  saved projects** (the one-off generate flow carries them; the project build path falls
  back safely to no/image cover).

- **Scene-break glyphs must exist in the body font.** Libre Baskerville ("Book") lacks many
  ornaments. Presets ship with font-safe marks (`* * *`, em-dashes, middots). Use the image
  ornament type for custom artwork instead of exotic Unicode.

- **Fonts:** `register_fonts` resolves bare filenames against `fonts/`, accepts absolute
  paths, and falls back to Times if a file is missing — so a build never hard-fails, but
  type may silently change. The preflight report surfaces this.

- **Paragraph-after-scene/subhead** is set flush (no indent) via the `flush_next` flag in
  `_build_story`; the chapter's first paragraph gets the `open_style` once via `opened`.

- **Opening-paragraph markup slicing:** `_inline()` converts Word bold/italic runs to
  ReportLab XML (`<b>`, `<i>`). The `_opening_para()` function strips this via `_plain()`
  before any character/word-level operations (drop cap, raised initial, small-caps lead-in)
  — these styles are incompatible with inline markup on the first paragraph anyway. Never
  pass raw `text` with embedded tags to code that slices by index or splits on spaces.

- **TOC two-pass build:** when `meta['include_toc']` is True, `build_pdf` runs the story
  through a first (temp-file) build to capture `doc._toc_entries` and `doc._body_start`,
  estimates the TOC page count, adjusts folios by that count, then does a second build with
  the TOC injected via `_build_story(..., toc_flowables=...)`. The TOC is inserted after
  the copyright page and before dedications/epigraph.

- **Front/back matter blank pages:** only the *first* item in each group (front extras:
  dedication + epigraph; back matter: acknowledgments + about + also-by) is recto-forced
  via `RectoBreak`. Subsequent items in the same group use plain `PageBreak` to avoid
  inserting unnecessary blank versos between consecutive special pages.

- **`_matter_page` and `_build_toc` import `_ms_inline` from `manuscript.py`** (no
  circular dependency — manuscript.py does not import engine.py). Keep it that way.

- **`doc_block` rendering:** the `box` frame style wraps all paragraphs in a single-column
  `Table` so ReportLab can split it across pages with proper borders. The `ruled` and `none`
  styles use plain `Paragraph` flowables. Never use `KeepTogether` for long blocks.

- **`doc_block` is a 2- or 3-tuple:** `('doc_block', paras)` for plain blocks;
  `('doc_block', paras, meta_dict)` for typed blocks where `meta_dict['_type']` is the
  block type. All dispatch code must index by position (`block[0]`, `block[1]`,
  `block[2] if len(block) > 2 else {}`) — never unpack with `kind, val = block` as that
  crashes on 3-tuples. `checker.py` uses `block[1]` only and is safe.

- **Telegram font:** uses ReportLab's built-in `'Courier'` — always available, no
  registration needed. No other epistolary type introduces a new font dependency.

- **`dateline_style: "smallcaps"`** is faked as uppercase + bold (no true small-caps font
  registered). Text is uppercased in `_ep_dtext()` before being passed to the bold font.

---

## Feature status

### ✓ Tier 1 — shipped

**1. Projects: save & re-generate a book**
`app.py` (`/projects`, `/project/<pid>/*` routes) · `templates/projects.html`,
`templates/project_edit.html` · `projects/` + `projects/manuscripts/` on disk.
After composing, the result page offers "Save as project". Projects remember manuscript,
style, all meta, and output format. Regenerate any time from the Projects page.

**2. Spine & margin calculator**
`app.py` (`print_spec()`, `_KDP_MARGINS`, `_INGRAM_MARGINS`, `_PAPER` constants) ·
`templates/result.html` (Print spec card). Shows spine width for white/cream/color paper
and flags inside-margin adequacy for KDP and IngramSpark after every PDF build.

**3. Preflight report**
`engine.py` (`register_fonts` returns `fallback` + `details`) · `app.py` (`_preflight()`)
· `templates/result.html` (Preflight card). Checks: font loading, fonts embedded, page
count within KDP range. Red ✗ with explanation on failure; green ✓ when clear.

**4. Epistolary / mixed-media document blocks**
`manuscript.py` (`DOCBLOCK_RE`, `_parse_block_header()`; plain `~~~` → 2-tuple;
typed `~~~ letter from="…"` etc. → 3-tuple with `_type` + attrs) · `engine.py`
(`_render_doc_block()` dispatches to five type-specific render functions: letter, journal,
telegram, newspaper, redacted; `_ep_plain()`, `_ep_dfont()`, `_ep_dtext()` helpers) ·
`epub.py` (per-type CSS classes + semantic `<header>` element) ·
`templates/editor.html` (Document blocks fieldset: frame/indent/size/header size/dateline
style + typed syntax hint).

**12. EPUB export** *(moved up from Tier 4)*
`epub.py` (stdlib-only EPUB 3 builder: manifest, spine, nav, CSS, chapter XHTML, cover,
part pages, matter pages, TOC page) · `app.py` (format selector in generate + projects) ·
`templates/generate.html` (Output format fieldset: PDF / EPUB / Both).

**13. Continuity checker**
`checker.py` (`run_tier1()`: duplicate chapter titles, name spelling variants via difflib,
POV pronoun drift, repeated sentences ≥10 words, thin/empty chapters; `run_tier2()`:
Claude Haiku semantic analysis when `ANTHROPIC_API_KEY` is set) ·
`templates/continuity_result.html` (two-card preflight layout, badge-ok / badge-warn) ·
`app.py` (`POST /project/<pid>/continuity` route) ·
`templates/projects.html` (Check button on each project card).

**14. Genre presets (×7)**
`presets/`: Classic Literary 6×9, Gothic/Horror 5.5×8.5, Modern Clean 6×9,
Thriller/Crime 5.5×8.5 (bare numeral headings, em-dash scene break),
Mass Market Paperback 4.25×6.87 (9.5pt, hyphenation on),
Romance/Women's Fiction 5.5×8.5 (raised initial, 16pt leading),
Science Fiction & Fantasy 6×9 (dropcap, deep sink).

**15. Designed cover templates (text-driven)**
`covers/*.json` (new subsystem, parallel to presets — one file per house style;
`ashforge-house.json` ships: dark navy gradient, gold double border + corner brackets,
letterspaced collection lines, gold display title, teal accent, diamond ornament, italic
epigraph, studio footer) · `engine.py` (`_draw_designed_cover`, `_register_cover_fonts`,
and `_hex` / `_tracked_centre` / `_wrap_tracked` / `_diamond` helpers; `build_pdf` branches
on `cover_mode`) · `app.py` (`list_cover_templates()`, `load_cover_template()`, a context
processor exposing templates to all pages, and the `cover_*` meta keys) ·
`templates/generate.html` (Cover fieldset: mode selector None/Designed/Upload + template
dropdown + text fields, with a small toggle script). Fonts are swappable via the template
JSON — the shipped file approximates the house display serif with the "Book" faces. Known
gaps: EPUB and saved projects don't carry designed covers yet.

**16. Cover Studio — browser editor for cover templates**
`app.py` (`COVER_DEFAULTS`, `parse_cover_form()` mirroring `parse_preset_form`,
`save_cover_template`/`unique_cover_id`/`list_fonts` helpers, and routes `/covers`,
`/cover/new`, `/cover/<cid>`, `/cover/save[/<cid>]`, `/cover/clone/<cid>`,
`/cover/delete/<cid>`, `/cover/preview`) · `templates/covers.html` (gallery with palette
swatches, mirrors index.html) · `templates/cover_editor.html` (full form over the cover
schema: identity, sample preview text, font pickers from `fonts/`, palette colour inputs,
border, and per-element type controls; debounced live preview that re-renders on every
edit) · `templates/base.html` (Covers nav link). The preview reuses the #10 rasterizer
pattern: `/cover/preview` builds a one-off designed cover via `engine.build_pdf` over
`DEFAULTS` + `PREVIEW_SAMPLE` and returns page 1 as a base64 PNG. Element colours are chosen
from palette keys (gold/teal/ink/muted); palette values are `<input type=color>` hex.
New templates appear in the Generate dropdown automatically (context processor). No engine
changes were needed — the renderer was already fully parametric.

**17. Font library — browser font upload (Cover Studio Tier 2)**
`app.py` (`BUILTIN_FONTS`, `FONT_EXTS`, `_is_embeddable_font()` validation via ReportLab
`TTFont`, and routes `/fonts`, `/fonts/upload`, `/fonts/delete/<name>`) ·
`templates/fonts.html` (upload form + installed-font list with per-file Remove) ·
`templates/base.html` (Fonts nav link) · `templates/editor.html` (preset font fields are now
dropdowns from the library, preserving any existing custom path via a `fontsel` macro) ·
`templates/cover_editor.html` (link to the Fonts page). Uploaded `.ttf`/`.otf` files are
saved to `fonts/` only if ReportLab can register them (so they will embed); the three
built-in `Book-*` faces are protected from deletion and name-collision. Both editors and the
`register_fonts` / `_register_cover_fonts` paths pick up new faces immediately.

**18. Full print wrap — back + spine + front (Cover Studio Tier 3)**
`engine.py`: the front-cover renderer was refactored into rect-based module painters
(`_paint_gradient`, `_paint_border`, `_paint_cover_panel`, plus `_pal_color`) so the same code
draws the standalone front (page 1) and the wrap's front panel; added `_paint_back_panel`
(collection line, centred serif blurb, studio footer, white ISBN/barcode reserve zone),
`_paint_spine` (title + author rotated −90°, top-to-bottom, auto-sized to spine width; skipped
under ~0.32" / ~140pp), `_paint_wrap_guides` (dashed fold + trim proof lines), and
`build_cover_wrap(tpl, cf, meta, dims, out_path, guides)` — a standalone `reportlab.pdfgen`
canvas at `2·trim_w + spine + 2·bleed` × `trim_h + 2·bleed`. `_draw_designed_cover` now just
calls the shared painters. `app.py`: `_wrap_from_form` (spine from page count × paper `ppi`,
reusing `_PAPER`), routes `/cover/wrap` (returns the wrap PDF as a download) and
`/cover/wrap/preview` (base64 PNG + computed dims). `templates/cover_editor.html`: a Print
wrap fieldset (trim, page count, paper, bleed, proof-guides toggle, back-cover blurb) with
Preview-wrap and Download-wrap-PDF buttons. New meta key `cover_blurb`. The wrap is a separate
deliverable (the interior PDF is unchanged); page count comes from the interior build shown on
the result page.

### ✓ Tier 2 — shipped

**5. Smart punctuation**
`manuscript.py` (`_smarten()` called at the start of `_inline()` when `smartquotes=True`).
Converts `--` → em dash, `...` → ellipsis, straight quotes → curly. Toggle per book on
the compose page. Off for `.docx` files that already have curly quotes from Word.

**6. Real hyphenation**
`engine.py` (`_hyphenate_markup()`, `pyphen.Pyphen(lang='en_US')`). When `body.hyphenate`
is on in the preset, soft hyphens (U+00AD) are inserted into 5+ letter words in all body
paragraphs, chapter openers, and doc blocks. Tags in ReportLab XML markup are skipped.

**7. Parts / section dividers**
`manuscript.py` (`PART_RE`, `=== Part title` parsing → `ch['part']` on each chapter) ·
`engine.py` (`part_num` + `part_title` styles, part divider logic before chapter loop) ·
`epub.py` (`_part_xhtml()`, part pages in spine + nav) · `templates/editor.html`
(Part dividers fieldset: number format, sizes, sink).

**8. Front/back matter pages**
`engine.py` (`_matter_page()` helper; front extras after copyright, back matter after last
chapter) · `epub.py` (`_matter_xhtml()`, matter pages in spine/nav/zip) ·
`templates/generate.html` + `templates/project_edit.html` (Front matter extras + Back matter
fieldsets) · `app.py` (five new meta keys: dedication, epigraph, acknowledgments,
about_author, also_by).

**9. Custom scene-break ornament (image)**
`engine.py` (`SceneBreak` flowable: `image_path` arg, draws proportional image via
`ImageReader`, falls back to text glyph if file missing) · `app.py` (sb_type, sb_image
form fields) · `templates/editor.html` (type selector + image path field).

### ✓ Tier 3 — shipped

**10. Live page preview**
`app.py` (`POST /preview` route: parses current form, builds sample PDF, rasterizes via
PyMuPDF, returns base64 PNG array as JSON) · `templates/editor.html` (Preview pages button
+ image panel in sidebar, fetch JS). Uses `PREVIEW_SAMPLE` constant — no manuscript upload
required. Reflects unsaved form changes instantly.

**11. Auto table of contents**
`engine.py` (`TocMarker` flowable records chapter page during build; `_build_toc()` with
dot leaders and part headings; `_estimate_toc_pages()`; two-pass in `build_pdf()`) ·
`epub.py` (`_toc_page_xhtml()` clickable chapter list) · `templates/generate.html` +
`templates/project_edit.html` (Include table of contents checkbox, off by default).

### ◻ Tier 4 — planned / backlog

*(Cover Studio Tiers 1–3 all shipped: features #16 designed templates + editor, #17 font
library, #18 full print wrap. Possible follow-ups: wire the wrap's page count directly from
a completed interior build on the result page; per-retailer wrap presets; author-photo /
logo image on the back panel.)*

**In-app manuscript editor — author a book start to finish** *(large; a product-identity
step from "typesetting tool" toward "authoring + typesetting suite")*

Reframe before building: **not** a Word-style WYSIWYG. The engine deliberately consumes a
*semantic* block model (`para` / `subhead` / `scene` / `doc_block` + typed epistolary), and
the whole value proposition is that the **preset** owns typography while the manuscript
carries only structure + emphasis. A free-form formatting editor would fight that. Target a
*structured* editor (à la Ulysses / iA Writer / Docs "pageless") with a fixed style set that
maps 1:1 onto the existing blocks.

Cheapest, safest route reuses everything: an editor that **emits the existing Markdown**
runs through `manuscript.parse_markdown` → PDF/EPUB/continuity/preview unchanged.

- **Phase A (low risk, recommended first):** a Markdown authoring surface — writing pane
  (word count, chapter nav, find/replace) + toolbar that inserts the app's own conventions
  (`#`/`##`/`===`/`* * *`/`*..*`/`**..**`/`~~~ letter ~~~`), split-pane live preview (reuse
  the PyMuPDF rasterizer), **autosave into the project manuscript file**. No new dependency,
  no break of the offline / no-CDN / system-fonts convention. Pairs directly with the
  continuity checker (write → check → typeset in one place).
- **Phase B (optional, bigger):** true WYSIWYG via a *vendored* structured editor
  (ProseMirror / TipTap / Lexical) constrained to the block/style set, still emitting the
  same Markdown.

**Decision to make first (blocks Phase B, not Phase A):** stay dependency-free / no bundled
JS, or adopt a locally-vendored editor library with a build step? This reverses the current
"no external assets, tiny inline JS" convention and shapes everything downstream.

**New obligation once people author in-app:** autosave + backups + no data loss — a higher
bar than a tool that only transforms files the user already has stored elsewhere. Keep
`.docx` import as the on-ramp for existing manuscripts.

---

## Conventions for contributions

- Keep the engine **single-pass** unless a feature genuinely needs two (TOC, cross-refs);
  if so, isolate the measuring pass in `build_pdf` and pass the result into `_build_story`.
- New preset fields: update `DEFAULTS`, `parse_preset_form`, `editor.html` together, and
  keep defaults backward-compatible with existing `presets/*.json` (use `.get(...)`).
- New per-book options go on the **generate** page + `meta`, not the preset, when they vary
  per book (cover, front matter, TOC, smart punctuation) rather than per style.
- Preserve offline operation: no CDN assets in templates; system-font stacks only.
- After any imposition change, re-verify: folio starts at 1 on the first story page; blanks
  appear only where intended; recto/verso text margins alternate correctly.
- `_matter_page` and `_build_toc` call `_ms_inline` from `manuscript.py` — that import
  direction (engine → manuscript) is intentional and safe; never reverse it.
