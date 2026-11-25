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
