"""Editor document model  <->  canonical Markdown.

This is the round-trip layer under a structured (WYSIWYG) editor: the editor maps
its contenteditable DOM to/from the *document model* defined here, and the model
serializes to the same light Markdown convention that ``manuscript.parse_markdown``
already consumes -> PDF / EPUB / preview unchanged. The engine stays the single
owner of typography; this module only carries structure + emphasis.

Guarantee (validated by ``test_doc_model.py`` over the sample + every real
manuscript, and proven in the serialization spike before this was built):

    ENGINE FIDELITY   parse_markdown(md) == parse_markdown(to_markdown(from_markdown(md)))
    MODEL STABILITY   from_markdown(md)  == from_markdown(to_markdown(from_markdown(md)))

The first parse normalizes (smart quotes, hard-wrap line-joining), so these are
fixed-point properties, not raw-string equality -- editing then re-rendering never
changes the typeset output, and re-opening a saved manuscript never drifts.

Document model
--------------
A document is a list of blocks. Each block is a plain JSON-able dict:

    {"type": "chapter",  "title": str | None}          # "# ..."   title stored raw
    {"type": "part",     "title": str | None}          # "=== ..." title stored raw
    {"type": "subhead",  "runs": [run, ...]}           # "## ..."
    {"type": "para",     "runs": [run, ...]}           # a paragraph
    {"type": "scene"}                                   # scene break
    {"type": "docblock", "block_type": str,            # "" for a plain ~~~ fence
                         "attrs": {key: value, ...},    # ordered as authored
                         "children": [para, ...]}       # each child is a para block

    run = {"text": str, "bold": bool, "italic": bool}  # emphasis is non-nesting

Chapter and part titles are stored raw (no smartening / emphasis) to mirror the
engine; subheads and paragraphs carry smartened text with emphasis runs.

Literal emphasis / marker characters
------------------------------------
The convention has no escape syntax, so a paragraph a writer *types* literally --
"5 * 3", a ``snake_case`` name, a line starting ``#`` or ``~~~`` -- could re-parse
as emphasis or structure. ``to_markdown`` emits a backslash escape ONLY when the
literal text would otherwise re-parse as something other than itself (see
``_escape_plain``), so real-world prose serializes with zero backslashes. Fully
supporting a *deliberately* typed literal ``*word*`` or line-start marker also
needs the matching (backward-compatible) unescape in ``manuscript`` -- see the
roadmap; it is not required for any existing manuscript.
"""

import re

import manuscript


# Bold before italic, mirroring manuscript._inline's substitution order. Emphasis
# is non-nesting in this convention, so a flat run list is faithful.
_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
_ITALIC_STAR = re.compile(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)')
_ITALIC_UNDER = re.compile(r'_(?!\s)(.+?)(?<!\s)_')


# ---------------------------------------------------------------------------
# Escape layer. A backslash escapes a literal emphasis char; escaped chars are
# parked on private-use codepoints so the emphasis regexes never see them, then
# restored to literals. No manuscript contains a backslash, so this is inert on
# existing content.
# ---------------------------------------------------------------------------

_BSL = chr(92)                 # a single backslash
_PARK_STAR = chr(0xE000)
_PARK_UNDER = chr(0xE001)
_PARK_BSL = chr(0xE002)


def _park_escapes(text):
    text = text.replace(_BSL + _BSL, _PARK_BSL)      # \\  -> literal backslash
    text = text.replace(_BSL + '*', _PARK_STAR)      # \*  -> literal *
    text = text.replace(_BSL + '_', _PARK_UNDER)     # \_  -> literal _
    return text


def _restore_escapes(text):
    return (text.replace(_PARK_STAR, '*')
                .replace(_PARK_UNDER, '_')
                .replace(_PARK_BSL, _BSL))


def _escape_all(text):
    """Escape every literal emphasis char (used inside emphasis spans)."""
    return (text.replace(_BSL, _BSL + _BSL)
                .replace('*', _BSL + '*')
                .replace('_', _BSL + '_'))


