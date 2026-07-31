# Changelog

What changed in each release, in the words of someone using the app rather than
building it. The version lives in the `VERSION` file — the app, the `.iss` and the
build script all read it, so the installer and its filename can never disagree with
what the About page reports; `ROADMAP.md` has the engineering record behind every
line here.

---

## Unreleased

---

## 1.2.2 — 31 July 2026

A repair release, mostly for Word import: a manuscript arriving from Word now
looks like the manuscript you wrote. The desktop window also gets its right-click
menu back.

### Fixed

- **Right-click works again in the desktop app.** The window had no context menu at
  all, so a misspelled word couldn't be corrected from the spell checker's
  suggestions — and cut, copy and paste were missing from it too. (The app in a
  browser tab was never affected.)
- **Your Word paragraphs stay your Word paragraphs.** Text that merely *looked* like
  the app's own markup was being read as markup: a line beginning `~~~` opened a block
  and pulled the rest of the document into it, a line beginning `# ` became a chapter
  you never wrote, a literal `*hello*` came back italic, and `file_name_here` came back
  with the middle in italics. Imported text is now treated as words.
- **A bold chapter heading no longer prints its asterisks.** A Word Heading 1 with bold
  applied gave a chapter titled `**Chapter One**`, asterisks and all, on the printed
  page.
- **Bold *and* italic survives the import.** A Word phrase marked both came through as
  bold only.
- **A table inside a table is no longer lost.** A Word table with another nested inside
  it was dropped whole and without a word about it — not even a line in the import
  summary. Its contents now come through.

---

## 1.2.1 — 30 July 2026

- **Your words are kept.** Saves in the manuscript editor are now all-or-nothing, so an
  interrupted save can't leave an empty file, and every few minutes of writing is copied
  into the project's history. A **History** panel lists the versions; restoring one keeps
  what you have first, so going back is itself undoable.
- **An About page**, with the version you're running and an optional check for new
  releases — **off by default**, because this app talks to nobody unless you ask it to.
  It never installs anything itself; it tells you, and you download when you choose.

### Fixed

- **`***bold italic***` no longer stops the build.** Writing a word in bold *and* italic
  produced a PDF that refused to build at all, and an EPUB shops would reject. It sets
  correctly now, in print and ebook alike — as does `___bold italic___`.
- **A stray asterisk is just an asterisk.** A lone `*` earlier in a paragraph — a
  multiplication, a footnote mark typed by hand — could pair up with the emphasis later
  in the same paragraph and take the whole build down with it. It stays literal now.
- **Bold *and* italic survives a save in the editor.** Marking a phrase both bold and
  italic in the manuscript editor quietly lost the italic the next time the file was
  opened. Both are kept.
- **A mistyped in-book link no longer costs you the book.** `[see](#chapter-12)` in a
  ten-chapter book — or a link made from a chapter title you later renamed — used to
  stop the PDF with an error that named neither the link nor the chapter. The book now
  builds, the words stay put, and the preflight panel lists every link that points
  nowhere so you can fix it.
- **Every line of a `~~~` block is typeset.** In a quote, poem or table, only the last
  line to need rewriting kept the change — notes and links on the lines above it were
  dropped.
- **Re-opening a manuscript no longer nudges the text.** Certain runs of asterisks and
  underscores were re-saved slightly differently each time the editor round-tripped
  them. What you wrote is what comes back.

---

## 1.2.0 — 28 July 2026

The release that finished the book. Everything a manuscript can contain now has a
way to be written, imported, typeset and exported: illustrations, tables, lists,
quotations, links, notes at either end of the book, verse, and the pages around the
text. Hardcovers and jackets joined the paperback wrap, and interiors can now be
built for a printing press rather than a screen.

### Writing

- **Illustrations.** `~~~ figure src="map.png"` places a picture with a caption,
  inline or on a page of its own. Upload images on the new **Figures** page, or
  straight from the manuscript editor. A missing picture prints a labelled box in
  the proof rather than vanishing.
- **Tables.** `~~~ table` — one row per line, cells split on `|`. The header row
  repeats at the top of every page a long table runs onto. Columns are measured
  against the face each cell is actually set in, so no column is ever narrower than
  its longest word.
