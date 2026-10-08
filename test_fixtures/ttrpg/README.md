# TTRPG fixtures (ROADMAP #74)

Prepared on 2026-10-07, before any #74 code, so Phase 1 (the game blocks: `readaloud`,
`sidebar`, `statblock`) starts with its test material, its spec and its "before" already
in hand. The plan itself is the #74 entry in `ROADMAP.md`.

## Files

| File | What it is for |
|---|---|
| `adventure.md` | *The Drowned Bell*, a short original adventure (2 parts, 4 chapters) using every Phase 1 block in context, alongside existing blocks (tables, lists, parts). The `sample/` adventure the plan calls for, ready to move there when Phase 1 ships. Room keys are `##` subheads, because `###` arrives in Phase 2. |
| `statblocks.md` | A corpus of 9 stat blocks: 5 in the 5e shape (tiny, written modifiers, an NPC, a legendary gargantuan one with every section, a spellcaster with no `meta`) and 4 generic (old-school, narrative/PbtA, sci-fi horror, Fate). All original text. |
| `edge_cases.md` | 21 numbered cases, each with a subhead saying what should happen: empty blocks, odd score rows, colons, section lines, escapes, markup, curly quotes, nesting, Unicode, an unclosed fence. |
| `statblock_formats.md` + `.json` | **Every accepted stat block format, most common first**: one creature (the Bog-Thrall) written as the classic 5e layout (bold labels; and pasted from a PDF), Homebrewery V3 and legacy/GM Binder, the colon form, the 2024 layout, and an old-school stat line; plus two Homebrewery blocks pasted with no fence. The `.json` has the ranking, the reading rules and the model each format must read into (formats 1–3 identically). |
| `statblock_lines.json` | **The stat block line grammar as a spec**: 58 single lines, the format readers' included, with where they sit (head or section) and the expected classification (`field` / `scores` / `section` / `entry`), including the worked-out modifiers. Cases marked `open` are recommendations to confirm when Phase 1 starts. |
| `preset_sections.json` | A **draft** of the three preset sections in `app.DEFAULTS`' shape, every colour with a print-safe twin. |
| `make_long_book.py` | Generates `generated/long_book.md` (22 chapters, 264 keyed rooms, 132 stat blocks; **311 pages** at 6 × 9 today) and `generated/long_statblock.md` (one 120-entry stat block that runs to 7 pages). Deterministic (seed 74). Re-run it rather than committing the output. |
| `make_baseline.py` | Builds every fixture with the current code and writes `baseline/baseline.json`. Run it again after each phase and diff. |
| `baseline/baseline.json` | The "before", taken at 1.3.2. |

Generated Markdown, PDFs and EPUBs are ignored by this folder's `.gitignore`.

**The author's own books** are a second, larger test set: `Edenfall for test/` in the repo
root (a Bestiary with 71 stat blocks, a magic-item Compendium, the Volume 1 adventure and
its finished PDF, two maps). It is **gitignored and must never be committed** (the repo
is public), so any test that uses it skips when it is absent. What it showed is in the
#74 entry of `ROADMAP.md`, "The author's own books".

```
python test_fixtures/ttrpg/make_long_book.py
python test_fixtures/ttrpg/make_baseline.py
```

## What the app does with this today (1.3.2)

Measured by `make_baseline.py` and by hand:

- **Everything builds.** All five files make a PDF and an EPUB with no error. The 311-page
  long book builds in about 0.8 s (one column, no contents page). That is the yardstick for
  Phase 4's timing gate.
- **An unknown fence type is a plain document block.** `~~~ statblock`, `~~~ readaloud` and
  `~~~ sidebar` keep their type and attributes in the parsed block, but render as the
  style's plain `~~~` block. Prose blocks keep their paragraphs, so a read-aloud box or a
  sidebar already looks roughly right.
- **A stat block's lines are joined into one paragraph.** This happens in both the parser
  (prose fences join lines) and the rich editor's round trip, so editing a stat block in
  rich mode today would flatten it. All 132 stat blocks in the long book come out as one
  paragraph each.
- **Smart punctuation turns `---` into an em dash.** A `--- Actions` line reaches the block
  as "— Actions". The stat block parser has to classify each line *before* the inline pass,
  the way table cells are split before `_inline` (see the table gotcha in ROADMAP).
- **`***x***` already works** as bold italic, which the entry names rely on.
- **Curly-quoted attributes are dropped, for every block type.** `_ATTR_RE`
  (`manuscript.py:66`) only accepts straight quotes, so `src=“map.png”` pasted from a word
  processor silently loses the figure's picture. An existing bug, worth fixing in Phase 1
  (edge case 13), with the round trip writing straight quotes back.
