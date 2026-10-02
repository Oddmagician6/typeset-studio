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

# 6. a note that cites another note (#69). The reference used to reach the
# builders un-numbered, and both dropped it without a word.
t6 = ('# One\n\nA claim.[^a]\n\n[^a]: See also[^b] for more.\n'
      '[^b]: The other note.\n[^c]: Cited by nothing at all.\n')
for placement in ('end', 'foot'):
    out, r = build(t6, preset(placement))
    d = fitz.open(out); txt = ' '.join(p.get_text() for p in d); d.close()
    check(f'a note citing a note keeps its number ({placement})',
          re.search(r'See also\s*2\s*for more', txt) is not None,
          re.findall(r'See also.{0,20}', txt))
    os.remove(out)

import epub, zipfile
fd, ep = tempfile.mkstemp(suffix='.epub'); os.close(fd)
epub.build_epub(manuscript.parse_markdown(t6, smartquotes=True), preset('end'), ep, META)
with zipfile.ZipFile(ep) as z:
    notes_x = z.read(next(n for n in z.namelist()
                          if n.endswith('endnotes.xhtml'))).decode('utf-8')
check('the ebook links a note to the note it cites',
      '<a href="#note-1-2">2</a>' in notes_x and '<note' not in notes_x,
      re.findall(r'See also.{0,80}', notes_x))
bad = [c for c in epub.check(ep) if not c['ok']]
check('the ebook still passes its own checks', not bad, bad)
os.remove(ep)

# 7. a note too long for its page continues on the next (#73). It used to be
# planned whole, the reservation grew to nearly the full page, and the build
# died with a LayoutError on the next tall flowable.
def norm(s):
    return re.sub(r'\s+', ' ', s.replace('­', ''))

long_note = ' '.join('Sentence %d of a very long scholarly note that keeps going.' % k
                     for k in range(1, 61))
t7 = '# One\n\n' + '\n\n'.join(
    body % (i, '[^big]' if i == 2 else ('[^small]' if i == 3 else '')) for i in range(1, 30))
t7 += '\n\n[^big]: ' + long_note + ' THE-END.\n[^small]: A short one after it.\n'
try:
    out, r = build(t7, preset())
    built = True
except Exception as exc:
    built, r = False, {'error': repr(exc)}
check('a book with an overlong footnote builds', built, r)
if built:
    d = fitz.open(out)
    texts = [norm(p.get_text()) for p in d]
    def page_with(s):
        return next((i for i, t in enumerate(texts) if s in t), None)
    start, end, small = page_with('Sentence 1 of'), page_with('THE-END'), page_with('A short one')
    check('nothing is reported unplaced', r.get('notes_unplaced') == 0, r.get('notes_unplaced'))
    check('the note starts on its reference\'s page', start == 0, start)
    check('and continues onto later pages', end is not None and end > start, (start, end))
    whole = ' '.join(texts)
    check('every sentence of it is printed',
          all(' %d of a very long' % k in whole for k in range(1, 61)),
          [k for k in range(1, 61) if ' %d of a very long' % k not in whole][:5])
    check('the next note follows it, in order', small is not None and small >= end, (end, small))

    def rule_width(page):
        ws = [it['rect'].width for dr in page.get_drawings() for it in [dr]
              if dr['rect'].height < 2 and dr['rect'].width > 20]
        return max(ws) if ws else 0
    w0, w1 = rule_width(d[start]), rule_width(d[start + 1])
    check('a continued note sits under a full-measure rule', w1 > 2 * w0 > 0, (w0, w1))
    d.close(); os.remove(out)

# 8. ...and on the last page of a book there is no next page: it says so
t8 = ('# One\n\nA short book with one claim.[^big]\n\n[^big]: '
      + ' '.join('Sentence %d of a very long scholarly note that keeps going.' % k
                 for k in range(1, 121)) + '\n')
try:
    out, r = build(t8, preset())
    check('an overlong note on the last page builds', True)
    check('and the part with no page is reported', r.get('notes_unplaced') == 1,
          r.get('notes_unplaced'))
    os.remove(out)
except Exception as exc:
    check('an overlong note on the last page builds', False, repr(exc))

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
