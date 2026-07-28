# Typeset Studio

A small, private tool for setting print-ready book interiors. It runs on your own
computer, opens in your browser, and turns a manuscript into a typeset 6×9 (or any
trim) PDF with the fonts embedded — ready for KDP or IngramSpark.

It is built around **styles**: a style is the complete typographic recipe for a
book's interior (trim, margins, body type, chapter openings, scene breaks, running
heads, page numbers, fonts). You build a style once, then **duplicate it per customer**
and tweak only what that book needs.

---

## Running it (Windows)

1. Make sure **Python 3.10+** is installed. If not, get it from
   <https://www.python.org/downloads/> and tick **"Add Python to PATH"** during setup.
2. Double-click **`run.bat`**.
   - The first run sets up a private workspace and installs what it needs (about a minute).
   - Every run after that starts immediately.
3. A browser tab opens at <http://127.0.0.1:5050>. Keep the little black window open
   while you work; close it to stop the tool.

Running it any other way (Mac / manual):

```
python -m venv .venv
.venv\Scripts\activate        (Windows)   or   source .venv/bin/activate   (Mac/Linux)
pip install -r requirements.txt
python app.py
```

---

## Using it

**Styles** (the home page) lists every style as a spec card. From a card you can
**Set a book** in that style, **Edit** it, **Duplicate** it, derive a **Large print**
edition of it, or **Delete** it. Use **New style** to start one from scratch.

**Large print** makes a second style from the one you're looking at, following the
RNIB/NAVH guidance: 16pt minimum, generous leading, ragged right (justified text opens
rivers that are much harder to track), no hyphenation, wider margins, and a 7 × 10"
page — 16pt type in a mass-market trim would give about six words a line. It's an
ordinary style afterwards, so tweak it like any other, and your original is untouched.
One book, two editions.

The style editor's **Standard sizes** list covers the trims KDP and IngramSpark accept;
picking one fills in the width and height. A non-standard size is still allowed — just
type it.

**Set a book**:
1. Pick a style.
2. Add the manuscript — upload a `.docx`, `.md`, or `.txt` file, paste the text, or
   tick *Use the bundled sample* to try a style.
3. (Optional) Add **cover art** — see below.
4. Fill in the title page and choose how much **front matter** you want.
5. **Compose the book.** You'll get a page to open the PDF or download it.

Composed files are saved in the `out/` folder as well, named by title and timestamp.

### Blank pages and front matter

On the *Set a book* page you control the pages before your story:

- **Front matter** — choose *Half-title, title page, copyright* (the traditional set),
  *Title page + copyright*, *Copyright page only*, or *None* to open straight on the story.
- **Add blank pages so each part starts on a right-hand page** — on by default, because
  that's how printed books are laid out (it's why a title page often has a blank facing
  it). **Uncheck it for no blank pages at all** — handy for short works or screen reading.

The story always begins numbering at page 1, however much front matter you include.

### Cover art

Optionally drop in a **cover image** (`.jpg`/`.png`). It becomes a full-bleed first page,
cropped to your trim. Two ways to use it:

- **Art already has the title on it** — leave *Print the title and author over the art*
  unchecked, and the image prints exactly as supplied.
- **Plain art** — check the overlay box and the tool prints the title and author over the
  image, in the book's own type. Pick *light* text for dark art, *dark* for light art.

This cover is meant for proofing or an all-in-one PDF. Print platforms (KDP, IngramSpark)
still want the cover uploaded as its own file with bleed — keep doing that separately.

### Manuscript markup

The tool reads a light, plain-text convention:

| You write          | You get                       |
|--------------------|-------------------------------|
| `=== Part title`   | a part divider page           |
| `# Chapter title`  | starts a new chapter          |
| `#* Prologue`      | a chapter with no number      |
| `## Subhead`       | a section subhead             |
| `* * *` (own line) | a scene break                 |
| `~~~` … `~~~`      | an epistolary / document block|
| `~~~ figure src="map.png"` … `~~~` | an illustration; the block's text is its caption |
| `~~~ list` … `~~~` | a bulleted list — one item per line |
| `~~~ quote` … `~~~` | an inset quotation |
| `~~~ center` … `~~~` | a centred block (also `right`, `left`) |
| `~~~ table` … `~~~` | a table — one row per line, cells split on `\|` |
| `[text](https://…)` | a link (also `mailto:` and `#in-book` targets) |
| `[^label]` … `[^label]: text` | an endnote reference and its text |
| `*italic*`         | *italic*                      |
| `**bold**`         | **bold**                      |
| blank line         | new paragraph                 |

