"""Round-trip tests for doc_model  (run: python test_doc_model.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

Asserts, over sample.md + every real manuscript and a set of adversarial models:

    ENGINE FIDELITY   parse_markdown(md) == parse_markdown(to_markdown(from_markdown(md)))
    MODEL STABILITY   from_markdown(md)  == from_markdown(to_markdown(from_markdown(md)))

Both first-parse normalization (smart quotes, hard-wrap joining) and the
escape layer for literal emphasis chars are covered.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import manuscript
import doc_model
import engine


# ---- structural diff for readable failure messages --------------------------

def _diff(a, b, path="root"):
    if type(a) != type(b):
        return f"{path}: type {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        if set(a) != set(b):
            return f"{path}: keys {sorted(a)} != {sorted(b)}"
        for k in a:
            d = _diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return ""
    return "" if a == b else f"{path}: {a!r} != {b!r}"


_failures = []


def _check(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        if detail:
            print(f"         {detail}")
        _failures.append(label)


# ---- manuscript round-trips -------------------------------------------------

def _manuscripts():
    targets = []
    sample = os.path.join(HERE, "sample", "sample.md")
    if os.path.exists(sample):
        targets.append(("sample/sample.md", sample))
    msdir = os.path.join(HERE, "projects", "manuscripts")
    if os.path.isdir(msdir):
        for fn in sorted(os.listdir(msdir)):
            if fn.endswith(".md"):
                targets.append((f"projects/manuscripts/{fn}",
                                os.path.join(msdir, fn)))
    return targets


def test_roundtrips():
    targets = _manuscripts()
    assert targets, "no manuscripts found to test"
    for smart in (True, False):
        print(f"\n[manuscripts]  smartquotes={smart}")
        for name, path in targets:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            doc1 = doc_model.from_markdown(raw, smartquotes=smart)
            md2 = doc_model.to_markdown(doc1)
            doc2 = doc_model.from_markdown(md2, smartquotes=smart)

            eng_a = manuscript.parse_markdown(raw, smartquotes=smart)
            eng_b = manuscript.parse_markdown(md2, smartquotes=smart)

            _check(f"{name}: engine fidelity", eng_a == eng_b, _diff(eng_a, eng_b))
            _check(f"{name}: model stability", doc1 == doc2, _diff(doc1, doc2))


# ---- adversarial models a real editor could emit ----------------------------

def _p(text, bold=False, italic=False):
    return {"type": "para", "runs": [doc_model._run(text, bold, italic)]}


ADVERSARIAL = [
    ("literal asterisk math",  [_p("She paid 5 * 3 = 15 coins.")]),
    ("snake_case identifier",  [_p("Open the file_name_here.txt now.")]),
    ("two underscores",        [_p("Use my_var and your_var today.")]),
    ("bare double asterisk",   [_p("Rated 5** stars, they said.")]),
    ("emphasis-looking plain", [_p("He wrote *hello* by hand.")]),
    ("line-start hash typed",  [_p("# not a heading, just prose")]),
    ("tilde fence typed",      [_p("~~~ not a block")]),
    ("triple-equals typed",    [_p("=== not a part")]),
    ("real bold run",          [{"type": "para", "runs": [
                                   doc_model._run("a "),
                                   doc_model._run("bold", bold=True),
                                   doc_model._run(" word")]}]),
    ("adjacent bold italic",   [{"type": "para", "runs": [
                                   doc_model._run("X", bold=True),
                                   doc_model._run("Y", italic=True)]}]),
    ("backtick-hugged stars",  [_p("scene break with `* * *` inline")]),
    ("docblock preserved",     [{"type": "docblock", "block_type": "letter",
                                 "attrs": {"from": "A", "to": "B", "date": "1st"},
                                 "children": [_p("Line one."), _p("Line two.")]}]),
]


def test_adversarial():
    print("\n[adversarial models]")
    for name, doc in ADVERSARIAL:
        md = doc_model.to_markdown(doc)
        doc2 = doc_model.from_markdown(md)
        _check(f"{name}: model stability", doc == doc2, _diff(doc, doc2))


def _para_texts(md):
    parsed = manuscript.parse_markdown(md, smartquotes=True)
    return [b[1] for c in parsed["chapters"] for b in c["blocks"] if b[0] == "para"]


def test_bold_italic():
    """***both*** is one span, and survives the round trip.

    Left to the ** and * passes separately it came out cross-nested --
    `<b><i>x</b></i>` -- which is not well-formed: ReportLab's parser aborts the
    whole PDF build on it, and the EPUB's XHTML is invalid. The model carries it
    as one run with both flags, so the editor cannot silently drop the italic.
    """
    print("\n[bold-italic]")
    _check("*** renders as one nested span",
           _para_texts("She was ***utterly certain*** of it.")
           == ["She was <b><i>utterly certain</i></b> of it."])
    _check("___ renders as one nested span",
           _para_texts("She was ___utterly certain___ of it.")
           == ["She was <b><i>utterly certain</i></b> of it."])
    _check("two *** spans on a line stay nested",
           _para_texts("***a*** and ***b***")
           == ["<b><i>a</i></b> and <b><i>b</i></b>"])
    _check("plain ** and * are unaffected",
           _para_texts("**b** and *i*") == ["<b>b</b> and <i>i</i>"])
    _check("emphasis nested inside bold still works",
           _para_texts("**bold with *ital* inside**")
           == ["<b>bold with <i>ital</i> inside</b>"])

    # the markup ReportLab is handed must actually parse
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    style = getSampleStyleSheet()["Normal"]
    ok = True
    for src in ("***bold italic***", "___bold italic___", "***a*** and ***b***"):
        try:
            Paragraph(manuscript._inline(src), style).wrap(400, 400)
        except Exception:
            ok = False
    _check("ReportLab parses the emitted markup", ok)

    # a run the WYSIWYG editor can produce (B *and* I) must not lose the italic
    both = [{"type": "para", "runs": [{"text": "utterly certain", "bold": True,
                                       "italic": True, "link": ""}]}]
    md = doc_model.to_markdown(both)
    _check("bold+italic run serializes to ***", md.strip() == "***utterly certain***")
    _check("bold+italic run survives the round trip",
           doc_model.from_markdown(md) == both, _diff(doc_model.from_markdown(md), both))


def test_emphasis_never_crosses_a_tag():
    """A stray asterisk must not pair with one inside a later bold span.

    `a*b **a *b* c**` used to come out `a<i>b <b>a *b</i> c</b>` -- cross-nested,
    so the PDF build aborted and the EPUB's XHTML was invalid.
    """
    print("\n[emphasis vs tag boundaries]")
    _check("stray * does not straddle a bold span",
           _para_texts("a*b **a *b* c**") == ["a*b <b>a <i>b</i> c</b>"])
    _check("emphasis inside the bold span still applies",
           _para_texts("5 * 3 **a *b* c**") == ["5 * 3 <b>a <i>b</i> c</b>"])

    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    style = getSampleStyleSheet()["Normal"]
    bad = []
    for src in ("a*b **a *b* c**", "a*b *c* d", "** — *** x *** a*b",
                "***bold ital*** _u_ ** a*b 5 * 3 **a *b* c**"):
        try:
            Paragraph(manuscript._inline(src), style).wrap(400, 400)
        except Exception:
            bad.append(src)
    _check("ReportLab parses every stray-marker case", not bad, f"crashed on {bad}")


def test_doc_block_rewrites_all_lines():
    """Every line of a doc_block survives a rewrite, not just the last.

    The setter used to rebuild the block from the copy captured when the walk
    started, so with two lines to change the first change was thrown away. Both
    builders use this to turn `<note …/>` into their own superscript.
    """
    print("\n[doc_block rewrites]")
    chapters = [{"title": "C", "blocks": [
        ("doc_block", [("para", "one"), ("para", "two"), ("para", "three")],
         {"_type": "quote"}),
        ("para", "tail")]}]
    out = manuscript.map_block_texts(chapters, lambda t, ch: t.upper())
    _check("every line of the block is rewritten",
           out[0]["blocks"][0][1] == [("para", "ONE"), ("para", "TWO"), ("para", "THREE")],
           str(out[0]["blocks"][0][1]))
    _check("the block's attrs survive", out[0]["blocks"][0][2] == {"_type": "quote"})
    _check("ordinary blocks still rewrite", out[0]["blocks"][1] == ("para", "TAIL"))
    _check("the caller's chapters are untouched",
           chapters[0]["blocks"][0][1] == [("para", "one"), ("para", "two"),
                                           ("para", "three")])


def test_dead_inbook_links():
    """A link to an anchor the book hasn't got is reported, not fatal.

    ReportLab treats an unresolved internal destination as fatal, so one stale
    `#anchor` cost the whole PDF. The EPUB has always reported these in preflight.
    """
    print("\n[dead in-book links]")
    import tempfile
    import app as _app

    meta = {"title": "T", "author": "A", "year": "2026", "publisher": "P",
            "front_matter": "none", "right_hand_starts": False,
            "smartquotes": True, "include_toc": False}

    def build(md):
        ms = manuscript.parse_markdown(md)
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            return engine.build_pdf(ms, _app.DEFAULTS, path, dict(meta)), ms
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    res, _ = build("# The Plateau\n\nOpening plain para.\n\nSee [a](#chapter-1).\n")
    _check("a live anchor is left alone", res["dead_links"] == [])

    res, ms = build("# The Plateau\n\nOpening plain para.\n\n"
                    "See [go there](#the-old-title).\n")
    _check("a stale anchor builds anyway", res["dead_links"] == ["#the-old-title"],
           str(res["dead_links"]))
    _check("and is reported in preflight",
           any(c["label"] == "In-book links" and not c["ok"]
               for c in _app._preflight(res, _app.DEFAULTS, 0)))
    _check("the manuscript itself is not edited",
           "#the-old-title" in str(ms["chapters"][0]["blocks"]))

    res, _ = build("# C\n\nOpening plain para.\n\nSee [a](https://x.test/a_b).\n")
    _check("an external link is never touched", res["dead_links"] == [])

    res, _ = build("# C\n\nOpening plain para.\n\nA line with a note.^[the note]\n")
    _check("footnote links are not unlinked", res["dead_links"] == [])

    res, _ = build("# C\n\nOpening plain para.\n\n~~~ table\n| a | [t](#nope) |\n~~~\n")
    _check("a dead link inside a block is caught", res["dead_links"] == ["#nope"],
           str(res["dead_links"]))


def test_run_boundary_escapes():
    """Runs are escaped as a line, not one at a time.

    `_escape_plain` asks whether a run survives a parse on its own, which is not
    enough: a plain "*" next to an italic "*y*" concatenates to "**y*" and
    re-reads as bold, so the model drifted on re-open.
    """
    print("\n[run-boundary escapes]")
    for md in ("*_y_", "*x* * *y*", "a * *b*", "***_y_"):
        b1 = doc_model.from_markdown(md)
        b2 = doc_model.from_markdown(doc_model.to_markdown(b1))
        _check(f"{md!r}: model stability", b1 == b2, _diff(b1, b2))


def test_engine_escapes():
    """The backward-compatible escape support added to manuscript (step 2)."""
    print("\n[engine escapes]")
    # literal emphasis chars render literally, not as markup
    _check("escaped asterisks -> literal",
           _para_texts(r"He wrote \*hello\* by hand.") == ["He wrote *hello* by hand."])
    _check("escaped underscores -> literal",
           _para_texts(r"file\_name\_here") == ["file_name_here"])
    _check("escaped backslash -> literal",
           _para_texts(r"a \\ b") == [r"a \ b"])

    # line-start markers, escaped, become paragraph text (not structure)
    for md, marker in [(r"\# not a heading", "#"),
                       (r"\~~~ not a block", "~~~"),
                       (r"\=== not a part", "===")]:
        parsed = manuscript.parse_markdown(md, smartquotes=True)
        blocks = [b for c in parsed["chapters"] for b in c["blocks"]]
        _check(f"escaped line-start {marker!r} -> paragraph",
               blocks == [("para", md[1:])], _diff(blocks, [("para", md[1:])]))

    # unescaped markers still work (no regression)
    _check("unescaped '# real heading' -> chapter",
           manuscript.parse_markdown("# real heading")["chapters"][0]["title"] == "real heading")

    # no private-use placeholder ever leaks into output
    pua = {chr(0xE000), chr(0xE001), chr(0xE002)}
    leaked = any(p in repr(_para_texts(r"x \* y \_ z \\ w")) for p in pua)
    _check("no private-use char leaks", not leaked)


POEM_MD = """# Verse

