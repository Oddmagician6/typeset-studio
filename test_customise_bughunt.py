"""Customise keeps what the template had  (run: python test_customise_bughunt.py).

Joint bug hunt, round 3, section 15:

    15.1  a late conversion doesn't land on the book opened since
    15.2  a blurb cut short above the barcode keeps all its copy, and says so
    15.3  an .otf with TrueType outlines is a designer font; no font at all is said
    15.4  a Cover Studio upload can't stand in for a converted picture
    15.5  front-flap copy follows the fold when the trim grows
    15.6  a damaged old template doesn't stop Customise from another one
    15.7  art the template names but the library lacks is noted
    15.8  a title and byline set alike stay two boxes
    15.9  one-line paragraphs keep the line leading, the gap kept for the breaks
    15.10 a title broken between letters stays one word, and says so
    15.11 a label keeps the spaces it was typed with
"""

import copy, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.ERROR)

import app as A
import engine
import wrap_convert as WC
import wrap_design as WDm

fails = []


def check(label, ok, detail=''):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f'         {detail}')
        fails.append(label)


tmp = tempfile.mkdtemp(prefix='ts-customise-')
A.OUT_DIR = os.path.join(tmp, 'out')
A.WRAP_DESIGN_DIR = os.path.join(A.OUT_DIR, '_wrap_designer')
A.COVER_ASSET_DIR = os.path.join(tmp, 'assets')
A.PROJECT_DIR = os.path.join(tmp, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
REAL_COVERS = A.COVER_DIR
A.COVER_DIR = os.path.join(tmp, 'covers')
WDm.ART_DIRS = [A.COVER_ASSET_DIR, A.WRAP_DESIGN_DIR]
WC.IMPORT_DIR = A.WRAP_DESIGN_DIR
for d in (A.WRAP_DESIGN_DIR, A.COVER_ASSET_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR, A.COVER_DIR):
    os.makedirs(d, exist_ok=True)
shutil.copy(os.path.join(REAL_COVERS, 'ashforge-house.json'), A.COVER_DIR)

CLASSIC = A.load_cover_template('ashforge-house')
INTERIOR = engine.register_fonts(A.DEFAULTS)
META = {'title': 'The Salt Road', 'author': 'Ada Merrow', 'cover_studio': 'Ashforge Studio',
        'cover_blurb': 'A road no map shows.'}
DIMS = A._wrap_dims({'wrap_retailer': 'kdp'}, 320)


def convert(tpl=None, dims=None, **meta):
    tpl = tpl or CLASSIC
    cf = engine._register_cover_fonts(tpl, INTERIOR)
    return WC.from_template(tpl, cf, dict(META, **meta), dims or DIMS)


def texts(design):
    return [e for e in design['elements'] if e['type'] == 'text']


def test_text():
    print('\nthe writer\'s text')
    blurb = '\n'.join(f'Line {i} of the copy.' for i in range(60))
    design, notes = convert(cover_blurb=blurb)
    el = next((e for e in texts(design) if 'Line 0 of' in e['text']), None)
    check('15.2 a blurb too long for the back keeps every line',
          el and 'Line 59 of the copy.' in el['text'], el and el['text'][-60:])
    check('     and the conversion says so', any('back cover' in n for n in notes), notes)

    tpl = copy.deepcopy(CLASSIC)
    tt = tpl.setdefault('title', {})
    tt['size'] = 30
    tpl['accent'] = dict(tpl.get('accent', {}), size=30,
                         color=tt.get('color', 'gold'), tracking=tt.get('tracking', 0.6))
    design, _ = convert(tpl, title='Salt', author='Ada')
    front = [e['text'] for e in texts(design) if e.get('anchor') == 'front']
    check('15.8 a title and byline set alike are two boxes',
          'SALT' in front and 'ADA' in front, front)

    design, _ = convert(cover_blurb='First paragraph.\n\nSecond paragraph.\n\nThird paragraph.')
    el = next(e for e in texts(design) if 'First paragraph' in e['text'])
    step = el['leading'] * el['size']
    check('15.9 one-line paragraphs keep their breaks',
          el['text'] == 'First paragraph.\n\nSecond paragraph.\n\nThird paragraph.', el['text'])
    check('     and the line leading, not the gap', abs(step - el['size'] * 16 / 11) < 0.01
          and abs(el.get('blank', 1) - 0.6) < 1e-6, (step, el.get('blank')))
    layout = WDm.text_layout(el)
    check('     laid out as the template drew it: the gap as before',
          abs((layout[2][2] - layout[0][2]) - step * 1.6) < 0.01, [r[2] for r in layout])

    design, notes = convert(title='W' * 250)
    el = max(texts(design), key=lambda e: len(e['text']))
    check('15.10 a title broken between letters stays one word', el['text'] == 'W' * 250,
          el['text'][:40])
    check('      and the conversion says so', any('too long for its frame' in n for n in notes), notes)

    design, _ = convert(cover_collection='North     Star')
    el = next((e for e in texts(design) if 'NORTH' in e['text']), None)
    check('15.11 a label keeps its spaces', el and el['text'] == 'NORTH     STAR'
          and el.get('keep_spaces'), el)
    check('      and prints with them', el and WDm.break_lines(el) == ['NORTH     STAR'],
          el and WDm.break_lines(el))
    plain = dict(el, text='NORTH     STAR', keep_spaces=False)
    check('      (a box without the mark breaks as before)',
          WDm.break_lines(plain) == ['NORTH STAR'], WDm.break_lines(plain))


def test_flap():
    print('\nthe front flap')
    small = A._wrap_dims({'wrap_retailer': 'ingramspark', 'wrap_binding': 'jacket',
                          'wrap_trim_w': 5, 'wrap_trim_h': 8}, 320)
    big = A._wrap_dims({'wrap_retailer': 'ingramspark', 'wrap_binding': 'jacket',
                        'wrap_trim_w': 6, 'wrap_trim_h': 9}, 320)
    design, _ = convert(dims=small, cover_jacket_blurb='Copy for the front flap of the jacket.')
    on = [e for e in design['elements'] if e.get('flap') == 'front']
    check('15.5 front-flap copy is kept to its fold', any(e['type'] == 'text' for e in on),
          [(e.get('label') or e.get('text', '')[:20], e.get('anchor')) for e in design['elements']])
    for which, dims in (('5 x 8', small), ('6 x 9', big)):
        g = engine.wrap_geometry(dims)
        fold = g['front_x'] + g['panel_w']
        off = [e.get('text', '')[:20] for e in on
               if not fold <= WDm.el_rect(g, e)[0] <= fold + g['flap']]
        check(f'     and stays on the flap at {which}', not off, off)


def test_files():
    print('\nfonts, art and the route')
    fonts = os.path.join(tmp, 'fonts')
    os.makedirs(fonts)
    real = WDm.FONT_DIR
    src = os.path.join(A.FONT_DIR, 'Book-Regular.ttf')
    shutil.copy(src, os.path.join(fonts, 'Face-Regular.otf'))
    with open(os.path.join(fonts, 'Cff-Regular.otf'), 'wb') as fh:
        fh.write(b'OTTO' + b'\0' * 64)
    try:
        WDm.FONT_DIR = fonts
        check('15.3 an .otf with TrueType outlines is a designer font',
              bool(WDm.font_file('Face-Regular.otf')))
        check('     one with PostScript outlines is not', WDm.font_file('Cff-Regular.otf') is None)
        os.remove(os.path.join(fonts, 'Face-Regular.otf'))
        try:
            WC._font_file('Helvetica', [])
            said = False
        except ValueError as exc:
            said = 'font library' in str(exc)
        check('     a library with no usable font is said, not an empty name', said)
    finally:
        WDm.FONT_DIR = real

    name = 'imported-0123456789ab.png'
    from PIL import Image
    Image.new('RGB', (4, 4), 'red').save(os.path.join(A.WRAP_DESIGN_DIR, name))
    Image.new('RGB', (4, 4), 'blue').save(os.path.join(A.COVER_ASSET_DIR, name))
    check('15.4 a converted picture is found in the designer\'s own folder first',
          os.path.dirname(WDm.art_file(name)) == A.WRAP_DESIGN_DIR, WDm.art_file(name))
    Image.new('RGB', (4, 4), 'blue').save(os.path.join(A.COVER_ASSET_DIR, 'plain.png'))
    check('     any other name as before', os.path.dirname(WDm.art_file('plain.png'))
          == A.COVER_ASSET_DIR)

    tpl = copy.deepcopy(CLASSIC)
    tpl['background'] = dict(tpl.get('background') or {}, image='gone-forever.png')
    _, notes = convert(tpl)
    check('15.7 art the library lacks is noted', any('gone-forever.png' in n for n in notes), notes)

    with open(os.path.join(A.COVER_DIR, 'broken.json'), 'w', encoding='utf-8') as fh:
        fh.write('{"name": "Broken", ')
    pid = 'damaged-cover'
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as fh:
        fh.write('# One\n\nText.\n')
    A.save_project_file(pid, {'name': 'Damaged', 'preset': 'classic-literary', 'title': 'Damaged',
                              'author': 'A. Writer', 'manuscript_file': pid + '.md',
                              'manuscript_type': 'file', 'cover_mode': 'designed',
                              'cover_template': 'broken'})
    client = A.app.test_client()
    res = client.post('/wrap-designer/customise', headers={'Origin': 'http://localhost'},
                      json={'template': 'ashforge-house', 'project': pid}).get_json()
    check('15.6 a damaged old template doesn\'t stop Customise from another',
          res and res.get('ok'), res and res.get('error'))

    js = open(os.path.join(HERE, 'static', 'wrap_designer.js'), encoding='utf-8').read()
    body = js[js.index('function customise('):js.index("$('wd-from-btn')")]
    check('15.1 a conversion that comes back after another book opened is dropped',
          "$('wd-project').value !== pid" in body
          and body.index('!== pid') < body.index('design = res.design'))


if __name__ == '__main__':
    try:
        for t in (test_text, test_flap, test_files):
            t()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{"all passed" if not fails else f"{len(fails)} FAILED"}')
    sys.exit(1 if fails else 0)