### Word files

A `.docx` is converted to the same convention on import:

| In Word | You get |
|---------|---------|
| Heading 1 / Title | a new chapter |
| Heading 2, 3, … | a subhead |
| **bold** / *italic* runs | inline emphasis |
| a centred `* * *` line | a scene break |
| an image | a figure, with a following *Caption* paragraph as its caption |
| a table | a real table, columns intact (a `\|` inside a cell becomes `/`) |
| Quote / Intense Quote | a quotation block |
| a bulleted or numbered list | a list block |
| a centred paragraph | a centred block |
| a hyperlink | a link, address and all |
| a footnote or endnote | an endnote, its text collected in the same chapter |
| a Verse / Poem / Poetry paragraph style | a poem block, verse lines kept |
| manual line breaks (Shift+Enter) | a line-preserving block, so the breaks survive |

After importing, the app tells you exactly what came across and what didn't — nothing
is dropped silently. Images land in your Figures library, named after the Word file, so
re-importing the same document doesn't pile up copies.

A few things are worth knowing:

- **Notes.** Word footnotes and endnotes both become endnotes here — where they *print*
  is the style's choice, under *Notes* in the style editor, so the same import can give
  you a book with notes at the foot of the page or a Notes page at the back.
- **Links.** A web or email address comes across. A link to a bookmark or a file on your
  computer keeps its words and loses the address, and you're told how many.
- **Verse.** Word has no verse element, so a paragraph *style* named Verse, Poem or
  Poetry is the only signal trusted. Consecutive verse paragraphs become one poem, one
  stanza each.
- **Line breaks.** A manual break is you saying "break here", so those lines are kept
  rather than run together — in a block that changes alignment only, not the type.

### Prologues, epilogues and other unnumbered chapters

A prologue isn't a separate kind of page — it's a chapter that takes no number:

```
#* Prologue
```

Write `#*` instead of `#` and the chapter gets no number, **and doesn't use one up**
— the chapter after a prologue is still Chapter One. Same for an epilogue, an
interlude or a coda. Everything else works normally: it appears in the contents,
can take a byline, and can hold notes and figures.

### The pages around your book

Each of these is a box on the *Set a book* page. Fill one in and it becomes its own
page, in the right place, automatically:

- **Front:** Dedication · Epigraph · Foreword · Preface · Introduction
- **Back:** Notes (automatic — see below) · Afterword · Bibliography ·
  Acknowledgments · Contributors · About the Author · Also by … · Praise

### Endnotes

```
The plateau was surveyed twice.[^survey] The second disagreed.[^second]

[^survey]: Ferrun Cartographic Office, *Survey of the Salt Road*, 1891.
[^second]: The disagreement was never formally settled.
```

Put `[^label]` where the reference belongs and `[^label]: …` as its own paragraph
anywhere in the same chapter — usually at the end. The label is just your handle for
the note; **numbers are assigned automatically** in reading order and **restart each
chapter**, and a **Notes** page is added after the last chapter. There is nothing to
switch on: write a note and the page appears.

- Cite the same note twice and it keeps one number.
- A reference with no matching text still gets a number, and the Notes page says
  `[no note text]` rather than quietly dropping it.
- A note you wrote but never referenced is kept too, numbered last.
- In the ebook the number links to the note, and the note links back to the sentence.

### Footnotes or endnotes — same writing, two placements

Under *Notes* in the style editor, choose where they go:

- **Endnotes** — a *Notes* page at the back, grouped by chapter (the default).
- **Footnotes** — at the foot of the page the reference is on, under a short rule.

You write them the same way either way, so you can try both and keep whichever suits
the book. Heading, grouping, sizing and the footnote rule all live in the style.

One limit worth knowing: a footnote has to fit on the page its reference is on. If a
page's notes are longer than the page can hold, the surplus can't be placed — the
build tells you how many, so you can shorten them or switch to endnotes. Nothing is
ever dropped silently. In the **ebook** notes are always endnotes, linked both ways;
an ebook has no pages to put a footnote at the bottom of.