~~~ poem title="The Road Not Taken"
Two roads diverged in a yellow wood,
And sorry I could not travel both

Then took the other, as just as fair,
And *having* perhaps the better claim,
~~~

A prose line after the poem.
"""


def test_poems():
    """Poem blocks preserve verse lines + stanzas through the round trip."""
    print("\n[poems]")
    for smart in (True, False):
        doc1 = doc_model.from_markdown(POEM_MD, smartquotes=smart)
        md2 = doc_model.to_markdown(doc1)
        doc2 = doc_model.from_markdown(md2, smartquotes=smart)
        eng_a = manuscript.parse_markdown(POEM_MD, smartquotes=smart)
        eng_b = manuscript.parse_markdown(md2, smartquotes=smart)
        _check(f"poem engine fidelity (smart={smart})", eng_a == eng_b, _diff(eng_a, eng_b))
        _check(f"poem model stability (smart={smart})", doc1 == doc2, _diff(doc1, doc2))

    # structural expectations on the parsed model
    doc = doc_model.from_markdown(POEM_MD)
    poem = [b for b in doc if b["type"] == "docblock" and b["block_type"] == "poem"][0]
    _check("poem has 2 stanzas", len(poem["children"]) == 2,
           "got %d" % len(poem["children"]))
    _check("stanza 1 has 2 verse lines", len(poem["children"][0]["lines"]) == 2)
    _check("poem title preserved", poem["attrs"].get("title") == "The Road Not Taken")
    # a serialized poem re-parses to identical engine output (verse not collapsed)
    md = doc_model.to_markdown(doc)
    _check("verse lines not collapsed in serialization", md.count("\n") >= 6,
           repr(md))

    # model → md → model stability for a hand-built poem model (editor-authored)
    built = [{"type": "docblock", "block_type": "poem", "attrs": {"title": "X"},
              "children": [
                  {"type": "stanza", "lines": [
                      {"runs": [doc_model._run("line one")]},
                      {"runs": [doc_model._run("line "), doc_model._run("two", italic=True)]}]},
                  {"type": "stanza", "lines": [
                      {"runs": [doc_model._run("second stanza")]}]},
              ]}]
    back = doc_model.from_markdown(doc_model.to_markdown(built))
    _check("editor-built poem model round-trips", back == built, _diff(back, built))


BYLINE_MD = """# The Lottery | Shirley Jackson

