"""Word import keeps what the page shows  (run: python test_import_bughunt.py).

Joint bug hunt, round 3, section 13:

    13.1  replacing a .DOCX manuscript with a .docx keeps the new one
    13.2  a `~~~` table cell doesn't swallow the next chapter
    13.3  tracked insertions, content controls, smart tags, fields, text boxes
    13.4  merged cells stay in their columns; a cell merged down isn't repeated
    13.5  pictures and note references in table cells
    13.6  a Read Aloud box doesn't take the chapter's note texts
    13.7  a note on a chapter heading belongs to that chapter
    13.8  a note that is all link
    13.9  numbered lists by their numbering, and counting on after a nested list
    13.10 italic then bold in one word prints no stray asterisks
    13.11 `###` on the left is text; centred it is a scene break
    13.12 a link keeps its #fragment
    13.13 Set a book's paste wraps Homebrewery stat blocks
    13.14 previewing the same Word file twice saves its pictures once
    (spec.) a picture with a compatibility fallback is imported once
"""

import io, os, sys, re, shutil, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import manuscript as M
from docx import Document
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import qn, nsdecls
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.enum.text import WD_ALIGN_PARAGRAPH

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
fails = []


def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp()
M.FIGURE_DIR = os.path.join(TMP, 'figures')


def note_ref(par, nid, kind='footnote'):
    r = OxmlElement('w:r')
    ref = OxmlElement(f'w:{kind}Reference')
    ref.set(qn('w:id'), str(nid))
    r.append(ref)
    par._p.append(r)


def with_notes(src, dest, notes_xml):
    """Inject a footnotes part (python-docx can't author one)."""
    ct = ('<Override PartName="/word/footnotes.xml" ContentType="application/vnd.'
          'openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>')
    rel = ('<Relationship Id="rIdFootnotes" Type="http://schemas.openxmlformats.org/'
           'officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
           '<Relationship Id="rIdLinkN" Type="http://schemas.openxmlformats.org/'
           'officeDocument/2006/relationships/hyperlink" Target="https://example.test/archive" '
           'TargetMode="External"/>')
    frel = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns='
            '"http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdLinkN" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/hyperlink" Target="https://example.test/archive" '
            'TargetMode="External"/></Relationships>')
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zo:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == '[Content_Types].xml':
                data = data.replace(b'</Types>', ct.encode() + b'</Types>')
            elif item.filename == 'word/_rels/document.xml.rels':
                data = data.replace(b'</Relationships>', rel.encode() + b'</Relationships>')
            zo.writestr(item, data)
        body = ['<w:footnote w:type="separator" w:id="0"><w:p/></w:footnote>',
                '<w:footnote w:type="continuationSeparator" w:id="1"><w:p/></w:footnote>']
        for nid, inner in notes_xml:
            body.append(f'<w:footnote w:id="{nid}"><w:p><w:r><w:footnoteRef/></w:r>'
                        f'{inner}</w:p></w:footnote>')
        zo.writestr('word/footnotes.xml',
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    f'<w:footnotes xmlns:w="{W}" xmlns:r="http://schemas.openxmlformats.org/'
                    'officeDocument/2006/relationships">' + ''.join(body) + '</w:footnotes>')
        zo.writestr('word/_rels/footnotes.xml.rels', frel)


def plain_note(text):
    return f'<w:r><w:t xml:space="preserve"> {text}</w:t></w:r>'


def imported(build, notes=None, name='p.docx'):
    path = os.path.join(TMP, name)
    d = Document()
    build(d)
    if notes:
        raw = os.path.join(TMP, 'raw-' + name)
        d.save(raw)
        with_notes(raw, path, notes)
    else:
        d.save(path)
    rep = {}
    md = M.import_docx(path, report=rep)
    return md, rep, M.parse_markdown(md, smartquotes=False)


def blocks(parsed):
    return [b for c in parsed['chapters'] for b in c['blocks']]


def body_xml(d, xml):
    d.element.body.insert(len(d.element.body) - 1, parse_xml(xml))


def png():
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (12, 12), (200, 10, 10)).save(b, 'PNG')
    b.seek(0)
    return b


