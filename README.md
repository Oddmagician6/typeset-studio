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
**Set a book** in that style, **Edit** it, **Duplicate** it, or **Delete** it.
Use **New style** to start one from scratch.

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
| `## Subhead`       | a section subhead             |
| `* * *` (own line) | a scene break                 |
| `~~~` … `~~~`      | an epistolary / document block|
| `~~~ figure src="map.png"` … `~~~` | an illustration; the block's text is its caption |
| `~~~ list` … `~~~` | a bulleted list — one item per line |
| `~~~ quote` … `~~~` | an inset quotation |
| `~~~ center` … `~~~` | a centred block (also `right`, `left`) |
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
| a table | a set-apart block, one row per line (there is no table layout yet) |
| Quote / Intense Quote | a quotation block |
| a bulleted or numbered list | a list block |
| a centred paragraph | a centred block |
| a hyperlink | its words (the web address is dropped) |

After importing, the app tells you exactly what came across and what didn't — nothing
is dropped silently. Footnotes and endnotes are **not** imported yet; you'll be told how
many were found. Images land in your Figures library, named after the Word file, so
re-importing the same document doesn't pile up copies.

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

## Handing off to print

The interior PDF embeds and subsets its fonts, which is what KDP and IngramSpark
require. Before uploading, still confirm per platform:

- **Trim size** matches the book you set up on the platform.
- **Inside (spine) margin** is generous enough for the page count (longer books need more).
- Cover is a **separate** file (this tool sets interiors only).

---

## Folder map

```
typeset_studio/
  run.bat            double-click to start (Windows)
  app.py             the web app
  engine.py          the typesetting engine
  manuscript.py      reads .md / .docx into chapters
  requirements.txt   what to install
  presets/           one .json per style  <- your per-customer styles live here
  fonts/             .ttf files used by styles
  figures/           illustrations placed with ~~~ figure src="…"
  sample/            a sample manuscript for trying styles
  out/               composed PDFs land here
  uploads/           manuscripts you upload (created on first use)
```