The morning of June 27th was clear and sunny.

# An Untitled Piece

Plain body here.

# Notes | A. B. Author | with C. D.

Body under a multi-pipe heading.
"""


def test_bylines():
    """Anthology bylines ('# Title | Author') round-trip and parse correctly."""
    print("\n[bylines]")
    for smart in (True, False):
        doc1 = doc_model.from_markdown(BYLINE_MD, smartquotes=smart)
        md2 = doc_model.to_markdown(doc1)
        doc2 = doc_model.from_markdown(md2, smartquotes=smart)
        eng_a = manuscript.parse_markdown(BYLINE_MD, smartquotes=smart)
        eng_b = manuscript.parse_markdown(md2, smartquotes=smart)
        _check(f"byline engine fidelity (smart={smart})", eng_a == eng_b, _diff(eng_a, eng_b))
        _check(f"byline model stability (smart={smart})", doc1 == doc2, _diff(doc1, doc2))

    # engine parse: the byline lands on the chapter dict, title stays clean
    chs = manuscript.parse_markdown(BYLINE_MD)["chapters"]
    _check("chapter 1 title", chs[0]["title"] == "The Lottery")
    _check("chapter 1 byline", chs[0]["byline"] == "Shirley Jackson")
    _check("chapter 2 has no byline", chs[1]["byline"] is None)
    _check("chapter 2 title intact", chs[1]["title"] == "An Untitled Piece")
    # multi-pipe: split on the first separator only, remainder stays in the byline
    _check("multi-pipe title", chs[2]["title"] == "Notes")
    _check("multi-pipe byline", chs[2]["byline"] == "A. B. Author | with C. D.")

    # editor document model: chapter carries a byline field
    doc = doc_model.from_markdown(BYLINE_MD)
    ch0 = [b for b in doc if b["type"] == "chapter"][0]
    _check("model chapter byline", ch0.get("byline") == "Shirley Jackson")

    # hand-built model with a byline serializes and re-parses identically
    built = [{"type": "chapter", "title": "A Tale", "byline": "Jane Roe"},
             {"type": "para", "runs": [doc_model._run("Once.")]}]
    back = doc_model.from_markdown(doc_model.to_markdown(built))
    _check("editor-built byline model round-trips", back == built, _diff(back, built))


FIGURE_MD = """\
# Illustrated

