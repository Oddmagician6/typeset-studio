# Joint bug hunt: Codex + Claude

Second app-wide hunt, planned 2026-11-24 after 1.14.0. The first hunt (12 items, in ROADMAP.md) finished in 1.3.1. Almost everything added since then has never been hunted: TTRPG layout, fillable sheets, Send to print, cover families, picture books and fixed-layout EPUB.

## How the work is split

- **Codex reads the code and writes the bug reports.** It always runs with `--sandbox read-only`, so it can read and search files but can't edit anything or run the tests. Its findings come from reading the code.
- **Claude checks the findings and fixes them.** Claude writes a short, scoped prompt for each section, checks each finding by reading only the lines it cites, reproduces only High-severity bugs, and fixes the bugs that are confirmed. This keeps Claude's usage low.

## Running a section

```
codex exec -s read-only -C . --ephemeral \
  -o bug_reports/NN-<section>.md - < bug_reports/prompts/NN-<section>.md
```

- `-o` makes Codex save its final report to a file. The CLI writes that file, not the sandbox, so read-only mode doesn't block it.
- `bug_reports/` is listed in `.git/info/exclude`. Raw reports and prompts stay local and never reach the public repo.
- Sections can run in parallel because Codex runs cost no Claude usage. Claude then triages them together in one pass.

### Every prompt includes

- The files in scope and what to look for (see the table below).
- What to skip: anything the first hunt already fixed (ROADMAP.md, "Bug hunt plan").
- "Do not open or quote anything under `projects/`." The user's books stay out of the reports.
- The required format for each finding:
  - **Severity**: High (data loss, wrong printed output, crash), Medium (wrong behaviour that has a workaround), Low (cosmetic, edge case)
  - **Where**: `file:line`
  - **Trigger**: concrete steps or input that set it off
  - **Expected / actual**
  - **Confidence**: certain / likely / speculative
- A cap of about 15 findings, ranked. Speculative findings go in a short list at the end.

### Prompt template

Copy this to `bug_reports/prompts/NN-<section>.md` and fill in the two bracketed parts from the sections table:

```
You are reviewing the Typeset Studio repository (a local Flask app that typesets
book interiors and covers into print-ready PDFs and EPUBs) for bugs.
Read-only review: do not try to modify files or run the test suite.

Section: <name>
Files in scope: <files>   (follow calls into other files where needed)
Look especially for: <focus>

Skip: anything already fixed in ROADMAP.md "Bug hunt plan". Do not open or
quote anything under projects/ (private user data); invent examples instead.

Report at most 15 findings, most severe first. For each finding:
- Severity: High (data loss, wrong printed output, crash) / Medium / Low
- Where: file:line
- Trigger: concrete steps or input that set it off
- Expected / actual
- Confidence: certain / likely / speculative
End with a short "Speculative" list for anything you couldn't confirm by reading.
```

## Starting a session

1. Read this file and the Progress table to find the next section.
2. Write that section's prompt from the template.
3. Launch Codex in the background with the command above.
4. Wait for the completion notification. Don't read the code yourself while Codex runs.
5. Triage the report and give the user a short list.

## Sections, highest risk first

| # | Section | Main files | What to look for |
|---|---|---|---|
| 1 | Picture books & fixed-layout EPUB (1.12–1.14) | `fixed_epub.py`, `page_plan.py`, `templates/page_plan.html`, colour paths in `engine.py` | EPUB pages that don't match the PDF, page plans with missing or extra pages, colour handling, picture-book trims |
| 2 | TTRPG layout | `statblock.py`, `bookindex.py`, two-column, spreads, bleed and page-designer code in `engine.py` | Broken column balancing, page references that go stale after reflow, index edge cases, bleed maths |
| 3 | Fillable sheets & Send to print | Package, publish and cover-spec routes in `app.py`, `wrap_convert.py`, `templates/cover_specs.html`, `templates/print_package.html` | Spine and bleed calculations, wraps built from uploaded art, package file names, fillable form fields |
| 4 | Wrap designer & cover families | `wrap_design.py`, `static/wrap_designer.js`, `templates/cover_editor.html`, `covers/*.json` | Changes since 1.3.0: Customise, long titles, justify/align, flaps, emblem slots, undo |
| 5 | Manuscript parsing & reflowable EPUB | `manuscript.py`, `epub.py` | Poem blocks, anthology bylines, anchors, escaping, unusual Unicode |
| 6 | WYSIWYG / doc model | `doc_model.py`, `static/doc_model.js`, `static/wysiwyg.js`, `templates/manuscript_editor.html` | Text lost in the round trip, verse editing, keeping the Python and JS models in sync |
| 7 | `app.py` across all routes | All routes and `templates/` | Path traversal, upload handling, XSS in templates, non-atomic writes, damaged-file handling for the newer file kinds, thread safety |
| 8 | Upgrades & packaging | `upgrade_project` (fields added in 1.4–1.14), update check, `typeset-studio.spec`, `typeset-studio.iss` | Opening the frozen `test_fixtures/v1.x` books, bundled data missing from the build |

