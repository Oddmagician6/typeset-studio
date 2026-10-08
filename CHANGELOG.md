# Changelog

What changed in each release, in the words of someone using the app rather than
building it. The version lives in the `VERSION` file — the app, the `.iss` and the
build script all read it, so the installer and its filename can never disagree with
what the About page reports; `ROADMAP.md` has the engineering record behind every
line here.

---

## Unreleased

### Fixed

- **Word files import with their bold and italic intact.** A bold or italic
  phrase whose run ended in a space, which is how Word usually stores a name
  like "***Keen Smell.***" before the text after it, came in with its
  closing marks in the wrong place, and the book printed stray asterisks: two
  for every trait and action in a stat block. An italic phrase Word had split
  into pieces did the same. Both now come in as the emphasis they were.
- **A Word file with no "Normal" style imports.** Documents made by some
  tools rather than by Word itself don't define one, and importing them
  stopped with an error. Their unstyled paragraphs now import as body text.

## 1.3.2 — 7 October 2026

A small fix for print covers: a designed cover’s art, colour and bands now run
right out to the edge of the print wrap, so nothing from underneath can show at
the edge of the finished book when the cut wanders.

### Fixed

- **A designed cover's art runs to the edge of the print wrap.** On a print
  wrap, a cover template's background picture, vignette and overlay, and the
  flat colour and bands of the geometric, stripe and postcard designs, stopped
  at the trim. The eighth-inch bleed round the front cover, and a hardcover's
  turn-in, showed the plain gradient underneath, so a sliver of it could appear
  at the edge of the finished book when the cut wandered. They now run out to
  the edge of the sheet, as uploaded cover art already did. The front cover
  looks the same once trimmed.

## 1.3.1 — 6 October 2026

A release of fixes from a bug hunt through the whole app, page by page. Work saved
by older versions opens as it was meant; long books save, and the same book open in
two tabs no longer loses words; uploads, deletes and a damaged data folder are
handled with care and say what they did; large print, the ebook and the style editor
do what they show; the continuity check reads the whole book and only asks Claude
when you do; and the wrap designer’s edges - locked boxes, small barcodes, undo -
behave.

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
- **Cover templates damaged by the old cover editor get their look back.**
  Before 1.3.0, saving a geometric, typographic, vintage, minimal, stripe or
  postcard cover in the editor dropped that design's own settings, so it
  quietly fell back to plain defaults. A bundled template, or a copy of one
  still named "… (copy)", now has what it lost restored from the original -
  only what was missing, never anything you changed. (A vintage cover's
  accent colour, which the old editor switched to gold, is left as it is.)
- **Long books save.** The writing page couldn't save a manuscript past about
  100,000 words: every save was refused, and the page only said "Save
  failed". Books of any length save now.
- **The same book open in two tabs no longer loses work.** The tab that saved
  last silently wrote over the other's changes. Now a tab that is behind stops
  saving and says so, keeps what it has in History, and lets you choose: open
  the saved version, or keep this one (the other then goes to History). The
  same happens if the manuscript is replaced on the Edit page while the
  writing page is open.
- **Nothing typed is lost on leaving the writing page.** Leaving within half a
  second of typing in rich mode, or straight after an edit to a book longer
  than a few chapters, could lose the edit. Typeset, Book settings and
  Projects now save before they go; any other way out saves too or, when a
  book is too long to send while closing, asks first.
- **Typeset builds what is on the page**, including the sentence just typed;
  it used to build the last autosave.
- **A save that fails is tried again**, and the page says why, instead of
  showing "Save failed" once and giving up.
- **Going back to an earlier version keeps unsaved typing** in History rather
  than dropping it.
- **Typing in a long book in Markdown mode is about twice as quick:** the
  word count and chapter list wait for a pause, and only the changed lines are
  repainted.
- **Smaller fixes on the writing page:** the Table button works in Markdown
  mode; Ctrl+F in rich mode finds what was just typed (it searched the text
  from before the last edits); and the word count counts words in Cyrillic,
  Greek and other scripts while you type (it showed none until the page was
  reloaded).
- **Saving a book's settings no longer changes what you didn't touch.** If a
  book's style or cover template had been deleted, the Edit page quietly
  switched it to the first style, or to no designed cover; it now keeps it
  and says it's missing. The same for a printer, paper, format or other
  choice the page doesn't list.
- **Text files in other encodings read as written.** A manuscript saved as
  Windows "ANSI" lost its accents and curly quotes, a "Unicode" (UTF-16) one
  came out as noise, and a UTF-8 file with a byte-order mark lost its first
  chapter heading. All three now read correctly, in every place a
  manuscript is opened - including books already saved that way.
- **Files named in other scripts upload.** A Word file called "Роман.docx"
  lost its extension on the way in and was read as plain text; a cover,
  figure or font with such a name was refused. All of them now upload.
- **The Edit page checks what you upload, and says when it won't take it:**
  a manuscript that isn't a .docx, .md or .txt file (or is empty, or a Word
  file that won't open), and a cover or back-cover image that isn't a real
  .jpg or .png picture. Everything else on the page still saves.
