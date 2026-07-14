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
library, #18 full print wrap; plus #22 wrap auto page-count, #24 per-retailer wrap presets,
and #25 back-cover image. Cover Studio backlog clear.)*

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
  while the textarea stays the source of truth. A *true* hide-the-markup WYSIWYG via a vendored
  structured editor (ProseMirror / TipTap / Lexical) remains an optional, heavier future path —
  it would need the build-step reversal below.

**Decision made (2026-07): stay dependency-free.** No bundled JS / build step — the offline,
no-CDN, tiny-inline-JS convention is preserved. A Node toolchain inside a Python-first,
solo-maintained app was judged not worth it, especially since the live page-preview already
shows true typeset fidelity. Phase B was therefore delivered as an aligned highlight overlay
(monospace surface; colour/weight/italic only, no resize — a larger heading would desync the
caret). Revisit only if true hide-the-markup WYSIWYG becomes a hard requirement.

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
- layout archetypes beyond centred-classic (title-at-top, bottom band, split band, full-bleed
  image with a title panel) — new `_paint_*` routines selected by a template `layout` key;
- background options (background image/texture behind the frame, subtle vignette, pattern) —
  partially exists for wraps;
- a few positioned image/emblem "slots" (logo, series badge, author mark) as presets, not
  freeform placement.
These extend the existing `covers/*.json` renderer incrementally, keeping "good by default."

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