### Round 2 (started 2026-11-25, after 1.14.1)

Code the first eight sections didn't cover.

| # | Section | Main files | What to look for |
|---|---|---|---|
| 9 | Core interior typesetting | `engine.py` novel layout (openers, drop caps, running heads, TOC, footnotes, document blocks), `matter.py`, `ornaments.py` | Dropped or leaked text, wrong heads/folios, TOC numbers that disagree with the body, unescaped markup |
| 10 | Template cover rendering | `engine.py` cover code, `covers/*.json` | Text off the trim or into the spine, wrap maths, crashes on empty or very long fields |
| 11 | Preflight & results pages | `checker.py`, preflight/continuity/figures/fonts routes and templates | False passes, false blocks, wrong locations in warnings |
| 12 | Project & editor front end | `editor.html`, `project_edit.html`, `projects.html`, `base.html`, `covers.html` | Lost unsaved changes, fields that don't round-trip, titles that break the page |

### Round 3 (started 2026-11-25)

| # | Section | Main files | What to look for |
|---|---|---|---|
| 13 | Manuscript import | `manuscript.import_docx`, import routes and helpers in `app.py` | Text dropped or duplicated on import, unescaped markup, crashes on unusual .docx files, wrong import summaries |
| 14 | Reflowable EPUB for newer features | `epub.py` (ornaments, matter, notes, stat blocks, index, page references, chapter art) | Features in the PDF that are lost or garbled in the EPUB, XHTML/OPF that epubcheck would reject |
| 15 | Customise (template to designer) | `wrap_convert.py`, `/wrap-designer/customise` | A customised design that doesn't match its template, elements lost in conversion, crashes on empty fields |
| 16 | Styles, defaults & libraries | Style editor routes, large print, defaults restore, fonts/figures libraries, history restore, repair | Settings saved but ignored, deleting a font or figure still in use, restores that drop data |

### Round 4 (started 2026-11-25, after 1.14.2)

| # | Section | Main files | What to look for |
|---|---|---|---|
| 17 | Regressions from the fixes | Non-test changes since v1.14.0 | Double or missing escapes, guards that refuse valid input, call sites not updated, fixes on one output path only |
| 18 | Build pipeline & outputs | generate/preview/rebuild/download routes, `generate.html`, `result.html` | Overlapping builds sharing state, stale outputs after a failed build, preview vs final differences, swallowed errors |
| 19 | Ornaments & matter end to end | `ornaments.py`, `matter.py` and their readers in PDF and EPUB | Matter missing or reordered between outputs, ornament size/position, page parity, heads and folios on matter pages |
| 20 | Fonts, glyphs & unusual text | Font registration and embedding, text measurement (Python and `wrap_text.js`), smart quotes | Missing glyphs with no warning, JS/Python measurement mismatch, wrong apostrophes, case changes |

### Round 5 (started 2026-11-25, after round 4 merge)