- **Customise, Write and the Wrap designer links save your changes first.**
  They used to leave the Edit page and lose them; leaving any other way with
  unsaved changes now asks first (Cancel still discards).
- **The back-cover image's width and position** can no longer be saved as
  nonsense (letters, "nan", negative) - a value that isn't a number keeps the
  old one, and out-of-range values are brought into range.
- **A book's settings are saved all at once**, so an interrupted save can no
  longer leave a half-written file that no page can open.
- **Saving a Set-a-book result as a project keeps the right manuscript.**
  Uploads were stored under their own file names, so setting a second
  "book.docx" before saving the first result gave the first project the
  second book's text. Each upload now keeps a file of its own.
- **Set a book and its previews check what you give them:** a file that isn't
  a manuscript (a PDF, say), an empty one, a Word file that won't open or has
  no words, and cover art that isn't a real .jpg or .png are refused with a
  message saying which, instead of building nonsense or failing halfway. A
  cover file left in the picker is ignored when the book uses a designed
  cover.
- **Books titled in other scripts get sensible names.** A book called "Война
  и мир" was saved as a project named "style" and built as
  "style-….pdf"; it is now "book", and a draft "draft". Accented titles keep
  their letters ("Été" is "ete", not "t"). The same fix names cover and wrap
  downloads.
- **Typesetting a book whose style is missing says so** - a draft made before
  any style existed, or a book whose style was deleted - instead of showing a
  bare "Not Found" page. Send to print says the same.
- **Save as project only takes files from Set a book's own uploads.** It
  copied whatever file the page named.
- **Fonts change when you change them.** The app held on to the first font
  it had used under a name until it was restarted: a cover template given
  new fonts kept the faces of the first cover drawn that session, a style
  whose fonts were changed but whose family name stayed kept its old ones, and
  a font file replaced in the library was still printed (and measured in the
  Wrap designer) as the old one. Each font is now its own file, as it is now.
- **Covers and books drawn at the same time keep their own fonts** - the
  cover gallery draws many at once, and could print one cover in another's
  faces. Two ebooks exported at once kept their own in-book links too; one
  could point into the other's chapters.
- **A save made while a book builds is kept.** Typeset and Send to print
  wrote the book back as it was when they started, so settings saved or the
  first writing-page save of a Word book made meanwhile in another tab were
  undone (the book then showed its old text). A book deleted while it built
  no longer comes back.
- **Two builds of a book in the same second write two files**, rather than
  both writing one; a build that fails leaves no empty file behind.
- **Snapshots taken at the same moment each keep their own text** in History.
- **A broken font uploaded under a name a good font once had** is refused, as
  any broken font is.
- **Uploading to the Fonts or Figures page never loses what is there.** A
  broken file uploaded under the name of a good one deleted the good one, and
  a different picture or font under a name already in use replaced it - in
  every book that used it. A different file now goes in beside it ("map-2.png",
  and the page says so); the same file again is simply the one already there.
- **Removing a font or figure that something uses asks first, and says
  what:** the styles, cover templates, wrap designs and books that name it.
- **What went missing is in the checks.** A book whose figures or cover
  fonts have left the library says which, on Typeset and in Send to print -
  a missing figure printed only as a grey box. A wrap design's text whose font
  is gone isn't printed at all, title included; the Wrap designer and the
  print package now say so, and the designer's font picker shows the missing
  font instead of the first one in the list. Pictures gone from a wrap design
  are named too.
- **A picture too big to print** (hundreds of megapixels) is refused with
  that reason, not as "not a readable image".
- **Fonts and figures with spaces or quotes in their names** (put in the
  folder by hand) can be shown and removed; a quote in a font's name no
  longer let Remove skip its "are you sure?".
- **Large print is large throughout.** A large-print style set the body at
  16pt, but the title page, the copyright page (8.5pt), the epigraph and the
  letters, telegrams and newspaper cuttings kept their own smaller sizes. Now
  nothing to read is set under 16pt (running heads and page numbers keep
  their own), and the copyright page, now larger, still fits on its page. The
  style editor shows this as **Smallest text**, under Body text, so it can be
  changed - and it is no longer lost when a large-print style is saved.
- **Letters, journals, telegrams, newspaper cuttings and redacted files with
  "&" or "<" in their headers** (`from="A & B"`) print as typed. The PDF
  dropped anything in angle brackets, and the ebook's chapter came out
  malformed - a store would reject the file.
- **Two chapters with the same title can each be linked to.** They shared
  one link name, so the second couldn't be reached, and the PDF and the ebook
  disagreed about which chapter a link went to. The first keeps its name
  (`#1984`); the next is `#1984-2`.
- **Delete always asks first.** A book, style or cover template with an
  apostrophe or quote in its name ("O'Brien's Road") was deleted at once,
  without the "are you sure?" - and a deleted book can't be brought back.
- **Deleting a book takes everything that was only its own** - its History,
  back-cover image, wrap front and thumbnail too, not just the manuscript and
  cover. A new book later given the same name used to inherit the old one's
  History, where Restore offered the deleted book's text. Files another book
  also uses are kept, and so are the PDFs and packages it built.