Text before the plate.

~~~ figure src="map.png" alt="Map of the plateau" width="0.5" align="left"
The plateau, as *surveyed* in the third year.
~~~

~~~ figure src="plate.png" full="yes"
~~~

Text after.
"""


def test_figures():
    """Figure blocks keep their attrs and caption through the round trip."""
    print("\n[figures]")
    for smart in (True, False):
        doc1 = doc_model.from_markdown(FIGURE_MD, smartquotes=smart)
        md2 = doc_model.to_markdown(doc1)
        doc2 = doc_model.from_markdown(md2, smartquotes=smart)
        eng_a = manuscript.parse_markdown(FIGURE_MD, smartquotes=smart)
        eng_b = manuscript.parse_markdown(md2, smartquotes=smart)
        _check(f"figure engine fidelity (smart={smart})", eng_a == eng_b, _diff(eng_a, eng_b))
        _check(f"figure model stability (smart={smart})", doc1 == doc2, _diff(doc1, doc2))

    doc = doc_model.from_markdown(FIGURE_MD)
    figs = [b for b in doc if b["type"] == "docblock" and b["block_type"] == "figure"]
    _check("both figures parsed", len(figs) == 2, "got %d" % len(figs))
    _check("attrs kept in authored order",
           list(figs[0]["attrs"]) == ["src", "alt", "width", "align"],
           repr(figs[0]["attrs"]))
    _check("caption is the block content", len(figs[0]["children"]) == 1)
    _check("caption emphasis survives",
           any(r["italic"] for r in figs[0]["children"][0]["runs"]))

    # A caption-less figure must survive the *engine* parse too — it would
    # otherwise be an illustration silently dropped from the book.
    eng = manuscript.parse_markdown(FIGURE_MD)
    eng_figs = [b for b in eng["chapters"][0]["blocks"]
                if b[0] == "doc_block" and len(b) > 2 and b[2].get("_type") == "figure"]
    _check("engine keeps the caption-less figure", len(eng_figs) == 2,
           "got %d" % len(eng_figs))
    _check("caption-less figure has no paragraphs", eng_figs[1][1] == [])
    _check("full attr preserved", eng_figs[1][2].get("full") == "yes")

    # hand-built model (what the editor's Figure button produces)
    built = [{"type": "docblock", "block_type": "figure",
              "attrs": {"src": "x.png", "alt": ""}, "children": []}]
    back = doc_model.from_markdown(doc_model.to_markdown(built))
    _check("editor-built figure model round-trips", back == built, _diff(back, built))


BLOCKS_MD = """\
# Provisions