### Links

```
Find the rest at [ashforgestudio.com](https://ashforgestudio.com/books),
or write to [the studio](mailto:hello@example.com).

The route is described again in [the second chapter](#the-plateau).
```

Links work in **both** outputs — clickable in the PDF, real links in the EPUB. This
matters most on the *Also By* and *About the Author* pages, where a reader tapping
your newsletter link is the whole point.

Three kinds of target are recognised, and only these — so ordinary prose like
`[sic](ibid)` is never mistaken for a link:

- `https://…` or `http://…`
- `mailto:…`
- `#in-book` — either `#chapter-2` or the chapter title's slug, e.g. `#the-plateau`

To type a literal bracket that would otherwise start a link, escape it: `\[`.

In print, links are **clickable but unstyled** by default: no colour, no underline,
because a POD interior is usually black and a blue link looks like a mistake on paper.
The style can turn on a print underline, and set the ebook's link colour separately —
see *Lists, quotations, alignment & links* in the style editor.

One limit: a link in a chapter's **first paragraph** is dropped when the style uses a
drop cap, raised initial or small-caps lead-in. Those openings re-set the first words
as plain text, so any markup in them goes; the words survive, the link doesn't. Put
links in a later paragraph, or use an opening style of *None*.

### Lists, quotations and aligned passages

```
~~~ list
Salt, four measures a head
Rope, tarred, two coils
~~~

~~~ list type="number" start="3"
Load the mules before dawn
~~~

~~~ quote source="Berrin of Ferrun"
The plateau does not kill travellers. It simply
declines to help them.
~~~

~~~ center
NO WATER BEYOND THIS POINT
~~~
```

A **list** and an **aligned block** are line-oriented: one item, or one line, per line
of the source. A **quotation** is prose — lines wrap together and a blank line starts a
new paragraph, exactly like body text. `~~~ right` and `~~~ left` work like `~~~ center`.

Alignment blocks change *alignment only*; the style still owns size, face and leading.
Everything else about how these look — bullet character, indents, quote size, the source
line — lives in the style, under *Lists, quotations & alignment* in the style editor.

### Tables

```
~~~ table caption="Recorded yields, 1897" align="left,right,right"
Region     | Wheat | Barley
Northmarch | 1,240 | 880
Salt Coast |   960 | 1,105
~~~
```

One row per line; cells are separated by `|`. Spacing around the pipes is up to you —
line them up in the source if it helps you read it, or don't.

The **first row is the header**: it is set apart and it repeats at the top of every
page a long table runs onto. Write `header="no"` if the table has no header row.

Optional attributes:

- `align="left,right,right"` — alignment per column. A short list repeats its last entry.
- `widths="3,1,1"` — relative column widths. Left out, widths are measured from the
  content, and no column is ever squeezed narrower than its longest word.
- `caption="…"` — a caption above the table (book convention; figure captions go below).

Emphasis and links work inside a cell. A cell cannot contain a literal `|` — that
character always starts a new column.

Everything else — size, rules, cell padding, header style, caption style — lives in the
style, under *Tables* in the style editor.

### Illustrations

Upload images on the **Figures** page (or with the **Figure** button in the manuscript
editor, which uploads and inserts in one step), then place one anywhere in the text:

```
~~~ figure src="map.png" alt="Map of the plateau"
The plateau, as surveyed in the third year.
~~~
```

The block's text is the caption — leave it empty for no caption. Per-figure options on
the opening line:

- `width="0.5"` — fraction of the text width (default comes from the style)
- `align="left"` / `"center"` / `"right"`
- `full="yes"` — give the figure its own page

Caption size, style and spacing belong to the **style**, under *Figures* in the style
editor, so every illustration in a book matches. If a `src` can't be found, the page
shows a labelled placeholder box rather than silently dropping the picture.

---

## Building a style per customer

The fastest workflow:

1. Start from the closest existing style and click **Duplicate**.
2. Rename it for the customer (e.g. *"Aldren series — J. Marsh"*) and add a one-line
   description so future-you remembers when to use it.
3. Change only what that book needs and **Save changes**.