- **Round trip** (with smart quotes off, as `test_doc_model.py` checks it): the only losses
  in `adventure.md` and `statblocks.md` are the joined stat block lines. Block types are
  normalised to lower case with one space (edge case 19), and a backslash before `---`
  inside a fence comes back doubled (edge case 10). Both need deciding in Phase 1.
- **No existing book uses the new syntax.** Checked the repo's `projects/`, `sample/`,
  `test_fixtures/` and the installed app's data folder (`%APPDATA%\Typeset Studio`) for the
  three fence types and for `###` headings (Phase 2): none found.
- **Prose here avoids underscores and backslashes.** The app reads `_x_` as italic even
  inside backticks (there are no code spans), so fixture text that names files like
  `long_book.md` gets reformatted by the round trip.

## Phase 1 touch points

The seven-file round from Tier 5A, with the places found. `quote` (#48) is the model for
the two prose blocks, and `table` (#57) for the line-oriented stat block.

| Where | What changes |
|---|---|
| `manuscript.py` | `LINE_BLOCKS` (line 35) gains `statblock`. `flush_block_para` (~line 380) classifies stat block lines before `_inline`, the way `table` splits cells. `_ATTR_RE` (line 66) accepts curly quotes. The module docstring's conventions list. |
| `doc_model.py` / `static/doc_model.js` | Both read `manuscript.LINE_BLOCKS`; the JS keeps its own copy at line 30 and must stay byte-identical in behaviour. Decide the backslash-before-`---` escape (edge case 10). |
| `engine.py` | `_render_doc_block` (~line 3602) dispatches three new renderers beside `quote` and `table`. The stat block is a single-column `Table`, so it splits across pages and never uses `KeepTogether` (the doc_block gotcha). The tapered rule is a vector, like `ornaments.py`'s. |
| `epub.py` | The dispatch at ~line 675 and the CSS at ~line 266: `.doc-block-readaloud`, `-sidebar`, `-statblock` (a definition list for fields, a `<table>` for scores). |
| `static/wysiwyg.js` | `docHeadLabel` (line 74) labels the three; the generic doc-block render at ~line 216 keeps one paragraph per line for a stat block (a `LINE_BLOCKS` member). Check `read(render(m))`, not just the Markdown (the `data-block` gotcha). |
| `templates/manuscript_editor.html` | Toolbar buttons (beside "Quote", line 248), their two insert handlers (~lines 662 and 1066), the rich-mode CSS (~line 166), and the formatting guide rows (~line 288). |
| `app.py` | `DEFAULTS` (line 1015) gains the three sections (draft in `preset_sections.json`). `parse_preset_form` (line 1536, `quote` at ~1616) reads them. The large-print loop at line 2167 must include them, or large print sets them under 16 pt. `PREVIEW_SAMPLE` (line 706) could show one block so the style editor previews them. |
| `templates/editor.html` | A style-editor section per block (model: `quote` at ~line 388) and the syntax help (~line 479). |
| `checker.py` | Reads `block[1]` only, so it is safe. Stat block lines are not prose, so check the continuity checker doesn't flag "STR" or "Hit Points" as misspelt names. |
| Tests | `test_doc_model.py` fidelity and stability cases for each block; a new `test_game_blocks.py` driven by `statblock_lines.json`, the corpus, the edge cases and the long stat block (splits, loses no line); `test_epub.py`'s validator over the adventure; `test_outputs.py`. |

## Decided (with the user, 2026-10-07)

The grammar questions, all answered as recommended:

1. A hyphen-minus in a written modifier (`(-2)`) prints as a true minus (−2); the
   manuscript keeps what was typed.
2. A row mixing written and missing modifiers keeps the written ones as written and works
   out the missing ones (5e score names only).
3. A line of `|`-separated pieces that are *each* `Label: value` splits into that many
   fields; otherwise it is one field (`Speed: 30 ft. | climb 20 ft.`).
4. Score names must be capitals or title case (`STR`, `Str`); lower case is an ordinary line.
5. Any run of three or more hyphens starts a section line; em dashes never do.
6. `\---` (a literal line starting with hyphens) is kept exactly as typed in the
   manuscript and the backslash is hidden in print; Phase 1 fixes today's round trip,
   which doubles the backslash.

And the format questions (`decided` in `statblock_formats.json`): Homebrewery blocks are
wrapped by the paste/import converter only, the 2024 saves print as their own column, and
plain-text entry names are recognised inside a fence only.