# ---- 13.1 ------------------------------------------------------------------
print('13.1 .DOCX replaced by .docx')
import app as A
A.PROJECT_MS_DIR = os.path.join(TMP, 'ms')
os.makedirs(A.PROJECT_MS_DIR)
open(os.path.join(A.PROJECT_MS_DIR, 'bk.DOCX'), 'wb').write(b'old')
stale = []
A._replace_file('bk', b'new', 'bk.docx', 'bk.DOCX', stale)
A._drop_files(stale)
check('the new manuscript is still there',
      os.path.exists(os.path.join(A.PROJECT_MS_DIR, 'bk.docx'))
      and open(os.path.join(A.PROJECT_MS_DIR, 'bk.docx'), 'rb').read() == b'new',
      os.listdir(A.PROJECT_MS_DIR))
src = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
check('a new book stores its manuscript extension in lower case',
      "ext = os.path.splitext(ms_src)[1].lower()" in src)

# ---- 13.2 ------------------------------------------------------------------
print('13.2 a ~~~ table cell')
def b2(d):
    d.add_heading('One', level=1)
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = 'Sign', 'Meaning'
    t.cell(1, 0).text, t.cell(1, 1).text = '~~~', 'Example'
    d.add_heading('Two', level=1)
    d.add_paragraph('Second chapter text.')
md, rep, parsed = imported(b2)
check('the next chapter survives', [c['title'] for c in parsed['chapters']] == ['One', 'Two'],
      md)
tbl = [b for b in blocks(parsed) if b[0] == 'doc_block' and b[2].get('_type') == 'table']
check('and the row is in the table', tbl and '~~~' in str(tbl[0][1]) and 'Example' in str(tbl[0][1]),
      tbl)

# ---- 13.3 ------------------------------------------------------------------
print('13.3 wrapped and boxed text')
def b3(d):
    d.add_heading('One', level=1)
    p = d.add_paragraph('Open the ')
    p._p.append(parse_xml(f'<w:ins {nsdecls("w")} w:id="1" w:author="x"><w:r><w:t xml:space="preserve">never </w:t></w:r></w:ins>'))
    p._p.append(parse_xml(f'<w:del {nsdecls("w")} w:id="2" w:author="x"><w:r><w:delText>gone </w:delText></w:r></w:del>'))
    p.add_run('valve.')
    p2 = d.add_paragraph('Call ')
    p2._p.append(parse_xml(f'<w:smartTag {nsdecls("w")} w:uri="u" w:element="place"><w:r><w:t>Harbourton</w:t></w:r></w:smartTag>'))
    p2._p.append(parse_xml(f'<w:fldSimple {nsdecls("w")} w:instr="DATE"><w:r><w:t xml:space="preserve"> today</w:t></w:r></w:fldSimple>'))
    body_xml(d, f'<w:sdt {nsdecls("w")}><w:sdtPr/><w:sdtContent><w:p><w:r><w:t>Inside a content control.</w:t></w:r></w:p></w:sdtContent></w:sdt>')
    host = d.add_paragraph('Host line.')
    host._p.append(parse_xml(
        f'<w:r {nsdecls("w", "wp", "a")} xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor><wp:docPr id="5" name="Box"/>'
        '<a:graphic><a:graphicData uri="x"><wps:wsp><wps:txbx><w:txbxContent>'
        '<w:p><w:r><w:t>Words in a box.</w:t></w:r></w:p>'
        '</w:txbxContent></wps:txbx></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>'
        '<mc:Fallback><w:pict><w:txbxContent><w:p><w:r><w:t>Words in a box.</w:t></w:r></w:p></w:txbxContent></w:pict></mc:Fallback>'
        '</mc:AlternateContent></w:r>'))
md, rep, parsed = imported(b3)
check('a tracked insertion is read', 'Open the never valve.' in md, md)
check('a tracked deletion is not', 'gone' not in md)
check('smart tags and field results are read', 'Call Harbourton today' in md, md)
check('a content control is read', 'Inside a content control.' in md, md)
check('a text box is read once', md.count('Words in a box.') == 1, md)

