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
matter.py         The front/back-matter vocabulary — one table, read by app + engine + epub.
test_epub.py      EPUB self-check tests: builds one good file, then breaks it eleven ways.
checker.py        Continuity checker: tier-1 rule checks + tier-2 Claude Haiku analysis.
templates/        Jinja2 UI: base, index (styles), editor (preset form + live preview),
                  generate, result, projects, project_edit, continuity_result.
presets/*.json    One file per style. Cloneable per customer. Seven presets ship by default.
covers/*.json     One file per designed cover template (text-driven page-1 layout). Cloneable per line.
                  Edited in the browser via the Cover Studio (no hand-editing needed).
figures/          Interior illustrations placed with ~~~ figure src="…" (uploaded in-app; gitignored).
fonts/*.ttf       Embeddable TrueType faces — seven bundled OFL book serifs (see #44) plus any
                  the user uploads. Also stores scene-break ornament images. fonts/licenses/ holds
                  the OFL texts for the bundled families.
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
list:          {bullet, number_format, indent, marker_gap, item_gap,
               space_around, font_size, line_leading}   number_format uses "{n}"
quote:         {indent, right_indent, first_indent, font_size, line_leading,
               style, space_around, para_gap,
               source_style, source_align, source_gap}
               style / source_style: "regular" | "italic"
align:         {space_around, indent, para_gap}     alignment blocks only
link:          {underline, color, epub_underline}
               underline is the PRINT setting; color/epub_underline are ebook-only
endnotes:      {heading, group_by_chapter, font_size, line_leading, indent,
               entry_gap, group_gap, marker_scale}
figure:        {width, align, max_height, space_around,
               caption_size, caption_style, caption_align, caption_gap}
               width/max_height are fractions (of the text width / text height)
               align, caption_align: "left" | "center" | "right"
               caption_style: "italic" | "regular" | "bold"
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
      "notes":  [{"n": int, "label": str, "text": html}]  # only when the chapter has endnotes
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
| `~~~ figure src="map.png"` … `~~~` | an illustration; the block content is its caption |
| `~~~ list` / `~~~ list type="number"` | a list — **one item per line** |
| `~~~ quote source="…"` | an inset quotation (prose; lines wrap) |
| `~~~ center` / `right` / `left` | an aligned block — **one line per line** |
| `[text](https://…)` | a link: web, `mailto:`, or an in-book `#anchor` |
| `[^label]` / `[^label]: text` | an endnote reference and its text (numbered per chapter) |
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

`.docx` import (`manuscript.import_docx`) maps Heading 1/Title → chapter, other headings →
subhead, runs → bold/italic, images → `~~~ figure` (extracted to the figure library), tables
and Quote styles → plain `~~~` blocks, list items → bullet/number-prefixed paragraphs, and
hyperlink text → plain text. Pass a dict as `report=` for counts; `import_summary(report)`
turns it into the two sentences the UI flashes. See feature #47.

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
  Designed covers reach the EPUB as a rasterised page-1 JPEG (feature #43; `epub.py` itself is
  still image-only) and are persisted in saved projects (feature #29).

- **Scene-break glyphs must exist in the body font.** The bundled book serifs lack most ornaments.
  Presets ship with font-safe marks (`* * *`, em-dashes, middots, bullets) — all seven bundled
  families were checked against the four the presets use plus curly quotes / ellipsis / en dash.
  Use the image ornament type for custom artwork instead of exotic Unicode, and re-check coverage
  when pointing a preset at a new face. (U+00AD is *not* required: two of the bundled families lack
  it and hyphenation still renders a real hyphen — ReportLab breaks on the soft hyphen itself.)

- **Figures never overflow the page, and never vanish.** `_render_figure_block` clamps the image
  to the page's text height *minus the measured caption* before wrapping the pair in
  `KeepTogether`, so the group always fits in a frame — `KeepTogether` on something taller than the
  page would loop. A missing `src` renders a labelled placeholder box (PDF) or a
  `[missing image: …]` note (EPUB) with the caption intact; it is never silently dropped. Note a
  *typed* empty fence is deliberately kept by `parse_markdown` (a caption-less figure is the common
  case) while a plain empty `~~~` is still discarded.

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
  **Since #49 this also drops links** in a chapter's first paragraph under those three styles
  (`open_style: "none"` keeps them, since it passes the original markup through). The words
  survive, the `<a>` does not. Documented in the README rather than worked around: recovering
  it would mean mapping character offsets back through the markup for a rare case.

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
gaps closed since: saved projects carry designed covers (#29) and so does the EPUB (#43).

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

**19. In-app manuscript editor — Phase A (Markdown authoring)**
A project-integrated writing surface, so a book can be drafted start to finish in the app.
`app.py`: `_project_manuscript_text(proj)` (loads a project's manuscript as editable Markdown,
importing `.docx`/sample as needed — also the shared loader for future reuse),
`_load_preset_or_default`, `_wordcount`, and routes `/project/new-draft` (creates an empty
project seeded with `STARTER_DRAFT` and opens the editor), `/project/<pid>/write` (editor),
`/project/<pid>/write/save` (autosave → writes `<pid>.md`, switches `manuscript_type` to
`markdown`, returns word/chapter counts), `/project/<pid>/write/preview` (builds the real
manuscript with the project's preset, returns the first ≤6 pages as PNGs). ·
`templates/manuscript_editor.html`: textarea writing surface + formatting toolbar (Chapter /
Subhead / Part / Scene break / Bold / Italic / Letter block insert the existing Markdown
conventions), live word count, chapter count, debounced autosave (+ Ctrl/⌘-S and a
`sendBeacon` flush on page-hide), a page-preview pane, and a Typeset button. ·
`templates/projects.html`: a "Start writing" new-draft field and a per-card **Write** button.
Reuses `manuscript.parse_markdown` and the interior build unchanged — no new dependency, no
break of the offline / no-CDN convention. Phase B (vendored WYSIWYG) still open; see backlog.

**20. Manuscript editor — chapter outline + jump-to nav**
`templates/manuscript_editor.html` (client-side only): a live **Chapters** panel in the editor
sidebar lists each `# chapter` (numbered when untitled) and `=== part`, rebuilt on every edit;
clicking an entry scrolls the writing pane to that heading. Scrolling is wrapping-aware — a
hidden mirror `<div>` mirrors the textarea's font/width/padding to compute the caret's pixel
top (a plain line-count × line-height would drift once paragraphs wrap). No backend change.

**21. Manuscript editor — find / replace**
`templates/manuscript_editor.html` (client-side only): a floating find bar (Find button on the
toolbar or Ctrl/⌘-F) with find field, replace field, match-case toggle, live match count
(`n / total`), next/prev (Enter / Shift-Enter, wrapping), Replace, Replace all, and Esc to
close. Next/prev select the match and scroll to it via the same mirror-based caret measurement
as the chapter outline; edits route through `changed()` so autosave, word count, and the
outline stay in sync. No backend change.

**22. Cover wrap — auto page-count from a book**
`app.py`: `project_generate` stores `last_page_count` on the project after a PDF build (and
`project_create` carries it from the result page via a new hidden `page_count` field in
`templates/result.html`); `_projects_for_wrap()` summarises projects (name, page count, preset
trim, title/author/publisher) and is passed to the cover editor. ·
`templates/cover_editor.html`: a **From a book** picker in the Print wrap section fills trim,
page count, and the preview title/author/studio from the chosen project, showing a "Spine from
last build: N pages" note (or a prompt to build the book first). The picker `<select>` has no
`name`, so it never enters the saved template. Removes the manual page-count entry for the
common case.

**23. Manuscript editor — scene-level outline entries**
`templates/manuscript_editor.html` (client-side): `buildOutline` now nests **subheads**
(`## …`, by title) and **scene breaks** (`* * *` / `***` / `---` / `###`, labelled with a
6-word snippet of the following line, or "Scene N") under each chapter, indented and muted.
Each jumps to that line via the existing mirror-based caret scroll. Scene detection mirrors
`manuscript.SCENE_BREAK_RE`. No backend change.

**24. Cover wrap — per-retailer presets**
`app.py`: `WRAP_RETAILERS` (Amazon KDP, IngramSpark, Generic) bundling `bleed` and a
`spine_text_min` page count plus a guidance note; `_wrap_from_form` reads `wrap_retailer` and
passes `pages` + `spine_text_min` into the wrap. · `engine.py`: `build_cover_wrap` gates spine
text on `pages >= spine_text_min` (and a physical floor) via a new `draw_text` arg on
`_paint_spine`, and reports `spine_text` in its result. · `templates/cover_editor.html`: a
Retailer select in the Print wrap section that pre-fills bleed and shows a live note
("spine text included/omitted (N pp)"); the wrap preview info reports the spine-text state.
Paper calipers stay in `_PAPER` (standard by weight); the note reminds users to verify against
the retailer's own cover template. So e.g. an 80-page book gets spine text on IngramSpark
(min 48) but not KDP (min 100).

**25. Cover wrap — back-cover image (author photo / logo)**
`engine.py`: `_paint_back_panel` draws an optional image from `meta['cover_back_image']`
(centred, aspect preserved via `ImageReader`, width clamped to the frame, `mask='auto'` for
transparent PNG logos), positioned by `cover_back_image_w`/`cover_back_image_y`. ·
`app.py`: `_save_back_image()` writes the upload to a temp file; both wrap routes read
`request.files['wrap_back_image']`, pass the path through `_wrap_from_form`, and clean it up. ·
`templates/cover_editor.html`: a Back-cover image file input plus width and vertical-position
fields; the front-cover live preview strips the file from its FormData so a photo isn't
re-uploaded on every keystroke. Drawn between the blurb and the barcode reserve.

**26. Manuscript editor — styled-Markdown surface (Phase B, dependency-free)**
`templates/manuscript_editor.html` (client-side only): the plain textarea is now a
**highlight overlay** — a painted backdrop `<div>` behind a transparent-text textarea, so the
textarea remains the source of truth (autosave, find/replace, outline, mirror-scroll all keep
working). `buildHighlightHTML` colours chapters/subheads/parts, bold/italic, scene breaks and
`~~~` fences; character content is preserved exactly (verified invariant) so the caret stays
aligned. Requires a **monospace** surface and **colour/weight/italic only, no font-size change**
(a larger heading would desync the caret vs the textarea's uniform metrics). Backdrop width is
matched to `textarea.clientWidth` (scrollbar), scroll synced via `translate`, re-render throttled
with `requestAnimationFrame`. Degrades gracefully: highlighting is JS-gated via a `hl-active`
class, so without JS the textarea shows normal text. No dependency, no build step — see the
Tier-4 decision.

**27. Genre cover presets (×5)**
`covers/`: Thriller Noir (black + blood-red rule/byline, bold bone title), Romance Blush
(light blush gradient, rose + warm-gold, elegant italics), Sci-Fi Cosmic (deep indigo, icy
title, cyan accents), Fantasy Emerald (forest green + antique gold, heavier rule), Literary
Ivory (light ivory, deep-ink type, fine classic rule). Data-only (no renderer change) — each
is a palette/border/type variation on the shared cover renderer; they appear automatically in
the Covers gallery and the Generate dropdown. First exercise of the renderer on **light
backgrounds** (Romance/Literary) — confirmed legible. Epigraph placed low (0.26) as a tagline
so it clears the dynamic ornament.

**28. Genre interior presets — Fantasy + Sci-Fi split (×2)**
`presets/`: Fantasy (Epic) 6×9 (deep drop-cap openings, airy 11.5/16.5 leading, generous
margins, decorative `•  •  •` break) and Science Fiction (Clean) 6×9 (large bare-numeral
`{n}` openers at 30pt, `open_style: none`, hyphenated justification, minimal single `—` break).
Splits the combined `science-fiction-fantasy` preset so the two distinct cover genres (#27
Fantasy Emerald / Sci-Fi Cosmic) each have a matching interior. Data-only (existing schema
fields); the combined preset and the existing thriller/romance/literary interiors — which
already pair with their covers — were left untouched to avoid duplicates. Verified via rendered
chapter-opener proofs.

**29. Designed covers persist in saved projects (bug fix)**
Closes the gap flagged in #15: a book generated with a designed cover, once saved as a project,
lost the cover on edit/regenerate. Now the designed-cover fields (`cover_mode`,
`cover_template`, `cover_collection`/`kicker`/`accent`/`epigraph`/`studio`) round-trip through
the whole project flow — `app.py` `project_create` + `project_edit` persist them, `templates/
result.html` passes them as hidden fields on **Save as project**, `project_generate` rebuilds
the `meta` (loading `cover_template_data`) so regeneration reproduces the cover, and
`templates/project_edit.html` gains a Cover section (mode selector + template dropdown + text
fields) to edit it. Backward-compatible: old projects (no `cover_mode`) default to `none`/image
as before. Verified end-to-end (save → persisted → edit shows fields → regenerate renders the
designed cover on page 1).

**30. Poetry collections — line-preserving poem blocks** *(first "new document type")*
A poem is a typed fenced block `~~~ poem title="…"` … `~~~` whose content **preserves verse
line breaks** (the paragraph joiner in `parse_markdown` deliberately space-joins wrapped prose,
which is wrong for verse); a blank line starts a new stanza. It reuses the doc-block plumbing so
it round-trips through `doc_model` and the WYSIWYG editor. `manuscript.py` (poem branch in
`flush_block_para`, verse lines joined with `<br/>` to keep the doc_block tuple contract) ·
`engine.py` (`_render_poem_block`: poem title + per-line flowables with a hanging **runover**
indent; verse never hyphenated) · `app.py` `DEFAULTS` (a `poem` preset section:
font/leading/indent/runover/stanza spacing/align/title styling) · `doc_model.py` +
`static/doc_model.js` (stanza round-trip: poem `children` are `{type:'stanza', lines:[…]}`) ·
`static/wysiwyg.js` (`renderPoem`/`readPoem`, full rich verse editing — Enter splits a verse) ·
`templates/manuscript_editor.html` (Poem toolbar button + cheatsheet row) · `epub.py`
(poem `<header>` title + `.doc-block-poem` CSS). Tested via `test_doc_model.py::test_poems`
(engine fidelity + model stability), a live PDF render, and an EPUB build. v1 follow-ups: no
`.docx` poem import; the 9 preset JSONs fall back to `DEFAULTS` (no per-preset `poem` section);
EPUB runover indent is per-stanza not per-line.

**31. Anthologies / essay collections — per-piece byline + contributors page** *(second "new
document type"; the roadmap's "nearly free quick win")*
Two additions that extend the book model without a new paginator:
- **Per-piece byline.** A chapter heading `# Title | Author` attaches an author byline rendered
  in italic under the piece title (the KDP "Title | Subtitle" idiom; split on the first ` | `
  only, so a byline may itself contain a pipe and still round-trips). `manuscript.py`
  (`BYLINE_SEP`, `_split_byline`, `ch['byline']`) · `engine.py` (`chap_byline` style + render
  under the title) · `epub.py` (`p.chapter-byline` + CSS) · `doc_model.py` + `static/doc_model.js`
  (chapter block gains a `byline` field) · `static/wysiwyg.js` (byline rides on `data-byline`,
  shown under the title via CSS `::after`, round-trips through `read()`; its **text** is edited in
  Markdown mode, like doc-block metadata) · `templates/manuscript_editor.html` (cheatsheet row +
  rich-mode CSS). Tested via `test_doc_model.py::test_bylines` (fidelity + stability, incl.
  multi-pipe) and a live PDF/EPUB render.
- **Contributors page.** A collection-level back-matter page (`meta['contributors']`, one
  contributor per blank-line block; the name before an em dash / `--` is set **bold**, the rest is
  the bio). `engine.py` (`_back` entry + a `contributors` branch in `_matter_page`) · `epub.py`
  (`_back_items`/`_back_nav` entries, `matter-contributors` CSS, and a local `_md_emph_to_html`
  so raw author text bolds/italicises in EPUB) · `app.py` (threaded through the generate meta,
  `project_create`/`project_edit` persistence, and both project-build meta dicts) ·
  `templates/generate.html` + `project_edit.html` (Back-matter textarea) + `result.html` (hidden
  field so **Save as project** carries it). Verified end-to-end (byline opener + Contributors page
  render correctly in both PDF and EPUB). Deferred v1 follow-up: **per-piece epigraph/attribution**
  (the third roadmap bullet) — a rarer need that would add heading-parse surface; left for a
  follow-up. WYSIWYG byline editing is display-and-preserve (value edited in Markdown mode); the
  contenteditable feel needs the same interactive pass PR #24 flagged (no node/Chrome harness here).

**32. Cover enrichment — layout archetypes + backgrounds + emblem slots** *(the "enrich the
template, not a design studio" direction from the cover strategy note)*
Three composable, backward-compatible additions to the parametric cover renderer. All are opt-in
template keys; the six shipped covers (which set none of them) render byte-identically.
- **Layout archetypes** — a template `layout` key (`centered` | `top` | `bottom` | `band`) selects
  the title-cluster placement. `engine.py` `_COVER_LAYOUTS` supplies vertical fractions per
  archetype; `centered` is an empty override so existing templates keep their own `y` values.
- **Backgrounds** — `background: {image, vignette, overlay:{color,opacity}}`. `_paint_background`
  draws cover-fit (fill-and-crop, clipped) art over the base gradient and under the border + text;
  `_paint_vignette` is a soft edge-darkening built from non-overlapping translucent frame bands; a
  flat colour overlay tints busy art so the title stays legible.
- **Title panel** — `panel:{enabled,color,opacity,top,bottom}`, a translucent band behind the title
  (implicit for the `band` archetype, opt-in elsewhere) for legibility over art.
- **Emblem slots** — `emblems: [{image, slot, w}]` (≤2), fixed named slots (`top-center`,
  `bottom-right`, …) for a logo / series badge / author mark — not freeform placement.
Assets live in `covers/assets/` (new writable dir; gitignored) resolved by `engine._cover_asset_path`
(→ `engine.COVER_ASSET_DIR`, set by `app.py`). `app.py`: `COVER_DEFAULTS` + `parse_cover_form`
(+ `_parse_emblems`) carry the new schema; a `/cover/asset/upload` route stores an image (Pillow-
validated) and returns its filename; `COVER_LAYOUTS`/`COVER_FILL_KEYS`/`EMBLEM_SLOTS` feed the
editor. `templates/cover_editor.html`: Layout &amp; background, Title panel, and Emblems fieldsets,
plus an `imgpick` control that uploads on file-select and writes the filename into a named text
field (so it round-trips) — the live preview and print-wrap pick everything up unchanged. Both
cover-draw paths (`_draw_designed_cover`, `build_cover_wrap`) call `_paint_background`. Verified:
rendered proofs of every archetype + background/vignette/overlay + panel + emblems; a full Flask
test-client pass (editor renders for new and all old templates; asset upload incl. non-image
rejection; band+bg+panel+emblem preview; save→load schema round-trip). The interactive editor feel
(imgpick + debounced preview) wasn't driven in a real browser this session — same class of pass as
PR #24. Not done: cover-asset delete/library UI; emblem opacity (ReportLab `drawImage` ignores fill
alpha); background/emblems reach the EPUB cover only as pixels in the #43 raster, not as assets.

**33. Cover design families — dispatch + full-bleed photographic** *(the "genuinely different
designs" ask; the biggest lever after enrichment #32)*
Addresses the top cover feedback — users wanting visibly *different* covers, not more recolors.
Root cause: every template ran through **one** hardcoded composition (`_paint_cover_panel` — border
frame + centred title + diamond ornament), so the six covers were skins of a single design; even the
#32 layout archetypes only slid the *same* cluster around. Fix: a template `design` key selects a
whole front-cover **renderer**, dispatched through a new `engine._paint_cover_front` (registry
`_COVER_DESIGNS`). Absent → `classic-frame` = the existing `_paint_cover_panel`, so the six shipped
covers (which set no `design`) render **byte-identically** — verified by rendered proofs. Both draw
paths (`_draw_designed_cover`, `build_cover_wrap`) dispatch through the one entry point.
- **New family: `photographic`** (`engine._design_photographic` + `_paint_bottom_scrim`) — full-bleed
  cover art (reuses the #32 `background.image` plumbing, painted before dispatch) with a large
  lower-anchored title over a soft foot **scrim** (stacked non-overlapping strips, no alpha
  double-composite), a top series line, an author line over a short rule, and a studio footer. **No
  border, no ornament** — a deliberately distinct trade look. Fine-tuning lives in an optional `photo`
  dict (scrim opacity/height/colour, title y/size/leading, author size, rule) with sensible defaults,
  so `{"design":"photographic","background":{"image":"…"}}` looks right with nothing else set.
- `app.py`: `COVER_DEFAULTS['design']`, `COVER_DESIGNS` list, `parse_cover_form` carries `design` (bad
  value → `classic-frame`) and preserves the JSON-only `photo` block via `_existing_photo` (hidden
  `photo_json` field) so a browser save never drops it; `designs` passed to both editor routes.
- `templates/cover_editor.html`: a **Design** fieldset (family selector + note) and the hidden
  `photo_json`. Live preview + wrap post the whole form, so both pick up `design` unchanged.
- `covers/photo-dusk.json`: a shipped photographic template (dusk palette, full schema so it round-trips
  in the editor and still reads if toggled back to `classic-frame`); appears in the gallery + Generate
  dropdown automatically. Verified: front + wrap PDF renders (art and no-art), a Flask test-client pass
  (editor renders for the new + all old templates; preview builds; save→load persists `design`+`photo`).

  **Three more families added same session** (`engine._design_typographic` / `_design_geometric` /
  `_design_vintage`, shared helpers `_tracked_left` + `_fit_title_lines`; registered in `_COVER_DESIGNS`;
  `app.COVER_DESIGNS` now lists all five; shipped templates `typographic-bold.json`, `geometric-block.json`,
  `vintage-pulp.json`; each reads optional per-design tuning `typo`/`blocks`/`vintage`):
  - **typographic** — oversized *left-aligned* display title filling the upper page + heavy accent rule +
    tagline; no frame/art. **geometric** — flat colour-blocked ground (overpaints the gradient) with the
    title reversed out of a bold band; series above, author below. **vintage** — top title bracketed by
    double rules + italic tagline + a filled author band across the foot. All eyeballed via rendered proofs
    and covered by the five-family test-client pass (every template's thumbnail + preview builds; classic
    covers still default to `classic-frame`, unchanged).

  **v1 follow-ups:** per-field editor controls for the `photo`/`typo`/`blocks`/`vintage` tuning blocks
  (JSON-only for now); photographic art doesn't extend into the wrap **bleed** yet (base gradient covers
  it); the EPUB cover is a flat raster of the design (#43). **Next up: the design-gallery picker (#34).**

**34. Design-gallery picker — thumbnail tiles for choosing a cover** *(the discoverability lever for
#32/#33; visibility, no engine change)*
The per-book cover chooser was a plain name `<select>`, so the enrichment (#32) and design families
(#33) were invisible until after a build. Now it's a **visual gallery**: a rendered front-cover
thumbnail per template.
- `app.py`: `_cover_thumb_bytes(cid)` renders page 1 of a designed cover over `DEFAULTS` + a fixed
  neutral sample (title *The Salt Road* / *Ellinor Vale* / series + studio, so every family shows its
  furniture), rasterized via PyMuPDF; **disk-cached** in `COVER_THUMB_DIR` (`out/_cover_thumbs`) and
  keyed by the template JSON's **mtime**, so a Cover-Studio edit/save auto-refreshes the tile. Route
  `/cover/thumb/<cid>.png` serves it (`Cache-Control: no-cache` to revalidate; 404 if the template is
  gone). Reuses the #10/#16 preview rasterizer pattern — **no engine change**.
- `templates/generate.html` + `project_edit.html`: the `<select name="cover_template">` becomes a
  `.cover-gallery` of `.cover-tile` **radio** cards (thumbnail + name; the radio keeps the exact same
  field name/value so the compose + project flows are unchanged). Selection highlight is CSS-only via
  `:has(input:checked)` (Chromium/Edge-WebView — the app's runtime).
- `templates/covers.html`: each management card gains a centred 150px thumbnail above the specimen.
- `templates/base.html`: shared `.cover-gallery`/`.cover-tile` styles (one place for both pickers).
Verified via a Flask test-client pass: thumbnails build + PNG-cache, cache is reused on repeat and
**invalidates when the template changes**, missing template → 404, and all three pages
(Generate / `/covers` / `project_edit`) render the tiles. Rendered thumbnails eyeballed
(classic-frame vs photographic clearly distinct). Follow-ups: a "clear stale thumbs on template
delete" sweep (harmless orphans today); optional hover-to-enlarge.

**35. Gallery categories + colour variants** *(picker cleanup for #33/#34; data + presentation, no
engine change)*
The picker/gallery was a flat wall of tiles that only got busier as families grew. Now templates are
**grouped by design family into labelled categories**, and each new family has real colour choices.
- `app.py`: `COVER_CATEGORIES` (ordered `(key, label, blurb)` per family) + `group_cover_templates(items)`
  → `[{key,label,blurb,tiles}]` (bucketed by each template's `design`, unknown → Classic Frame, empty
  groups dropped, tiles sorted by name; key is `tiles` not `items` to dodge Jinja's `dict.items()`). The
  context processor now also injects `cover_groups`.
- `templates/generate.html` + `project_edit.html`: the flat `.cover-gallery` becomes one `.cover-cat`
  section per category (heading + blurb + its own tile grid); the radio `name`/`value` are unchanged.
  `templates/covers.html`: management cards grouped the same way, and the per-card spec shows **Design**
  (family label) instead of the border line (meaningless for non-framed families). Shared `.cover-cat`
  heading CSS in `base.html`.
- **Eight colour variants** (data-only; each reuses its family's base template and only swaps
  name/description/palette — the tuning blocks reference palette *keys*, so a recolour cascades):
  `photo-sand`/`photo-forest`, `typographic-noir`/`typographic-slate`, `geometric-coral`/`geometric-mono`,
  `vintage-rust`/`vintage-noir`. So each of the four new families now ships **3** options (Classic still 6);
  18 templates total.
Verified: contact-sheet proof of all eight variants (legible, distinct), a Flask test-client pass
(grouping buckets every template in category order, all 18 thumbnails build, Generate + `/covers` +
`project_edit` render all five category headings), and a live browser screenshot of `/covers` (clean
category sections). Follow-up unchanged: per-field editor controls for the tuning blocks.

**36. Cover editor — emblem placement + dimension guide** *(usability; template-only, no engine/backend
change)*
The Emblems section offered a slot dropdown (`top-left`/`center`/`bottom-right`/…) and a width in inches
with no indication of *where* those land or *how big* they are, and the background image's coverage wasn't
stated. Added a live **slot/dimension map** to the Emblems fieldset in `templates/cover_editor.html`: a
mini-cover (`#slotmap`) sized to the **trim aspect** (`prev_w`×`prev_h`) with the seven fixed slots as
faint dots. A JS `updateSlotMap()` draws each configured emblem as an accurately-scaled **footprint box**
— width = the emblem's `w` as a fraction of the trim (square placeholder; a note says real height follows
the image's proportions), edge-anchored per slot using `margin = bd_inset + 0.14` (mirrors
`engine._slot_xy`), **solid** = has an image / **dashed** = an empty slot, numbered 1/2. A monospace
readout prints the exact figures (`Cover 6 × 9 in · Emblem 1 0.7 in wide · Emblem 2 0.6 in wide`), and a
legend notes the **background image fills the whole cover** (cropped to fit). Recomputed on every form
`input` and after the imgpick upload/clear handlers (which set the image field programmatically). CSS in
the editor's own style block. Verified: Flask test-client renders the map (slots + boxes + dims readout +
background note) for new and existing templates; a live browser check confirmed the default state
(Emblem 1 top-center, Emblem 2 bottom-center), that a box **moves** when the slot changes, and that it
**resizes** when the width changes (0.7 → 2 in visibly grows to ~⅓ of the cover width).

**37. Three more design families + collapsible categories** *(extends #33/#35; engine + data + UI)*
Grew the cover system to **8 design families / categories** and made the gallery fold up for a cleaner
picker as the list got long.
- **New families** (`engine._design_minimal` / `_design_stripe` / `_design_postcard`, registered in
  `_COVER_DESIGNS`; `app.COVER_DESIGNS` + `COVER_CATEGORIES` extended): **minimal** (quiet, tracked serif
  title in whitespace + hairline rule), **stripe** (full-height side colour band + large left-aligned
  title, editorial/asymmetric), **postcard** (cover art in an inset **mat + frame** above a title — a
  framed alternative to full-bleed; empty → a tinted placeholder panel). Each reads an optional
  `minimal`/`stripe`/`postcard` tuning dict. Small **refactor**: the cover-fit image draw was extracted
  from `_paint_background` into a shared `engine._draw_image_cover(canv, path, x0,y0,w,h)` so postcard can
  reuse it for the inset (existing full-bleed output unchanged). 6 shipped templates (2 per family):
  `minimal-ivory`/`-noir`, `stripe-crimson`/`-indigo`, `postcard-classic`/`-slate`. **24 templates total.**
- **Collapsible categories**: each `.cover-cat` is now a `<details>`/`<summary>` (native, no JS) across
  `generate.html`, `project_edit.html`, `covers.html`; shared summary/chevron CSS in `base.html`. In the
  pickers only the **selected** template's category is open by default (falls back to the first when the
  project has no cover set); `/covers` opens all (browse) and shows a per-category **count**.
Verified: proof sheet of all 6 new templates (both palettes, legible + distinct); a Flask test-client
pass (8 families registered + categorized in order; all 24 templates carry a valid design and build a
thumbnail; previews build for every new template; both pages render `<details>` with all 8 headings;
classic covers unchanged); and a live browser check (collapse/expand works, the three new categories
render with thumbnails). Follow-up unchanged: per-field editor controls for the tuning blocks.

**43. Designed covers reach the EPUB** *(first Tier-5 item; closes the gap open since #15/#32/#33)*
A book set with a **designed** cover kept it in the PDF but lost it entirely in the ebook — `epub.py`
reads `meta['cover_image']` only, so `cover_mode == 'designed'` produced a coverless EPUB. The eight
design families were print-only in practice.
- `app.py`: `_epub_cover(preset, meta)` — a `contextlib.contextmanager` that rasterises page 1 of the
  designed cover to a temp **JPEG** (quality 88, `EPUB_COVER_H = 2560` px on the long edge, KDP's ideal)
  and yields a **meta copy** whose `cover_image` points at it, cleaning the temp files up on exit. Same
  PyMuPDF path as `_cover_thumb_bytes` (#34), but run over a **stub manuscript** (`# Cover` + one line,
  `front_matter='none'`, `include_toc=False`) so it typesets one cover page instead of rebuilding the
  whole book — a 400-page book with a TOC would otherwise be built twice more. JPEG not PNG because a
  photographic-family cover rasterises to multiple megabytes. Both EPUB call sites (`generate()` and
  `project_generate()`) wrap the build in `with _epub_cover(...) as emeta:`.
- **Fails soft by design:** no PyMuPDF/Pillow, no `cover_template_data`, or a render error → the
  original meta is yielded untouched and the EPUB builds coverless, exactly as before. Note the
  `yield` sits *outside* the `except` (a contextmanager that re-yields after an exception is thrown
  into it raises `RuntimeError`) — keep it that way.
- `epub.py`: `_content_opf` now also emits the legacy `<meta name="cover" content="…"/>` alongside the
  EPUB 3 `properties="cover-image"` (derived from the manifest, so the signature is unchanged). Kindle
  tooling and older readers only look at the legacy tag; this benefits **uploaded-image** covers too.
Verified: three families (classic-frame / typographic / photographic) each produce a distinct
1707×2560 JPEG carrying the real book's title, author and series line — eyeballed, not just asserted;
`cover.jpg` + `cover.xhtml` + both OPF pointers present; temp files removed; **no-cover, missing-template
and uploaded-image paths unchanged** (uploaded art is never deleted); and end-to-end through both routes
(`POST /generate` with `format=epub`, and a project regenerate with `format=both`). Resulting EPUBs
68–90 KB. Not done: the EPUB cover is a flat raster, so `background`/`emblems` (#32) come along as pixels
rather than as separate assets — fine for an ebook cover.

**44. Six more bundled book faces — one typeface per genre style** *(Tier-5E; the largest
perceived-quality change per hour in the gap list. Data + one constant; no engine change)*
All nine presets set `"regular": "Book-Regular.ttf"`, so the nine "genre styles" differed in
*layout* but every book came out in Libre Baskerville — against Vellum's 8 styles (each a distinct
display + body pairing) and Atticus's 1,500 fonts. The font-library plumbing (#17) already existed;
we simply shipped one family.
- `fonts/`: **EB Garamond, Vollkorn, Alegreya, Crimson Pro, Lora, Spectral** — Regular/Bold/Italic
  each, 18 files, ~4.8 MB (fonts/ total 5.1 MB). All **SIL OFL**, so they may be embedded in a book
  someone sells; licence texts in the new `fonts/licenses/`. Sourced from `google/fonts`; the five
  families that upstream ships only as **variable** fonts were cut to static Regular (wght 400) and
  Bold (wght 700) instances with `fontTools.varLib.instancer` — a variable TTF registered as "bold"
  would render at its 400 default, so bold text would not be bold. Spectral ships static upstream and
  was copied as-is. (fontTools was used in a throwaway venv; it is **not** a project dependency.)
- Preset mapping — Classic Literary → EB Garamond · Gothic/Horror → Vollkorn · Fantasy (Epic) +
  Science Fiction & Fantasy → Alegreya · Mass Market → Crimson Pro · Romance → Lora ·
  Thriller/Crime + Science Fiction (Clean) → Spectral. **Modern Clean deliberately keeps Book**
  (Libre Baskerville's large x-height and wide fit *is* the airy contemporary look that style is for).
- Sizes were re-set, not carried over. Libre Baskerville is a screen face — x-height 0.530 em and
  0.587 em average advance, against 0.400/0.437 for EB Garamond — so at a fixed point size the new
  faces set narrower and look smaller. Sizes were chosen by **characters per line** (the measure that
  matters for a book page): the presets ran 44–55 CPL, which is a short measure; they now land
  **54–65**. Only five presets changed size at all (e.g. Classic Literary 11/15.5 → 12/16.5).
- `app.py`: `BUILTIN_FAMILIES` now derives `BUILTIN_FONTS` (21 files), so every bundled face is
  protected from deletion in the Fonts manager — deleting one would silently drop a preset to Times.
- `README.md`: the Fonts section is now a family → registered-name → preset table plus the OFL note.
Verified: all 21 faces register and embed via the app's own `_is_embeddable_font`; every family
covers the glyphs the presets actually use (`*`, `•`, `—`, `·`, curly quotes, ellipsis, en/em dash);
rendered page proofs of all nine presets eyeballed; a scripted pass over all nine (no font fallback,
no line set tighter than the preset's own leading, incl. parts/subheads/scene breaks/doc blocks/TOC);
the style editors show the right faces pre-selected; a full `POST /generate` compose (PDF+EPUB) with
no fallback; all 24 cover thumbnails still build; `test_doc_model.py` ALL PASS.
**Note for upgraders:** `_seed_defaults()` copies *missing* files into `%APPDATA%`, so an existing
install gains the six new families in its font library, but its already-seeded preset JSONs keep
pointing at Book. Only new installs get the new pairings automatically; existing users can switch a
style's faces in the editor. Deliberate — never overwrite a user's edited preset.

**45. Raised-initial openings no longer collide with the next paragraph** *(pre-existing engine bug,
found while proofing #44; present since the feature shipped and reproducible at HEAD with the old
Book font, so not a font-swap regression)*
`open_style: "raised_initial"` (Romance ships it; any preset can select it) set the initial as an
oversized `<font size>` run inside the opening Paragraph. ReportLab drops the first baseline to clear
a tall run but `wrap()` still reports `lines × leading`, so the paragraph drew about a line lower than
the space reserved for it and **overprinted the following paragraph** — measured at HEAD: 7.0 pt
between baselines where the preset's leading is 16.0. (`autoLeading='max'` was tried first and only
narrows it — ReportLab's measure and its draw disagree there too.)
- `engine.py`: new `RaisedInitial` flowable beside `DropCap`, owning its geometry — it wraps the body
  as a Paragraph with `firstLineIndent` = the initial's width, reserves `ascent(initial) −
  ascent(body)` above the first line, and draws the initial on that first baseline, so measured height
  and drawn height agree. `_opening_para()` returns it instead of the marked-up Paragraph.
- **It splits.** Unlike `DropCap` (which returns no split and *raises `LayoutError` on an opening
  paragraph taller than the frame* — still true, untouched here), `RaisedInitial.split()` keeps the
  initial with the first part and flows the remainder as an ordinary paragraph, matching what the
  plain Paragraph it replaced could do. Verified with a page-length opening paragraph: 2 pages, clean
  continuation, no stray indent.
Verified: baseline spacing across all nine presets is now exactly the preset leading (worst −0.1 pt,
rounding); the check **fails at HEAD** (−9.0 pt on Romance) and passes with the fix, so it tests the
bug rather than the code; rendered proof eyeballed (initial sits on the first baseline, paragraphs
evenly spaced) in Lora, Book and EB Garamond.

**46. Figures — illustrations with captions** *(Tier-5A's biggest hole: there was **no image block
at all**, so maps, plates, diagrams and chapter art simply could not go in a book)*
A figure is a typed doc block — `~~~ figure src="map.png" alt="…"` — whose content is its **caption**
(a figure may have none). Reusing the doc-block shape means the round-trip layer, the WYSIWYG, the
outline and the escape rules all came along for free: **`doc_model.py` and `doc_model.js` needed no
change at all**, verified by the new tests rather than assumed.
- `manuscript.py`: one behavioural fix — a *typed* fence with no content is no longer discarded
  (`if block_buf or block_type`). Without it a caption-less figure was silently dropped, which is the
  common case. A plain empty `~~~` is still discarded.
- `engine.py`: `FIGURE_DIR` + `_figure_asset_path` (mirrors the cover-asset resolver, but returns
  **None** when the file is missing so the renderer can say so), `_figure_size` (aspect-preserving fit
  via `ImageReader`), the `FigureImage` flowable (scales into the column, honours `align`, and draws a
  labelled **placeholder box** for a missing `src` — a dropped illustration is worse than an obvious
  gap), and `_render_figure_block`, dispatched from `_render_doc_block` beside `poem`. Image + caption
  are wrapped in `KeepTogether`, and the height is clamped to the page's text area (minus the caption),
  so the group always fits and can never loop. `full="yes"` emits `PageBreak, image, caption, PageBreak`.
- `epub.py`: `_collect_figures()` walks the chapters, **de-duplicates by src** (the same plate used
  twice is stored once) and skips missing files; each becomes an `images/figNNN.ext` manifest item and
  a zip entry. `_figure_html()` emits `<figure><img><figcaption>`, with the width as a percentage and
  a `[missing image: …]` note when the file is gone — the caption survives either way. New `figure*`
  CSS. `_chapter_xhtml` takes the src→href map (default `None`, so the signature stays back-compatible).
- `app.py`: `FIGURE_DIR` data dir, wired into `engine` **and** `epub`; `list_figures`/`_save_figure`
  (Pillow-verified, so a renamed non-image is rejected and deleted); routes `/figures`,
  `/figures/upload` (returns JSON to `X-Requested-With: fetch`), `/figures/delete/<name>`,
  `/figures/file/<name>`; `DEFAULTS['figure']` + `parse_preset_form` (the ROADMAP's three-place rule).
- `templates/`: a new `figures.html` manager (grid of thumbnails, dimensions, first-run panel), a
  **Figures** nav link, a Figures fieldset in `editor.html` (width / align / max height / spacing /
  caption size, style, alignment, gap + the syntax hint), and in `manuscript_editor.html` a **Figure**
  toolbar button that uploads the chosen file and inserts the block in one step (both Markdown and rich
  mode) plus a cheatsheet row.
- `static/wysiwyg.js`: `renderFigure`/`readFigure` show the **actual image** with an editable caption
  under it; placement attrs ride on `data-attrs` and are edited in Markdown mode, as with other
  doc-block metadata. Absolute paths aren't previewable (not servable) and fall back to a label.
- `.gitignore`: `figures/` (user content, like `covers/assets/`).
Verified: `test_doc_model.py::test_figures` (engine fidelity + model stability at both smartquote
settings, attr order, caption emphasis, the caption-less case surviving the engine parse, and an
editor-built model); rendered PDF proofs **looked at** — inline centred figure with caption, a 45%
left-aligned one, a full-page plate, and the missing-image placeholder; EPUB checked for the zip
entries, the de-duplication, the manifest, and the `<figure>` markup; the Figures fieldset round-trips
through a real editor save with nothing else in the preset disturbed; upload validation (non-image and
wrong extension both rejected, nothing left on disk); a full `POST /generate` compose (PDF+EPUB) and
the book-preview route; all nine presets still pass the #45 regression with figures in the manuscript;
and the #43 designed-cover EPUB test still passes.
**Not done — `.docx` images.** Word still drops images (and tables) on import; that is Tier-5C's
import-fidelity item, and the natural next step now that a figure block exists to import *into*.

**47. `.docx` import fidelity** *(Tier-5C — "the gap most likely to read as *the tool is broken*";
unblocked by #46, since there is finally a figure block to import *into*)*
`import_docx` walked `doc.paragraphs` and rebuilt emphasis from `p.runs`. Measured on a Word file
exercising the usual features, that silently lost: **both images**, **the entire table** (
`doc.paragraphs` skips `w:tbl` outright), and **every hyperlinked phrase** — `Paragraph.runs` does
not include runs nested in a `w:hyperlink`, so "the survey map" vanished mid-sentence. Quotes and
list items arrived indistinguishable from body text.
- `manuscript.py`: the importer now walks `doc.iter_inner_content()` (paragraphs **and** tables, in
  document order). New helpers `_para_md` (walks runs *and* hyperlinks — keeps the words, drops the
  URL, counts it), `_para_images` (pulls `a:blip` → `related_parts` blobs into the figure library),
  `_table_md`, `_slug`, `_emph`. Also `FIGURE_DIR` as a module global, set by `app.py` like
  `engine.FIGURE_DIR` — manuscript.py still imports neither app nor engine.
- **Mapping:** images → `~~~ figure`, with a following **Caption**-styled paragraph becoming the
  caption; tables → a plain `~~~` block, one row per paragraph, cells joined with ` · `; Quote /
  Intense Quote (consecutive ones merged) → a plain `~~~` block; list items → paragraphs keeping a
  `• ` bullet or a running `1. ` number as literal text; hyperlink text → plain text.
- **Image names are content-addressed** (`<docx-slug>-<sha1[:8]>.ext`), so the project build path —
  which re-imports the `.docx` on *every* rebuild — overwrites the same file instead of piling up
  copies. Verified idempotent. `docPr/@descr` becomes the figure's `alt`; `@name` is ignored on
  purpose (Word fills it with "Picture 1").
- **Nothing is dropped silently.** `import_docx(path, report=dict)` fills counts; `import_summary()`
  turns them into two sentences, flashed by `app._flash_import` on the two paths where a user has
  just supplied the file (the compose upload, and opening the manuscript editor on a `.docx`
  project). It reports both halves — what came across, *and* that tables aren't laid out as tables,
  lists keep their marker as text, links lost their address, and **how many footnotes/endnotes were
  found but not imported** (there is still no note block; that is Tier-5A).
- Signature stays `import_docx(path) -> str`, so all five existing call sites are untouched.
Verified by a scripted pass: a plain manuscript parses **identically to the old importer** (no
regression) and writes nothing to the figure library; footnotes counted and surfaced; an unreadable
image format reported rather than crashing; re-import byte-identical with no duplicate figures; an
imported manuscript still satisfies the doc_model fidelity + stability properties. Then end-to-end
through the real compose flow: the flash reads *"Imported from Word: 1 chapter, 1 subhead, 2 images,
1 table, 1 quotation, 3 list items"*, and the built PDF contains the linked phrase, both table rows,
the bullets, the numbered item and the quotation — every one of which the old importer dropped —
with both images in the PDF **and** the EPUB.
**Still not imported:** footnotes/endnotes, tables as real tables, and link addresses. *(Since #49
and #50 the block types exist — Word footnotes could now be imported as endnotes, and link addresses
kept. That is a follow-up on this importer, no longer a missing feature.)*

**48. Lists, block quotations and alignment blocks** *(Tier-5A; the three remaining cheap block
types. Also upgrades what #47 can do with a Word file)*
Three typed doc blocks on the plumbing #46 proved out:
`~~~ list` (`type="number"`, `start="3"`), `~~~ quote` (`source="…"`), and
`~~~ center` / `~~~ right` / `~~~ left`.
- **A parser change was needed, and it is the interesting part.** Inside a fence, lines are joined
  into a paragraph — right for prose, wrong for a list, where the first proof came out as *one*
  bullet containing every item. Lists and alignment blocks are **line-oriented**: one source line =
  one item / one line. New `manuscript.LINE_BLOCKS` drives that, mirrored in `doc_model.py` **and**
  `static/doc_model.js` (both parse *and* serialize) — the poem precedent, minus stanzas. Quotations
  stay prose: hard-wrapped lines join and a blank line starts a paragraph.
- `engine.py`: `_render_list_block` (hanging indent, so wrapped lines align under the item text, not
  back at the margin; bullet or running number), `_render_quote_block` (inset both sides, smaller,
  optional right-aligned italic source line), `_render_align_block` (alignment **only** — the style
  still owns size, face and leading, so an alignment block can't smuggle in ad-hoc formatting), plus
  `_ALIGN_MAP`; all dispatched from `_render_doc_block`.
- `epub.py`: real `<ul>`/`<ol>` (with `start`), `<blockquote>` + a `.quote-source` line, and
  `.align-center/-right/-left` divs, with CSS for each.
- `app.py` + `templates/editor.html`: `list` / `quote` / `align` preset sections through `DEFAULTS`,
  `parse_preset_form` and a new **Lists, quotations & alignment** fieldset (bullet, number format,
  indents, gaps, quote size/style, source style + alignment).
- `templates/manuscript_editor.html`: **List** and **Quote** toolbar buttons (via a shared
  `insertDocBlock`), three cheatsheet rows, and rich-mode CSS keyed off `data-btype` — including
  numbered lists via a `[data-attrs*='"type":"number"']` counter, so **no JS change was needed** for
  the WYSIWYG.
- **`manuscript.import_docx` now emits these blocks** instead of approximating: Word lists become
  `~~~ list` (bullets and numbers kept as separate runs), Quote styles become `~~~ quote`, and a
  centred paragraph that isn't a scene break becomes `~~~ center`. Two lines of the import summary's
  "not imported" half went away as a result.
Verified: 15 new `test_doc_model.py::test_blocks` checks (fidelity + stability at both smartquote
settings, one-item-per-line, `type`/`start` preserved, quotes staying prose, engine block order);
a **JS↔Python port-parity run** over the new corpus plus figures and poems (model *and*
serialization byte-identical); a rendered PDF proof looked at — hanging bullets, aligned numbers, an
inset quote with its italic source, centred sign lines; EPUB checked for `<ul>`/`<ol>`/`<blockquote>`
/`.quote-source`/align divs; the new preset fieldset round-tripping a real editor save; a `.docx`
end-to-end where the imported bullets, numbers and quotation all render; and a **live browser pass** —
rich mode shows bullets, counters, the quote rule and centred text, and pressing Enter in a list makes
a new item that serializes as its own line. All prior suites still pass.

**49. Links — `[text](target)`, clickable in both outputs** *(Tier-5B)*
Nothing emitted an `<a>`, so an *Also By* page couldn't send a reader anywhere — the gap with the
most direct commercial cost, and one a free competitor (Reedsy) already closes.
- **Targets are restricted on purpose**: `http(s)://`, `mailto:`, or an in-book `#anchor`
  (`manuscript.LINK_TARGET`). A permissive rule would silently turn `[sic](ibid)` in an existing
  manuscript into a link — the same backward-compatibility trap avoided for lists in #48. `\[`
  escapes a literal bracket.
- `manuscript.py`: `_inline` stashes link targets **before** the emphasis passes (a URL containing
  `_` or `*` would otherwise be eaten) and re-wraps them afterwards, so emphasis *inside* link text
  still works. New `chapter_anchors(chapter, idx)` — `#chapter-N` plus the title slug — lives here,
  not in the engine, because **both** builders need the same answer and neither should import the
  other; `epub.py` picks it up as its one project import (manuscript.py is stdlib-only too).
- `engine.py`: chapter openers plant `<a name="…"/>` destinations, so `#anchor` links resolve inside
  the PDF (verified as real GOTO links, not just text). Links are clickable but **unstyled in print**
  by default — colour and underline are screen idioms and a POD interior is black; a preset can turn
  the underline on.
- `epub.py`: `<a href>` passes through as valid XHTML; in-book `#anchor` targets are rewritten to the
  chapter *file* that holds them (`_ANCHORS` + `_resolve_anchors`), and link colour/underline come
  from the preset via the stylesheet.
- **Matter pages were quietly wrong and are now fixed.** `_matter_xhtml` rendered *raw author text*,
  so the ebook showed literal `**asterisks**` where the PDF (which runs the same text through
  `_ms_inline`) showed bold — and would have dropped every link on the Also By page. It now uses
  `_md_emph_to_html`, extended to handle links the same way `_inline` does.
- **Round-trip**: runs gained a `link` field across `doc_model.py`, `static/doc_model.js` **and**
  `static/wysiwyg.js` (which now renders real `<a>` elements and reads them back). `to_markdown`
  groups consecutive runs sharing a target, so `[**bold** link](url)` round-trips as *one* link.
  Found along the way: `doc_model.py` keeps its **own copy** of the escape layer, so `\[` had to be
  added there too — the JS↔Python parity run is what caught it.
Verified: 16 new `test_doc_model.py::test_links` checks (fidelity + stability, every target kind,
emphasis inside a link, underscores in a URL surviving, `[sic](ibid)` and `\[` staying literal,
chapter anchors); a JS↔Python parity run over a link corpus plus blocks, figures and poems; a
rendered PDF with real external **and** internal (GOTO) links; an EPUB where in-book links resolve to
`chapterNNN.xhtml` and the Also By page carries a live link; and a live browser pass — rich mode shows
`<a>` elements, editing link text round-trips, and a link split across bold/plain runs re-serializes
as one link, with no console errors.
**Known limit (pre-existing, now documented):** a link in a chapter's *first* paragraph is lost under
the drop-cap / raised-initial / small-caps-lead-in opening styles, because `_opening_para` re-sets
those first words as plain text via `_plain()`. The words survive; the link doesn't. Opening style
*None* keeps it.

**50. Endnotes — `[^label]` references and a Notes page** *(Tier-5A; the last text feature Vellum
and Atticus had that we didn't, bar footnotes)*
A reference `[^label]` sits in the sentence; its text is a paragraph `[^label]: …` anywhere in the
same chapter. Labels are the author's handle — **numbers are assigned at parse time**, in reading
order, restarting each chapter (the book convention), so the PDF and the EPUB can never disagree
about them. A **Notes** page is added after the last chapter automatically; there is nothing to
switch on.
- `manuscript.py`: `NOTE_REF_RE` / `NOTE_DEF_RE`; `_inline` turns a reference into a **neutral**
  `<note n=… id=…/>` marker; definitions are lifted out of the body by a *line-level* check (a run of
  definitions would otherwise be joined into one paragraph and swallow each other — the same trap as
  #48's lists, hit again here). `_number_notes` assigns numbers and attaches `chapter['notes']`;
  `_walk_block_texts` / `map_block_texts` are the new shared way to rewrite every markup string in a
  chapter, returning a **copy** because app.py parses once and builds both outputs from it.
- Each builder renders the marker its own way: `engine._apply_note_markers` → a linked
  `<super size=…>` (size set explicitly; ReportLab's default `<super>` keeps the body size);
  `epub._apply_note_markers` → `<sup>` linking to the Notes page, with an `id` so the note can link
  **back** to the sentence — the thing an ebook does that paper can't. A repeated citation gets the
  id only once, or the XHTML would carry a duplicate `id`.
- `engine._endnotes_page` / `epub._endnotes_xhtml`: entries grouped under chapter headings, hanging
  numbers, and manifest/spine/nav entries in the EPUB. Notes lead the back matter — they belong to
  the text in a way acknowledgments and author bios don't.
- **Superscripts survive the decorative chapter openings.** Drop-cap / raised-initial / small-caps
  openings re-set their first words as plain text (`_plain()`), which strips a `<super>` tag and
  would drop an endnote number to full size mid-sentence, reading as a typo. `_opening_para` now
  swaps the marker for a real superscript **character** first — with a per-face check, because Lora
  only carries ¹–⁴; a face without the glyph falls back to the plain digit rather than printing a
  .notdef box.
- **Round-trip needed no new model field**: a reference is literal text to `doc_model`, so it rides
  through as-is. But both ports needed the same line-level fix as the parser, or a run of
  definitions came back merged — caught by the engine-fidelity test, not by inspection.
Verified: 14 new `test_doc_model.py::test_notes` checks (fidelity + stability, definitions leaving
the body, repeated labels keeping one number, per-chapter restart, orphan definitions kept, a
reference with no text still numbered, and no `notes` key on a manuscript without any); a JS↔Python
parity run over a notes corpus plus links, blocks, figures and poems; a rendered PDF proof looked at
(superscripts in body *and* opening paragraphs, Notes page grouped by chapter with italics intact);
an EPUB with forward and back links, unique ids, and every XHTML document checked to be well-formed;
the new preset fieldset round-tripping a real editor save. All prior suites still pass.
**Not footnotes.** Bottom-of-page notes remain the hard, deferred case — breakable note areas
anchored to a reference line is real `BookDoc` work, and the Tier-4 note's sequencing (endnotes
first, footnotes last) still holds.

**51. Element vocabulary — six more matter sections, and unnumbered chapters** *(Tier-5F)*
Two things, one of which is a refactor that had to come first.
- **`matter.py` — one table instead of a dozen wiring sites.** Every named section was hand-wired in
  ~19 places (the compose form, the project form, `result.html`'s hidden fields, five meta dicts in
  `app.py`, project load/save, the engine's page list, the EPUB's manifest / spine / nav / writer).
  Adding six sections that way is ~114 edits with a silent failure mode for each one missed. The new
  `matter.SECTIONS` table (key, label, front/back, page style, EPUB id + href, form hint) is now the
  single definition: `app.py` builds forms and meta from it, `engine.py` lays the pages out from it,
  `epub.py` manifests them from it. **Adding a section is one row.** Stdlib-only and importing nothing
  from the project, so both builders can use it without dragging anything in. The compose and project
  forms are Jinja loops over the table; `result.html`'s hidden fields likewise.
- **Six new sections:** *foreword*, *preface*, *introduction* (front); *afterword*, *bibliography*,
  *blurbs* (back). Blurbs reuse the epigraph setting — quotes with an em-dash source line — which
  needed only a heading branch there, no new page style.
- **`#* Prologue` — an unnumbered chapter.** A prologue isn't a matter page, it's a chapter that takes
  no number *and doesn't consume one*: the chapter after it is still Chapter One. `#` requires a space
  after it, so `#*` was previously an ordinary paragraph — nothing existing changes meaning. New
  `manuscript.chapter_numbers()` returns the displayed number (or `None`) per chapter, and **both**
  builders read it, because position and number are now different things: position still identifies a
  chapter (its file, its anchors, its notes) while the number is what the reader sees.
- Round-trip: the chapter block gained an `unnumbered` flag in `doc_model.py` and `static/doc_model.js`,
  carried **only when set** so an existing chapter model compares equal as before.
Verified: 14 new `test_doc_model.py::test_vocabulary` checks (fidelity + stability, the numbering
skipping unnumbered chapters while anchors stay positional, an unnumbered chapter still taking a
byline, a plain chapter model unchanged, and the table's own invariants — unique keys, unique EPUB
ids and hrefs, `present()` ordering and emptiness, `{author}` filling into a heading); a JS↔Python
parity run over a vocabulary corpus plus notes, links, blocks, figures and poems; and a full compose
where the PDF shows Foreword → Prologue → **Chapter 1** → Afterword → Bibliography → Praise in order
with the prologue taking no number, and the EPUB carries a document per section. All prior suites pass.

**52. EPUB preflight — check the file we just wrote** *(Tier-5D; the gap where paid tools quietly won)*
Vellum ships "EPUB 3 validated" and ACE-approved accessible output. We shipped an EPUB nobody had
ever checked, with no accessibility metadata at all.
- `epub.check(path)` opens the **built file** and reports eleven things a reader or a shop would
  object to: the container layout (mimetype first and stored), the package document, manifest↔zip
  agreement **in both directions** (missing files *and* undeclared strays), the spine, a declared
  navigation document, every content document parsing as XHTML, alt text on every image, every
  in-book link resolving (file *and* fragment), the cover being declared both the modern and the
  legacy way, and accessibility metadata. Stdlib-only, like the rest of `epub.py`.
- **It checks the artefact, not the intent.** A self-check that reads back the builder's own data
  structures can only confirm the builder agrees with itself; opening the zip is what catches a
  builder mistake. That distinction is the whole value of the feature.
- `epub._a11y_meta`: `schema:accessMode`, `accessModeSufficient`, `accessibilityFeature`
  (structural navigation, table of contents, reading order, plus alternative text when the book has
  images), `accessibilityHazard: none`, and a summary. A reflowable book generated from a semantic
  model genuinely *is* accessible — the claim just has to be stated, and an EPUB with no such
  metadata reads to a checker as an unknown quantity rather than a good one. Now required in
  practice by the European Accessibility Act.
- `app.py`: `_epub_preflight()` + an optional `_run_epubcheck()` that uses the reference validator
  when `EPUBCHECK_JAR` (or an `epubcheck.jar` beside the app) and a JRE are present, and is silently
  skipped otherwise. `templates/result.html`: a second preflight card, same markup as the print one.
- New `test_epub.py`: builds one good EPUB, asserts it passes everything, then **breaks it eleven
  ways** — removes the mimetype, deletes a manifested file, adds an undeclared one, corrupts an
  XHTML document, empties an alt attribute, points a link at a missing file, points one at a missing
  fragment, strips the nav property, breaks a spine idref, strips the accessibility metadata — and
  asserts the matching check fails each time. A validator that cannot fail is worthless, so the
  negative cases are the point of the file.
Verified: the eleven negative cases above, a real compose showing the card reading **All clear**
across eight applicable checks, and the optional epubcheck path degrading to nothing on a machine
with no Java. All prior suites still pass.

**53. Ebook device preview — the same book, reflowed** *(Tier-5D; closes the preview half of the gap)*
Both existing previews (#10 style, #39 book) rasterise the **PDF**. An ebook has no fixed page, so a
page image is the one thing that *can't* show you what a reader sees — and we shipped an EPUB nobody
could look at before building it. Vellum previews on Kindle/iPad/iPhone, Atticus on eight devices.
- `app.py`: `/generate/epub-preview` **builds the real EPUB to a temp file and reads the documents
  back out of it**, in spine order, rather than re-rendering chapters for the preview. The zip is the
  artefact readers get, so previewing anything else previews a guess — the same reasoning as #52's
  "check the artefact, not the intent". Note markers, figures, links and matter pages are therefore
  exactly what shipped. Images are inlined as data URIs, since an iframe built from a string can't
  fetch out of a zip.
- **Refactor first:** the 80-line form-reading half of `/generate/preview` became
  `_book_from_compose_form()`, shared by both previews, with a `_PreviewError` for messages meant
  for the user rather than the log. Neither route persists anything.
- `templates/generate.html`: a **Preview the ebook** button and an overlay with Phone / E-reader /
  Tablet tabs (375×667, 500×690, 768×1024 CSS px), rendering into a **sandboxed** iframe — no
  scripts, no navigation — with the EPUB's own stylesheet, so the preview inherits the real design.
  Switching device rewraps the text, which is the whole point.
Verified live in a browser: the overlay opens, all three tabs render, switching to Phone visibly
reflows the prose to the narrower measure, the dimensions readout tracks the device, and the console
is clean. Also verified the route returns the documents, stylesheet and truncation counts for a book
with lists, endnotes and back matter, and that the refactored page-image preview still behaves
(including both of its error paths). All prior suites pass.
**Note for the next person:** the JS lives inside a Jinja template, so a `\n` escape in a JS string
literal does not survive — it arrives as a real line break and the script dies with a
`SyntaxError` that only shows in the browser console. This script therefore contains no backslash
escapes at all. Worth remembering before adding any.

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

### ✓ Discoverability & UX pass — shipped

Five changes from a walkthrough review aimed at first impressions and everyday flow
(commits `321a2ed`, `5205418`, `696feb8`, `72b2413`, `a3382f6` on `master`; shipped in v1.1.0).

**38. Favicon + share metadata + OG card** *(discoverability; base template + one route, no engine change)*
`app.py` (`/favicon.ico` serves the bundled `app.ico`) · `typeset-studio.spec` (bundles `app.ico`
into the frozen build's data files so the route works when installed, not just as the exe icon) ·
`templates/base.html` (`<meta description>`, favicon links, `theme-color`, and Open Graph /
Twitter `summary_large_image` tags — `og:title` inherits each page's `<title>` via Jinja block
references, so a shared `/covers` link reads "Covers · Typeset Studio") · `static/og-typeset-studio.jpg`
(1200×630 share card drawn with Pillow using the bundled Book fonts). Tabs/bookmarks now get an icon
and shared links render a card. Verified live: `/favicon.ico` 200, OG image 200, per-page `og:title`
on all five pages.

**39. Book preview on "Set a book"** *(the compose page's flagship UX gap; new route + template, no engine change)*
`app.py` (`POST /generate/preview`: mirrors `generate()`'s form reading + meta but **persists nothing** —
uploads and the built PDF go to temp files cleaned up in `finally`. Typesets only the first
`PREVIEW_MAX_CHAPTERS` (2) and rasterises the first `PREVIEW_MAX_PAGES` (8) via PyMuPDF, so a 400-page
manuscript still previews in ~a second; returns how much of the book was shown) · `templates/generate.html`
("Preview first pages" button + theme-aware overlay, dismissable via Close / backdrop / Escape). Unlike
the #10 style preview (fixed sample), this renders the user's **actual** manuscript. Verified live:
sample truncates 3→2 chapters, chapter opener renders with the real style; paste / upload / sample and
the error paths all correct.

**40. Section navigation on the compose form** *(the form was one long single scroll; template-only)*
`templates/generate.html`: a sticky section rail (Style → Manuscript → Cover → Title page → Front matter
→ Back matter → Output) beside the form on wide screens, collapsing to a sticky horizontal bar ≤860px.
An IntersectionObserver **scroll-spy** highlights the current section; smooth scroll gated on
`prefers-reduced-motion`; each fieldset gets an `id` + `scroll-margin-top` so jumps clear the sticky nav.
Verified live: click-to-jump + scroll-spy on desktop.

**41. Project thumbnails + filter** *(text-only cards were hard to tell apart — several "Untitled draft"s)*
`app.py` (`/project/<pid>/thumb.png` rasterises **page 1 of a project's `last_pdf`** — its cover, or the
first front-matter page — cached to `out/_project_thumbs`, keyed by the PDF's **mtime** so a regenerate
refreshes it; `project_last_pdf_path()` helper; the `/projects` route flags `has_thumb` per project.
Reuses the #33 cover-thumb caching pattern) · `templates/projects.html` (portrait thumbnail per card,
with a serif-initial placeholder tile for never-built drafts; a client-side filter box narrows the grid
by title / author / style with a live count + a "no matches" message). Verified live: real covers render,
"kins" → 1 of 7 shown, no-match message shows.

**42. First-run empty-state guidance** *(new users had no sense of the flow; shared component + three templates)*
`templates/base.html` (shared `.firstrun` panel component) · `templates/projects.html` (the one page not
seeded with defaults, so genuinely empty on first run: a "Set your first book" panel spelling out the
draft / Set-a-book / Save-as-project flow with Set-a-book + Browse-styles CTAs) · `templates/index.html`
+ `templates/covers.html` (compact "Create your first …" panels shown only if a user deletes every seeded
template). Verified: empty Projects seen live (project JSONs temporarily moved aside, then restored);
all three empty branches render.

**Build / version tooling.** Bumped to **1.1.0** in `typeset-studio.iss` — the single source of truth,
driving `AppVersion` and the installer's `OutputBaseFilename`. `make-installer.bat` now parses that
version from the `.iss` (via `findstr`) instead of hardcoding it in its status message, so the message
never goes stale on a version bump.

*Not done — website OG card:* the public site repo already had a stronger, on-brand card (gold accent +
`ashforgestudio.com` domain), so it was left as-is; the new card above powers only the app's own local OG tags.

### ◻ Tier 4 — planned / backlog

*(Cover Studio Tiers 1–3 all shipped: features #16 designed templates + editor, #17 font
library, #18 full print wrap; plus #22 wrap auto page-count, #24 per-retailer wrap presets,
and #25 back-cover image. Cover Studio backlog clear.)*

**New document types — reach more writers with the same engine** *(medium; extends the book
model rather than forking it)*

Deliberately **not** screenplays/scripts. A screenplay has exactly one correct format (Courier,
sluglines, centered cues, indented dialogue, `(MORE)`/`(CONT'D)`, page ≈ minute) — it *inverts*
the app's "preset owns typography" bet (no preset variety to offer), needs a different block
model + paginator (effectively a second engine sharing only "emits a PDF via ReportLab"), and is
already served by Fountain + free converters. It would be a product pivot to a different
audience, not an extension. Same reasoning rules out stage plays. The high-value directions are
the ones that reuse the existing book model, front matter, presets, cover wrap, and the
doc_model / WYSIWYG round-trip:

- **Poetry collections — SHIPPED (feature #30).** Line-preserving `~~~ poem` blocks with
  stanza spacing, a poem-title style, and a hanging runover indent; round-trips through
  `doc_model` + the WYSIWYG. v1 follow-ups noted in #30 (no `.docx` poem import; presets fall
  back to `DEFAULTS`; EPUB runover is per-stanza).

- **Anthologies / essay collections — SHIPPED (feature #31).** Per-piece byline
  (`# Title | Author`, italic under the title) + a collection-level Contributors back-matter page.
  **Deferred:** per-piece epigraph/attribution (the third original bullet) — a rarer need that
  adds heading-parse surface; left for a follow-up.

- **Nonfiction structure — footnotes + simple figures** *(the remaining "new document type")*.
  **Endnotes — SHIPPED (feature #50)**; **figures — SHIPPED (feature #46)**.
  **Footnotes** are hard — breakable notes anchored to their reference line, a bottom-of-page
  note area, and numbering that resets per chapter; that's real paginator work in `engine.py`.
  **Figures**: an image block with caption + placement. Broadens the book audience meaningfully
  but sequence it after the two cheaper wins above. *(Superseded in detail by **Tier 5A** below —
  the paid-app scan reached the same conclusion from the other direction, and endnotes/footnotes/
  figures are specced there alongside the other missing block types.)*

These grow *what* the app does; per the strategy note below, **packaging still grows *who* uses
it**, and remains the bigger lever for a free+donate app. Rank poetry ≈ anthologies (cheap,
on-philosophy) above nonfiction (heavier), and all below distribution.

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

- **Phase A — SHIPPED (features #19–#21, #23):** a project-integrated Markdown authoring
  surface with a formatting toolbar, live word/chapter counts, debounced autosave, a page
  preview, an outline sidebar (chapters, parts, subheads, and scenes) with jump-to navigation,
  and find/replace. Phase-A polish complete.
- **Phase B — SHIPPED as styled-Markdown highlighting (feature #26):** the dependency-free
  path was chosen (see decision below). The writing surface now paints live Markdown styling
  (coloured/bold headings, bold/italic, styled scene breaks/fences) instead of a raw textarea,
  while the textarea stays the source of truth.
- **Phase C — SHIPPED as a hand-rolled WYSIWYG (PR #24, 2026-07):** the true hide-the-markup
  rich mode was built **without** a vendored framework or build step, so the dependency-free
  convention held. A plain-JS `contenteditable` surface (`static/wysiwyg.js`) sits over a
  Markdown⇄document-model round-trip layer (`doc_model.py` + a byte-identical JS port
  `static/doc_model.js`), toggled beside the Phase-B Markdown view. The textarea stays the source
  of truth; rich mode is a view that syncs into it, reusing all autosave / preview / outline /
  find wiring. `manuscript.py` gained backward-compatible backslash escapes (`\*` `\_` `\\`,
  line-start `\#` `\~~~` `\===`) so literal markup survives. Storage stays raw Markdown —
  byte-identical whether edited in Markdown or rich mode. Validated by the serialization spike
  below plus 66 headless-Chrome + Python round-trip checks.

**Decision (2026-07), since superseded by Phase C.** Phase B stayed dependency-free (no bundled
JS / build step; offline, no-CDN, tiny-inline-JS convention preserved). The key insight that
unblocked Phase C: a *true* WYSIWYG did **not** require the feared vendored framework / Node
build-step reversal — a hand-rolled `contenteditable` over a lossless round-trip layer keeps the
convention intact. The serialization spike (below) was the gate: it round-tripped cleanly, so the
build was justified.

**Entry point if revisited — a serialization spike (do this before building anything).** The
riskiest part of a real WYSIWYG is lossless round-tripping, not the editor UI. So the first
step is a throwaway script: Markdown → a ProseMirror/TipTap document model → back to Markdown,
run over `sample/sample.md` and any real manuscripts, asserting `parse → serialize → parse` is
stable (especially the custom `~~~ letter from="…"` doc-blocks, epigraph/attribution lines, and
smart-quote interplay). A few hours; it surfaces the real pain and tells us whether the full
build (schema, two-way serialization, rewired toolbar/outline/find, Node bundling) is worth it.
Only commit to the heavy build if the spike round-trips cleanly.

**New obligation once people author in-app:** autosave + backups + no data loss — a higher
bar than a tool that only transforms files the user already has stored elsewhere. Keep
`.docx` import as the on-ramp for existing manuscripts.

### ◻ Tier 5 — competitive gap backlog (from the paid-app scan, 2026-07-26)

Source: a feature scan of **Vellum** ($199/$249, macOS-only), **Atticus** ($147, web),
**Reedsy Studio** (free), **Jutoh**, **Kindle Create**, checked against this codebase. Only
gaps that are *real* (verified absent in the source, not just unmentioned in this doc) and
*on-philosophy* (the preset still owns typography; no freeform canvas) are listed. Ranked
A → D by value-per-effort; D is the explicit "don't build" list.

Context on where we already lead, so it isn't re-litigated: the five typed epistolary blocks
(#4) beat Vellum's two (Text Conversation, Written Note); the eight cover **design families**
+ print wrap (#33/#37/#18) have no equivalent in either — Vellum and Atticus do interiors only
and expect a cover from elsewhere; the continuity checker (#13) is unique; and the whole thing
is free, local, and offline.

---

**A. In-chapter content features — the biggest cluster, and the "is this a real formatter?" bar**

Vellum ships 16 "text features"; our block model has six (`para`, `subhead`, `scene`,
`doc_block` ×5 types, `poem`). Each item below is a new block type, so each costs the same
seven-file round: `manuscript.py` (parse) · `engine.py` (render) · `epub.py` (XHTML + CSS) ·
`doc_model.py` **and** `static/doc_model.js` (kept byte-identical) · `static/wysiwyg.js`
(render/read) · `templates/manuscript_editor.html` (toolbar + cheatsheet) ·
`test_doc_model.py` (fidelity + stability). Presets gain a section in `app.DEFAULTS` +
`parse_preset_form` + `editor.html` where the look should vary per style.

- ~~**Images / figures — the single biggest hole.**~~ — **SHIPPED (feature #46):** a
  `~~~ figure src="…"` block (caption = the block's content), inline or `full="yes"` for its own
  page, a shared library + Figures manager, a preset `figure` section, and `<figure>` output in the
  EPUB. Word images now import into it too — **SHIPPED (feature #47)**.
- ~~**Lists (bulleted / numbered).**~~ — **SHIPPED (feature #48)** as `~~~ list`, line-oriented
  (one item per line), with a preset `list` section and real `<ul>`/`<ol>` in the EPUB. Note the
  fenced form was chosen over Markdown `- ` / `1. ` on purpose: line-start parsing would silently
  reinterpret existing manuscripts whose paragraphs begin with a dash.
- ~~**Block quotation.**~~ — **SHIPPED (feature #48)** as `~~~ quote source="…"`, inset both sides,
  smaller, with an optional source line.
- ~~**Alignment block**~~ — **SHIPPED (feature #48)** as `~~~ center` / `~~~ right` / `~~~ left`.
- ~~**Endnotes.**~~ — **SHIPPED (feature #50)** as `[^label]` + `[^label]: text`, numbered per
  chapter, with a Notes back-matter page and, in the ebook, a link each way.
- **Footnotes.** Still the hard one (breakable notes anchored to the reference line, a
  bottom-of-page note area, per-chapter renumbering = real `BookDoc` work). Unchanged
  recommendation: last.
- **Tables.** Nonfiction only, and `_render_doc_block`'s `box` frame already proves the
  `Table`-flowable split behaviour. Low priority for the fiction audience; note that `.docx`
  table text is currently dropped entirely.

**B. Links — ~~the biggest EPUB-specific gap~~ SHIPPED (feature #49)**

~~Nothing in `epub.py` emits an `<a>`, so an ebook whose *Also By* and *About the Author*
pages aren't clickable was commercially weaker than a free competitor's output.~~ **SHIPPED
(feature #49):** `[text](url)` inline, web / `mailto:` / in-book `#anchor` targets, clickable in
both outputs, print-safe by default. **Remaining:** Vellum's **Store Link** (a "buy from your
preferred retailer" page) is a different feature — it needs the per-retailer ebook builds in
section D, not link syntax.

**C. Import fidelity — the gap most likely to read as "the tool is broken"**

~~The importer dropped images, tables, hyperlink text, lists and quotes on the floor.~~ —
**SHIPPED (feature #47):** images become figures, hyperlink text survives, tables become set-apart
blocks, and an import summary reports both what came across and what didn't. **#48 then upgraded
it further:** Word lists, Quote styles and centred paragraphs now import as real `list` / `quote` /
`center` blocks rather than approximations. **Remaining**, each blocked on a Tier-5A block type
rather than on the importer: **tables as real tables**. **Word footnotes and link addresses are no
longer blocked** — #49 and #50 built the targets, so importing them is now just importer work. Also
still open from #30: no `.docx` **poem** import.

**D. Output correctness / validation — paid tools quietly win here**

- ~~**EPUB validation + accessibility.**~~ — **SHIPPED (feature #52):** an EPUB preflight card
  beside the print one, eleven structural checks run against the built file, accessibility metadata
  in the OPF, and optional real `epubcheck` when a jar and a JRE are present. **Remaining:** no
  **EPUB 2 fallback** — worth its own look only if a retailer actually refuses EPUB 3, which in 2026
  is rare.
- ~~**Designed covers in EPUB.**~~ — **SHIPPED (feature #43)**, the first Tier-5 item: page 1 of
  the designed cover is rasterised to a 2560px JPEG and handed to `epub.py` as the cover image, and
  the OPF now also carries the legacy `<meta name="cover">` pointer that Kindle tooling wants.
- **PDF/X-1a.** Vellum advertises press-standard PDF/X-1a; we emit stock RGB ReportLab PDF. KDP
  accepts ours, IngramSpark is fussier. Worth a spike on what ReportLab can actually assert
  (output intent, no transparency, embedded profile) before promising it.
- ~~**Ebook device preview.**~~ — **SHIPPED (feature #53):** the built EPUB's own documents and
  stylesheet, reflowed in a sandboxed iframe at phone / e-reader / tablet widths.
- **Spread balancing.** `engine.py:1526` sets `allowWidows=0, allowOrphans=0`, so widows/orphans
  are handled; Vellum additionally balances **facing-page depth**. Genuinely hard in ReportLab —
  note it, don't schedule it.

**E. Type & design assets — best perceived-quality-per-hour in the whole list**

- ~~**One typeface for nine styles.**~~ — **SHIPPED (feature #44):** six OFL families (EB Garamond,
  Vollkorn, Alegreya, Crimson Pro, Lora, Spectral) bundled and the presets repointed, one considered
  face per genre style, with sizes re-set by characters-per-line. ~4.8 MB added.
- **Ornament / flourish library.** `SceneBreak` supports an image ornament (#9) but the repo
  ships **zero artwork**, so every book gets `* * *` or an em dash. Vellum ships flourishes,
  custom ornaments, custom backgrounds, full-bleed interior pages and chapter-heading images. A
  dozen bundled public-domain/CC0 ornaments + a picker in `editor.html` is data-plus-template.
- **Chapter-heading art / full-bleed interior pages.** The heavier half of the same idea; after
  the figure block exists (A), a chapter-opener image is mostly a preset field.

**F. Element vocabulary — cheap breadth, especially for nonfiction**

~~We support ten named sections; Vellum adds foreword, preface, introduction, afterword,
bibliography, blurbs — plus uncounted chapters, which prologues and epilogues have to fake.~~ —
**SHIPPED (feature #51):** six new sections (foreword, preface, introduction, afterword,
bibliography, blurbs) and `#*` unnumbered chapters, which is what a prologue or epilogue actually
is. **Remaining:** *full-page image* is already covered by `~~~ figure full="yes"` (#46), and
*uncategorized matter* — a free-form titled page — is the only real gap left, worth adding only if
someone asks for it.

**G. Editions & scale — real, but heavier and lower-frequency**

- **Hardcover case-wrap / dust jacket.** `build_cover_wrap` is paperback-only; hardcover needs
  hinge gaps, board overhang and wrap-around bleed. A natural extension of `WRAP_RETAILERS` (#24).
- **Large-print edition** — Vellum ships it as a one-click variant. For us it is nearly free: a
  derived preset (larger size/leading, wider margins, fewer words per line) generated from any
  existing style. Possibly the cheapest item in G.
- **Trim-size presets** — Vellum offers 24 named trims; our trim is free-entry. A datalist of
  standard KDP/IngramSpark trims in `editor.html` is minutes of work and prevents typos that
  fail upload.
- **Box sets / omnibus** — combine several projects into one book with merged front matter and a
  unified TOC (Vellum's "Volume" element, Atticus's bundles). Needs a multi-manuscript build path;
  defer.
- **Batch regenerate** — Vellum regenerates every edition with one command; we regenerate one
  project at a time. A "rebuild all" on `/projects` is small if wanted.

**H. Explicitly NOT doing** *(recorded so the scan doesn't get re-run into the same answers)*

- **Index generation** (InDesign-class). Enormous, and the audience overlaps almost zero with
  ours.
- **Collaboration / beta-reader sharing / cloud sync** (Atticus). Requires becoming a hosted
  multi-user service — see the hosting note in the strategy section; it is a different product.
- **Writing goals / sprints / session analytics** (Atticus, Scrivener). Plausible in the editor
  someday, but it competes with drafting tools rather than formatting ones, and the editor's own
  open obligation (backups / no data loss) outranks it.
- **Freeform cover canvas** — already ruled out in the cover strategy note below; restated here
  because Book Brush-style tools show up in every comparison.

**Suggested order.** ~~Designed-cover-in-EPUB (D)~~ #43 → ~~bundled typefaces (E)~~ #44 →
~~figures/images incl. `.docx` (A + C)~~ #46/#47 → ~~lists / block quote / alignment (A)~~ #48 →
~~links (B)~~ #49 → ~~endnotes (A)~~ #50 → ~~element vocabulary (F)~~ #51 →
~~EPUB preflight (D)~~ #52 → ~~device preview (D)~~ #53 →
**large print + trim presets (G)** ← next → endnotes (A) → EPUB preflight + device preview (D) →
large print + trim presets (G) → footnotes (A, last). Note this whole tier is *feature* work: per the strategy note below, **packaging still
grows who uses the app more than any of it**.

### ◻ Strategy notes (context for prioritising, not committed work)

**Distribution / packaging — the real reach lever (free + donate model).** The app is
released free with an optional donate button, not sold. In that model "value" = reach and
goodwill, and the dominant adoption barrier is **not** any editor feature — it's that this is a
local Flask app you must install Python and run a server to use. So if broader adoption / more
potential donors is ever a goal, **packaging beats polish**: a one-click installer (e.g.
PyInstaller/briefcase bundling Python + a launcher) or a hosted version would move the needle
far more than WYSIWYG or more presets. The donation pitch is already strong — the app replaces
things authors otherwise pay for (typesetting, cover design, formatting). Rank for reach:
**distribution/packaging > more genre presets & polish > WYSIWYG.**

*Packaging plan: (1) data-dir refactor — DONE; (2) PyInstaller onedir spec + test build —
DONE; (3) Inno Setup installer script — DONE (compile on Windows); (4) polish: app icon +
quiet frozen logging — DONE; (5) pywebview native window — DONE (window itself needs an
interactive Windows check).*

**Cross-platform targets (Linux / macOS / Android) — backlog, not committed.** The Windows
packaging above is done; other OSes were assessed 2026-07-17. Key finding: the app is already
mostly portable — the typesetting engine (ReportLab / python-docx / pyphen) is **pure Python**,
`app.py:_user_data_root()` **already branches** for Windows / macOS (`~/Library/Application
Support`) / Linux (`XDG_DATA_HOME`), and every `requirements.txt` dep has Mac/Linux wheels. So
"porting" is about the *shell* (native window), *packaging*, and — for Android only — *native C
deps*, not the app logic.

- **Linux — LOW (~1 day).** Data dir already handled. `pywebview` needs a system WebKit backend
  (webkit2gtk + PyGObject, or Qt/QtWebEngine); if absent, the existing **browser fallback** runs
  anyway. Build with PyInstaller on Linux → tarball / AppImage / `.deb` (replaces the Windows-only
  Inno Setup step). Mostly "pick a backend + package + test," no code rewrite.
- **macOS — LOW–MEDIUM (~2–3 days).** Data dir already handled. `pywebview` uses native WKWebView
  (no runtime to bundle). PyInstaller builds a `.app` → `.dmg`, but **must be built on a Mac** (no
  cross-compile). Real friction = **codesigning + notarization** (Apple Developer $99/yr) to clear
  Gatekeeper — the Mac analogue of the Windows SmartScreen/signing note. Code work ≈ zero.
- **Android — HIGH (weeks); a re-shell, not a repackage.** The desktop model breaks: `pywebview`
  has **no Android backend**, PyInstaller/Inno don't target Android (use BeeWare/Briefcase or
  Kivy + python-for-android, with an Android WebView pointed at an in-process localhost Flask
  server). Biggest risk is the **native C deps** — **PyMuPDF** (the live-preview rasterizer =
  MuPDF) and Pillow need Android/ARM builds via p4a recipes; PyMuPDF may force dropping live
  preview there. File I/O also moves from `%APPDATA%`/file dialogs to app-private storage + the
  Storage Access Framework (share/save intents). The pure-Python engine carries over; everything
  else is new.
- **The mobile shortcut = host it (ties to the reach lever above).** Deploying the same Flask app
  to a server runs it in the browser on **Android / iOS / Chromebook / any desktop** with **zero
  native porting** and 100% code reuse — dramatically less work than a native Android build. Cost:
  it becomes a **multi-user service** (auth, per-user data isolation, resource/timeout limits on
  the CPU-heavy PDF builds, storage, hosting bill) — a real operational commitment, but far below
  a native Android app.

  *Recommended sequence if pursued: Linux + macOS desktop builds first (cheap — code already
  anticipates them); for mobile, host rather than build native; reserve a native Android app only
  if offline / app-store presence is specifically needed. A quick audit for lingering Windows-only
  assumptions (paths, `.bat` launchers) would de-risk the Linux/Mac builds.*

**Step 5 shipped** (`app.py`, `requirements.txt`, `.spec`): the packaged app opens in a native
desktop window (pywebview / Edge WebView2) instead of a browser tab; closing it quits. Entry
point serves Flask on a **free port** (`_free_port`, falls back off 5050 if busy) in a daemon
thread, then `webview.start()` on the main thread — with a **browser fallback** if the window
can't initialise, so a webview failure never bricks the app. `_want_window()` gates it: on when
frozen, off in dev (opt in with `TS_WINDOW=1`; `TS_NO_WINDOW=1` forces the browser — used to
smoke-test the frozen server path). `.spec` collects `webview` data/submodules; `pywebview` added
to `requirements.txt` (browser fallback if absent). Verified here: decision logic, and a frozen
build that bundles the WebView2 backend (`Microsoft.Web.WebView2.Core.dll`) + `clr_loader` with
no errors (~97 MB). The **window rendering itself needs an interactive run on Windows** — can't
drive a GUI window here. Once confirmed, flip the `.spec` to `console=False` for a windowed
(no-console) app.

**Step 4 polish shipped** (`app.ico`, `app.py`, `.spec`, `.iss`): a brand `app.ico`
(navy + gold serif "T" in Book-Bold, echoing the cover frame; multi-size 16–256) wired into the
`.spec` (`icon='app.ico'`) and the installer (`SetupIconFile`) — rebuild confirmed PyInstaller
embeds it ("Copying icon to EXE"). Logging drops to WARNING when frozen (DEBUG in dev), so the
packaged console stays quiet while errors still surface (verified: root level 10 dev / 30
frozen). Replace `app.ico` with a custom icon anytime — the wiring stays.

**Step 3 written** (`typeset-studio.iss`, `make-installer.bat`): Inno Setup 6 script that wraps
`dist\Typeset Studio\` into `TypesetStudio-Setup-<ver>.exe` — **per-user install**
(`PrivilegesRequired=lowest`, no UAC), Start-menu shortcut, optional desktop shortcut, and an
uninstaller. User data in `%APPDATA%\Typeset Studio` is deliberately **not** removed on
uninstall (never deletes someone's books). Stable `AppId` GUID for clean upgrades. Build order:
`build.bat` → `make-installer.bat` (finds `ISCC.exe`; `dist_installer/` gitignored). Not
compiled here — Inno Setup isn't installed in this environment, so producing the actual
`Setup.exe` must be done on Windows (`make-installer.bat` after installing Inno Setup 6).
PyInstaller already bundles the VC++ runtime DLLs, so no separate redistributable is needed.

**Step 2 shipped** (`typeset-studio.spec`, `build.bat`, `requirements-build.txt`): onedir
PyInstaller spec bundling `templates`/`sample`/default `presets`/`covers`/`fonts` at their
resource paths, `collect_data_files` for **pyphen** (hyphenation dicts) and **reportlab**, and
`excludes=['anthropic','tkinter']` (anthropic is a lazy import → droppable). Built and
**smoke-tested the actual .exe**: with `%APPDATA%` redirected to a temp dir it served `/`,
`/covers`, `/fonts` and completed a `POST /cover/preview` PDF build (exercising reportlab +
PyMuPDF + pyphen), and first-run seeding copied the 9 presets in. ~91 MB onedir, no missing-
module warnings, debug/reloader off when frozen. `build/` + `dist/` gitignored; the `.spec` is
tracked. Building/running must be done on Windows (can't drive a GUI from CI here).

**Step 1 shipped** (`app.py`): a `resource_path()` helper resolves
read-only bundled assets (`templates/`, `sample/`, default `presets`/`covers`/`fonts`) via
`sys._MEIPASS` when frozen; a `_user_data_root()` puts writable data (`out`, `uploads`,
`projects`, and the **editable** `presets`/`covers`/`fonts`) under `%APPDATA%\Typeset Studio`
when frozen, or the repo folder in dev (unchanged); `_seed_defaults()` copies bundled defaults
into the user dir on first run; `engine.FONT_DIR` is pointed at the writable font library; the
entry point disables Flask debug/reloader when `IS_FROZEN`. Verified via a simulated-frozen run
(seeding + a full PDF build against `%APPDATA%`) and an unchanged dev run. Remaining: a free
**code-signing** cert avoids the SmartScreen "unknown publisher" warning (skippable at first);
consider making the `anthropic` dep a lazy import to slim the bundle.

**Cover customization — enrich the template, do NOT build a freeform design studio.** A full
in-app graphic editor (layers, shapes, drag-anything — a mini Canva via a vendored Fabric.js /
Konva.js) is explicitly **not** the direction. It fights the app's core value the same way a
Word-style editor would fight the interior engine: the cover system is good *because* it is
constrained and opinionated (pick a genre house style, fill in text → a professional cover). A
blank canvas hands non-designer authors the responsibility for good design and mostly produces
worse covers — at enormous cost (building a vector editor; a bigger dependency/build-step
reversal than the WYSIWYG one). The high-value, on-philosophy path is more *parametric* power:
- ~~layout archetypes beyond centred-classic~~ — **SHIPPED (feature #32):** a template `layout`
  key (`centered`/`top`/`bottom`/`band`);
- ~~background options~~ — **SHIPPED (feature #32):** `background` image (cover-fit) + vignette +
  colour overlay, plus a translucent title `panel`;
- ~~a few positioned image/emblem "slots"~~ — **SHIPPED (feature #32):** `emblems` (≤2 fixed slots).
These extended the existing `covers/*.json` renderer incrementally, keeping "good by default."

**Update (post-#32): the feedback was "different *designs*", not more recolors.** The enrichment
knobs above still skinned **one** hardcoded composition, so covers read as variations of a single
framed look. The on-philosophy answer is **design families** — a small, curated set of distinct
front-cover *renderers* selected by a `design` key — not a freeform canvas. **SHIPPED as feature
#33:** the dispatch mechanism (`_paint_cover_front` / `_COVER_DESIGNS`, `classic-frame` default =
byte-identical) + a first contrasting family, **`photographic`** (full-bleed art, no frame, large
lower title over a foot scrim). This is still constrained + opinionated (pick a family, fill in text
→ a professional cover); it just widens the *vocabulary* of looks rather than handing over a blank
canvas. Remaining directions, ranked:
- **Design-gallery picker — SHIPPED (feature #34).** The per-book template `<select>` (Generate +
  `project_edit`) is now a **thumbnail gallery** of radio tiles, plus real thumbnails on the `/covers`
  management cards, so authors *see* the families × palettes before choosing.
- **More design families — SHIPPED (feature #33):** `typographic`, `geometric` (color-block), and
  `vintage` (pulp) joined `photographic`, so five families now ship. Each is one renderer in
  `_COVER_DESIGNS`; JSON still tunes color/font within it. Further families are cheap to add the same way.
- **Per-field editor controls** for the `photo`/`typo`/`blocks`/`vintage` tuning blocks, currently JSON-only.
- Older follow-ups: a cover-asset library/delete UI; photographic art into the wrap **bleed**;
  ~~carrying backgrounds/emblems/designs onto the EPUB cover~~ — **SHIPPED (#43)** as a page-1 raster.

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
