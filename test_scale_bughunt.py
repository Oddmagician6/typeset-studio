"""Joint bug hunt round 6, section 28: scale and pathological input.

(run: python test_scale_bughunt.py)

Each block names the finding it pins down. 28.1 (headings in two columns
leaving blank pages) did not reproduce: a thousand consecutive headings fill
every page. The quadratic slowdowns (28.5, 28.7, 28.8, 28.10-28.14) are left
for another round.
"""

import sys, os, io, shutil, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import engine, epub, manuscript, statblock, bookindex
from werkzeug.datastructures import FileStorage
from PIL import Image

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix='ts-bh28-')
try:
    # ---- 28.2 a challenge rating too big for a float sorts, not crashes
    try:
        key = bookindex.cr_order('9' * 400 + '/1')
        check('28.2 a 400-digit CR fraction sorts with the words', key[0] == 1, key)
    except Exception as exc:
        check('28.2 a 400-digit CR fraction sorts with the words', False, repr(exc))
    check('28.2 ordinary CRs still sort by number',
          bookindex.cr_order('1/4') < bookindex.cr_order('1') < bookindex.cr_order('10'))

    # ---- 28.2 an ability score thousands of digits long prints as written
    cells = [{'name': n, 'score': '10', 'mod': ''} for n in statblock.FIVE_E]
    cells[0]['score'] = '1' * 4301
    try:
        statblock._finish_scores(cells)
        check('28.2 a 4,301-digit score is left without a modifier',
              cells[0]['mod'] == '' and cells[1]['mod'] == '+0', cells[:2])
    except Exception as exc:
        check('28.2 a 4,301-digit score is left without a modifier', False, repr(exc))

    # ---- 28.3 a manuscript upload is read no further than its limit
    old = (A.MANUSCRIPT_TEXT_MAX_BYTES, dict(A.MANUSCRIPT_MAX_BYTES))
    A.MANUSCRIPT_TEXT_MAX_BYTES = 1000
    try:
        big = FileStorage(io.BytesIO(b'# One\n\n' + b'word ' * 1000), filename='huge.txt')
        try:
            A._manuscript_upload(big, os.path.join(TMP, 'up'))
            check('28.3 an over-limit .txt is refused', False, 'accepted')
        except A._PreviewError as exc:
            check('28.3 an over-limit .txt is refused', 'larger than' in str(exc), str(exc))
        check('28.3 nothing staged for the refused upload',
              not os.listdir(os.path.join(TMP, 'up')) if os.path.isdir(os.path.join(TMP, 'up')) else True)
        small = FileStorage(io.BytesIO(b'# One\n\nA few words.\n'), filename='ok.txt')
        path, text = A._manuscript_upload(small, os.path.join(TMP, 'up'))
        check('28.3 a small .txt still reads', 'A few words.' in text)
    finally:
        A.MANUSCRIPT_TEXT_MAX_BYTES, A.MANUSCRIPT_MAX_BYTES = old[0], old[1]

    # ---- 28.3 a Word file that unpacks to too much is refused before parsing
    try:
        from docx import Document
        have_docx = True
    except ImportError:
        have_docx = False
    if have_docx:
        doc = Document()
        doc.add_heading('One', 1)
        doc.add_paragraph('Words in the chapter.')
        dpath = os.path.join(TMP, 'big.docx')
        doc.save(dpath)
        old_xml = manuscript.DOCX_MAX_XML
        manuscript.DOCX_MAX_XML = 1000
        try:
            manuscript.import_docx(dpath)
            check('28.3 a Word file unpacking past the limit is refused', False, 'imported')
        except ValueError as exc:
            check('28.3 a Word file unpacking past the limit is refused', 'unpacks' in str(exc), str(exc))
        finally:
            manuscript.DOCX_MAX_XML = old_xml
        check('28.3 the same file imports under the real limit',
              'Words in the chapter.' in manuscript.import_docx(dpath))

        # ---- 28.4 a cell declaring a 500-million-column span
        from docx.oxml.ns import qn
        doc = Document()
        doc.add_heading('One', 1)
        t = doc.add_table(rows=1, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = 'Sword', 'd8'
        tcPr = t.cell(0, 0)._tc.get_or_add_tcPr()
        gs = tcPr.makeelement(qn('w:gridSpan'), {qn('w:val'): '500000000'})
        tcPr.append(gs)
        spath = os.path.join(TMP, 'span.docx')
        doc.save(spath)
        try:
            md = manuscript.import_docx(spath)
            row = [ln for ln in md.splitlines() if 'Sword' in ln]
            check('28.4 a huge declared span imports, bounded',
                  row and row[0].count('|') <= manuscript.DOCX_MAX_COLS + 2 and 'd8' in md,
                  (row[0][:80] if row else md[:200]))
        except MemoryError as exc:
            check('28.4 a huge declared span imports, bounded', False, repr(exc))
    else:
        print('  skip 28.3/28.4 Word cases: python-docx not installed')

    # ---- 28.6 a huge figure is scaled to its printed size before ReportLab
    big = os.path.join(TMP, 'big.png')
    Image.new('RGB', (6000, 4000), (200, 120, 40)).save(big)
    im = engine._sized(big, 144, 96)          # two inches wide
    size = im.size if hasattr(im, 'size') else Image.open(im).size
    check('28.6 a 6000 px figure placed 2 in wide is scaled down',
          size[0] <= 2 * engine.FIGURE_MAX_DPI + 2, size)
    check('28.6 a figure already near its size goes through as the path',
          engine._sized(big, 6000 / engine.FIGURE_MAX_DPI * 72, 4000 / engine.FIGURE_MAX_DPI * 72) == big)
    jpg = os.path.join(TMP, 'big.jpg')
    Image.new('RGB', (6000, 4000), (40, 120, 200)).save(jpg, quality=80)
    im = engine._sized(jpg, 144, 96)
    check('28.6 a large JPEG is scaled down too', im.size[0] <= 2 * engine.FIGURE_MAX_DPI + 2, im.size)

    # ---- 28.9 an EPUB is written beside its name and renamed into place
    ms = manuscript.parse_markdown('# One\n\nThe words.\n')
    out = os.path.join(TMP, 'book.epub')
    seen = {}
    real = epub._build_epub
    def spy(m, p, path, meta):
        seen['path'] = path
        seen['final_absent'] = not os.path.exists(out)
        return real(m, p, path, meta)
    epub._build_epub = spy
    try:
        epub.build_epub(ms, dict(A.DEFAULTS), out, {'title': 'T', 'author': 'A'})
    finally:
        epub._build_epub = real
    check('28.9 the EPUB is built under a working name', seen.get('path') == out + epub.EPUB_PART, seen)
    check('28.9 ... and lands under its own name, the working copy gone',
          zipfile.is_zipfile(out) and not os.path.exists(out + epub.EPUB_PART))
    def boom(*a, **k):
        open(a[2], 'wb').write(b'PK half')
        raise RuntimeError('cut off')
    epub._build_epub = boom
    out2 = os.path.join(TMP, 'cut.epub')
    try:
        epub.build_epub(ms, dict(A.DEFAULTS), out2, {'title': 'T', 'author': 'A'})
    except RuntimeError:
        pass
    finally:
        epub._build_epub = real
    check('28.9 a build cut off leaves nothing under either name',
          not os.path.exists(out2) and not os.path.exists(out2 + epub.EPUB_PART))
    # the startup sweep clears an old working copy and its empty reserved name
    old_out = A.OUT_DIR
    A.OUT_DIR = os.path.join(TMP, 'out')
    os.makedirs(A.OUT_DIR)
    try:
        final = os.path.join(A.OUT_DIR, 'b.epub')
        open(final, 'wb').close()
        open(final + epub.EPUB_PART, 'wb').write(b'PK half')
        os.utime(final + epub.EPUB_PART, (1, 1))
        A._sweep_stale()
        check('28.9 the startup sweep clears a cut-off EPUB',
              not os.path.exists(final) and not os.path.exists(final + epub.EPUB_PART))
    finally:
        A.OUT_DIR = old_out

    # ---- 28.15 the EPUB check reads a picture's header, not the picture
    opened = []
    real_read = zipfile.ZipFile.read
    def counting(self, name, pwd=None):
        opened.append(name)
        return real_read(self, name, pwd)
    fig = os.path.join(TMP, 'fig.png')
    Image.new('RGB', (40, 30), (1, 2, 3)).save(fig)
    old_fig = epub.FIGURE_DIR
    epub.FIGURE_DIR = TMP
    try:
        ms = manuscript.parse_markdown('# One\n\nWords.\n\n~~~ figure src="fig.png" alt="A square"\n~~~\n')
        out3 = os.path.join(TMP, 'fig.epub')
        epub.build_epub(ms, dict(A.DEFAULTS), out3, {'title': 'T', 'author': 'A'})
        zipfile.ZipFile.read = counting
        try:
            res = epub.check(out3)
        finally:
            zipfile.ZipFile.read = real_read
    finally:
        epub.FIGURE_DIR = old_fig
    with zipfile.ZipFile(out3) as zf:
        imgs = [n for n in zf.namelist() if n.lower().endswith('.png')]
    check('28.15 the book carries the picture', bool(imgs), zipfile.ZipFile(out3).namelist())
    check('28.15 the check never reads a whole picture', not any(n in opened for n in imgs), opened)
    check('28.15 the picture still passes its type check',
          all(r['ok'] for r in res if 'type' in r['label'].lower() or 'image' in r['label'].lower()),
          [r for r in res if not r['ok']])

finally:
    shutil.rmtree(TMP, ignore_errors=True)

print()
if fails:
    print(f'{len(fails)} FAILED:')
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('all passed')
