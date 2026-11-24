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

## After each section

1. **Triage.** Claude sorts every finding as confirmed, false positive or needs a repro, and gives the user a short list.
2. **Choose.** The user picks which bugs to fix. Any change to printed output needs the user's OK, as in the first hunt.
3. **Fix.** Claude works on a branch, one per section. Each fix gets a test in the existing harness style, and the full suite runs before merging.
4. **Record.** The table below is updated, written generically with invented examples and no quotes from the user's books.

## Progress

| # | Section | Report | Confirmed | Fixed | Merged |
|---|---|---|---|---|---|
| 1 | Picture books & fixed-layout EPUB | 13 (+2 spec.) | 7 Highs (1.1 by design) | 7 Highs (with 3.4) | Highs merged |
| 2 | TTRPG layout | 14 (+1 spec.) | 9 Highs | 9 Highs (+1 found while fixing: a note in a long opening paragraph sits on its start page) | Highs merged |
| 3 | Fillable sheets & Send to print | 13 (+1 spec.) | – | – | – |
| 4 | Wrap designer & cover families | – | – | – | – |
| 5 | Manuscript parsing & reflowable EPUB | – | – | – | – |
| 6 | WYSIWYG / doc model | – | – | – | – |
| 7 | `app.py` across all routes | – | – | – | – |
| 8 | Upgrades & packaging | – | – | – | – |
