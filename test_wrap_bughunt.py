"""Bug hunt section 4: the wrap designer and the cover families
(run: python test_wrap_bughunt.py).

Server-side regressions: a zero type size, a sideways phone photo, a cleared
line spacing, flap copy too long for its flap, jacket fills that ran over the
flaps, and a wrap left as the cover once unticked.
"""

import sys, os, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import engine
import wrap_design as WDm

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-wrapbug-')
A.OUT_DIR = os.path.join(tmp, 'out')
A.WRAP_DESIGN_DIR = os.path.join(A.OUT_DIR, '_wrap_designer')
A.COVER_ASSET_DIR = os.path.join(tmp, 'assets')
A.PROJECT_DIR = os.path.join(tmp, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
WDm.ART_DIRS = [A.COVER_ASSET_DIR, A.WRAP_DESIGN_DIR]
for d in (A.OUT_DIR, A.WRAP_DESIGN_DIR, A.COVER_ASSET_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR):
    os.makedirs(d, exist_ok=True)
client = A.app.test_client()
FORM = {'name': 'Test', 'prev_title': 'The Salt Road', 'prev_author': 'Ellinor Vale',
        'wrap_pages': '320', 'wrap_trim_w': '6', 'wrap_trim_h': '9'}

try:
    print('[4.4 a type size of 0]')
    tpl = A.parse_cover_form(dict(FORM, title_size='0', acc_size='-3'))
    check('a size of 0 or less falls back to the template\'s',
          tpl['title']['size'] > 0 and tpl['accent']['size'] > 0, (tpl['title'], tpl['accent']))
    r = client.post('/cover/wrap', data=dict(FORM, title_size='0'))
    check('the wrap still downloads', r.status_code == 200 and r.data[:4] == b'%PDF', r.status_code)
    fd, p = tempfile.mkstemp(suffix='.pdf', dir=tmp); os.close(fd)
    saved0 = A.load_cover_template('ashforge-house')
    saved0['title'] = dict(saved0.get('title', {}), size=0)
    cf = engine._register_cover_fonts(saved0, engine.register_fonts(A.DEFAULTS))
    try:
        engine.build_cover_wrap(saved0, cf, {'title': 'The Salt Road'},
                                {'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.5, 'bleed': 0.125}, p)
        ok = True
    except ZeroDivisionError as exc:
        ok = exc
    check('a template already saved with a size of 0 still builds', ok is True, ok)

    print('\n[4.7 one word too long for the classic frame]')
    import fitz
    tpl0 = A.load_cover_template('ashforge-house')
    engine.build_cover_wrap(tpl0, cf, {'title': 'W' * 80},
                            {'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.5, 'bleed': 0.125}, p)
    with fitz.open(p) as doc:
        # the front's title lines: horizontal (the spine's run up the page)
        ws = [w for w in doc[0].get_text('words')
              if w[4].startswith('WW') and w[2] - w[0] > w[3] - w[1]]
    front0 = (0.125 + 6.0 + 0.5) * 72
    check('it shrinks, and breaks, to stay inside the front panel',
          ws and all(front0 < w[0] and w[2] < front0 + 6.0 * 72 for w in ws),
          [(round(w[0]), round(w[2])) for w in ws])

    print('\n[4.5 a phone photo stored sideways]')
    from PIL import Image
    im = Image.new('RGB', (200, 100), (180, 40, 40))       # stored landscape...
    ex = im.getexif(); ex[0x0112] = 6                       # ...shown turned: portrait
    photo = os.path.join(A.WRAP_DESIGN_DIR, 'phone.jpg')
    im.save(photo, exif=ex)
    design = {'elements': [{'id': 'p', 'type': 'image', 'anchor': 'front', 'x': 1, 'y': 1,
                            'w': 2, 'h': 2, 'src': 'phone.jpg', 'fit': 'contain'}]}
    pdf = os.path.join(tmp, 'phone.pdf')
    WDm.build_pdf(design, A._wrap_dims({}, 320), pdf)
    with fitz.open(pdf) as doc:
        info = [i for i in doc[0].get_image_info() if i['width'] and i['height']]
    check('it prints upright, as the browser shows it',
          info and info[0]['width'] == 100 and info[0]['height'] == 200,
          [(i['width'], i['height']) for i in info])

    print('\n[4.6 a cleared line spacing]')
    el = {'type': 'text', 'text': 'One\nTwo\nThree', 'font': 'EBGaramond-Regular.ttf',
          'size': 20, 'w': 3, 'leading': 0}
    base = [l[2] for l in WDm.text_layout(el)]
    check('the lines still step down the page, as on the canvas',
          base == [l[2] for l in WDm.text_layout(dict(el, leading=1.2))], base)

    print('\n[4.8 flap copy too long for its flap]')
    jacket = dict(FORM, wrap_binding='jacket', wrap_retailer='ingramspark')
    short = client.post('/cover/wrap/preview', data=jacket).get_json()
    check('short flap copy gives no warning',
          short['ok'] and not any('flap copy' in w for w in short['warnings']), short.get('warnings'))
    long_ = client.post('/cover/wrap/preview', data=dict(
        jacket, wrap_flap_bio='\n'.join(f'Line {i}' for i in range(60)))).get_json()
    check('sixty lines on the back flap are flagged',
          long_['ok'] and any('back flap copy' in w for w in long_['warnings']), long_.get('warnings'))

    print('\n[4.9 a jacket\'s fills stop at the flaps]')
    g = engine.wrap_geometry(A._wrap_dims({'wrap_binding': 'jacket', 'wrap_retailer': 'ingramspark'}, 320))
    fx, _, fw, _ = WDm.fill_rect(g, 'front')
    bx, _, bw, _ = WDm.fill_rect(g, 'back')
    check('the front fill ends at the front flap\'s fold',
          g['flap'] > 0 and abs(fx + fw - (g['front_x'] + g['panel_w'])) < 1e-9, (fx, fw, g))
    check('the back fill starts at the back flap\'s fold', abs(bx - g['back_x']) < 1e-9 and bw == g['panel_w'])
    gp = engine.wrap_geometry(A._wrap_dims({}, 320))
    check('a paperback\'s front still runs to the sheet\'s edge',
          abs(sum(WDm.fill_rect(gp, 'front')[::2]) - gp['wrap_w']) < 1e-9)

    print('\n[4.11 the Title fields on a family that sets its own title]')
    import json
    typo = A.load_cover_template('typographic-bold')
    f11 = dict(FORM, base_json=json.dumps(typo), title_size='20',
               title_leading=str(typo['title']['leading']), title_y=str(typo['title']['y'] + 0.1))
    t11 = A.parse_cover_form(f11)
    check('Size and position reach the family\'s own title settings',
          abs(t11['typo']['title_size'] - 20) < 0.01
          and abs(t11['typo']['title_top'] - (typo['typo']['title_top'] + 0.1)) < 1e-6, t11['typo'])
    t11b = A.parse_cover_form(dict(FORM, base_json=json.dumps(typo),
                                   title_size=str(typo['title']['size']),
                                   title_leading=str(typo['title']['leading']),
                                   title_y=str(typo['title']['y'])))
    check('untouched, they leave it as it was', t11b['typo'] == typo['typo'])

    print('\n[4.12 Customise keeps a one-line title\'s side]')
    import wrap_convert as WC
    cf12 = engine._register_cover_fonts(typo, engine.register_fonts(A.DEFAULTS))
    d12 = A._wrap_dims({}, 320)
    design, _ = WC.from_template(typo, cf12, {'title': 'Map', 'author': 'Ada Merrow'}, d12)
    title = [e for e in design['elements'] if e.get('type') == 'text' and e.get('text') == 'MAP' and e.get('anchor') == 'front']
    check('a left-set title stays left-set', title and title[0]['align'] == 'left',
          [(e.get('text'), e.get('align')) for e in design['elements'] if e.get('type') == 'text'])

    print('\n[4.13 unticking "Use as this book\'s cover"]')
    PID = 'salt-road'
    with open(os.path.join(A.PROJECT_MS_DIR, PID + '.md'), 'w', encoding='utf-8') as f:
        f.write('# The Salt Road\n\nA paragraph.\n')
    A.save_project_file(PID, {'name': 'The Salt Road', 'preset': 'classic-literary',
                              'title': 'The Salt Road', 'manuscript_file': PID + '.md',
                              'manuscript_type': 'file', 'front_matter': 'none',
                              'cover_mode': 'none', 'format': 'pdf'})
    DES = {'elements': [{'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': '#20283b'}]}
    on = client.post(f'/wrap-designer/project/{PID}/save',
                     json={'design': DES, 'use_as_cover': True, 'settings': {}}).get_json()
    off = client.post(f'/wrap-designer/project/{PID}/save',
                      json={'design': DES, 'use_as_cover': False, 'settings': {}}).get_json()
    check('the wrap stops being the cover', on['is_cover'] and not off['is_cover']
          and A.load_project(PID)['cover_mode'] == 'none', (on, off))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
