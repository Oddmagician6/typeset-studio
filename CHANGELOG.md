# Changelog

What changed in each release, in the words of someone using the app rather than
building it. The version lives in the `VERSION` file — the app, the `.iss` and the
build script all read it, so the installer and its filename can never disagree with
what the About page reports; `ROADMAP.md` has the engineering record behind every
line here.

---

## Unreleased

### Fixed

- **Wrap designs made before 1.3.0 keep their barcode box.** A design saved
  in 1.2.5–1.2.9 opened in 1.3.0 saying "No barcode area", its box couldn't
  take an ISBN, and "+ Barcode" stacked a second box on top. The old box is
  now recognised and becomes the barcode box when the design opens - from a
  book or from the designer's own working copy - and prints just as it did.
- **Books from the first releases have their covers back.** A book made
  before cover choices existed (1.0) kept its uploaded cover art, but from
  1.2.3 it was treated as having no cover, and saving it on the Edit page
  made that permanent. It is page 1 again.
- **Right-hand chapter starts stay on** when an older book is saved on the
  Edit page. A book that had never set them was built with them on but shown
  with the box unticked, so saving it switched them off.

## 1.3.0 — 3 October 2026

The Wrap designer is finished: a real ISBN barcode on the back cover, review
quotes, ellipses and rules, layers you can lock, hide and group, snapping and
zoom. And a round of fixes from a bug hunt in the cover editor, the worst of
which quietly changed some cover templates whenever they were saved.

### Added

- **A real ISBN barcode in the Wrap designer.** Every design has a barcode
  box in the lower right of the back cover, where printers expect it, locked
  so it isn't moved by accident. Type the book's ISBN (13 digits, or an old
  10-digit one) and an optional five-digit price code, and the box prints the
  barcode itself - which IngramSpark expects on your cover. On KDP you can
  leave it empty and KDP prints its own there. A mistyped ISBN is caught as
  you type, and anything laid over the box is flagged.
- **Review quotes.** Add a review quote, or a "Praise for…" heading with
  three quotes, to the back cover in your design's own faces, ready for your
  reviews' words.
- **More to draw with:** ellipses and rules alongside boxes, outlines on any
  of them (or an outline alone, with no fill), and pictures you can turn by
  quarters.
- **Layers you can lock, hide and group.** Locked things can't be moved on
  the cover by accident; hidden ones leave the screen and the printed file;
  grouped ones are picked up together with a click.
- **Snapping.** Things you drag catch on the folds, the trim, the safe lines,
  the middle of each panel and the edges and middles of everything else, with
  a guide line to show it. Hold Alt to drag freely.
- **Zoom** in on the cover for fine work.
- **More checks as you work:** a picture or shape that reaches the edge but
  stops short of the bleed, and a picture too small for the size it is placed
  at.

### Fixed

- **Saving a cover template no longer changes it.** The cover editor rebuilt
  a template from its own fields on every save, so each design family's own
  settings were thrown away: the geometric and typographic covers looked
  different after a save with nothing changed, and the minimal, postcard,
  stripe and vintage covers lost settings that only happened to match the
  defaults. The editor's live preview showed the same wrong cover. Saves now
  keep everything the editor has no field for.
- **The vintage covers keep their spine author colour when saved**, and any
  colour or font a dropdown doesn't list is kept rather than replaced by the
  first one in the list.
- **"From a book" in the cover editor's print wrap now takes the book's
  printer, paper and binding,** as well as its back-cover and flap copy. It
  used to fill only the trim and page count, so the wrap could be worked out
  for KDP on white paper when the book was set for IngramSpark on cream, with
  a spine the wrong width.
- **A wrap downloaded from a cover named without Latin letters** (Тайга) is
  now called "cover-wrap.pdf" rather than "-wrap.pdf".

---

## 1.2.9 — 3 October 2026

The Wrap designer gains justified text, a way to select several things and
line them up or space them evenly, and one-click jacket flaps filled from
the book's own copy.

### Added

- **Justified text in the Wrap designer.** Set a text box to Justified and
  every line but the last of each paragraph runs the full width of the box,
  on screen and in the printed PDF alike.
