"""What reaches a printer or a store  (run: python test_outputs.py).

Bug hunt item 7: large print, the ebook, and the Send to print / publish page.
Checked, against throwaway folders:

    LARGE PRINT   every bundled style's large-print edition, over the sample with
                  full front matter: nothing to read under 16pt (running heads and
                  folios aside), the copyright page on one page, the trim and name;
                  the route, and the style editor keeping its smallest-text floor;
                  an ordinary book built alongside keeps its own sizes
    EBOOK         every style, the sample and an awkward manuscript: a structural
                  validation epubcheck would make (container, metadata, manifest
                  against the zip, media types, XHTML namespace, unique ids, every
                  link to a file and an id that exist) and our own checks clean;
                  block headers with & and < in them; the ebook preview
    LINKS         two chapters with one title: each linkable, and the PDF and the
                  ebook send a link to the same chapter
    PACKAGE       the Send to print and Send to publish pages: the checks shown are
                  the spec sheet's, the download serves the zip, a re-run makes a
                  second one and keeps the first
"""

import sys, os, io, re, json, shutil, tempfile, threading, zipfile, posixpath, collections
from html.parser import HTMLParser
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import engine, epub, manuscript, matter
import fitz

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-outputs-')
ROOT = os.path.join(tmp, 'data')
os.makedirs(ROOT)
shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(ROOT, 'presets'))
shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(ROOT, 'covers'),
                ignore=shutil.ignore_patterns('assets'))
A.PRESET_DIR, A.COVER_DIR = os.path.join(ROOT, 'presets'), os.path.join(ROOT, 'covers')
A.PROJECT_DIR = os.path.join(ROOT, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(ROOT, 'out')
A.UPLOAD_DIR = os.path.join(ROOT, 'uploads')
A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.COVER_THUMB_DIR, A.PROJECT_THUMB_DIR):
    os.makedirs(d, exist_ok=True)

C = A.app.test_client()
SAMPLE = open(A.SAMPLE, encoding='utf-8').read()
FULL_META = {'title': 'The Salt Road', 'author': 'Ellinor Vale', 'front_matter': 'full',
             'right_hand_starts': True, 'include_toc': True, 'cover_mode': 'none',
             **matter.blank(), 'dedication': 'For M.', 'epigraph': 'Salt keeps.',
             'about_author': 'Ellinor lives by the sea.'}

AWKWARD = '''=== Part One & the "Opening"

# 1984

Opening.

The first chapter, with a note.[^a] See [the other one](#the-salt-road), [the second
1984](#1984-2) and [the first](#1984).

[^a]: A note with **bold** & an ampersand.

# The Salt Road | Ada Merrow & Co

Text < with > odd & characters, "quotes" and 'apostrophes'.

~~~ poem title="Salt & <Ash>"
The first line of verse
  an indented second

A second stanza
~~~

~~~ table
Name | Value
Salt | 3 & 4
~~~

# 1984

Opening.

The same title again.[^b] Back to [the first](#1984).

[^b]: Second note.

#* Epilogue

Глава на русском.

~~~ letter from="A & B" to="<C>" date="1 May"
Dear C,
~~~

~~~ journal date="2 & 3 May" author="<D>"
Entry.
~~~

~~~ telegram to="E & <F>"
STOP
~~~

~~~ newspaper headline="Salt & <Ash>" date="4 May" source="The <Courier> & Post"
Story.
~~~

~~~ redacted classification="Secret & <Restricted>"
Text.
~~~
'''


def text_spans(path):
    """[(page, size, text, y0, y1, page_h)] for every span with text."""
    out = []
    with fitz.open(path) as d:
        for pno, page in enumerate(d):
            for b in page.get_text('dict')['blocks']:
                for l in b.get('lines', []):
                    for s in l['spans']:
                        if s['text'].strip():
                            out.append((pno, s['size'], s['text'], s['bbox'][1], s['bbox'][3],
                                        page.rect.height))
    return out


