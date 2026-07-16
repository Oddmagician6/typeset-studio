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


if __name__ == "__main__":
    test_roundtrips()
    test_adversarial()
    test_engine_escapes()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        sys.exit(1)
    print("ALL PASS")