- **Select several things at once, and line them up.** Shift+click on the
  cover (or in the layers list) to pick more than one; drag them, nudge them
  with the arrow keys or delete them together. **Line them up** by their left,
  right, top or bottom edges or their centres, and space three or more evenly
  across or down the cover. With one thing selected, the same buttons line it
  up with its panel: centre a title on the front cover in one click.
- **Ready-made jacket flaps.** On a dust jacket, the Wrap designer fills a
  flap in one click: the title over the jacket copy on the front flap, and
  "About the author" with the author photo and bio on the back, set in your
  design's own faces and colours and taken from the book's Send to print
  settings.

---

## 1.2.8 — 2 October 2026

A fix for long titles on every cover template: a title that wraps onto four
or more lines now makes room for itself instead of running into the epigraph,
the author line or the edge of the cover.

### Fixed

- **Long titles no longer run into the rest of the cover.** On every cover
  template, a title long enough to wrap onto four or more lines used to grow
  down through whatever sat below it: through the epigraph on the classic
  frames, out of the colour band on the geometric ones, over the tagline on
  vintage, into the author or imprint line, or off the bottom of the cover. A
  long title now shrinks (or, on photographic covers, moves up) just enough to
  keep clear. Titles that already fitted are unchanged.

---

## 1.2.7 — 2 October 2026

Any cover template can now be opened in the Wrap designer and made your own:
Customise turns the whole wrap into layers you can move, edit and recolour,
starting from exactly what the template prints. Three template layout bugs
are fixed along the way: spine text, the barcode label, and long titles on
photographic covers.

### Added

- **Customise any cover template in the Wrap designer.** Every template now
  has a **Customise** button (on the Covers page and in a book's template
  picker), and the Wrap designer has a **Start from a cover** menu that also
  offers the book's own cover, uploaded art included. The whole wrap opens as
  layers you can edit: the title, author line and blurb as text boxes that
  re-flow when you change them, the pictures as pictures, and the frames,
  ornaments, bands and shading as shapes you can move, stretch and recolour.
  It starts out exactly as the template prints, for all 24 templates in every
  binding, and one Undo takes you back to the design you had.

### Fixed

- **Shape opacity in the Wrap designer now reaches the PDF.** A
  see-through band showed as see-through on screen but printed solid.
- **Spine text stays inside the spine.** The title and author on a template
  wrap's spine are now sized and centred to keep 1/16" clear of each fold, as
  printers ask; on a spine too thin to hold type inside that margin they're
  left off, and Send to print says why.
- **The barcode label stays in its box.** On a dust jacket, or any back cover
  without a blurb, "ISBN / barcode area" was letter-spaced like the series line
  and ran out past the white box.
- **Long titles on photographic covers keep the author on the page.** A title
  that wrapped to three lines pushed the author line off the bottom of the
  cover; the title and author now move up together to clear the imprint line.

---

## 1.2.6 — 2 October 2026

The Wrap designer can now make your book's actual cover: save a design to a
book and Send to print builds the wrap from it. It also gains undo and redo,
and pictures you can crop and zoom.

### Added

- **A wrap design is now your book's cover.** Pick a book in the Wrap
  designer and it opens with that book's trim, page count, printer and paper,
  and a starting layout that fits it. **Save to book** keeps the design with
  the book and makes it the cover: its front becomes page 1 and the ebook
  cover, and Send to print and Send to publish build the whole wrap from it,
  sized to the book's real page count, with a resolution check for every
  picture on it.
- **Undo and redo in the Wrap designer** (Ctrl+Z, Ctrl+Y), for every change:
  moves, edits, deleted layers, even Start over.
- **Crop and zoom pictures in the Wrap designer.** Zoom into a picture and
  choose which part of it shows; the printed cover crops it exactly as the
  screen does, and the resolution check accounts for the zoom.

---

## 1.2.5 — 2 October 2026

A long footnote no longer stops a book from building: it runs on to the next
page, as it would in print. And there is a first look at the wrap designer,
for laying out your whole printed cover yourself.

### Added

