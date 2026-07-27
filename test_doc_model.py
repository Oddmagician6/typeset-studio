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


if __name__ == "__main__":
    test_roundtrips()
    test_adversarial()
    test_engine_escapes()
    test_poems()
    test_bylines()
    test_figures()
    test_blocks()
    test_links()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        sys.exit(1)
    print("ALL PASS")