# ---- 13.4 ------------------------------------------------------------------
print('13.4 merged cells')
def b4(d):
    d.add_heading('One', level=1)
    t = d.add_table(rows=3, cols=3)
    for i, h in enumerate(('Name', 'Kind', 'Score')):
        t.cell(0, i).text = h
    m = t.cell(1, 0).merge(t.cell(1, 1))
    m.text = 'Wide'
    t.cell(1, 2).text = '90'
    down = t.cell(1, 2).merge(t.cell(2, 2))
    t.cell(2, 0).text, t.cell(2, 1).text = 'Lo', 'x'
md, rep, parsed = imported(b4)
rows = [ln for ln in md.split('\n') if '|' in ln]
check('the value stays under column three', any(re.fullmatch(r'Wide \|\s*\| 90', r) for r in rows),
      rows)
check('a cell merged down is not repeated', md.count('90') == 1, rows)

# ---- 13.5 ------------------------------------------------------------------
print('13.5 pictures and notes in cells')
def b5(d):
    d.add_heading('One', level=1)
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).paragraphs[0].add_run().add_picture(png())
    p = t.cell(0, 1).paragraphs[0]
    p.add_run('Cited')
    note_ref(p, 2)
md, rep, parsed = imported(b5, notes=[(2, plain_note('The cell note.'))])
check('the picture is placed after the table', '~~~ figure src=' in md and rep['figures'] == 1, md)
check('the note is kept', '[^note1]' in md and 'The cell note.' in md, md)

# ---- 13.6 ------------------------------------------------------------------
print('13.6 Read Aloud and the note texts')
def b6(d):
    d.add_heading('One', level=1)
    p = d.add_paragraph('Opening')
    note_ref(p, 2)
    d.add_heading('Read Aloud', level=2)
    d.add_paragraph('The door creaks.')
md, rep, parsed = imported(b6, notes=[(2, plain_note('A note.'))])
box = md[md.index('~~~ readaloud'):]
box = box[:box.index('\n~~~\n') + 4] if '\n~~~\n' in box else box
check('the box holds its own text only', 'A note.' not in box and 'The door creaks.' in box, box)
ch = parsed['chapters'][0]
check('the note keeps its definition', ch.get('notes') and ch['notes'][0]['text'] == 'A note.',
      ch.get('notes'))

# ---- 13.7 ------------------------------------------------------------------
print('13.7 a note on a chapter heading')
def b7(d):
    d.add_heading('One', level=1)
    d.add_paragraph('First text.')
    h = d.add_heading('Two', level=1)
    note_ref(h, 2)
    d.add_paragraph('Second text.')
md, rep, parsed = imported(b7, notes=[(2, plain_note('About chapter two.'))])
c1, c2 = parsed['chapters'][0], parsed['chapters'][1]
check('the note is in chapter two', not c1.get('notes') and c2.get('notes')
      and 'About chapter two.' in c2['notes'][0]['text'], (c1.get('notes'), c2.get('notes')))
check('the title stays clean', c2['title'] == 'Two', c2['title'])

# ---- 13.8 ------------------------------------------------------------------
print('13.8 a note that is all link')
def b8(d):
    d.add_heading('One', level=1)
    p = d.add_paragraph('Source')
    note_ref(p, 2)
md, rep, parsed = imported(b8, notes=[(2, '<w:hyperlink r:id="rIdLinkN"><w:r><w:t>Survey archive</w:t></w:r></w:hyperlink>')])
check('the note text survives', 'Survey archive' in md and '[^note1]' in md, md)

# ---- 13.9 ------------------------------------------------------------------
print('13.9 numbering')
NUMBERING = ('<w:numbering %s><w:abstractNum w:abstractNumId="7">'
             '<w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>'
             '<w:lvl w:ilvl="1"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
             '<w:num w:numId="9"><w:abstractNumId w:val="7"/></w:num></w:numbering>' % nsdecls('w'))
def b9(d):
    d.add_heading('One', level=1)
    # python-docx's default template has a numbering part: replace its content
    part = d.part.numbering_part
    part._element = parse_xml(NUMBERING)
    def item(text, lvl):
        p = d.add_paragraph(text)
        p._p.get_or_add_pPr().append(parse_xml(
            f'<w:numPr {nsdecls("w")}><w:ilvl w:val="{lvl}"/><w:numId w:val="9"/></w:numPr>'))
    item('First', 0); item('Second', 0); item('Child', 1); item('Third', 0)