- **Wrap designer (beta).** A new tab for laying out the whole printed cover
  yourself: back, spine and front, at the exact size your printer needs for
  your page count, paper and binding. Drag text, colour blocks and pictures
  where you want them; blurbs wrap exactly as they will in print; and the
  checks warn you about text outside the safe zone or a spine too thin for
  text. **Proof** builds the real PDF to download. It is a first version for
  trying out: designs are kept in your browser and are not yet saved with a
  project or used by Send to print.

### Fixed

- **`run.bat` works while the installed app is open.** Running Typeset Studio
  from its folder used to fail if the installed app was already running, and
  the browser opened the installed one instead. It now takes the next free
  port (5051, 5052…) and says so in its window.
- **A long footnote runs on to the next page.** A footnote too long for the
  space at the foot of its page used to stop the whole PDF from building. Now
  it starts on the page of its reference and continues at the foot of the next
  page, under a full-width rule, the way a printed book sets a continued note.
  Notes also stay in number order when one runs on.

---

## 1.2.4 — 2 October 2026

Rich mode is safe to write in again: it no longer drops your scene breaks, and
pasting, Enter and the heading buttons now do what you expect. The Projects
page can rebuild every book in one go, and notes that cite other notes keep
their numbers.

### Added

- **Rebuild all.** The Projects page has a button that builds every book again
  with its current style and settings, one after another, showing each one as
  it finishes with its PDF and EPUB links and anything its checks found. Filter
  the page first and it rebuilds only the books you can see.

### Fixed

- **Rich mode edits safely.** A round of fixes from testing the rich editor
  the way you use it:
  - Clicking Chapter or Subhead with the cursor inside a letter, poem or
    figure no longer replaces the whole block with a heading.
  - Turning a paragraph into a subhead keeps its italics, bold, links and notes.
  - Shift+Enter no longer glues the last word of one line to the next.
  - Pasting from Word, Google Docs or a web page keeps paragraphs and list
    items apart and keeps italics, without turning a whole Google Docs paste
    bold. A copied word keeps the space after it.
  - A space typed after a note or a link is an ordinary space, not a
    non-breaking one. Non-breaking spaces already in your manuscript stay.
  - Enter at the end of a subhead starts a normal paragraph.
  - Backspace after a scene break removes just the break.
  - Enter on an empty last line leaves a letter, list or caption; in a poem,
    Enter twice starts a new stanza and a third time leaves the poem.
- **Rich mode no longer deletes your scene breaks.** Editing a book in rich
  mode saved it without any of its `* * *` breaks, and turned a `#* Prologue`
  into a numbered chapter. Both now come through. If a book lost its breaks
  this way, the History panel has the versions from before.
- **A note that cites another note keeps its number.** A note reading "See
  also [^b]" printed as "See also for more", with the number missing. The
  number now prints, and in the ebook it links to the note it names.
- **Note labels with an underscore work.** A label like `[^my_note]` could
  break the paragraph around it when that paragraph also had italics written
  with underscores.
- **A typed `\[^label]` stays literal.** Switching to rich mode turned it into
  a real endnote with an entry on the Notes page. Typing `[^label]` in rich
  mode still makes a note; it now shows as a small superscript that deletes in
  one keystroke.
- **No dead links on the ebook's Notes page.** A note the text never cites
  linked back to a spot that doesn't exist, which the ebook check flagged as
  a broken link.

---

## 1.2.3 — 22 September 2026

Your book goes out the door from here: Send to print packs the paperback for a
printer, Send to publish adds the ebook, and your own commissioned cover art now
works with both.

### Added

- **Send to print — the paperback, packed for the printer.** A printer wants the
  interior and the cover as two files, and the width of the spine depends on how
  many pages the interior turns out to have. Send to print builds them in that
  order: a press-ready interior without the cover, then a cover wrap sized to
  that interior's real page count. The zip also has a front-cover image for your
  shop listing and a `PRINT-SPEC.txt` with every check and the upload steps for
  the printer you picked. Print settings are saved with the project.
- **Cover specs for designing your own wrap.** If you're designing a cover
  outside the app, you need the wrap's exact size before you start. Every style
  now has a Cover specs page. Put in your page count, paper, binding and printer,
  and it gives you the measurements in inches, millimetres and pixels, a
  to-scale diagram, guide positions to copy into your design app, and a blank
  full-size template PDF with the bleed, spine, safe areas and barcode space
  marked. They're the same measurements the app's own designed wraps are built
  to.