def _escape_plain(text):
    """Escape a plain run only if leaving it bare would re-parse as emphasis.

    The empirically-correct minimal rule: don't reason char-by-char about the
    engine's guards (fragile, and coupled to exact regex behaviour) -- just ask
    whether the literal text survives a parse unchanged. If it does, emit it bare.
    Quote-independent, so we probe with smartquotes off.
    """
    escaped_bsl = text.replace(_BSL, _BSL + _BSL)
    if _parse_inline(escaped_bsl, smartquotes=False) == [_run(text)]:
        return escaped_bsl
    return escaped_bsl.replace('*', _BSL + '*').replace('_', _BSL + '_')


# ---------------------------------------------------------------------------
# Inline: Markdown emphasis  <->  runs
# ---------------------------------------------------------------------------

def _run(text, bold=False, italic=False):
    return {"text": text, "bold": bold, "italic": italic}


def _parse_inline(text, smartquotes=True):
    """Smarten (optional), then split into emphasis runs."""
    text = _park_escapes(text)
    if smartquotes:
        text = manuscript._smarten(text)

    runs = []
    # Pass 1: carve out bold spans.
    segments = []                                        # (is_bold, str)
    pos = 0
    for m in _BOLD_RE.finditer(text):
        if m.start() > pos:
            segments.append((False, text[pos:m.start()]))
        segments.append((True, m.group(1)))
        pos = m.end()
    if pos < len(text):
        segments.append((False, text[pos:]))

    # Pass 2: carve out italics within each non-bold segment.
    for is_bold, seg in segments:
        if is_bold:
            runs.append(_run(seg, bold=True))
            continue
        for is_italic, chunk in _split_italics(seg):
            if chunk:
                runs.append(_run(chunk, italic=is_italic))

    runs = _coalesce(runs)
    for r in runs:                                       # parked -> literal chars
        r["text"] = _restore_escapes(r["text"])
    return runs


def _split_italics(seg):
    """Yield (is_italic, str) for a non-bold segment: *...* then _..._ ."""
    out = []
    pos = 0
    for m in _ITALIC_STAR.finditer(seg):
        if m.start() > pos:
            out.append((False, seg[pos:m.start()]))
        out.append((True, m.group(1)))
        pos = m.end()
    if pos < len(seg):
        out.append((False, seg[pos:]))

    final = []
    for is_italic, piece in out:
        if is_italic:
            final.append((True, piece))
            continue
        p2 = 0
        for m in _ITALIC_UNDER.finditer(piece):
            if m.start() > p2:
                final.append((False, piece[p2:m.start()]))
            final.append((True, m.group(1)))
            p2 = m.end()
        if p2 < len(piece):
            final.append((False, piece[p2:]))
    return final


def _coalesce(runs):
    """Merge adjacent runs with identical emphasis (keeps the model canonical)."""
    out = []
    for r in runs:
        if out and out[-1]["bold"] == r["bold"] and out[-1]["italic"] == r["italic"]:
            out[-1]["text"] += r["text"]
        else:
            out.append(dict(r))
    return [r for r in out if r["text"]]


def _runs_to_md(runs):
    """Serialize runs back to Markdown emphasis. _italic_ normalizes to *italic*."""
    parts = []
    for r in runs:
        if r["bold"]:
            parts.append(f"**{_escape_all(r['text'])}**")
        elif r["italic"]:
            parts.append(f"*{_escape_all(r['text'])}*")
        else:
            parts.append(_escape_plain(r["text"]))
    return "".join(parts)


def _block_collision(line):
    """True if a paragraph line would be mistaken for a structural block."""
    return bool(
        manuscript.CHAPTER_RE.match(line)
        or manuscript.SUBHEAD_RE.match(line)
        or manuscript.PART_RE.match(line)
        or manuscript.DOCBLOCK_RE.match(line)
        or manuscript.SCENE_BREAK_RE.match(line)
    )


# ---------------------------------------------------------------------------
# Markdown  ->  document model
# ---------------------------------------------------------------------------

