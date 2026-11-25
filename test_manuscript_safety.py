"""Manuscript text reaches the book whole  (run: python test_manuscript_safety.py).

Joint bug hunt, section 5:

    5.1  a heading written straight after an endnote starts its chapter
    5.2  a telegram with `&` in it makes a well-formed EPUB page
    5.3  emphasis that straddles a link's edge never crosses its tags
    5.4  control characters from a text file never reach the XHTML
    5.5  two neighbouring Word table cells that read the same are both kept
    5.7  Word verse in one bold run across Shift+Enter stays bold on each line
"""

import sys, os, tempfile, shutil, zipfile
import xml.dom.minidom as minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import manuscript as M
import epub
import json
PRESET = json.load(open(os.path.join(HERE, 'presets', 'classic-literary.json'), encoding='utf-8'))
META = {'title': 'T', 'subtitle': '', 'author': 'A', 'year': '2026', 'publisher': '',
        'front_matter': 'none', 'right_hand_starts': False, 'include_toc': False,
        'smartquotes': True, 'cover_mode': 'none', 'cover_image': '',
        'cover_overlay': False, 'cover_color': 'light'}

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


def chapters_parse(path):
    """Every chapter page of an EPUB parses as XML: (ok, why)."""
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith('.xhtml'):
                try:
                    minidom.parseString(z.read(n))
                except Exception as exc:
                    return False, f'{n}: {exc}'
    return True, ''


def build(text, tmp, name):
    out = os.path.join(tmp, name + '.epub')
    epub.build_epub(M.parse_markdown(text), PRESET, out, dict(META))
    return out


def main():
    tmp = tempfile.mkdtemp(prefix='ts-ms-')
    try:
        print('5.1  a heading after an endnote')
        p = M.parse_markdown('# Sea\n\nA bell.[^bell]\n\n[^bell]: Brass.\n# Inland\nA new chapter.\n\n')
        check('starts its chapter', [c['title'] for c in p['chapters']] == ['Sea', 'Inland'],
              [c['title'] for c in p['chapters']])
        check('with its text', p['chapters'][-1]['blocks'] == [('para', 'A new chapter.')],
              p['chapters'][-1]['blocks'])
        p = M.parse_markdown('# Sea\n\nA bell.[^b]\n\n[^b]: Brass,\nwrapped on.\n')
        check('a wrapped note line still joins its note', 'wrapped on' not in str(p['chapters'][0]['blocks']))

        print('5.2  a telegram with an ampersand')
        ok, why = chapters_parse(build('# One\n\n~~~ telegram\nSalt & ash, <now> [go](https://x.test/a_b)\n~~~\n',
                                       tmp, 'tele'))
        check('makes a well-formed page', ok, why)
        with zipfile.ZipFile(os.path.join(tmp, 'tele.epub')) as z:
            body = ''.join(z.read(n).decode('utf-8') for n in z.namelist() if n.endswith('.xhtml'))
        check('reading SALT &amp; ASH, &lt;NOW&gt;', 'SALT &amp; ASH, &lt;NOW&gt;' in body)

        print('5.3  emphasis at a link\'s edge')
        check('a span half inside a link is left as typed',
              M._inline('*[Guide*](https://example.test)') ==
              '*<a href="https://example.test">Guide*</a>', M._inline('*[Guide*](https://example.test)'))
        check('a span around a whole link still works',
              M._inline('*[Guide](https://e.test)*') == '<i><a href="https://e.test">Guide</a></i>')
        ok, why = chapters_parse(build('# One\n\n*[Guide*](https://example.test) and **[Map**](https://m.test)\n',
                                       tmp, 'links'))
        check('and the EPUB page is well-formed', ok, why)

        print('5.4  control characters')
        text = '# One\n\nFirst page\x0cSecond page \x01odd\x00 \x1b[go](https://x.test)\n'
        ok, why = chapters_parse(build(text, tmp, 'ctrl'))
        check('never reach the XHTML', ok, why)
        check('a form feed reads as a line break',
              M.parse_markdown(text)['chapters'][0]['blocks'][0][1].startswith('First page Second page'))

        try:
            import docx
            from docx.enum.style import WD_STYLE_TYPE
        except ImportError:
            print('  (python-docx missing: Word checks skipped)')
            return
        print('5.5  Word table cells that read the same')
        d = docx.Document()
        t = d.add_table(rows=3, cols=3)
        for i, v in enumerate(['Mon', 'Tue', 'Wed']):
            t.cell(0, i).text = v
        for i, v in enumerate(['8', '8', '6']):
            t.cell(1, i).text = v
        t.cell(2, 0).merge(t.cell(2, 1)).text = 'Both'
        t.cell(2, 2).text = 'x'
        f = os.path.join(tmp, 'table.docx')
        d.save(f)
        md = M.import_docx(f)
        check('are both kept', '8 | 8 | 6' in md, md)
        check('while a merged cell is still one', 'Both | x' in md, md)

        print('5.7  Word verse in one bold run')
        d = docx.Document()
        d.add_heading('Poems', 1)
        d.styles.add_style('Verse', WD_STYLE_TYPE.PARAGRAPH)
        r = d.add_paragraph(style='Verse').add_run('Dawn')
        r.bold = True
        r.add_break()
        r.add_text('Dusk')
        f = os.path.join(tmp, 'verse.docx')
        d.save(f)
        md = M.import_docx(f)
        check('is bold on each line', '**Dawn**\n**Dusk**' in md, repr(md))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print()
        if fails:
            print(f'{len(fails)} FAILED: ' + '; '.join(fails))
            sys.exit(1)
        print('all manuscript safety checks passed')


if __name__ == '__main__':
    main()