Styles are just plain text files in the **`presets/`** folder (one `.json` per style).
You can back them up, copy them between machines, or hand a customer's style to a
colleague by sending the single file. Drop a `.json` into `presets/` and it appears in
the tool automatically.

### Scene-break ornaments

Between two scenes a book prints a small mark. A style can set that mark three ways,
in the editor's **Scene breaks** section:

- **Text glyph** — characters you type, e.g. `* * *`, `—  —  —`, `·  ·  ·`. Make sure
  the style's font actually carries the character you pick.
- **Bundled ornament** — one of **twelve drawn marks** that ship with the tool: swelled
  rule, double rule, dotted rule, diamond rule, lozenge, three lozenges, six-point star,
  asterism, wave, arabesque, ivy leaf and leaf pair. Click one in the picker; the tile
  shows exactly what will print. They are **drawn, not photographed** — so they stay
  sharp at any size, need no font, and come out identical in the PDF and the ebook.
- **Your own image** — a PNG or JPG in the `fonts/` folder, for custom artwork.

Each ornament has a width that suits it (a swelled rule runs nearly half the text
width; a lozenge is a few millimetres). **Ornament width** overrides that as a
fraction of the text width — `0.25` is a quarter of the column. Leave it at `0` to
use the ornament's own. Height always follows the width, so an ornament can never
squash or stretch.

### Chapter-opening art

A style can print one illustration at the top of **every** chapter — a rule, a crest,
a small drawing — from the editor's **Chapter openings** section:

- **Image** — anything in your figure library (upload it on the **Figures** page; a
  transparent PNG sits best on the page). *None* means plain openings, which is what
  every style does until you choose one.
- **Position** — above the chapter number, or below the title.
- **Width** — a fraction of the text width; `0.32` is about a third of the column.
  The height follows the picture's own proportions, so it can never squash or stretch.
- **Space** — inches between the art and the heading.
- **Maximum height** — inches; a tall picture is scaled down to fit rather than
  crowding the page. The art can never take more than half the text height.

The art is a *style* setting, so it repeats on every chapter and no chapter carries
markup for it. Placed above the number, it pushes the heading down by its own height —
if you want the title to stay where it was, take the same amount off the **sink**. Art
does not appear on part-divider pages. If the file goes missing, the PDF prints a
labelled placeholder box (so you see it in the proof) and the ebook simply opens
without it. In the ebook the picture is stored once and marked decorative, so a
screen reader doesn't announce it at the head of every chapter.

The three starting styles:

- **Classic Literary (6×9)** — warm, traditional novel interior; a good default.
- **Gothic / Horror (5.5×8.5)** — tighter trim, denser page, sunken drop-cap openings.
- **Modern Clean (6×9)** — airy and contemporary, centered folios, no running heads.

---

## Fonts

The tool ships with **seven book serifs**, each with a regular, bold and italic:

| Family | Registered as | Used by |
|--------|---------------|---------|
| Libre Baskerville | `Book` | Modern Clean |
| EB Garamond | `EB Garamond` | Classic Literary |
| Vollkorn | `Vollkorn` | Gothic / Horror |
| Alegreya | `Alegreya` | Fantasy (Epic), Science Fiction & Fantasy |
| Crimson Pro | `Crimson Pro` | Mass Market Paperback |
| Lora | `Lora` | Romance / Women's Fiction |
| Spectral | `Spectral` | Thriller / Crime, Science Fiction (Clean) |

All seven are under the SIL Open Font Licence — free to use and to embed in a book
you sell. The licence texts are in `fonts/licenses/`.

In a style's **Fonts** section you can point to your own typefaces two ways:

- A **filename** (e.g. `Book-Regular.ttf`) is looked up in the `fonts/` folder — drop
  new `.ttf` files there.
- A **full path** (e.g. `C:\Windows\Fonts\Georgia.ttf`) is used directly.

Use fonts you are licensed to embed. If a file can't be found, the tool falls back to a
standard serif so a build never fails outright — but check the **Fonts** fields if type
looks wrong.

---

## Seeing the book before you build it

The *Set a book* page has two preview buttons, one per output:

- **Preview first pages** shows the printed interior as page images — the type,
  the margins, the chapter opening.
- **Preview the ebook** shows the *same book reflowed*, at phone, e-reader and
  tablet widths. Text has no fixed page in an ebook, so this is the only honest
  way to see it: switch device and watch the lines rewrap.