def from_markdown(raw, smartquotes=True):
    """Parse canonical Markdown into the editor document model (list of blocks)."""
    lines = raw.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    blocks = []
    para_buf = []

    in_block = False
    block_children = []
    block_para_buf = []
    block_type = ''
    block_attrs = {}

    def flush_para():
        nonlocal para_buf
        if para_buf:
            joined = ' '.join(s.strip() for s in para_buf).strip()
            if joined:
                blocks.append({"type": "para",
                               "runs": _parse_inline(joined, smartquotes)})
            para_buf = []

    def flush_block_para():
        nonlocal block_para_buf
        if block_para_buf:
            joined = ' '.join(s.strip() for s in block_para_buf).strip()
            if joined:
                block_children.append({"type": "para",
                                       "runs": _parse_inline(joined, smartquotes)})
            block_para_buf = []

    def close_block():
        nonlocal in_block, block_children, block_type, block_attrs
        flush_block_para()
        blocks.append({"type": "docblock", "block_type": block_type,
                       "attrs": dict(block_attrs), "children": list(block_children)})
        block_children = []
        block_type = ''
        block_attrs = {}
        in_block = False

    for line in lines:
        # A leading backslash guarding a block marker => literal paragraph text.
        if not in_block and line[:1] == _BSL and _block_collision(line[1:]):
            para_buf.append(line[1:])
            continue

        if not in_block:
            m_part = manuscript.PART_RE.match(line)
            if m_part:
                flush_para()
                blocks.append({"type": "part",
                               "title": m_part.group(1).strip() or None})
                continue

        m_doc = manuscript.DOCBLOCK_RE.match(line)
        if m_doc:
            if in_block:
                close_block()
            else:
                flush_para()
                block_type, block_attrs = manuscript._parse_block_header(m_doc.group(1))
                in_block = True
            continue

        if in_block:
            if line.strip() == '':
                flush_block_para()
            else:
                block_para_buf.append(line)
            continue

        m_ch = manuscript.CHAPTER_RE.match(line)
        m_sub = manuscript.SUBHEAD_RE.match(line)
        if m_ch:
            flush_para()
            blocks.append({"type": "chapter", "title": m_ch.group(1).strip() or None})
            continue
        if manuscript.SCENE_BREAK_RE.match(line):
            flush_para()
            blocks.append({"type": "scene"})
            continue
        if m_sub:
            flush_para()
            blocks.append({"type": "subhead",
                           "runs": _parse_inline(m_sub.group(1).strip(), smartquotes)})
            continue
        if line.strip() == '':
            flush_para()
        else:
            para_buf.append(line)

    if in_block:
        close_block()
    flush_para()
    return blocks


# ---------------------------------------------------------------------------
# Document model  ->  Markdown
# ---------------------------------------------------------------------------

def to_markdown(blocks):
    """Serialize the editor document model back to canonical Markdown."""
    out = []
    for b in blocks:
        t = b["type"]
        if t == "chapter":
            out.append("# " + (b["title"] or ""))
        elif t == "part":
            out.append("=== " + (b["title"] or ""))
        elif t == "subhead":
            out.append("## " + _runs_to_md(b["runs"]))
        elif t == "para":
            line = _runs_to_md(b["runs"])
            if _block_collision(line):                   # guard a would-be marker
                line = _BSL + line
            out.append(line)
        elif t == "scene":
            out.append("* * *")
        elif t == "docblock":
            header = "~~~"
            if b["block_type"]:
                header += " " + b["block_type"]
                for k, v in b["attrs"].items():
                    header += f' {k}="{v}"'
            out.append(header)
            kids = b["children"]
            for i, kid in enumerate(kids):
                out.append(_runs_to_md(kid["runs"]))
                if i < len(kids) - 1:
                    out.append("")                       # blank line between paras
            out.append("~~~")
        else:
            raise ValueError(f"unknown block type: {t!r}")
        out.append("")                                   # blank line between blocks
    return "\n".join(out)