- **Lists, block quotations and aligned passages.** `~~~ list` (bulleted or
  numbered), `~~~ quote source="…"`, and `~~~ center` / `right` / `left`.
- **Links.** `[text](https://…)`, `mailto:`, or `#an-anchor` inside the book —
  clickable in both the PDF and the ebook, and print-safe by default.
- **Notes, at either end.** `[^label]` writes a note; the *style* decides whether
  notes print on a **Notes page** at the back or as **footnotes at the foot of the
  page they belong to**. The same manuscript makes either book.
- **Six more sections** — foreword, preface, introduction, afterword, bibliography
  and blurbs — plus `#* Prologue` for a chapter that shouldn't be numbered.

### Word import

Word files come across whole now. Images become figures, tables become tables,
lists and quotations keep their shape, hyperlinks keep their addresses, footnotes
and endnotes become notes at the point in the sentence where they belong, Verse and
Poem styles become poems, and manual line breaks stop being silently joined. Every
import ends with a plain summary of what came across and what didn't.

### Type and design

- **Six more bundled book faces** — EB Garamond, Vollkorn, Alegreya, Crimson Pro,
  Lora and Spectral — so every genre style now has a typeface chosen for it rather
  than sharing one, with sizes re-set for each. Seven faces ship in total.
- **Twelve scene-break ornaments**, drawn as vectors rather than bundled as
  pictures, so they stay sharp at any size and print identically in the PDF and the
  ebook. Pick one from a tile grid in the style editor.
- **Chapter-opening art** — one illustration at the head of every chapter, above the
  number or below the title.
- **Large-print editions.** A *Large print* action on any style card derives a new
  style following the RNIB/NAVH rules. **Thirteen standard trim sizes** in the style
  editor, all accepted by KDP and IngramSpark.

### Ebooks

- **Designed covers reach the EPUB** — the cover you built in the Cover Studio is
  now the ebook's cover too.
- **EPUB preflight**: eleven structural checks run against the file that was just
  written, accessibility metadata in the package, and real `epubcheck` when you have
  a copy installed.
- **Device preview**: the built ebook's own pages and stylesheet, reflowed at phone,
  e-reader and tablet widths.

### Print

- **Hardcover case wrap** and **dust jackets** join the paperback print wrap — the
  turn-in and hinges a case needs, or board-sized panels with folded flaps and their
  own copy. Every allowance is editable, and the preview warns when a book falls
  outside a retailer's programme.
- **Press-ready interiors.** One tick sets every black and grey as a *single ink*
  instead of RGB — the difference between crisp body type and the four-ink black
  that comes back mis-registered — declares the trim box, and leaves out links and
  the cover page. The result page then reports how the finished file measures up.

### Fixes

- **Raised-initial chapter openings** drew about a line lower than the space
  reserved for them and overprinted the paragraph beneath. They now measure what
  they draw. This was visible in a shipped style (Romance).
- **Manuscript editor autosave** added a carriage return to every line ending, and
  the damage compounded on each save. Fixed, and an affected project was repaired.
- **Word lists immediately before a table** were emitted after it.

---

## 1.1.0 — 24 July 2026

- **A rich manuscript editor.** A hide-the-markup writing mode beside the Markdown
  one, built without a bundled framework, over a lossless round-trip layer — what
  you type is stored as plain Markdown either way.
- **Poetry collections and anthologies.** Line-preserving `~~~ poem` blocks with
  stanza spacing and a hanging runover indent; a per-piece byline (`# Title |
  Author`) and a Contributors page for collections.
- **Covers that look different, not just recoloured.** Design families — classic
  frame, photographic, typographic, geometric, vintage and more — chosen from a
  gallery of rendered thumbnails, plus background art, vignettes, title panels and
  emblem slots.
- **A pass over first impressions:** a favicon and share cards, a preview of your
  *actual* manuscript on the compose page, section navigation down the long compose
  form, project thumbnails with a filter box, and first-run guidance on the pages a
  new user meets empty.

Earlier releases predate this file; `ROADMAP.md` carries the full record.