The ebook preview is built from the real EPUB and its own stylesheet, so what you
see is what a reader gets rather than a re-rendering of it. Both previews show the
first two chapters and persist nothing.

## Checking the ebook

Every EPUB you build is opened again and checked before you see the result page, and
the findings appear as an **EPUB preflight** card next to the print one. It looks for
the things that actually break in readers or get a file rejected by a shop:

- the container is laid out the way the spec requires
- every file is declared, and everything declared is present
- the reading order is intact and a navigation document exists
- every page is well-formed XHTML
- every illustration carries alt text
- every in-book link lands somewhere real
- the cover is declared for both modern and older readers
- accessibility metadata is present — shops increasingly require it

**Optional:** if you want the reference validator too, put `epubcheck.jar` beside the
app (or set `EPUBCHECK_JAR` to its path) and have Java installed. It runs after the
checks above and adds its own line. Without it nothing is lost — the checks above are
ours and always run.

## Handing off to print

The interior PDF embeds and subsets its fonts, which is what KDP and IngramSpark
require. Before uploading, still confirm per platform:

- **Trim size** matches the book you set up on the platform.
- **Inside (spine) margin** is generous enough for the page count (longer books need more).
- The cover is a **separate** file — build it in the Cover Studio (below), or bring your own.

### The print wrap — paperback or hardcover

In the **Cover Studio**, the *Print wrap* section exports one flat cover PDF: back, spine
and front in a single page, sized for the printer. Pick the **binding**:

- **Paperback (perfect bound)** — bleed + back + spine + front + bleed. The spine comes
  from the page count and paper, so build the interior first and pull the page count in
  with **From a book**.
- **Hardcover (case laminate)** — the same three panels plus two allowances the press
  needs: the **wrap** (turn-in), 0.625" glued around the boards, and a **hinge** each side
  of the spine, 0.375", where the case bends open. The spine also carries a **board
  allowance** on top of the paper. So the page is
  `wrap + bleed + back + hinge + spine + hinge + front + bleed + wrap` across and
  `wrap + bleed + trim + bleed + wrap` down — a 200-page 6×9 comes out at 14.76 × 10.5".

- **Dust jacket** — the paper jacket that goes *over* a hardcover, so it is measured off
  the finished case rather than the pages: panels are the **board** (trim plus a board
  extension, 0.125", on the fore-edge and at head and tail), with a folded **flap** at each
  end (3.5" is the usual house figure). Laid flat, printed side up, the order is back flap,
  back, spine, front, front flap — each flap folds in behind the cover it adjoins.

Nothing that must be seen may sit in the turn-in or the hinge: the turn-in disappears
around the board, and printed detail in the hinge cracks as the cover flexes. Tick
**Proof guides** to see them — magenta for panels and folds, blue for the turn-in — and
untick it before you upload.

**Flap copy.** A jacket adds two text boxes. The **front flap** takes the jacket blurb
(the hook), under the book's title; leave it blank and the back-cover blurb moves there
instead, and the back panel drops it so the same paragraph isn't printed twice on one
jacket. The **back flap** takes an *About the author* note — and the back-cover image moves
there too, because on a jacket the author photo belongs on the flap. Set a front-flap blurb
of its own and the back panel keeps its own text, which is where reviews usually go.

Every allowance is editable, because printers differ. The defaults are the numbers KDP and
IngramSpark publish; **always confirm against the retailer's own downloadable cover
template** for your trim. KDP's hardcover programme is narrower than its paperback one —
75–550 pages, white paper, and five trims — and the wrap preview says so if the book you've
set up falls outside it. KDP doesn't print dust jackets at all; the preview says that too.

---

## Folder map

```
typeset_studio/
  run.bat            double-click to start (Windows)
  app.py             the web app
  engine.py          the typesetting engine
  manuscript.py      reads .md / .docx into chapters
  ornaments.py       the twelve drawn scene-break ornaments
  requirements.txt   what to install
  presets/           one .json per style  <- your per-customer styles live here
  fonts/             .ttf files used by styles
  figures/           illustrations placed with ~~~ figure src="…"
  sample/            a sample manuscript for trying styles
  out/               composed PDFs land here
  uploads/           manuscripts you upload (created on first use)
```