Everything below was copied from her book.

~~~ list
Salt, four measures a head
Rope, tarred, two coils
Water, which runs out sooner
~~~

She had opinions about the order.

~~~ list type="number" start="3"
Load the mules before dawn
Walk the first hour in silence
~~~

~~~ quote source="Berrin of Ferrun"
The plateau does not kill travellers. It simply
declines to help them.

Those who go up expecting hostility are disappointed.
~~~

~~~ center
NO WATER BEYOND THIS POINT
TURN BACK OR CARRY IT
~~~

~~~ right
— they never carry enough
~~~
"""


def test_blocks():
    """Lists and alignment blocks are line-oriented; quotes stay prose."""
    print("\n[lists / quotes / alignment]")
    for smart in (True, False):
        doc1 = doc_model.from_markdown(BLOCKS_MD, smartquotes=smart)
        md2 = doc_model.to_markdown(doc1)
        doc2 = doc_model.from_markdown(md2, smartquotes=smart)
        eng_a = manuscript.parse_markdown(BLOCKS_MD, smartquotes=smart)
        eng_b = manuscript.parse_markdown(md2, smartquotes=smart)
        _check(f"blocks engine fidelity (smart={smart})", eng_a == eng_b, _diff(eng_a, eng_b))
        _check(f"blocks model stability (smart={smart})", doc1 == doc2, _diff(doc1, doc2))

    doc = doc_model.from_markdown(BLOCKS_MD)
    by = {}
    for b in doc:
        if b["type"] == "docblock":
            by.setdefault(b["block_type"], []).append(b)

    # one line = one item, NOT one wrapped paragraph
    _check("bulleted list has 3 items", len(by["list"][0]["children"]) == 3,
           len(by["list"][0]["children"]))
    _check("numbered list keeps type + start",
           by["list"][1]["attrs"] == {"type": "number", "start": "3"},
           by["list"][1]["attrs"])
    _check("aligned block keeps its 2 lines separate",
           len(by["center"][0]["children"]) == 2, len(by["center"][0]["children"]))
    _check("right block parsed", len(by["right"][0]["children"]) == 1)

    # a quote is prose: hard-wrapped lines join, a blank line starts a paragraph
    q = by["quote"][0]
    _check("quote has 2 paragraphs, not 3 lines", len(q["children"]) == 2,
           len(q["children"]))
    _check("quote wrapped lines are joined",
           "simply declines" in "".join(r["text"] for r in q["children"][0]["runs"]),
           q["children"][0]["runs"])
    _check("quote source preserved", q["attrs"].get("source") == "Berrin of Ferrun")

    # the engine sees the same shape
    eng = manuscript.parse_markdown(BLOCKS_MD)
    blocks = [b for ch in eng["chapters"] for b in ch["blocks"] if b[0] == "doc_block"]
    kinds = [b[2].get("_type") for b in blocks]
    _check("engine block order", kinds == ["list", "list", "quote", "center", "right"], kinds)
    _check("engine list items stay separate", len(blocks[0][1]) == 3, len(blocks[0][1]))

    # hand-built model (what the List / Quote buttons produce)
    built = [{"type": "docblock", "block_type": "list", "attrs": {},
              "children": [{"type": "para", "runs": [doc_model._run("one")]},
                           {"type": "para", "runs": [doc_model._run("two")]}]}]
    back = doc_model.from_markdown(doc_model.to_markdown(built))
    _check("editor-built list round-trips", back == built, _diff(back, built))


TABLES_MD = """\
# Yields and Measures

Everything below was copied from the assessors' rolls.

~~~ table caption="Recorded yields, 1897" align="left,right,right"
Region | Wheat | Barley
Northmarch | 1,240 | 880
Salt Coast | 960 | 1,105
~~~

The second roll was kept by assessor rather than by region.

~~~ table header="no" widths="2,1"
Assessor | **Rolls held**
J. Marsh | 14
~~~