- **Deleting a style or cover template that books use says which books, and
  asks.** Afterwards those books say what's missing: a book whose cover
  template was deleted used to build with no cover and no word about it.
- **Cover gallery tiles stay current**: they are redrawn when a font they use
  leaves the library or after an update that draws covers differently, not
  only when the template is edited.
- **A new book, style or template never takes the name of a file that is
  there but damaged**, which it would have saved over.
- **A damaged file no longer breaks the app.** One cover template that
  couldn't be read made nearly every page fail ("Internal Server Error"), and
  one odd book took the whole Projects page down. Now each page opens. A
  damaged book, style or cover is named on its list page, and opening it shows
  which file is wrong and how (cut short by a crash, empty, edited by hand…).
- **Repair**, offered beside a damaged file, keeps every setting that can
  still be read, sets the rest to their defaults, and keeps the damaged file
  next to it. A book's manuscript is a separate file and stays safe; the
  repaired book uses it again.
- **Files saved from Notepad read as written**: a byte-order mark or Windows
  accents in a settings file no longer make it unreadable.
- **A full disk or a read-only file says so**, naming the file, instead of
  failing with a bare error page. The writing page shows the reason and keeps
  trying.
- **Styles and cover templates save all at once**, as books already did, so a
  crash mid-save can't leave an empty file.
- **Pictures that won't open are reported**: a figure, cover art, an uploaded
  cover or a wrap-designer picture that is damaged or isn't an image now shows
  in the checks (an uploaded cover that has gone missing too). A wrap with such
  a picture couldn't be sent to print at all; it now goes without the picture
  and says so.
- **Books with very long names can be made.** A long title gave file names
  past Windows' limit, and the book couldn't be created; file names are now
  cut short at a word, and the book keeps its whole name.
- **Deleting a style or cover template that came with the app sticks.** It
  used to come back the next time the app started. The Styles and Covers pages
  now list the ones you deleted, with a **Restore defaults** button that brings
  them back (it doesn't touch the ones you've edited).
- **Three of the bundled styles couldn't be saved.** Mass market, Modern clean
  and Science fiction & fantasy opened in the style editor, but Save did
  nothing except point at a field ("enter 0.34 or 0.36"). Neither did any style
  after picking one of five standard trims from the list (6.14 × 9.21 and
  others). Save now always saves, and each number is kept to a sensible range
  instead: a body size typed as 0 no longer makes a book of invisible text.
- **The standard-size list shows the trim a style has.** 5 × 8, 6 × 9, 7 × 10,
  8 × 10 and 8.25 × 11 reset the list to "Choose a trim…".
- **Clicking a scene-break ornament uses it.** On a style whose scene breaks
  were a text glyph, picking an ornament tile changed nothing in the book until
  the Type list was changed too. The tile now sets it, as does picking a picture.
- **A scene break can be your own picture from the Figures page.** The field
  wanted a file in the fonts folder, where the app had no way to put one.
  Styles that already use a picture there keep it. A missing scene-break
  picture is now in the checks (scene breaks print the glyph instead), and
  deleting a picture a style uses says so first.
- **The style editor says what's missing.** A font or chapter-art file that's
  no longer in its library is marked "(not in your … library)" in its list, and
  Preview names what it drew without, where it used to fall back to Times in
  silence.
- **The continuity check finds misspelt names anywhere in the book.** It only
  ever compared the first couple of hundred capitalised words, so in a novel a
  name spelt differently after the first few chapters was never noticed.
- **The continuity check's Claude analysis runs only when you ask.** With an
  Anthropic API key set, it used to send the start of every chapter to
  Anthropic each time you opened the report. Now there's an "Ask Claude as
  well" button, which says what will be sent.
- **Pages no longer wait on the update check.** With update checks on, a page
  could take several seconds to open while the app asked for the latest
  version - and while offline, every page did. The check now runs in the
  background, and after a failed one it waits an hour before trying again.
- **A style that can't fit its page says so in words**: "A space on page 2
  doesn't fit in the room a page has for text…", not a message about
  `Flowable <Spacer at 0x…>`.
- **Wrap designer: a locked element can't be resized by accident.** Locking
  stopped a drag but not the orange resize corner, so the locked barcode box
  could still be pulled out of shape.
- **Wrap designer: a barcode box made too small says so.** Shrunk with an ISBN
  in it, the bars came out upside down over the digits. Now a box too small for
  bars says how big to make it, and one small enough that the barcode may not
  scan is flagged in the checks.
- **Wrap designer: each action is its own undo.** Typing and then adding a
  preset, or adding something and nudging it straight away, made one undo step,
  so Undo took both back. Deleting several things at once still undoes in one.
- **Wrap designer: Save says why a very large design was refused.** Past 400
  elements it said "That design could not be read"; it now says how many it
  has, and the checks say so before you save.
- **Wrap designer: the Pages arrows step by 2**, not by 10 from 24 (24, 34 …
  324).

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