md, rep, parsed = imported(b9)
check('a decimal list styled Normal is numbered', '~~~ list type="number"' in md, md)
check('the nested items are their own list', md.count('~~~ list') == 3, md)
check('and the parent counts on from 3', '~~~ list type="number" start="3"' in md, md)

# ---- 13.10 -----------------------------------------------------------------
print('13.10 italic then bold')
def b10(d):
    d.add_heading('One', level=1)
    p = d.add_paragraph()
    p.add_run('un').italic = True
    p.add_run('broken').bold = True
    p.add_run(' word.')
md, rep, parsed = imported(b10)
para = [b for b in blocks(parsed) if b[0] == 'para']
check('no stray asterisks', para and '*' not in M.strip_markup(para[0][1])
      if hasattr(M, 'strip_markup') else para and '\\*' not in md and '*un***' not in md, md)
import doc_model
line = [ln for ln in md.split('\n') if 'broken' in ln][0]
runs = doc_model._parse_inline(line, smartquotes=False)
check('and both styles are kept', [(r['text'], r['bold'], r['italic']) for r in runs][:2]
      == [('un', False, True), ('broken', True, False)], runs)

# ---- 13.11 -----------------------------------------------------------------
print('13.11 ### on the left')
def b11(d):
    d.add_heading('One', level=1)
    d.add_paragraph('Before.')
    d.add_paragraph('###')
    c = d.add_paragraph('###')
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    d.add_paragraph('After.')
md, rep, parsed = imported(b11)
kinds = [b[0] for b in blocks(parsed)]
check('one scene break, from the centred one', kinds.count('scene') == 1, kinds)
check('the left one prints as typed', any(b[0] == 'para' and b[1] == '###' for b in blocks(parsed)),
      blocks(parsed))

# ---- 13.12 -----------------------------------------------------------------
print('13.12 a link fragment')
def b12(d):
    d.add_heading('One', level=1)
    p = d.add_paragraph('See ')
    rid = p.part.relate_to('https://example.com/guide', RT.HYPERLINK, is_external=True)
    p._p.append(parse_xml(f'<w:hyperlink {nsdecls("w", "r")} r:id="{rid}" w:anchor="installation">'
                          '<w:r><w:t>the guide</w:t></w:r></w:hyperlink>'))
md, rep, parsed = imported(b12)
check('the link keeps #installation', '(https://example.com/guide#installation)' in md, md)

# ---- 13.13 -----------------------------------------------------------------
print('13.13 a pasted Homebrewery block')
src = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
check('both paste paths wrap unfenced stat blocks',
      src.count("statblock.wrap_unfenced(_norm_newlines(form['pasted']))") == 2)

# ---- 13.14 -----------------------------------------------------------------
print('13.14 the same pictures twice')
def b14(d):
    d.add_heading('One', level=1)
    d.add_paragraph().add_run().add_picture(png())
p = os.path.join(TMP, 'one.docx'); d = Document(); b14(d); d.save(p)
shutil.copy(p, os.path.join(TMP, '20260101-000000-abc-Story.docx'))
shutil.copy(p, os.path.join(TMP, '20260101-000001-xyz-Story.docx'))
for n in ('20260101-000000-abc-Story.docx', '20260101-000001-xyz-Story.docx'):
    M.import_docx(os.path.join(TMP, n), stem='Story')
figs = [f for f in os.listdir(M.FIGURE_DIR) if f.startswith('story-')]
check('one copy of the picture', len(figs) == 1, os.listdir(M.FIGURE_DIR))

# ---- speculative ------------------------------------------------------------
print('(spec.) a picture with a fallback copy')
def bfb(d):
    d.add_heading('One', level=1)
    p = d.add_paragraph()
    p.add_run().add_picture(png())
    blip = p._p.find('.//' + qn('a:blip'))
    rid = blip.get(qn('r:embed'))
    p._p.append(parse_xml(
        f'<w:r {nsdecls("w", "a", "r")} xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><mc:AlternateContent><mc:Fallback><w:pict>'
        f'<a:blip r:embed="{rid}"/></w:pict></mc:Fallback></mc:AlternateContent></w:r>'))
md, rep, parsed = imported(bfb)
check('imported once', md.count('~~~ figure') == 1, md)

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