def large_print_tests():
    print('\n[large print, every bundled style]')
    ms = manuscript.parse_markdown(SAMPLE, smartquotes=True)
    out = os.path.join(tmp, 'lp.pdf')
    for it in A.list_presets():
        lp = A.make_large_print(A.load_preset(it['id']))
        engine.build_pdf(ms, lp, out, FULL_META)
        top, bottom = lp['margins']['top'] * 72, lp['margins']['bottom'] * 72
        # running heads and folios live in the margins: navigation, not reading
        small = [(p + 1, round(sz, 1), t[:30]) for p, sz, t, y0, y1, h in text_spans(out)
                 if sz < 15.95 and y0 > top - 2 and y1 < h - bottom + 2]
        with fitz.open(out) as d:
            cp = [i for i, pg in enumerate(d) if 'fictitious' in pg.get_text()
                  or 'Copyright' in pg.get_text()]
        check(f'{it["id"]}: nothing to read under 16pt', not small, small[:4])
        check(f'{it["id"]}: the copyright page is one page', len(cp) == 1, cp)
        check(f'{it["id"]}: at least 7" wide, named for its page',
              lp['trim']['w'] >= 7 and 'Large Print' in lp['name']
              and lp.get('min_text_size') == 16, (lp['trim'], lp['name']))

    print('\n[large print, from the styles page]')
    r = C.post('/large-print/classic-literary')
    new_id = r.headers['Location'].rsplit('/', 1)[-1]
    lp = A.load_preset(new_id)
    check('the route makes the style and opens it in the editor',
          r.status_code == 302 and '/editor/' in r.headers['Location']
          and lp['body']['size'] == 16, r.headers.get('Location'))
    html = C.get(f'/editor/{new_id}').get_data(as_text=True)
    check('the editor shows its smallest text', 'name="min_text_size" value="16' in html)
    form = form_of(html, '/save/')
    C.post(f'/save/{new_id}', data=form)
    check('saved unchanged in the editor, it keeps it',
          A.load_preset(new_id).get('min_text_size') == 16, A.load_preset(new_id).get('min_text_size'))
    form['min_text_size'] = '0'
    C.post(f'/save/{new_id}', data=form)
    check('set to 0, it is gone', 'min_text_size' not in A.load_preset(new_id))
    html = C.get('/editor/classic-literary').get_data(as_text=True)
    C.post('/save/classic-literary', data=form_of(html, '/save/'))
    check('an ordinary style saved unchanged gains no floor',
          'min_text_size' not in A.load_preset('classic-literary'))
    again = A.make_large_print(lp | {'min_text_size': 16})
    check('large print of a large-print style: same size, name not doubled',
          again['body']['size'] == 16 and again['name'].count('Large Print') == 1, again['name'])

    print('\n[large print beside an ordinary book, at once]')
    plain, sizes, errors = os.path.join(tmp, 'plain-%d.pdf'), {}, []
    def job(i):
        try:
            p = plain % i
            preset = A.make_large_print(A.load_preset('classic-literary')) if i % 2 else \
                A.load_preset('classic-literary')
            engine.build_pdf(ms, preset, p, FULL_META)
            sizes[i] = min(sz for pg, sz, t, *_ in text_spans(p) if 'Copyright' in t)
        except Exception as exc:
            errors.append(repr(exc))
    ts = [threading.Thread(target=job, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check('each keeps its own copyright size (8.5pt and 16pt)', not errors and
          all(abs(sizes[i] - (16 if i % 2 else 8.5)) < 0.05 for i in range(8)), (errors, sizes))


class FormFields(HTMLParser):
    """What a browser would submit from the form posting to `action`, untouched."""
    def __init__(self, action):
        super().__init__(convert_charrefs=True)
        self.action, self.inside, self.fields = action, False, []
        self.select, self.options, self.textarea = None, [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self.inside = self.action in (a.get('action') or '')
        if not self.inside or 'disabled' in a:
            return
        if tag == 'input' and a.get('name'):
            kind = (a.get('type') or 'text').lower()
            if kind in ('checkbox', 'radio'):
                if 'checked' in a:
                    self.fields.append((a['name'], a.get('value', 'on')))
            elif kind not in ('file', 'submit', 'button', 'image', 'reset'):
                self.fields.append((a['name'], a.get('value', '')))
        elif tag == 'select' and a.get('name'):
            self.select, self.options = a['name'], []
        elif tag == 'option' and self.select:
            self.options.append([a.get('value'), 'selected' in a, ''])
        elif tag == 'textarea' and a.get('name'):
            self.textarea = [a['name'], '']

    def handle_data(self, data):
        if self.textarea is not None:
            self.textarea[1] += data
        elif self.select and self.options and self.options[-1][0] is None:
            self.options[-1][2] += data

    def handle_endtag(self, tag):
        if tag == 'form':
            self.inside = False
        elif tag == 'textarea' and self.textarea is not None:
            name, text = self.textarea
            self.fields.append((name, text[1:] if text.startswith('\n') else text))
            self.textarea = None
        elif tag == 'select' and self.select:
            opts = [(v if v is not None else t.strip(), s) for v, s, t in self.options]
            pick = next((v for v, s in opts if s), opts[0][0] if opts else None)
            if pick is not None:
                self.fields.append((self.select, pick))
            self.select = None


def form_of(html, action):
    p = FormFields(action)
    p.feed(html)
    return dict(p.fields)


MEDIA = {'.xhtml': 'application/xhtml+xml', '.css': 'text/css', '.jpg': 'image/jpeg',
         '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif',
         '.ncx': 'application/x-dtbncx+xml', '.svg': 'image/svg+xml'}


def validate(path):
    """What epubcheck would object to, structurally. [] if nothing."""
    probs = []
    z = zipfile.ZipFile(path)
    names = z.namelist()
    if names[0] != 'mimetype' or z.read('mimetype') != b'application/epub+zip' \
            or z.getinfo('mimetype').compress_type != zipfile.ZIP_STORED:
        probs.append('mimetype entry')
    opf_path = minidom.parseString(z.read('META-INF/container.xml')).getElementsByTagName(
        'rootfile')[0].getAttribute('full-path')
    base = posixpath.dirname(opf_path)
    full = lambda h: posixpath.normpath(posixpath.join(base, h)) if base else h
    opf = minidom.parseString(z.read(opf_path))
    uid = opf.documentElement.getAttribute('unique-identifier')
    if not any(e.getAttribute('id') == uid for e in opf.getElementsByTagName('dc:identifier')):
        probs.append('unique-identifier names no dc:identifier')
    for tag in ('dc:title', 'dc:language'):
        el = opf.getElementsByTagName(tag)
        if not el or not el[0].firstChild:
            probs.append('missing ' + tag)
    mod = [m for m in opf.getElementsByTagName('meta')
           if m.getAttribute('property') == 'dcterms:modified']
    if len(mod) != 1 or not mod[0].firstChild or not re.fullmatch(
            r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', mod[0].firstChild.data):
        probs.append('dcterms:modified')
    items, ids = {}, set()
    for it in opf.getElementsByTagName('item'):
        iid, href, mt = it.getAttribute('id'), it.getAttribute('href'), it.getAttribute('media-type')
        if iid in ids:
            probs.append('duplicate manifest id ' + iid)
        ids.add(iid)
        items[iid] = (href, mt, it.getAttribute('properties'))
        ext = os.path.splitext(href)[1].lower()
        if MEDIA.get(ext) and MEDIA[ext] != mt:
            probs.append(f'media-type {mt} for {href}')
        if full(href) not in names:
            probs.append('manifest names a missing file: ' + href)
    for ref in opf.getElementsByTagName('itemref'):
        if ref.getAttribute('idref') not in items:
            probs.append('spine names a missing item: ' + ref.getAttribute('idref'))
    if not any('nav' in p.split() for _, _, p in items.values()):
        probs.append('no nav document')
    docs, doms = [full(h) for h, mt, _ in items.values() if mt == 'application/xhtml+xml'], {}
    for name in docs:
        try:
            d = minidom.parseString(z.read(name))
        except Exception as exc:
            probs.append(f'{name} not well-formed: {exc}')
            continue
        if d.documentElement.getAttribute('xmlns') != 'http://www.w3.org/1999/xhtml':
            probs.append(f'{name} outside the XHTML namespace')
        c = collections.Counter()
        def walk(n):
            if n.nodeType == n.ELEMENT_NODE:
                if n.getAttribute('id'):
                    c[n.getAttribute('id')] += 1
                for k in n.childNodes:
                    walk(k)
        walk(d.documentElement)
        if any(v > 1 for v in c.values()):
            probs.append(f'{name} repeats ids {[i for i, v in c.items() if v > 1][:3]}')
        doms[name] = (d, set(c))
    for name, (d, _) in doms.items():
        for a in d.getElementsByTagName('a'):
            href = a.getAttribute('href')
            if not href or re.match(r'[a-z]+:', href):
                continue
            file, _, frag = href.partition('#')
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), file)) if file else name
            if target not in doms:
                probs.append(f'{name}: link to a missing file {href}')
            elif frag and frag not in doms[target][1]:
                probs.append(f'{name}: link to a missing id {href}')
    return probs


def chapter_file_of(path, link_text):
    """The chapter file the link with this text points at, in an EPUB."""
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith('.xhtml'):
                m = re.search(r'<a href="([^"#]*)[^"]*">' + re.escape(link_text) + '</a>',
                              z.read(n).decode('utf-8'))
                if m:
                    return m.group(1)


def ebook_tests():
    print('\n[the ebook, every bundled style]')
    meta = dict(FULL_META, title='Salt & Ash: "Road"', author='Ada <Merrow>',
                dedication='For M & N.', also_by='One\nTwo', cover_image='')
    for it in A.list_presets():
        for label, text in (('sample', SAMPLE), ('awkward', AWKWARD)):
            out = os.path.join(tmp, f'{it["id"]}-{label}.epub')
            epub.build_epub(manuscript.parse_markdown(text, smartquotes=True),
                            A.load_preset(it['id']), out, meta)
            probs = validate(out)
            ours = [(c['label'], c['detail'][:70]) for c in epub.check(out) if not c['ok']]
            check(f'{it["id"]}, {label}: valid, and our checks clean', not probs and not ours,
                  (probs[:3], ours[:3]))

    print('\n[block headers with & and < in them]')
    ms = manuscript.parse_markdown(AWKWARD, smartquotes=True)
    pdf = os.path.join(tmp, 'aw.pdf')
    engine.build_pdf(ms, A.load_preset('classic-literary'), pdf,
                     dict(FULL_META, front_matter='none'))
    with fitz.open(pdf) as d:
        text = '\n'.join(pg.get_text() for pg in d)
    want = ['A & B to <C>', '2 & 3 May', '<D>', 'E & <F>', 'SALT & <ASH>',
            'The <Courier> & Post', 'SECRET & <RESTRICTED>', 'Salt & <Ash>']
    check('the PDF prints each as typed', all(w in text for w in want),
          [w for w in want if w not in text])
    ep = os.path.join(tmp, 'aw.epub')
    epub.build_epub(ms, A.load_preset('classic-literary'), ep,
                    dict(FULL_META, front_matter='none', cover_image=''))
    with zipfile.ZipFile(ep) as z:
        etext = ''.join(re.sub(r'<[^>]+>', '', z.read(n).decode('utf-8'))
                        for n in z.namelist() if re.search(r'chapter\d+\.xhtml$', n))
    import html as _h
    etext = _h.unescape(etext)
    check('so does the ebook', all(w in etext for w in want), [w for w in want if w not in etext])

    print('\n[two chapters with one title]')
    with fitz.open(pdf) as d:
        def target_of(text):
            for pg in d:
                for l in pg.get_links():
                    if l.get('kind') == fitz.LINK_GOTO and \
                            text in pg.get_textbox(l['from']).replace('\n', ' '):
                        return l['page'] + 1
        page_of = lambda s: next(i + 1 for i, pg in enumerate(d)
                                 if s in pg.get_text().replace('\n', ' '))
        first, second = page_of('with a note'), page_of('same title again')
        check('in the PDF, #1984 goes to the first and #1984-2 to the second',
              target_of('the first') == first,
              (target_of('the first'), first))
        check('and the second is linkable', target_of('1984') == second,
              (target_of('1984'), second))
    check('the ebook sends them to the same chapters',
          chapter_file_of(ep, 'the first') == 'chapter001.xhtml'
          and chapter_file_of(ep, 'the second\n1984') in ('chapter003.xhtml', None)
          and 'chapter003.xhtml' in zipfile.ZipFile(ep).read('OEBPS/chapter001.xhtml').decode(),
          chapter_file_of(ep, 'the first'))
    check('neither reports a dead link',
          engine.build_pdf(ms, A.load_preset('classic-literary'), pdf,
                           dict(FULL_META, front_matter='none'))['dead_links'] == []
          and not [c for c in epub.check(ep) if c['label'] == 'Internal links' and not c['ok']])

    print('\n[the ebook preview]')
    # the preview shows the first two chapters, so the letter goes first
    letter = AWKWARD[AWKWARD.index('~~~ letter'):]
    form = {'preset': 'classic-literary', 'pasted': '# One\n\n' + letter, 'title': 'Salt & Ash',
            'author': 'A', 'front_matter': 'none', 'cover_mode': 'none', 'smartquotes': 'on'}
    j = C.post('/generate/epub-preview', data=form).get_json()
    shown = _h.unescape(re.sub(r'<[^>]+>', '', ''.join(x['html'] for x in j.get('docs', []))))
    check('it shows the awkward book, headers as typed', j['ok'] and 'A & B to <C>' in shown,
          j.get('error'))


def book(pid, **extra):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as f:
        f.write(SAMPLE)
    A.save_project_file(pid, {
        'name': pid, 'preset': 'classic-literary', 'title': 'The Salt Road',
        'author': 'Ellinor Vale', 'front_matter': 'full', 'right_hand_starts': True,
        'cover_mode': 'designed', 'cover_template': 'fantasy-emerald', 'format': 'both',
        'include_toc': False, 'smartquotes': True, **matter.blank(),
        'manuscript_file': pid + '.md', 'manuscript_type': 'markdown',
        'print_retailer': 'kdp', 'print_binding': 'paperback', 'print_paper': 'cream',
        'print_isbn': '', 'last_pdf': '', 'last_epub': '', **extra})


def rows_on_page(html):
    """(mark, label, detail) for every check row the page shows."""
    out = []
    for m in re.finditer(r'<span class="icon (\w+)">.*?</span>\s*<span class="chk-label[^"]*">(.*?)</span>'
                         r'\s*<span class="chk-detail">(.*?)</span>', html, re.S):
        import html as _h
        out.append(({'ok': 'ok', 'note': '--', 'warn': '!!'}[m.group(1)],
                    _h.unescape(m.group(2)).strip(), _h.unescape(m.group(3)).strip()))
    return out


def package_tests():
    for scope in ('print', 'publish'):
        print(f'\n[Send to {scope}: the page]')
        book(f'pk-{scope}')
        r = C.post(f'/project/pk-{scope}/print-package', data={'scope': scope})
        html = r.get_data(as_text=True)
        zip_name = A.load_project(f'pk-{scope}')['last_print_package']
        z = zipfile.ZipFile(os.path.join(A.OUT_DIR, zip_name))
        spec = next(n for n in z.namelist() if n.endswith('SPEC.txt'))
        lines = [(m, l, d.strip()) for m, l, d in re.findall(r'^  \[(ok|--|!!)\] (.*?): (.*)$', z.read(spec).decode('utf-8'), re.M)]
        page = rows_on_page(html)
        check('the page shows the checks the spec sheet carries, in order',
              r.status_code == 200 and page and
              [(m, l, d) for m, l, d in page] == [(m, l, d) for m, l, d in lines],
              (len(page), len(lines), [x for x in zip(page, lines) if x[0] != x[1]][:2]))
        listed = re.findall(r'<li(?: class="nested")?>(.*?)</li>', html)
        inside = sorted(n.split('/', 1)[1] for n in z.namelist() if not n.endswith('/'))
        check('and lists the files the zip holds', sorted(listed) == inside, (listed, inside))
        if scope == 'publish':
            check('with the ebook in it, and its checks', any(n.endswith('.epub') for n in inside)
                  and 'EBOOK CHECKS' in z.read(spec).decode('utf-8'), inside)
        d = C.get(f'/download/{zip_name}')
        check('the download is the zip', d.status_code == 200 and d.data[:2] == b'PK'
              and 'attachment' in d.headers.get('Content-Disposition', ''))
        d.close()
        r2 = C.post(f'/project/pk-{scope}/print-package', data={'scope': scope})
        second = A.load_project(f'pk-{scope}')['last_print_package']
        check('a re-run makes a second package and keeps the first',
              r2.status_code == 200 and second != zip_name
              and os.path.exists(os.path.join(A.OUT_DIR, zip_name))
              and os.path.exists(os.path.join(A.OUT_DIR, second)), (zip_name, second))
        z.close()


def main():
    try:
        large_print_tests()
        ebook_tests()
        package_tests()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == '__main__':
    code = main()
    print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
    sys.exit(code)