| # | Section | Main files | What to look for |
|---|---|---|---|
| 21 | Page designer & Page Plan UI | `/page-designer/*` routes, `wrap_design.py` and `wrap_designer.js` page mode, `page_plan.html`, `page_plan.py` | Designs lost on rename/delete, spreads on the wrong side, plan drifting from the PDF, PDF vs fixed EPUB placement |
| 22 | Stat blocks & game blocks | `statblock.py`, block handling in `manuscript.py`, `engine.py`, `epub.py`, doc model | Fields dropped or misplaced, wrong modifiers, PDF/EPUB differences, unterminated blocks, Homebrewery variants |
| 23 | EPUB validity & accessibility | `epub.py`, `fixed_epub.py`, nav/opf generation | epubcheck errors (ids, links, manifest, metadata, XHTML), alt text, lang, landmarks, page-list |
| 24 | App startup, data dir & settings | Startup and seeding, `settings.json`, update check, pruning and housekeeping, frozen paths | First-run/upgrade clobbering user files, settings corruption, version compare, pruning in-use files |

### Round 6 (started 2026-11-25, after 1.15.0)

The 1.15.0 smoke test caught a round-5 regression the suite missed: the installed app crashed on its first start (an import-time call to a helper defined further down `app.py`), and the frozen build ignored `TS_PORT`. Both fixed before release; section 26 looks for more of the same.

| # | Section | Main files | What to look for |
|---|---|---|---|
| 25 | Send to print, re-checked | Package/publish routes, `print_package.html`, `cover_specs.html`, `wrap_convert.py`, spine/bleed maths | Package contents vs the page, spec sheet vs the packaged PDF, stale files, unsafe names |
| 26 | Regressions from rounds 4–5 | Non-test changes in `v1.14.2..v1.15.0` | Import-time order, frozen-only paths, locks, O_EXCL/link on odd drives, one-path-only fixes |
| 27 | Manuscript editor & autosave | `manuscript_editor.html`, `wysiwyg.js`, save/autosave/history routes | Lost edits on races and mode switches, two tabs overwriting, undo across modes, failed saves shown as saved |
| 28 | Scale & pathological input | Parsers, layout loops, regexes, uploads | Catastrophic backtracking, quadratic loops, recursion limits, passes that never settle, no size limits |

### Round 7 (started 2026-11-27, after 1.16.0)

| # | Section | Main files | What to look for |
|---|---|---|---|
| 29 | Regressions since 1.15.0 | Non-test changes in `v1.15.0..v1.16.0` (round 6, leftovers, page list, language, landmarks, KDP case wrap) | Linearised loops whose output changed, page-list markers that move text or point at the wrong page, locks and lock files, one-path-only fixes |
| 30 | Edition variants | Press-ready CMYK, screen PDF, large print, early readers (`para_space`, `keep_whole`), reference structure (`###`, taglines, contents depth, bookmarks, section heads) | Options ignored on one output, colour leaking into a press build, settings that combine badly, heads/bookmarks that disagree with the body |
| 31 | Anthology, poems & index | Bylines and contributors page, poem blocks, `bookindex.py`, page references, across PDF, both EPUBs and the doc model | Bylines lost or misattributed, verse lines rewrapped, index/page-ref numbers wrong after reflow or in the EPUB |
| 32 | Routes & templates since section 7 | Routes and templates added or changed since `v1.14.0` | Routes outside the same-origin guard, path handling, XSS, upload size limits, error pages that leak paths |

## After each section

1. **Triage.** Claude sorts every finding as confirmed, false positive or needs a repro, and gives the user a short list.
2. **Choose.** The user picks which bugs to fix. Any change to printed output needs the user's OK, as in the first hunt.
3. **Fix.** Claude works on a branch, one per section. Each fix gets a test in the existing harness style, and the full suite runs before merging.
4. **Record.** The table below is updated, written generically with invented examples and no quotes from the user's books.

## Progress

