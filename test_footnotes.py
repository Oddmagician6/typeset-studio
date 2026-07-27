"""Footnote placement tests  (run: python test_footnotes.py).

Notes at the foot of the page are the one feature here that cannot be checked by
reading the code: whether a note lands on its reference's page is only knowable
from the built PDF. So each case builds a book and measures the result.
"""

import sys, os, json, re, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)
import engine, manuscript, matter, fitz

BASE = HERE
fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond: fails.append(name)

def preset(placement='foot', **kw):
    p = json.load(open(os.path.join(BASE, 'presets', 'classic-literary.json'), encoding='utf-8'))
    p['endnotes'] = dict(p.get('endnotes', {}), placement=placement, **kw)
    return p

META = {'title': 'T', 'subtitle': '', 'author': 'E', 'year': '2026', 'publisher': '',
        'front_matter': 'none', 'right_hand_starts': False, 'include_toc': False,
        'smartquotes': True, 'cover_mode': 'none', 'cover_image': '',
        'cover_overlay': False, 'cover_color': 'light', **{k: '' for k in matter.KEYS}}

def build(text, p, meta=None):
    ms = manuscript.parse_markdown(text, smartquotes=True)
    fd, out = tempfile.mkstemp(suffix='.pdf'); os.close(fd)
    r = engine.build_pdf(ms, p, out, dict(META, **(meta or {})))
    return out, r

def pages_of(path):
    """[(refs, notes)] per page."""
    d = fitz.open(path); out = []
    for page in d:
        spans = [s for b in page.get_text('dict')['blocks'] for l in b.get('lines', [])
                 for s in l['spans']]
        SUP = dict(zip('⁰¹²³⁴⁵⁶⁷⁸⁹', '0123456789'))
        refs = {s['text'].strip() for s in spans
                if abs(s['size'] - 7.4) < 0.6 and s['text'].strip().isdigit()}
        for s in spans:            # decorative openings use real superscript glyphs
            for ch in s['text']:
                if ch in SUP:
                    refs.add(SUP[ch])
        refs = sorted(refs, key=int)
        notes = sorted({m.group(1) for s in spans if abs(s['size'] - 10.0) < 0.7
                        for m in [re.match(r'^(\d+)\.\s', s['text'])] if m}, key=int)
        out.append((refs, notes))
    d.close(); return out

body = ('Paragraph %d of the survey, with enough words to fill the measure and carry '
        'the text down the page.%s')

# 1. a note on the very first line of a chapter
t1 = '# One\n\nA claim right at the start.[^a]\n\n[^a]: The supporting note.\n'
out, r = build(t1, preset())
pg = pages_of(out)
check('a note on the opening line sits on that page', pg[0] == (['1'], ['1']), pg[:2])
os.remove(out)

# 2. many notes on one page -> the overflow runs on rather than eating the page
t2 = '# One\n\n' + '\n\n'.join(
    body % (i, ''.join('[^n%d_%d]' % (i, j) for j in range(1, 6))) for i in range(1, 4))
t2 += '\n\n' + '\n'.join(
    '[^n%d_%d]: A deliberately long note %d-%d that runs to a couple of lines so the '
    'foot of the page fills up quickly and something has to give.' % (i, j, i, j)
    for i in range(1, 4) for j in range(1, 6))
out, r = build(t2, preset())
pg = pages_of(out)
total_notes = sum(len(n) for _, n in pg)
# 15 two-line notes cannot share a one-page book with their references. The
# contract is not that they all fit - it is that the build says so.
check('what could not fit is reported, not dropped',
      total_notes + r.get('notes_unplaced', 0) == 15,
      (total_notes, r.get('notes_unplaced')))
check('no page is entirely notes', all(refs or not notes for refs, notes in pg), pg)
os.remove(out)

# 3. footnotes and a TOC together (both use extra passes)
t3 = '# One\n\n' + '\n\n'.join(body % (i, '[^n%d]' % i if i % 4 == 0 else '')
                               for i in range(1, 20))
t3 += '\n\n# Two\n\nMore text.[^z]\n\n[^z]: A note in chapter two.\n'
t3 += '\n' + '\n'.join('[^n%d]: Note %d.' % (i, i) for i in range(4, 20, 4))
out, r = build(t3, preset(), {'include_toc': True})
d = fitz.open(out); txt = ' '.join(p.get_text() for p in d); d.close()
check('TOC and footnotes coexist', 'Contents' in txt and r['page_count'] > 2, r['page_count'])
pg = pages_of(out)
check('numbering restarts in chapter two',
      any('1' in notes for refs, notes in pg[len(pg)//2:]), pg)
os.remove(out)

# 4. endnote mode is untouched
out, r = build(t3, preset('end'))
d = fitz.open(out); txt = ' '.join(p.get_text() for p in d); d.close()
check('endnote mode still makes a Notes page', 'Notes' in txt)
os.remove(out)

# 5. no notes at all -> no reservation, no wasted space
t5 = '# One\n\n' + '\n\n'.join(body % (i, '') for i in range(1, 8))
out_f, rf = build(t5, preset())
out_e, re_ = build(t5, preset('end'))
check('a book with no notes is identical either way', rf['page_count'] == re_['page_count'],
      (rf['page_count'], re_['page_count']))
os.remove(out_f); os.remove(out_e)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
