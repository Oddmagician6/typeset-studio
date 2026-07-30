"""Splice packed data-URI assets into a reel source -> publishable HTML.

    python build.py reel.src.html   assets.js    typeset-studio-reel.html
    python build.py reel_v.src.html assets_v.js  typeset-studio-reel-9x16.html

The published page is wrapped in a <head> we don't control, so we cannot rely
on a <meta charset>. Rather than gamble on the server's default encoding, the
build emits pure ASCII: decorative box-drawing in comments is flattened, and
every visible non-ASCII glyph becomes a numeric character reference (which is
charset-independent). Entities are NOT parsed inside <style>/<script>, so those
regions are flattened instead of escaped.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Box-drawing rules only ever appear in comment banners, in either region.
RULES = {"─": "-", "═": "="}
# An em dash inside <style>/<script> is prose in a comment and can be
# flattened; in the HTML region it is visible copy and must survive as an
# entity instead. Keep the two cases apart.
PROSE = {"—": "--"}


def flatten(s, prose=False):
    for a, b in RULES.items():
        s = s.replace(a, b)
    if prose:
        for a, b in PROSE.items():
            s = s.replace(a, b)
    return s


def entities(s):
    return "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in s)


def build(src_name, assets_name, dest_name):
    src = os.path.join(HERE, src_name)
    html = open(src, encoding="utf-8").read()
    js = open(os.path.join(HERE, assets_name), encoding="utf-8").read()

    m = re.match(r"\s*const A =\s*(.*);\s*$", js, re.S)
    if not m:
        raise SystemExit(f"{assets_name} not in the expected 'const A = {{...}};' shape")
    literal = m.group(1)

    if "__ASSETS__" not in html:
        raise SystemExit(f"no __ASSETS__ placeholder in {src_name}")

    packed = json.loads(literal)
    wanted = sorted(set(re.findall(r"__A_(\w+)__", html)))
    unknown = [k for k in wanted if k not in packed]
    if unknown:
        raise SystemExit(f"placeholders with no packed asset: {unknown}")
    unused = sorted(set(packed) - set(wanted) - {"wall"})
    print(f"  placeholders : {', '.join(wanted)}")
    print(f"  cover wall   : {len(packed.get('wall', []))}")
    if unused:
        print(f"  WARNING unused packed assets (wasted bytes): {', '.join(unused)}")

    parts, pos = [], 0
    for mm in re.finditer(r"<(style|script)\b.*?</\1>", html, re.S | re.I):
        parts.append(entities(flatten(html[pos:mm.start()])))
        parts.append(flatten(mm.group(0), prose=True))
        pos = mm.end()
    parts.append(entities(flatten(html[pos:])))
    html = "".join(parts)

    html = html.replace("__ASSETS__", literal)

    bad = [(i, c) for i, c in enumerate(html) if ord(c) > 127]
    if bad:
        raise SystemExit(f"output is not pure ASCII: {bad[:5]}")

    dest = os.path.join(HERE, dest_name)
    open(dest, "w", encoding="ascii").write(html)
    print(f"  wrote {dest_name}  {os.path.getsize(dest)/1024/1024:.2f} MB, pure ASCII\n")


if __name__ == "__main__":
    if len(sys.argv) == 4:
        build(*sys.argv[1:])
    else:
        build("reel.src.html", "assets.js", "typeset-studio-reel.html")
        build("reel_v.src.html", "assets_v.js", "typeset-studio-reel-9x16.html")