| # | Section | Report | Confirmed | Fixed | Merged |
|---|---|---|---|---|---|
| 1 | Picture books & fixed-layout EPUB | 13 (+2 spec.) | 7 Highs (1.1 by design) | 7 Highs (with 3.4); Mediums 1.8 (already fixed), 1.9, 1.10, 1.11, 1.12, 1.13 on bughunt-app | Highs merged |
| 2 | TTRPG layout | 14 (+1 spec.) | 9 Highs | 9 Highs (+1 found while fixing: a note in a long opening paragraph sits on its start page); 2.10–2.14 and the speculative unsettled-pass warning on bughunt-app (`test_mediums_bughunt.py`, print changes OK'd) | Highs merged |
| 3 | Fillable sheets & Send to print | 13 (+1 spec.) | 5 Highs (KDP hardcover spec. unverified) | 5 Highs (3.4 with section 1); 3.6–3.13 on bughunt-mediums / bughunt-app (3.8–3.10 in `test_fields.py`) | Highs merged |
| 4 | Wrap designer & cover families | 14 (+1 spec.) | 9 Highs, all confirmed; 4.5, 4.6, 4.7, 4.9 change print (OK'd) | All 14 on bughunt-app (`test_wrap_bughunt.py`); RTL justify speculative, left open | – |
| 5 | Manuscript parsing & reflowable EPUB | 14 (+1 spec.) | 7 Highs, all confirmed | 5.1–5.7 on bughunt-app (`test_manuscript_safety.py`); 5.6 OK'd (also escapes the title page, copyright and matter headings) | – |
| 6 | WYSIWYG / doc model | 13 (+2 spec.) | 10 Highs confirmed; 6.6 not a bug (the typesetter also ends a note at a `##` line) | 6.1–6.5, 6.7–6.13 on bughunt-app (`test_bughunt6` in `test_doc_model.py`, 12 rich-editor scenarios) | – |
| 7 | `app.py` across all routes | 13 (+2 spec.) | 12 Highs + 1 Medium, all confirmed (2 speculative left open) | All 13 on bughunt-app (`test_app_safety.py`); both speculatives fixed on bughunt-speculative (loopback-host + same-origin guard on state-changing requests, art route serves pictures only, nosniff) | – |
| 8 | Upgrades & packaging | 13 (+1 spec.) | 3 Highs, all confirmed; 8.1 changes print (OK'd) | 8.1–8.12 on bughunt-app (`test_upgrades_bughunt.py`, 8.2 in `test_fixed_layout.py`); feed pagination raised to 100 on bughunt-speculative; 8.13 (fixture gaps) left open | – |
| 9 | Core interior typesetting | 14 | 5 crashes (9.1–9.3, 9.9, 12.4) and the 9.10 garble reproduced; all 14 confirmed; print changes OK'd | All 14 on bughunt-round2 (`test_interior_bughunt.py`); a page-tall row or drop-cap paragraph splits only when it is taller than a page | – |
| 10 | Template cover rendering | 14 (+1 spec.) | 13 confirmed; 10.13 (guide vs template barcode spot) a convention, not a bug; print changes OK'd | 10.1–10.12, 10.14 on bughunt-round2 (`test_covers_bughunt.py`); front-panel lines held to the safe area; scrim stripes (spec.) left open | – |
| 11 | Preflight & results pages | 14 (+1 spec.) | 14 confirmed | All 14 on bughunt-round2 (`test_preflight_bughunt.py`); a telegram's Courier now shows as not embedded; spec. RGB-operand scan left open | – |
| 12 | Project & editor front end | 13 (+1 spec.) | 13 confirmed | 12.1–12.3, 12.5–12.13 on bughunt-round2 (`test_frontend_bughunt.py`); 12.4 with section 9; double-click Regenerate (spec.) left open | – |
| 13 | Word import | 14 (+1 spec.) | 14 confirmed | All 14 and the spec. on bughunt-round3 (`test_import_bughunt.py`) | – |
| 14 | EPUB extras | 13 | 13 confirmed; EPUB changes OK'd | All 13 on bughunt-round3 (`test_epub_bughunt.py`); a missing page design now fails the ebook's own checks | – |
| 15 | Customise (template to designer) | 11 (+1 spec.) | 11 confirmed; cover changes OK'd | All 11 and the spec. on bughunt-round3 (`test_customise_bughunt.py`); the engine names the text it draws (`engine._source`), front-flap copy measured from its fold, `keep_spaces` labels; title/byline separation is wired for Classic Frame only | – |
| 16 | Styles, defaults & libraries | 14 (+1 spec.) | 14 confirmed | All 14 on bughunt-round3 (`test_styles_bughunt.py`); overlapping builds swapping emphasis faces (spec.) left open | – |
| 17 | Regressions from the fixes | 11 (+2 spec.) | 11 confirmed; print changes OK'd | All 11 on bughunt-round4 (`test_regressions_bughunt.py`); a proof's cover is now a whole leaf (cover and its blank inside), so its count is the interior's; both speculatives left open | – |
| 18 | Build pipeline & outputs | 14 (+1 spec.) | 14 confirmed | All 14 and the spec. on bughunt-round4 (`test_pipeline_bughunt.py`): builds record only their own newest edition, one cover snapshot per build, PDFs laid out beside their name, scratch files go however a build ends | – |
| 19 | Ornaments & matter end to end | 13 (+1 spec.) | 13 confirmed; print and EPUB changes OK'd | All 13 on bughunt-round4 (`test_matter_bughunt.py`, 19.7 in `test_fixed_layout.py`); found while fixing: an `&` in a link address was escaped twice. Night-mode ornament ink (spec.) left open | – |
| 20 | Fonts, glyphs & unusual text | 15 (+1 spec.) | 15 confirmed; 20.2 (right-to-left PDF text), 20.9 (astral characters in copied PDF text) and 20.12 (fonts in the reflowable EPUB) are features, left open | The other 12 on bughunt-round4 (`test_glyphs_bughunt.py`; 20.3, 20.4, 20.6–20.8 landed with section 17) | Released in 1.15.0 |
| 21 | Page designer & Page Plan UI | 14 (+1 spec.) | 14 confirmed | All 14 on bughunt-round5 (`test_pagedesigner_bughunt.py`) | Released in 1.15.0 |
| 22 | Stat blocks & game blocks | 14 (+1 spec.) | 14 confirmed | All 14 on bughunt-round5 (`test_gameblocks_bughunt.py`, 7 rich-editor scenarios); an unclosed block ends at the next fence or chapter and preflight names it | Released in 1.15.0 |
| 23 | EPUB validity & accessibility | 14 (+1 spec.) | 14 confirmed; 23.5 (language setting), 23.11 (page-list), 23.12 (hazard metadata), 23.13 (landmarks) are features, left open | The other 10 on bughunt-round5 (`test_epubvalid_bughunt.py`) | Released in 1.15.0 |
| 24 | App startup, data dir & settings | 14 (+1 spec.) | 14 confirmed; 24.1 shipped two uploaded photos inside the installers | All 14 on bughunt-round5 (`test_lifecycle_bughunt.py`); the 1.14.2 release (the last one carrying the photos) was deleted when 1.15.0 shipped. Two regressions found by the release smoke test fixed before release | Released in 1.15.0 |
| 25 | Send to print, re-checked | 13 (+1 spec.) | 13 confirmed; the three retailer rules checked against KDP's and IngramSpark's own pages first; print changes OK'd | All 13 on bughunt-round6c (`test_sendprint_bughunt.py`): a package records only onto its own book and only if it is the newest; one snapshot of uploaded art per package; a wrap design's listing cover is cut from the package's own wrap; nothing rasterises a book with no cover; IngramSpark's spine counts its barcode page (+1 odd, +2 even); KDP page maxima follow its four trim groups (7x10 takes 828) and spine text starts at 80 pages; a back photo sits above the barcode box; designer warnings, the inside margin and what actually shipped reach the page and the sheet; the ZIP is written beside its name and moved on whole; template names carry printer and paper. IngramSpark calipers (spec.) left open | – |
| 26 | Regressions from rounds 4–5 | 12 (+2 spec.) | 12 confirmed (5 reproduced); print changes OK'd | All 12 on bughunt-round6 (`test_regressions6_bughunt.py`, 2 rich-editor scenarios): a `# ` line ends a block only when its closing fence isn't ahead; Page Plan reads blocks as the parser does and refuses a rewrite that changes the chapters; emphasis may hold a whole emphasised span; set-aside fonts are renamed in the user's styles, templates and designs. Speculatives left open | – |
| 27 | Manuscript editor & autosave | 13 (+2 spec.) | 13 triaged; all picked | 12 on bughunt-round6b (`test_editor_bughunt.py`, with a browser half): saves and restores hold a per-book lock (in-process and a lock file across copies); a Book settings save writes only what it changed onto the book as it is now; the snapshot just taken is never pruned, and future-stamped ones go first; the editor is read-only while it is left or a version restored, and leaving waits for typing that arrived mid-save; a beacon is not taken as a save; the editor knows its saved text (typed-and-undone is clean); the conflict reload waits for its keep; Find, Replace and the page picker don't act on the hidden editor; pasting only blocks over a title keeps it; a paste inside a block's fences adds none. bfcache spec fixed (pageshow). 27.12 (shared undo across modes) and the drag-drop spec left open | – |
| 28 | Scale & pathological input | 15 (+2 spec.) | Realistic items and cheap guards picked; 28.1 not reproduced (a thousand consecutive headings fill every page in two columns) | Six on bughunt-round6d (`test_scale_bughunt.py`): a CR fraction too big for a float sorts with the words and a score thousands of digits long prints without a modifier; manuscript uploads are read no further than a limit (64 MB text, 512 MB Word) and a Word file that unpacks past 2 GB (256 MB of XML) is refused before parsing; a table cell's span is capped at Word's 63 columns; a figure with far more pixels than its printed size needs (past 600 ppi) is scaled down before ReportLab holds it; the EPUB is written beside its name and renamed into place, and the startup sweep clears a cut-off one; the EPUB check reads a picture's first bytes, not the picture, and looks entries up by name. Quadratic slowdowns (28.5, 28.7, 28.8, 28.10-28.14) and the docx recursion speculative left open | – |
| – | Leftovers from rounds 5–6 | – | Picked from the open list | On leftovers-perf: 28.5, 28.7, 28.8, 28.11, 28.12, 28.14 made linear with the same output (`test_leftovers_bughunt.py`); 28.10 and 28.13 measured and left; text dropped into the rich editor goes through the paste cleanup (27 spec.); Word nesting is capped by the XML parser at 256 before Python's recursion limit (28 spec.); 23.5 a Language setting (both EPUB layouts and the PDF), 23.12 animated art makes flashing and motion hazards unknown, 23.13 landmarks in both layouts (`test_epubfeatures_bughunt.py`); KDP hardcover takes KDP's own 0.51" wrap and 0.4" hinges (print change OK'd). Left open: 23.11 (print page-list, feature-sized), IngramSpark calipers (its guide gives none), KDP's case board allowance (unverified) | – |
| – | 23.11 print page list | – | Feature, started at the user's request | On page-list (`test_pagelist_bughunt.py`): the PDF reports each folio's chapter block (`print_pages`: the block that starts first on the page, or the one still running) through zero-width `<onDraw>` tags and a mark on non-paragraph flowables - every word of the sample books sits where it did; an EPUB built beside the PDF (Build both, Regenerate, the publish package) marks each page with a doc-pagebreak span before its block, lists them in a page-list nav and claims pageNavigation, pageBreakMarkers and a11y:pageBreakSource (the print edition by title: the app has no ISBN field). Built alone, or given another book's pages, it claims none. Fixed layout says pageBreakSource none. Page breaks are at block granularity (not mid-paragraph); front and back matter pages are not listed | – |
| 29 | Regressions since 1.15.0 | 14 (+1 spec.) | All Highs and Mediums picked (29.1–29.13), print changes OK'd; 29.9/29.10 checked against EPUB 3.3/3.4 first | All 13 on bughunt-round7 (`test_regressions7_bughunt.py`, 29.12 also `bh29-*` in `test_rich_editor.js`): a manuscript save or restore checks it still holds the lock before writing, and one that lost it is kept in History and refused; Book settings snapshots and replaces the manuscript under the manuscript lock, from the book as it is now; the installed start's font set-aside repoints styles again (`_decode_text` defined before seeding runs); the page-list marker sits at the end of a block's first word, so an overlong first word splits again; the back photo is placed before the blurb, which stops above it (or is flagged when the photo sits over its opening); the page list runs to the last page the chapters reach, marks a figure's or designed page's first drawn flowable (not its break or spacer), and a split table or column run keeps its place; an EPUB lists print pages only when the PDF's `print_pages_key` (a fingerprint of the chapters) is its own; the print source is a `dc:source` refined `source-of: pagination` (3.3) - `a11y:pageBreakSource` is no property, and fixed layout names none; no Contents landmark without a Contents page (the nav isn't in the spine); language tags are checked as RFC 5646 and Book settings refuses a bad one; italics round a bold span parse and write back as the engine sets them (JS and Python doc models); past the key budget names are indexed by one-letter deletions, and a check cut short says so. Low 29.14 and the ZIP-replace speculative left open | – |
| 30 | Edition variants | 12 (+1 spec.) | All Highs and Mediums picked (30.1–30.9), print changes OK'd | All 9 on bughunt-round7b (`test_variants_bughunt.py`): the press canvas lets the footnote measuring pass's marker links through (that build is read back and thrown away), so a press PDF keeps foot-of-page notes after the first paragraph; a dead link in a `#>` tagline or a byline is unlinked and reported like a body one (also fixes 31.1); a keep-whole opening paragraph carries its footnote probe inside the KeepTogether, so a drop-cap opener's note moves with it; the screen PDF's own preflight problems come back as warnings (less print-only rows and what the print preflight already shows); PDF bookmarks and EPUB headings close up a skipped level and treat the same asked-for level as a sibling, so two `###` with no `##` are side by side; the press build's RGB fallback uses the colour interior's press canvas (no links, flattened fields, trim box; not claimed as colour) and the package says so; the page-by-page EPUB's left-out check names Notes (or Footnotes); Large Print stat-block small caps never go under the size floor; the display face stands in for a bold `###` only, an italic or regular one is set as picked. Lows 30.10–30.12 and the speculative left open | – |
| 31 | Anthology, poems & index | 14 (+1 spec.) | All Highs and Mediums picked (31.1–31.14), print changes OK'd; 31.6 deferred | 31.1 came with 30.2 and 31.9/31.10 are 29.6/29.7; the rest on bughunt-round7c (`test_anthology_bughunt.py`, bh31 in `test_rich_editor.js`): a telegram or small-caps table header keeps its index and anchor markers through the capitals, so the entry is listed and a page reference to it builds; every positional `chapter-N` is reserved before title slugs, so a chapter titled "Chapter 2" no longer takes the second chapter's name; the byline separator honours `\|` (a pipe in the title) and skips link labels, a Word heading's ` | ` is escaped on import, and a cleared title is written `# | Author` so the byline survives (Python and JS doc models); Word verse splits stanzas at blank manual lines; raised-initial and small-caps openings carry their markers inside the paragraph, so they move with it; the EPUB byline and tagline read their Markdown (also 30.11); a contributor's name ends at the first `--` or em dash; index terms are grouped NFC; an EPUB page-reference caption leaves out a heading's note number. **31.6 (verse indentation) left open as a feature at the user's call**; the speculative left open | – |
| 32 | Routes & templates since section 7 | 12 (+1 spec.) | All Highs and Mediums picked (32.1–32.9) | All 9 on bughunt-round7d (`test_routes7_bughunt.py`): a Page Plan move or + Page checks and writes under the manuscript lock, on the book as it is then (+ Page saves its design and placement in the one write); a wrap save renders first, then re-reads the book under the lock and writes only the wrap's fields, so a title or blurb saved meanwhile stands (a front rendered at a size the book no longer has is dropped); Book settings writes a replacement image, commits and drops the replaced file under one lock, and never drops a file the saved book points at; a page rename writes the manuscript first and the book with it, so a failed manuscript write keeps the old name; the cached wrap front is keyed on the design as well as the geometry; renames are kept in a dated log, and a History restore replays every rename made after that version, even once the old name is reused (the old map is still read for renames from before the log); Automatic EPUB layout goes page by page only when the manuscript places a page design; cover and back-cover uploads are read no further than 256 MB; the Page Plan reads a Word book without writing its pictures to Figures (`import_docx(save_images=False)`). Low 32.12 came free (a JSON list body is refused by both designers); Lows 32.10/32.11 and the speculative left open | – |