~~~ table
One | *two* | [the roll](https://example.com/a_b)
Short row
~~~
"""


def test_tables():
    """A table is line-oriented (one row per line); cells split on `|`."""
    print("\n[tables]")
    for smart in (True, False):
        doc1 = doc_model.from_markdown(TABLES_MD, smartquotes=smart)
        md2 = doc_model.to_markdown(doc1)
        doc2 = doc_model.from_markdown(md2, smartquotes=smart)
        eng_a = manuscript.parse_markdown(TABLES_MD, smartquotes=smart)
        eng_b = manuscript.parse_markdown(md2, smartquotes=smart)
        _check(f"table engine fidelity (smart={smart})", eng_a == eng_b, _diff(eng_a, eng_b))
        _check(f"table model stability (smart={smart})", doc1 == doc2, _diff(doc1, doc2))

    # the round-trip model needs no concept of a cell: to it a row is a line,
    # and the pipes are ordinary text. That is the whole reason this was cheap.
    doc = doc_model.from_markdown(TABLES_MD)
    tables = [b for b in doc if b["type"] == "docblock" and b["block_type"] == "table"]
    _check("three tables parsed", len(tables) == 3, len(tables))
    _check("a row is one line", len(tables[0]["children"]) == 3,
           len(tables[0]["children"]))
    _check("caption and alignment survive",
           tables[0]["attrs"] == {"caption": "Recorded yields, 1897",
                                  "align": "left,right,right"}, tables[0]["attrs"])
    _check("header=no and widths survive",
           tables[1]["attrs"] == {"header": "no", "widths": "2,1"}, tables[1]["attrs"])
    _check("pipes stay in the line text",
           "|" in "".join(r["text"] for r in tables[0]["children"][0]["runs"]),
           tables[0]["children"][0]["runs"])

    # the engine splits the cells, and each is inlined on its own
    eng = manuscript.parse_markdown(TABLES_MD, smartquotes=False)
    blocks = [b for ch in eng["chapters"] for b in ch["blocks"]
              if b[0] == "doc_block" and b[2].get("_type") == "table"]
    rows = [[c for c in text.split(manuscript.CELL_SEP)] for _, text in blocks[0][1]]
    _check("cells are split on the pipe",
           rows[0] == ["Region", "Wheat", "Barley"], rows[0])
    _check("every row is present", len(rows) == 3, len(rows))
    cells = blocks[2][1][0][1].split(manuscript.CELL_SEP)
    _check("emphasis works inside a cell", cells[1] == "<i>two</i>", cells[1])
    _check("a link works inside a cell", "<a href=" in cells[2], cells[2])
    _check("a URL's underscore is not read as emphasis",
           "a_b" in cells[2], cells[2])
    _check("a short row keeps its one cell",
           blocks[2][1][1][1].split(manuscript.CELL_SEP) == ["Short row"],
           blocks[2][1][1][1])

    # both builders pad a short row to the grid rather than dropping the words
    grid = engine._table_rows(blocks[2][1])
    _check("a ragged row is padded, not dropped",
           len(grid) == 2 and len(grid[0]) == len(grid[1]) == 3, grid)
    _check("padding is empty cells, words intact", grid[1][0] == "Short row", grid[1])

    # hand-built model (what the Table button produces)
    built = [{"type": "docblock", "block_type": "table", "attrs": {},
              "children": [{"type": "para", "runs": [doc_model._run("Column | Column")]},
                           {"type": "para", "runs": [doc_model._run("a | b")]}]}]
    back = doc_model.from_markdown(doc_model.to_markdown(built))
    _check("editor-built table round-trips", back == built, _diff(back, built))

    _check_docx_tables()


def _check_docx_tables():
    """A Word table imports with its columns, which is the last thing #47 left
    on the floor: `doc.paragraphs` skips tables entirely, and until there was a
    table block the importer could only set the words apart as a plain block."""
    import tempfile
    try:
        from docx import Document
    except ImportError:
        _check("python-docx present for the import check", False, "not installed")
        return

    d = Document()
    d.add_heading("Yields", level=1)
    d.add_paragraph("A paragraph before the table.")
    t = d.add_table(rows=3, cols=3)
    for r, row in enumerate([["Region", "Wheat", "Barley"],
                             ["Northmarch", "1,240", "880"],
                             ["Salt Coast|North", "960", "1,105"]]):
        for c, v in enumerate(row):
            t.rows[r].cells[c].text = v
    d.add_paragraph("And a paragraph after it.")

    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        d.save(path)
        report = {}
        md = manuscript.import_docx(path, report=report)
    finally:
        os.remove(path)

    parsed = manuscript.parse_markdown(md, smartquotes=True)
    blocks = [b for ch in parsed["chapters"] for b in ch["blocks"]
              if b[0] == "doc_block"]
    _check("a Word table imports as a table block",
           [b[2].get("_type") for b in blocks] == ["table"],
           [b[2].get("_type") for b in blocks])
    rows = [text.split(manuscript.CELL_SEP) for _, text in blocks[0][1]]
    _check("its columns survive", rows[0] == ["Region", "Wheat", "Barley"], rows[0])
    _check("all three rows survive", len(rows) == 3, len(rows))
    _check("a pipe inside a Word cell becomes a slash",
           rows[2][0] == "Salt Coast/North", rows[2][0])
    _check("the import summary no longer apologises for tables",
           manuscript.import_summary(report) == ("1 chapter, 1 table", ""),
           manuscript.import_summary(report))


LINKS_MD = """\
# Also By

Find the rest at [ashforgestudio.com](https://ashforgestudio.com/books) or write
to [the studio](mailto:hello@example.com).

A [**bold** link](https://example.com/a_b_c) and a cross-reference to
[the first chapter](#also-by).

Literal [sic](ibid) is not a link, and \\[this](https://x.com) is escaped.
"""


def test_links():
    """Links survive the round trip, and only real targets become links."""
    print("\n[links]")
    for smart in (True, False):
        doc1 = doc_model.from_markdown(LINKS_MD, smartquotes=smart)
        md2 = doc_model.to_markdown(doc1)
        doc2 = doc_model.from_markdown(md2, smartquotes=smart)
        eng_a = manuscript.parse_markdown(LINKS_MD, smartquotes=smart)
        eng_b = manuscript.parse_markdown(md2, smartquotes=smart)
        _check(f"link engine fidelity (smart={smart})", eng_a == eng_b, _diff(eng_a, eng_b))
        _check(f"link model stability (smart={smart})", doc1 == doc2, _diff(doc1, doc2))

    runs = [r for b in doc_model.from_markdown(LINKS_MD) if b["type"] == "para"
            for r in b["runs"]]
    linked = [r for r in runs if r["link"]]
    _check("four links found", len(linked) == 5, [r["link"] for r in linked])
    _check("web target kept",
           any(r["link"] == "https://ashforgestudio.com/books" for r in linked))
    _check("mailto kept", any(r["link"] == "mailto:hello@example.com" for r in linked))
    _check("in-book anchor kept", any(r["link"] == "#also-by" for r in linked))
    _check("emphasis inside a link survives",
           any(r["bold"] and r["link"].startswith("https://example.com") for r in linked))
    _check("underscores in a target are not italicised",
           any(r["link"] == "https://example.com/a_b_c" for r in linked),
           [r["link"] for r in linked])

    # things that must NOT become links
    plain = " ".join(r["text"] for r in runs if not r["link"])
    _check("[sic](ibid) stays literal", "[sic](ibid)" in plain, plain)
    _check("escaped bracket stays literal", "[this](https://x.com)" in plain, plain)

    # the engine markup carries a real anchor
    eng = manuscript.parse_markdown(LINKS_MD)
    body = " ".join(b[1] for ch in eng["chapters"] for b in ch["blocks"] if b[0] == "para")
    _check("engine emits <a href>", '<a href="mailto:hello@example.com">' in body, body[:200])
    _check("engine escapes nothing odd in the target",
           '<a href="https://example.com/a_b_c">' in body, body[:400])

    # chapter anchors, shared by both builders
    anchors = manuscript.chapter_anchors({"title": "The Salt Road"}, 2)
    _check("anchors: positional + slug", anchors == ["chapter-2", "the-salt-road"], anchors)
    _check("untitled chapter still linkable",
           manuscript.chapter_anchors({"title": None}, 3) == ["chapter-3"])


NOTES_MD = """\
# The Survey

The plateau was surveyed twice.[^survey] The second disagreed.[^second]

Later the office revised it again.[^survey]

[^survey]: Ferrun Cartographic Office, *Survey of the Salt Road*, 1891.
[^second]: The disagreement was never formally settled.
[^orphan]: A note nobody referenced.

# The Revision

Numbering restarts here.[^a] And a reference with no text.[^gone]

[^a]: Revised survey, 1904.
"""


def test_notes():
    """Endnotes: per-chapter numbering, definitions lifted out of the body."""
    print("\n[endnotes]")
    for smart in (True, False):
        doc1 = doc_model.from_markdown(NOTES_MD, smartquotes=smart)
        md2 = doc_model.to_markdown(doc1)
        doc2 = doc_model.from_markdown(md2, smartquotes=smart)
        eng_a = manuscript.parse_markdown(NOTES_MD, smartquotes=smart)
        eng_b = manuscript.parse_markdown(md2, smartquotes=smart)
        _check(f"notes engine fidelity (smart={smart})", eng_a == eng_b, _diff(eng_a, eng_b))
        _check(f"notes model stability (smart={smart})", doc1 == doc2, _diff(doc1, doc2))

    ms = manuscript.parse_markdown(NOTES_MD)
    ch1, ch2 = ms["chapters"]

    _check("definitions are not body paragraphs",
           all("[^" not in b[1] for b in ch1["blocks"] if b[0] == "para"),
           [b[1] for b in ch1["blocks"]])
    _check("reference became a numbered marker",
           '<note n="1" id="survey"/>' in ch1["blocks"][0][1], ch1["blocks"][0][1])
    _check("a repeated label keeps its number",
           '<note n="1" id="survey"/>' in ch1["blocks"][1][1], ch1["blocks"][1][1])

    n1 = {n["label"]: n for n in ch1["notes"]}
    _check("chapter 1 has three notes", len(ch1["notes"]) == 3, len(ch1["notes"]))
    _check("note text keeps emphasis", "<i>" in n1["survey"]["text"], n1["survey"]["text"])
    _check("orphan definition kept, numbered last",
           n1["orphan"]["n"] == 3, n1["orphan"])
    _check("numbering restarts per chapter",
           [n["n"] for n in ch2["notes"]] == [1, 2], ch2["notes"])
    _check("reference with no definition still numbered",
           any(n["label"] == "gone" and n["text"] == "" for n in ch2["notes"]),
           ch2["notes"])
    _check("scratch key removed", "note_defs" not in ch1)

    # a manuscript with no notes must not grow the key
    plain = manuscript.parse_markdown("# One\n\nNo notes here.\n")
    _check("no notes -> no notes key", "notes" not in plain["chapters"][0])


VOCAB_MD = """\
#* Prologue

Before it all began.

# The First Chapter

The story proper.

# The Second Chapter

More of it.

#* Epilogue | A Note

After.
"""


def test_vocabulary():
    """Unnumbered chapters, and the front/back matter table."""
    print("\n[element vocabulary]")
    import matter

    for smart in (True, False):
        doc1 = doc_model.from_markdown(VOCAB_MD, smartquotes=smart)
        md2 = doc_model.to_markdown(doc1)
        doc2 = doc_model.from_markdown(md2, smartquotes=smart)
        eng_a = manuscript.parse_markdown(VOCAB_MD, smartquotes=smart)
        eng_b = manuscript.parse_markdown(md2, smartquotes=smart)
        _check(f"vocab engine fidelity (smart={smart})", eng_a == eng_b, _diff(eng_a, eng_b))
        _check(f"vocab model stability (smart={smart})", doc1 == doc2, _diff(doc1, doc2))

    ms = manuscript.parse_markdown(VOCAB_MD)
    flags = [bool(c.get("unnumbered")) for c in ms["chapters"]]
    _check("prologue and epilogue are unnumbered", flags == [True, False, False, True], flags)
    _check("an unnumbered chapter can still carry a byline",
           ms["chapters"][3]["byline"] == "A Note", ms["chapters"][3])

    # the number a reader sees skips them; position does not
    nums = manuscript.chapter_numbers(ms["chapters"])
    _check("numbering skips unnumbered chapters", nums == [None, 1, 2, None], nums)
    _check("position still identifies every chapter",
           manuscript.chapter_anchors(ms["chapters"][0], 1) == ["chapter-1", "prologue"],
           manuscript.chapter_anchors(ms["chapters"][0], 1))

    # a plain chapter model is untouched by the new flag
    built = [{"type": "chapter", "title": "A Tale", "byline": None}]
    _check("plain chapter model unchanged",
           doc_model.from_markdown(doc_model.to_markdown(built)) == built)

    # the matter table itself
    _check("every section key is unique", len(matter.KEYS) == len(set(matter.KEYS)))
    _check("front and back partition the table",
           len(matter.FRONT) + len(matter.BACK) == len(matter.SECTIONS))
    _check("blank() covers every key", set(matter.blank()) == set(matter.KEYS))
    _check("present() honours order and emptiness",
           [s["key"] for s in matter.present({"also_by": "x", "afterword": "y",
                                              "foreword": " "})] == ["afterword", "also_by"],
           [s["key"] for s in matter.present({"also_by": "x", "afterword": "y"})])
    _check("author fills into the heading",
           matter.heading([s for s in matter.SECTIONS if s["key"] == "also_by"][0],
                          "Ellinor Vale") == "Also by Ellinor Vale")
    _check("a section with no label has no heading",
           matter.heading([s for s in matter.SECTIONS if s["key"] == "dedication"][0]) == "")
    _check("EPUB ids and hrefs are unique",
           len({s["eid"] for s in matter.SECTIONS}) == len(matter.SECTIONS)
           and len({s["href"] for s in matter.SECTIONS}) == len(matter.SECTIONS))


if __name__ == "__main__":
    test_roundtrips()
    test_adversarial()
    test_engine_escapes()
    test_bold_italic()
    test_emphasis_never_crosses_a_tag()
    test_doc_block_rewrites_all_lines()
    test_dead_inbook_links()
    test_run_boundary_escapes()
    test_poems()
    test_bylines()
    test_figures()
    test_blocks()
    test_tables()
    test_links()
    test_notes()
    test_vocabulary()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        sys.exit(1)
    print("ALL PASS")