- **Send to print now takes your own cover art.** A book whose cover is an
  image you uploaded — commissioned art, a designer's front — used to be turned
  away at Send to print and Send to publish, which wanted one of the built-in
  cover templates. Your art is now the front of the wrap: it runs out into the
  bleed so nothing white can show at the edge, the title overlay (if you use one)
  sits where it does in the book, and the back and spine are painted in a quiet
  colour taken from the art itself, with your blurb, imprint and the barcode
  space where they always were. The package also measures the art against the
  panel it has to fill and tells you the pixels and the dpi — the one thing about
  a commissioned cover that only shows up once it is printed — so a file that
  looked crisp on screen doesn't reach a printed proof soft. The only cover Send
  to print still refuses is no cover at all.

- **Send to publish — the whole book, both editions, in one download.** Send to
  print hands a printer the interior and the cover wrap. Send to publish, the
  button beside it, adds the ebook: the same manuscript comes out as a press-ready
  paperback in a `print/` folder and an EPUB in an `ebook/` folder, with one cover
  image that is both the picture on your shop listing and the cover readers see
  when they open the file. Because both editions are built in the same pass, the
  Kindle edition can no longer be a draft behind the paperback. `PUBLISH-SPEC.txt`
  in the package walks through both uploads — the print one and the ebook one —
  for whichever shop you picked, and the ebook’s own checks travel with it, so a
  file a shop would reject is something you hear about before you get there. If
  the ebook can’t be built for some reason, the print files still ship and the
  page says which half failed.

### Fixed

- **Photos taken on a phone print the right way up.** A phone often saves a
  photo on its side, with a note in the file saying which way is up. The app
  followed the note and showed the picture upright, but the PDF ignored it. An
  illustration, a chapter-opening picture or a picture used as a scene break
  could look fine on screen and then print on its side, stretched to the wrong
  shape. It now prints the way you see it. The ebook was never affected.
- **Grammarly and similar tools no longer write into your manuscript.**
  Grammarly, LanguageTool and ProWritingAid put their underlines and suggestion
  cards inside the text you're editing. The rich editor read some of that as
  part of your book, and autosave wrote it to the draft. It now skips anything
  those tools add. Markdown mode and the desktop window were never affected.
- **An "&" in a title no longer breaks the ebook.** A chapter called "Salt & Ash",
  a book called "Sense & Sensibility", two authors credited as "Lovelace &
  Babbage" — any ampersand (or `<`, `>`) in a title, subtitle, author, publisher,
  part title or Also By entry made most of the EPUB's pages malformed: the
  contents, the navigation, the chapter itself and the book's own metadata. Shops
  reject a file like that, and a strict reader won't open it. Body text was never
  affected, and neither was the PDF.
- **A link on a front-matter page can no longer cost you the whole book.** An
  "Also by this author" page (or a dedication, acknowledgements, contributors
  note — any matter page) that linked to a chapter which had since been renamed
  or removed stopped the PDF from building at all, with an error that named
  neither the page nor the link. The link now quietly becomes plain text and the
  broken target is listed in the build report, exactly as it already was for a
  link inside a chapter.
- **Bold italic on a front-matter page no longer breaks the ebook.** Writing
  `***like this***` in a dedication or an Also By list produced an EPUB that
  strict readers and the validator refuse — the page was malformed. `___like
  this___` had a second problem: it printed its underscores instead of setting
  the words bold italic. Both now match what the PDF has always done.
- **A book of verse is no longer told every chapter is empty.** The continuity
  check called any chapter "Empty" unless it had loose paragraphs, so a poem, a
  letter, a table or a quotation standing as the whole chapter counted for
  nothing — and a poetry collection was flagged from end to end. A chapter with
  genuinely nothing in it is still reported.
- **The continuity check reads verse and tables properly.** It was running the
  words either side of a line break or a cell divider together, so "Ada |
  Lovelace" was read as "AdaLovelace" — which could then be offered as a
  misspelled character name, and was what got sent for the deeper analysis.

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
