"""Wrap designer tests  (run: python test_wrap_designer.py).

The designer's promise is that what the editor shows is what prints, so the
checks are about agreement: the server builds the PDF the design describes, its
line breaks are the engine's, the geometry is the one the cover editor and the
print package use, and - in a real browser - the editor breaks every text box
exactly where the PDF does and moves things where you drag them.

The browser half needs Chrome or Edge (TS_BROWSER to point at one); without one
it is skipped and says so.
"""

import sys, os, json, shutil, tempfile, threading, subprocess

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
from test_rich_editor import find_browser

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-wrapdesign-')
A.OUT_DIR = os.path.join(tmp, 'out')
A.WRAP_DESIGN_DIR = os.path.join(A.OUT_DIR, '_wrap_designer')
A.COVER_ASSET_DIR = os.path.join(tmp, 'assets')
A.PROJECT_DIR = os.path.join(tmp, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
WDm.ART_DIRS = [A.COVER_ASSET_DIR, A.WRAP_DESIGN_DIR]
for d in (A.OUT_DIR, A.COVER_ASSET_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR):
    os.makedirs(d)

# A book to design a cover for (phase B): short, so its spine is too thin for text.
PID = 'salt-road'
with open(os.path.join(A.PROJECT_MS_DIR, PID + '.md'), 'w', encoding='utf-8') as f:
    f.write('# The Salt Road\n\nThe opening paragraph, long enough to set a line.\n\n'
            '# The Second Mile\n\nAnother chapter.\n')
A.save_project_file(PID, {'name': 'The Salt Road', 'preset': 'classic-literary',
                          'title': 'The Salt Road', 'author': 'Ellinor Vale',
                          'manuscript_file': PID + '.md', 'manuscript_type': 'file',
                          'front_matter': 'none', 'cover_mode': 'none', 'format': 'pdf',
                          'print_retailer': 'kdp', 'print_binding': 'paperback',
                          'print_paper': 'cream', 'print_blurb': 'A road of salt.'})
# The browser half's harness. Flask takes no new routes after its first request,
# so they are added here, ahead of the server-side checks.
from werkzeug.serving import make_server
from flask import request
result = {}
SCRIPT = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var E = w.WD_EDITOR, design = E.design();
    out.elements = design.elements.length;
    d.getElementById('wd-proof-btn').click();
    var w2 = setInterval(function () {
      var msg = d.getElementById('wd-proof-msg').textContent;
      if (msg.indexOf('Built') !== 0 && msg.indexOf('These') !== 0 && msg.indexOf('The PDF') !== 0) return;
      clearInterval(w2);
      out.proof = msg;
      out.download = !!d.querySelector('#wd-proof a[href*="/download/"]');
      var title = design.elements.find(function (e) { return e.id === 'title'; });
      var g0 = E.geometry(), x0 = g0.front_x;
      d.getElementById('wd-pages').value = 640;
      d.getElementById('wd-pages').dispatchEvent(new w.Event('input'));
      E.regeometry().then(function () {
        var g1 = E.geometry();
        out.front_moved_with_spine = Math.abs((g1.front_x - x0) - (g1.spine_w - g0.spine_w)) < 1e-9
                                      && g1.spine_w > g0.spine_w;
        var svg = d.getElementById('wd-svg');
        var t = svg.querySelector('[data-id="title"] rect');
        var b = t.getBoundingClientRect(), cx = b.left + b.width / 2, cy = b.top + b.height / 2;
        var tx = title.x;
        var fire = function (type, x, y, target) {
          target.dispatchEvent(new w.PointerEvent(type, {clientX:x, clientY:y, bubbles:true, pointerId:1, isPrimary:true}));
        };
        fire('pointerdown', cx, cy, t); fire('pointermove', cx + 100, cy, svg); fire('pointerup', cx + 100, cy, svg);
        var perPx = g1.wrap_w / svg.getBoundingClientRect().width;
        out.drag_ok = Math.abs((title.x - tx) - 100 * perPx) < 0.01;
        var moved = title.x;
        var key = function (k, shift) {
          d.dispatchEvent(new w.KeyboardEvent('keydown', {key:k, ctrlKey:true, shiftKey:!!shift, bubbles:true}));
        };
        var T = function () { return E.design().elements.find(function (e) { return e.id === 'title'; }); };
        key('z');
        out.undo_ok = Math.abs(T().x - tx) < 1e-9;
        key('y');
        out.redo_ok = Math.abs(T().x - moved) < 1e-9;
        var n0 = E.design().elements.length;
        d.querySelector('#wd-layers li button[title="Delete"]').click();      // the top layer
        var n1 = E.design().elements.length;
        key('z');
        out.delete_undo_ok = n1 === n0 - 1 && E.design().elements.length === n0;
        // zoom the front picture: its drawn width doubles
        var art = E.design().elements.find(function (e) { return e.type === 'image' && e.fill === 'front'; });
        var pic = function () { return svg.querySelector('[data-id="' + art.id + '"] svg image'); };
        var w0 = pic() ? +pic().getAttribute('width') : 0;
        art.zoom = 2; art.fx = 0;
        d.getElementById('wd-guides').dispatchEvent(new w.Event('change'));
        var w1 = pic() ? +pic().getAttribute('width') : 0;
        out.zoom_ok = w0 > 0 && Math.abs(w1 - 2 * w0) < 1e-6 && Math.abs(+pic().getAttribute('x')) < 1e-9;
        title = T();
        title.text = 'Title with a stray क glyph';
        title.x = -0.4;
        d.getElementById('wd-guides').dispatchEvent(new w.Event('change'));
        out.checks = d.getElementById('wd-checks').textContent;
        var x = new XMLHttpRequest(); x.open('POST', '/_wd_result', false); x.send(JSON.stringify(out));
      });
    }, 100);
  }, 100);
};'''
harness = ('<!doctype html><meta charset="utf-8"><iframe id="f" src="/wrap-designer" '
           'style="width:1300px;height:900px"></iframe><script>' + SCRIPT + '</script>')

@A.app.route('/_wd_harness')
def _wd_harness():
    return harness

@A.app.route('/_wd_result', methods=['POST'])
def _wd_result():
    result.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


SCRIPT2 = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var design = w.WD_EDITOR.design();
    out.title = (design.elements.find(function (e) { return e.id === 'title'; }) || {}).text;
    out.trim_locked = d.getElementById('wd-trim').disabled;
    out.paper = d.getElementById('wd-paper').value;
    out.save_shown = d.getElementById('wd-save-group').style.display !== 'none';
    d.getElementById('wd-save').click();
    var w2 = setInterval(function () {
      var st = d.getElementById('wd-save-status').textContent;
      if (st.indexOf('Saved') !== 0) return;
      clearInterval(w2);
      out.status = st;
      var x = new XMLHttpRequest(); x.open('POST', '/_wd_result2', false); x.send(JSON.stringify(out));
    }, 100);
  }, 100);
};'''
result2 = {}

@A.app.route('/_wd_harness2')
def _wd_harness2():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" src="/wrap-designer?project='
            + PID + '" style="width:1300px;height:900px"></iframe><script>' + SCRIPT2 + '</script>')

@A.app.route('/_wd_result2', methods=['POST'])
def _wd_result2():
    result2.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


SCRIPT3 = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var E = w.WD_EDITOR, svg = d.getElementById('wd-svg');
    var els = E.design().elements;
    out.vectors = els.filter(function (e) { return e.type === 'vector'; }).length;
    out.title = (els.find(function (e) { return e.type === 'text' && e.text.indexOf('SALT') !== -1; }) || {}).text;
    out.paths = svg.querySelectorAll('.el path').length;
    out.msg = d.getElementById('wd-from-msg').textContent;
    // the front and back panels' text against their safe zones, as the checks
    // measure it (the template's own spine title sits close to the folds)
    var g = E.geometry(), s = 0.25, e5 = 0.005;
    out.outside = els.filter(function (e) {
      if (e.type !== 'text' || (e.anchor !== 'front' && e.anchor !== 'back')) return false;
      var b = E.bbox(e), o = e.anchor === 'front' ? g.front_x : g.back_x;
      return b[0] < o + s - e5 || b[0] + b[2] > o + g.panel_w - s + e5 ||
             b[1] < g.edge + s - e5 || b[1] + b[3] > g.edge + g.panel_h - s + e5;
    }).map(function (e) { return e.text; });
    // recolour the front frame through its swatch
    var frame = els.find(function (e) { return e.label === 'Frame (front)'; });
    Array.prototype.find.call(d.querySelectorAll('#wd-layers li'), function (li) {
      return li.textContent.indexOf('Frame (front)') === 0;
    }).click();
    var sw = d.querySelector('#wd-props .swatches input');
    out.swatch = !!sw;
    if (sw) { sw.value = '#00ff00'; sw.dispatchEvent(new w.Event('input')); }
    out.recoloured = frame.ops.every(function (op) { return op[op.length - 1].stroke === '#00ff00'; })
      && !!svg.querySelector('[data-id="' + frame.id + '"] path[stroke="#00ff00"]');
    E.commit();
    d.getElementById('wd-proof-btn').click();
    var w2 = setInterval(function () {
      var msg = d.getElementById('wd-proof-msg').textContent;
      if (msg.indexOf('Built') !== 0 && msg.indexOf('These') !== 0 && msg.indexOf('The PDF') !== 0) return;
      clearInterval(w2);
      out.proof = msg;
      E.undo(); E.undo();                       // the recolour, then the conversion itself
      out.undone = E.design().elements.some(function (e) { return e.id === 'title'; })
        && !E.design().elements.some(function (e) { return e.type === 'vector'; });
      var x = new XMLHttpRequest(); x.open('POST', '/_wd_result3', false); x.send(JSON.stringify(out));
    }, 100);
  }, 100);
};'''
result3 = {}

@A.app.route('/_wd_harness3')
def _wd_harness3():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" src="/wrap-designer?project='
            + PID + '&from=ashforge-house" style="width:1300px;height:900px"></iframe><script>'
            + SCRIPT3 + '</script>')

@A.app.route('/_wd_result3', methods=['POST'])
def _wd_result3():
    result3.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


SCRIPT4 = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var E = w.WD_EDITOR, svg = d.getElementById('wd-svg');
    var byId = function (id) { return E.design().elements.find(function (e) { return e.id === id; }); };
    var box = function (id) { return E.bbox(byId(id)); };
    // justify the blurb: the editor's word positions, for the server to compare
    byId('blurb').align = 'justify';
    E.commit();
    d.getElementById('wd-guides').dispatchEvent(new w.Event('change'));
    out.justified = byId('blurb');
    out.justified_layout = E.layout(byId('blurb'));
    // Shift+click adds to the selection; a drag then moves both
    var fire = function (type, el, shift, dx) {
      var b = el.getBoundingClientRect(), x = b.left + b.width / 2 + (dx || 0), y = b.top + b.height / 2;
      (type === 'pointerdown' ? el : svg).dispatchEvent(new w.PointerEvent(type, {clientX:x, clientY:y,
        bubbles:true, pointerId:1, isPrimary:true, shiftKey:!!shift}));
    };
    var hitOf = function (id) { return svg.querySelector('[data-id="' + id + '"] rect'); };
    var t0 = box('title'), b0 = box('blurb');
    fire('pointerdown', hitOf('title')); fire('pointerup', hitOf('title'));
    fire('pointerdown', hitOf('blurb'), true); fire('pointerup', hitOf('blurb'));
    out.two_selected = d.getElementById('wd-props').textContent.indexOf('2 selected') !== -1;
    // measured once: the editor redraws on pointerdown, so the node goes stale
    var hb = hitOf('title').getBoundingClientRect(), cx = hb.left + hb.width / 2, cy = hb.top + hb.height / 2;
    var ev = function (type, x, target) {
      target.dispatchEvent(new w.PointerEvent(type, {clientX:x, clientY:cy, bubbles:true, pointerId:1, isPrimary:true}));
    };
    ev('pointerdown', cx, hitOf('title')); ev('pointermove', cx + 60, svg); ev('pointerup', cx + 60, svg);
    var t1 = box('title'), b1 = box('blurb');
    out.moved_together = Math.abs((t1[0] - t0[0]) - (b1[0] - b0[0])) < 1e-9 && t1[0] - t0[0] > 0.05;
    // three lined up by their left edges, then spaced evenly down
    byId('gone').y = 6.5;                       // room between them to share out
    E.select(['title', 'blurb', 'gone']);
    E.align('left');
    var L = ['title', 'blurb', 'gone'].map(function (id) { return box(id)[0]; });
    out.aligned_left = Math.max.apply(null, L) - Math.min.apply(null, L) < 1e-6;
    E.distribute('y');
    var bs = ['title', 'blurb', 'gone'].map(box).sort(function (p, q) { return p[1] - q[1]; });
    out.gaps = [bs[1][1] - (bs[0][1] + bs[0][3]), bs[2][1] - (bs[1][1] + bs[1][3])];
    out.tool_count = d.querySelectorAll('#wd-props [data-align]').length;
    // one alone: centred on its panel's safe area
    E.select(['title']);
    E.align('center');
    var tb = box('title'), z = E.safeBox(byId('title'));
    out.centred_on_panel = Math.abs((tb[0] + tb[2] / 2) - (z[0] + z[2]) / 2) < 1e-6;
    // a jacket: the flap presets
    d.getElementById('wd-binding').value = 'jacket';
    d.getElementById('wd-binding').dispatchEvent(new w.Event('change'));
    E.regeometry().then(function () {
      out.flaps_card = !d.getElementById('wd-flaps').hidden;
      var n0 = E.design().elements.length;
      return E.flapPreset('front').then(function () { return E.flapPreset('back'); }).then(function () {
        var added = E.design().elements.slice(n0), g = E.geometry();
        out.flap_added = added.map(function (e) { return e.type + ':' + (e.text || e.src).slice(0, 40); });
        out.flap_inside = added.every(function (e) {
          var b = E.bbox(e), s = E.safeBox(e);
          return b[0] >= s[0] - 0.005 && b[0] + b[2] <= s[2] + 0.005 && b[1] >= s[1] - 0.005 && b[1] + b[3] <= s[3] + 0.005;
        });
        out.on_flaps = added.every(function (e) {
          var b = E.bbox(e), mid = b[0] + b[2] / 2;
          return mid < g.back_x || mid > g.front_x + g.panel_w;
        });
        d.getElementById('wd-proof-btn').click();
        var w2 = setInterval(function () {
          var msg = d.getElementById('wd-proof-msg').textContent;
          if (msg.indexOf('Built') !== 0 && msg.indexOf('These') !== 0 && msg.indexOf('The PDF') !== 0) return;
          clearInterval(w2);
          out.proof = msg;
          var x = new XMLHttpRequest(); x.open('POST', '/_wd_result4', false); x.send(JSON.stringify(out));
        }, 100);
      });
    });
  }, 100);
};'''
result4 = {}

@A.app.route('/_wd_harness4')
def _wd_harness4():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" src="/wrap-designer?project='
            + PID + '" style="width:1300px;height:900px"></iframe><script>' + SCRIPT4 + '</script>')

@A.app.route('/_wd_result4', methods=['POST'])
def _wd_result4():
    result4.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


SCRIPT5 = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var E = w.WD_EDITOR, svg = d.getElementById('wd-svg'), g = E.geometry();
    var els = function () { return E.design().elements; };
    var byId = function (id) { return els().find(function (e) { return e.id === id; }); };
    var redraw = function () { d.getElementById('wd-guides').dispatchEvent(new w.Event('change')); };
    var checks = function () { return d.getElementById('wd-checks').textContent; };
    var bc = els().find(function (e) { return e.type === 'barcode'; });
    out.barcode_locked = !!(bc && bc.locked);
    out.checks_clear = checks();
    // an ISBN typed into the box: real bars, drawn from the server's layout
    Array.prototype.find.call(d.querySelectorAll('#wd-layers li'), function (li) {
      return li.textContent.indexOf('Barcode area') !== -1;
    }).click();
    var isbn = d.querySelector('#wd-props input[type=text]');
    isbn.value = '978-0-306-40615-7'; isbn.dispatchEvent(new w.Event('input'));
    setTimeout(function () {
      out.bars = svg.querySelectorAll('[data-id="' + bc.id + '"] rect').length - 1;
      out.checks_isbn = checks();
      bc.isbn = '9780306406158'; redraw();
      setTimeout(function () {
        out.checks_bad_isbn = checks();
        bc.isbn = '9780306406157';
        // something laid over the barcode is flagged
        var t = byId('blurb'); t.y = bc.y; t.x = bc.x; redraw();
        out.checks_over = checks();
        t.x = 0.6; t.y = 1.0;
        // hide: off the screen; the proof leaves it out and still agrees
        d.querySelector('#wd-layers li button[data-act="hide"]').click();
        var top = els()[els().length - 1];
        out.hidden_gone = top.hidden === true && !svg.querySelector('[data-id="' + top.id + '"]');
        top.hidden = false; delete top.hidden; redraw();
        // a picture ending at the trim, placed big enough to print soft
        els().push({id:'pic-x', type:'image', anchor:'front', x:0, y:0, w:g.panel_w, h:g.panel_h,
                    src:'halves.png', zoom:1});
        redraw();
        setTimeout(function () {
          out.checks_pic = checks();
          els().pop();
          // shapes
          d.getElementById('wd-add-ellipse').click(); d.getElementById('wd-add-rule').click();
          out.shapes = !!svg.querySelector('ellipse') && !!svg.querySelector('[data-id] line');
          // group two, then a click on one takes both
          var ids = ['title', 'author'];
          E.select(ids);
          var gb = d.querySelector('#wd-props [data-group="group"]');
          out.group_offered = !!gb; if (gb) gb.click();
          E.select([]);
          var hb = svg.querySelector('[data-id="title"] rect').getBoundingClientRect();
          svg.querySelector('[data-id="title"] rect').dispatchEvent(new w.PointerEvent('pointerdown',
            {clientX:hb.left + 5, clientY:hb.top + 5, bubbles:true, pointerId:1, isPrimary:true}));
          svg.dispatchEvent(new w.PointerEvent('pointerup', {clientX:hb.left + 5, clientY:hb.top + 5, bubbles:true, pointerId:1}));
          out.group_click = d.getElementById('wd-props').textContent.indexOf('2 selected') !== -1;
          // snapping: a box dropped a hair off the front's middle lands on it, unless Alt is held
          E.select([]);
          var box = {id:'snapme', type:'rect', anchor:'front', x:g.panel_w / 2 - 1 + 0.02, y:3, w:2, h:0.5, color:'#00ff00'};
          els().push(box);
          E.snapMove([box]);
          out.snapped = Math.abs(box.x - (g.panel_w / 2 - 1)) < 1e-9;
          // quotes: a praise block, grouped, inside the back's safe zone
          var n0 = els().length;
          E.quotePreset('praise').then(function () {
            var added = els().slice(n0);
            out.quotes = added.length;
            out.quotes_grouped = added.every(function (e) { return e.group && e.group === added[0].group; });
            out.quotes_inside = added.every(function (e) {
              var b = E.bbox(e), z = E.safeBox(e);
              return b[0] >= z[0] - 0.005 && b[0] + b[2] <= z[2] + 0.005 && b[1] >= z[1] - 0.005 && b[1] + b[3] <= z[3] + 0.005;
            });
            E.setZoom(2);
            out.zoomed = svg.style.width === '200%';
            E.setZoom(1);
            redraw();
            d.getElementById('wd-proof-btn').click();
            var w2 = setInterval(function () {
              var msg = d.getElementById('wd-proof-msg').textContent;
              if (msg.indexOf('Built') !== 0 && msg.indexOf('These') !== 0 && msg.indexOf('The PDF') !== 0) return;
              clearInterval(w2);
              out.proof = msg;
              var x = new XMLHttpRequest(); x.open('POST', '/_wd_result5', false); x.send(JSON.stringify(out));
            }, 100);
          });
        }, 600);
      }, 600);
    }, 600);
  }, 100);
};'''
result5 = {}

@A.app.route('/_wd_harness5')
def _wd_harness5():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" src="/wrap-designer" '
            'style="width:1300px;height:900px"></iframe><script>' + SCRIPT5 + '</script>')

@A.app.route('/_wd_result5', methods=['POST'])
def _wd_result5():
    result5.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


client = A.app.test_client()

SETTINGS = {'pages': 320, 'wrap_retailer': 'kdp', 'wrap_paper': 'white',
            'wrap_binding': 'paperback', 'wrap_trim_w': 6, 'wrap_trim_h': 9}
BLURB = ('The rain had not stopped for three days, and Aldren had begun to suspect it '
         'never would. He stood beneath the eaves of the Split Lantern Inn, watching the '
         'water carve small rivers through the mud of Briars Hollow.')
DESIGN = {'elements': [
    {'id': 'bg', 'type': 'rect', 'fill': 'back', 'color': '#20283b'},
    {'id': 'art', 'type': 'image', 'fill': 'front', 'src': 'stand-in-dusk.png'},
    {'id': 'title', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 0.9, 'w': 5,
     'text': 'The Salt Road', 'font': 'EBGaramond-Bold.ttf', 'size': 46, 'leading': 1.05,
     'color': '#fbf3e2', 'align': 'center', 'tracking': 0.5},
    {'id': 'blurb', 'type': 'text', 'anchor': 'back', 'x': 0.6, 'y': 1, 'w': 4.8,
     'text': BLURB, 'font': 'CrimsonPro-Regular.ttf', 'size': 12.5, 'leading': 1.4,
     'color': '#efe7d6', 'align': 'left', 'tracking': 0},
    {'id': 'spine', 'type': 'text', 'anchor': 'spine', 'cx': 0.11, 'y': 0.6, 'w': 7.8,
     'rotate': 90, 'text': 'THE SALT ROAD', 'font': 'Spectral-Regular.ttf', 'size': 12,
     'color': '#fbf3e2', 'align': 'center', 'tracking': 1.5},
    {'id': 'gone', 'type': 'image', 'anchor': 'front', 'x': 1, 'y': 1, 'w': 1, 'h': 1,
     'src': 'no-such-picture.png'},
]}

try:
    print('[the page and its routes]')
    page = client.get('/wrap-designer').get_data(as_text=True)
    check('the tab is in the navigation', 'href="/wrap-designer"' in page)
    check('the page lists the font library', 'EBGaramond-Bold.ttf' in page)
    check('the stand-in art is made for it',
          os.path.isfile(os.path.join(A.WRAP_DESIGN_DIR, A.WRAP_STAND_IN)))
    m = client.get('/wrap-designer/metrics/EBGaramond-Regular.ttf').get_json()
    check('width tables are served', m and m['widths'] and 'ascent' in m)
    check('a font outside the library is refused',
          client.get('/wrap-designer/font/..%2Fapp.py').status_code == 404
          and client.get('/wrap-designer/metrics/notafont.txt').status_code == 404)
    check('art outside the art folders is refused',
          client.get('/wrap-designer/art/..%2F..%2Fapp.py').status_code == 404)

    print('\n[geometry is the cover editor\'s]')
    geo = client.post('/wrap-designer/geometry', json=SETTINGS).get_json()
    want = A._wrap_dims({k: v for k, v in SETTINGS.items() if k != 'pages'}, 320)
    check('the spine is _wrap_dims\' spine', abs(geo['dims']['spine_w'] - want['spine_w']) < 1e-9,
          (geo['dims']['spine_w'], want['spine_w']))
    cream = client.post('/wrap-designer/geometry', json=dict(SETTINGS, wrap_paper='cream')).get_json()
    check('thicker paper, wider spine', cream['geometry']['spine_w'] > geo['geometry']['spine_w'])
    jk = client.post('/wrap-designer/geometry',
                     json=dict(SETTINGS, wrap_binding='jacket')).get_json()
    check('a jacket has flaps, and KDP is warned off it',
          jk['geometry']['flap'] > 0 and any('jacket' in w for w in jk['warnings']), jk['warnings'])

    print('\n[the PDF]')
    res = client.post('/wrap-designer/build', json={'design': DESIGN, 'settings': SETTINGS,
                                                    'name': 'The Salt Road'}).get_json()
    check('it builds', res and res['ok'], res)
    pdf = os.path.join(A.OUT_DIR, os.path.basename(res['pdf']))
    import fitz
    with fitz.open(pdf) as doc:
        g = engine.wrap_geometry(A._wrap_dims({'wrap_paper': 'white'}, 320))
        check('the page is the wrap, to the point',
              abs(doc[0].rect.width - g['wrap_w'] * 72) < 0.01
              and abs(doc[0].rect.height - g['wrap_h'] * 72) < 0.01,
              (doc[0].rect, g['wrap_w'], g['wrap_h']))
        text = ' '.join(doc[0].get_text().split())
    check('the text is in it', 'The Salt Road' in text and 'Split Lantern' in text, text[:120])
    check('a picture that isn\'t there is skipped, not fatal', res['ok'])
    eng = engine._wrap_tracked(BLURB, WDm.font_name('CrimsonPro-Regular.ttf'), 12.5, 4.8 * 72, 0)
    check('the blurb is broken by the engine\'s own breaker', res['lines']['blurb'] == eng)
    check('the download link works', client.get(res['pdf']).status_code == 200)
    check('the preview picture is there', res['png'].startswith('data:image/png;base64,'))
    gg = engine.wrap_geometry(A._wrap_dims({}, 320))
    x = WDm.el_rect(gg, DESIGN['elements'][4])[0]
    zdesign = {'elements': [{'id': 'pic', 'type': 'image', 'anchor': 'front', 'x': 1, 'y': 1,
                             'w': 2, 'h': 2, 'src': 'stand-in-dusk.png', 'zoom': 2, 'fx': 0, 'fy': 1}]}
    zp = os.path.join(tmp, 'zoom.pdf')
    WDm.build_pdf(zdesign, A._wrap_dims({}, 320), zp)
    zg = engine.wrap_geometry(A._wrap_dims({}, 320))
    with fitz.open(zp) as zd:
        info = zd[0].get_image_info()
    r_ = info[0]['bbox'] if info else (0, 0, 0, 0)
    bx, by = (zg['front_x'] + 1) * 72, (zg['edge'] + 1) * 72
    # the stand-in is 1200x1800: cover-fit to 2" wide is 3" tall, then zoomed 2x
    check('zoom and focus reach the PDF: 4x6" picture, left edge and bottom pinned',
          abs((r_[2] - r_[0]) - 4 * 72) < 0.5 and abs((r_[3] - r_[1]) - 6 * 72) < 0.5
          and abs(r_[0] - bx) < 0.5 and abs(r_[3] - (by + 2 * 72)) < 0.5, (r_, bx, by))
    pl = WDm.placed_images(zdesign, zg)
    check('a zoomed picture is measured at its zoomed size', pl and pl[0][1:] == (4, 4), pl)
    check('spine text placed from the spine\'s centre',
          abs(x - (gg['spine_x'] + gg['spine_w'] / 2 + 0.11)) < 1e-9)

    print('\n[a design saved with a book (phase B)]')
    info = client.get(f'/wrap-designer/project/{PID}').get_json()
    check('a book opens with its own settings',
          info['settings']['wrap_paper'] == 'cream' and info['settings']['wrap_trim_w'] == 6.0
          and info['design'] is None and info['title'] == 'The Salt Road', info)
    bad = client.post(f'/wrap-designer/project/{PID}/save', json={'design': {'oops': 1}}).get_json()
    check("a design that isn't one is refused", not bad['ok'], bad)
    saved = client.post(f'/wrap-designer/project/{PID}/save', json={
        'design': DESIGN, 'use_as_cover': True,
        'settings': {'wrap_retailer': 'ingramspark', 'wrap_paper': 'white',
                     'wrap_binding': 'paperback'}}).get_json()
    check('it saves', saved['ok'] and saved['is_cover'], saved)
    proj = A.load_project(PID)
    check('the design and the print settings are on the book',
          proj['wrap_design']['elements'][2]['text'] == 'The Salt Road'
          and proj['print_retailer'] == 'ingramspark' and proj['print_paper'] == 'white'
          and proj['cover_mode'] == 'wrap',
          {k: proj.get(k) for k in ('print_retailer', 'print_paper', 'cover_mode')})
    from PIL import Image
    front = os.path.join(A.PROJECT_MS_DIR, proj['wrap_front_file'])
    with Image.open(front) as im:
        check('its front is rendered at the trim, 300 dpi', im.size == (1800, 2700), im.size)
    meta, cover = A._project_meta(proj)
    check("the book's cover is now that front, with no title laid over it",
          meta['cover_mode'] == 'image' and cover == front and not meta['cover_overlay'])
    page = client.get(f'/project/{PID}/edit').get_data(as_text=True)
    check('the edit page offers it as the cover', 'value="wrap"' in page and 'My wrap design' in page)

    import zipfile
    pkg = A.build_print_package(proj, 'publish')
    with zipfile.ZipFile(os.path.join(A.OUT_DIR, pkg['zip_name'])) as z:
        names = z.namelist()
        wrapname = next(n for n in names if n.endswith('-cover-wrap.pdf'))
        wrapdoc = fitz.open(stream=z.read(wrapname), filetype='pdf')
        gp = engine.wrap_geometry(A._wrap_dims(
            {'wrap_retailer': 'ingramspark', 'wrap_paper': 'white'}, pkg['pages']))
        check('Send to print builds the design as the wrap, sized to the real page count',
              abs(wrapdoc[0].rect.width - gp['wrap_w'] * 72) < 0.01
              and 'Split Lantern' in ' '.join(wrapdoc[0].get_text().split()),
              (wrapdoc[0].rect.width / 72, gp['wrap_w']))
        wrapdoc.close()
        check('the ebook and the listing JPG come with it',
              any(n.endswith('.epub') for n in names) and any(n.endswith('.jpg') for n in names),
              names)
    rows = {c['label']: c for c in pkg['checks']}
    check('the package says the cover is the wrap design',
          pkg['cover_label'] == 'Wrap design')
    check('a thin book with spine text in its design is flagged',
          'Spine text' in rows and not rows['Spine text']['ok'], rows.get('Spine text'))
    check('every picture is measured at its placed size',
          any(l.startswith('Picture: stand-in-dusk.png') for l in rows), sorted(rows))

    print('\n[customise this design (phase C)]')
    import wrap_convert as WC
    from PIL import Image, ImageChops, ImageOps
    WC.IMPORT_DIR = A.WRAP_DESIGN_DIR
    META = {'title': 'The Salt Road Between Winters', 'author': 'Ada Merrow',
            'cover_collection': 'The Tidewater Cycle', 'cover_kicker': 'A novel',
            'cover_epigraph': 'What the sea keeps, it keeps for a reason.',
            'cover_studio': 'Ashforge Studio',
            'cover_blurb': ('On the night the lighthouse goes dark, Mara Venn finds a letter in '
                            'her dead father\'s coat. It names a road no map shows.\n\n'
                            'She has one winter to walk it.'),
            'cover_author_bio': 'Ada Merrow lives on the coast.'}

    def glyphs(path):
        out = {}
        with fitz.open(path) as doc:
            for b in doc[0].get_text('rawdict')['blocks']:
                for s in (s for l in b.get('lines', []) for s in l['spans']):
                    for c in s['chars']:
                        if c['c'].strip():
                            out.setdefault((c['c'], round(s['size'], 2)), []).append(c['origin'])
        return out

    def same_glyphs(a, b):
        """Every glyph of one PDF at the same place in the other, to 0.02 pt."""
        ga, gb = glyphs(a), glyphs(b)
        if {k: len(v) for k, v in ga.items()} != {k: len(v) for k, v in gb.items()}:
            return False
        return all(any(abs(p[0] - q[0]) < 0.02 and abs(p[1] - q[1]) < 0.02 for q in gb[k])
                   for k, ps in ga.items() for p in ps)

    def differ(a, b):
        """Pixels that differ visibly between two one-page PDFs, and whether every
        glyph sits in the same place. The pixels are counted at two resolutions and
        the smaller count kept: a baseline that lands on a half pixel can snap
        either way over a thousandth of a point, and does so at one resolution
        but not the next, where a real difference shows at both."""
        counts = []
        for dpi in (67, 73):
            ims = []
            for p in (a, b):
                with fitz.open(p) as doc:
                    pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
                    ims.append(Image.frombytes('RGB', (pix.width, pix.height), pix.samples))
            counts.append(sum(ImageChops.difference(*ims).convert('L').histogram()[25:]))
        return min(counts) if same_glyphs(a, b) else 10 ** 6

    def convert_and_compare(tpl, cf, meta, dims):
        a, b = os.path.join(tmp, 'tpl.pdf'), os.path.join(tmp, 'des.pdf')
        engine.build_cover_wrap(tpl, cf, meta, dims, a)
        design, notes = WC.from_template(tpl, cf, meta, dims)
        WDm.build_pdf(design, dims, b)
        return design, notes, differ(a, b)

    def outside_safe(design, g):
        """The text a design's checks would call outside the safe zone, measured
        as the editor's renderChecks measures it (static/wrap_designer.js)."""
        from reportlab.pdfbase import pdfmetrics
        s, ss, out = engine.WRAP_SAFE, engine.WRAP_SPINE_SAFE, []
        for e in design['elements']:
            if e['type'] != 'text' or e.get('anchor', 'sheet') == 'sheet':
                continue
            x, y, w, _ = WDm.el_rect(g, e)
            lines = WDm.break_lines(e)
            h = sum(e['size'] * e['leading'] * (1 if ln.strip() else e.get('blank', 1))
                    for ln in lines) / 72
            if not e.get('w'):
                w = max(WDm.line_width(ln, e) for ln in lines) / 72
            bb = (x - h, y, h, w) if e.get('rotate') == 90 else (x, y, w, h)
            o, pw = WDm.origin(g, e['anchor'])[0], WDm.panel_width(g, e['anchor'])
            inset = min(ss, pw / 2) if e['anchor'] == 'spine' else s
            x0, x1 = o + inset, o + pw - inset
            mid = bb[0] + bb[2] / 2
            if g['flap'] and mid < g['back_x']:
                x0, x1 = g['edge'] + s, g['back_x'] - s
            elif g['flap'] and mid > g['front_x'] + g['panel_w']:
                x0, x1 = g['front_x'] + g['panel_w'] + s, g['front_x'] + g['panel_w'] + g['flap'] - s
            if (bb[0] < x0 - 0.005 or bb[0] + bb[2] > x1 + 0.005 or bb[1] < g['edge'] + s - 0.005
                    or bb[1] + bb[3] > g['edge'] + g['panel_h'] - s + 0.005):
                out.append(e['text'][:30])
        return out

    def collisions(design, g, slack=0.02):
        """Pairs of front-cover text whose type runs into each other: each box
        from its first line's ascent to its last line's descent, in inches."""
        from reportlab.pdfbase import pdfmetrics
        boxes = []
        for e in design['elements']:
            if e['type'] != 'text' or e.get('anchor') != 'front' or e.get('rotate'):
                continue
            face = pdfmetrics.getFont(WDm.font_name(e['font'])).face
            lay = WDm.text_layout(e)
            x, y, w, _ = WDm.el_rect(g, e)
            boxes.append((e['text'][:24], x, y + (lay[0][2] - face.ascent / 1000 * e['size']) / 72,
                          x + w, y + (lay[-1][2] - face.descent / 1000 * e['size']) / 72))
        return [(a[0], b[0]) for i, a in enumerate(boxes) for b in boxes[i + 1:]
                if a[1] < b[3] and b[1] < a[3] and min(a[4], b[4]) - max(a[2], b[2]) > slack]

    interior = engine.register_fonts(A.DEFAULTS)
    off, count = [], 0
    for c in A.list_cover_templates():
        cf = engine._register_cover_fonts(c['data'], interior)
        for binding in ('paperback', 'hardcover', 'jacket'):
            dims = A._wrap_dims({'wrap_binding': binding, 'wrap_retailer': 'ingramspark'}, 320)
            design, notes, n = convert_and_compare(c['data'], cf, META, dims)
            count += 1
            if n > 10 or notes:
                off.append((c['id'], binding, n, notes))
            if c['id'] == 'ashforge-house' and binding == 'paperback':
                classic = design
    check(f'every template converts to a design that prints the same wrap, pixel for pixel '
          f'({count} wraps: each template in all three bindings)',
          count >= 72 and not off, off)
    # The templates themselves, read by the designer's own checks: a conversion
    # is faithful, so text a template prints outside the safe zone shows up here.
    # (Fixed together: spine text sized to the spine's safe margins, the barcode
    # label no longer inheriting the series line's tracking, and the
    # photographic title lifted when a long one would push the author off.)
    unsafe = []
    for c in A.list_cover_templates():
        cf = engine._register_cover_fonts(c['data'], interior)
        for binding in ('paperback', 'hardcover', 'jacket'):
            for pages in (150, 320):
                dims = A._wrap_dims({'wrap_binding': binding, 'wrap_retailer': 'ingramspark'}, pages)
                design, _ = WC.from_template(c['data'], cf, META, dims)
                bad = outside_safe(design, engine.wrap_geometry(dims))
                if bad:
                    unsafe.append((c['id'], binding, pages, bad))
    check('every template keeps its text inside the safe zones, spine and flaps included, '
          'with a three-line title', not unsafe, unsafe[:6])
    # A title as long as anyone will type: every family shrinks or lifts it to keep
    # its lines inside the safe zone and off each other (they used to grow down
    # through the epigraph, out of their band, or off the foot of the cover).
    LONG = ('A Very Long Title That Somebody Insisted On Because Their Editor Was Away '
            'On Holiday That Week')
    trouble = []
    dims = A._wrap_dims({'wrap_retailer': 'ingramspark'}, 320)
    g320 = engine.wrap_geometry(dims)
    for c in A.list_cover_templates():
        cf = engine._register_cover_fonts(c['data'], interior)
        for t in (META['title'], LONG):
            design, _ = WC.from_template(c['data'], cf, dict(META, title=t), dims)
            bad = outside_safe(design, g320) + collisions(design, g320)
            if bad:
                trouble.append((c['id'], t[:12], bad))
    check('a very long title stays inside the safe zone and clear of the other lines, '
          'in every template', not trouble, trouble[:6])
    thin = A._wrap_dims({'wrap_retailer': 'ingramspark'}, 60)
    tpl = A.load_cover_template('ashforge-house')
    res = engine.build_cover_wrap(tpl, engine._register_cover_fonts(tpl, interior), META, thin,
                                  os.path.join(tmp, 'thin.pdf'))
    check('a spine too thin for type inside its margins is left without, and says so',
          engine.wrap_geometry(thin)['spine_text'] and not res['spine_text'], res)
    labels = [e.get('label') for e in classic['elements']]
    texts = {e['text'] for e in classic['elements'] if e['type'] == 'text'}
    check('the background, frame and ornament are layers of their own',
          classic['elements'][0].get('fill') == 'sheet' and 'Frame (front)' in labels
          and 'Ornament (front)' in labels, labels)
    check('a title the template set on three lines is one text box with its words rejoined',
          'THE SALT ROAD BETWEEN WINTERS' in texts, texts)
    blurb = next(e for e in classic['elements'] if e['type'] == 'text' and 'lighthouse' in e['text'])
    check('a blurb keeps its paragraphs, and the gap between them',
          blurb['text'].count('\n\n') == 1 and abs(blurb['blank'] - 0.6) < 1e-6, blurb)
    # the design is the writer's now: a thicker book moves its front panel along
    d2 = A._wrap_dims({'wrap_retailer': 'ingramspark'}, 640)
    g1, g2 = (engine.wrap_geometry(A._wrap_dims({'wrap_retailer': 'ingramspark'}, 320)),
              engine.wrap_geometry(d2))
    frame = next(e for e in classic['elements'] if e.get('label') == 'Frame (front)')
    check('a converted frame moves with the front panel when the spine grows',
          abs((WDm.el_rect(g2, frame)[0] - WDm.el_rect(g1, frame)[0])
              - (g2['front_x'] - g1['front_x'])) < 1e-9 and g2['front_x'] > g1['front_x'])
    longer = json.loads(json.dumps(classic))
    next(e for e in longer['elements'] if e.get('text') == 'THE SALT ROAD BETWEEN WINTERS')['text'] \
        = 'THE SALT ROAD BETWEEN THE WINTERS OF THE NORTH'
    lines = WDm.build_pdf(longer, d2, os.path.join(tmp, 'longer.pdf'))
    check('an edited title re-flows in its box', any(len(v) > 3 for v in lines.values()), lines)

    # pictures: background art and an emblem from the asset library, a phone photo
    # stored on its side as the author photo, and uploaded art as the front
    engine_assets = engine.COVER_ASSET_DIR
    engine.COVER_ASSET_DIR = A.COVER_ASSET_DIR
    try:
        Image.new('RGB', (900, 1200), (40, 90, 140)).save(os.path.join(A.COVER_ASSET_DIR, 'sea.png'))
        Image.new('RGB', (200, 200), (220, 200, 60)).save(os.path.join(A.COVER_ASSET_DIR, 'mark.png'))
        photo = os.path.join(tmp, 'author.jpg')
        im = Image.new('RGB', (300, 200), (200, 80, 40))
        ex = im.getexif(); ex[0x0112] = 6
        im.save(photo, exif=ex)
        meta = dict(META, cover_back_image=photo, cover_back_image_w=1.4, cover_back_image_y=0.35)
        tpl = dict(A.load_cover_template('photo-dusk'),
                   background={'image': 'sea.png', 'vignette': 0.3},
                   emblems=[{'image': 'mark.png', 'slot': 'top-right', 'w': 0.8}])
        dims = A._wrap_dims({'wrap_retailer': 'ingramspark'}, 320)
        design, notes, n = convert_and_compare(tpl, engine._register_cover_fonts(tpl, interior),
                                               meta, dims)
        srcs = [e['src'] for e in design['elements'] if e['type'] == 'image']
        check('background art, an emblem and a turned author photo carry over',
              n <= 10 and 'sea.png' in srcs and 'mark.png' in srcs
              and any(s.startswith('imported-') for s in srcs), (n, srcs))
        check('the turned photo is copied upright where the designer can serve it',
              any(client.get('/wrap-designer/art/' + s).status_code == 200
                  for s in srcs if s.startswith('imported-')))
        art_meta = dict(meta, cover_mode='image', cover_overlay=True,
                        cover_image=os.path.join(A.COVER_ASSET_DIR, 'sea.png'))
        design, notes, n = convert_and_compare(engine.image_wrap_template(art_meta['cover_image']),
                                               engine.image_cover_fonts(A.DEFAULTS), art_meta, dims)
        check('a wrap around uploaded art converts too', n <= 10 and any(
            e.get('src') == 'sea.png' for e in design['elements']), n)
    finally:
        engine.COVER_ASSET_DIR = engine_assets

    # opacity reaches the PDF (ReportLab's colours carry their own alpha, and
    # used to undo it), and a stretched shape keeps its line width
    half = {'elements': [{'id': 'k', 'type': 'rect', 'fill': 'sheet', 'color': '#000000'},
                         {'id': 'w', 'type': 'rect', 'fill': 'sheet', 'color': '#ffffff',
                          'opacity': 0.5}]}
    hp = os.path.join(tmp, 'half.pdf')
    WDm.build_pdf(half, A._wrap_dims({}, 320), hp)
    with fitz.open(hp) as doc:
        px = doc[0].get_pixmap(dpi=10).pixel(20, 20)
    check('a shape at half opacity prints at half opacity', 110 < px[0] < 145, px)
    vec = {'type': 'vector', 'id': 'v', 'anchor': 'front', 'x': 1, 'y': 1, 'w': 4, 'h': 1,
           'vw': 2, 'vh': 1, 'ops': [['path', [['M', 0, 0.5], ['L', 2, 0.5]],
                                      {'stroke': '#ff0000', 'lw': 3}]]}
    vp = os.path.join(tmp, 'vec.pdf')
    WDm.build_pdf({'elements': [vec]}, A._wrap_dims({}, 320), vp)
    with fitz.open(vp) as doc:
        dr = doc[0].get_drawings()
    check('a shape stretched to twice its width: twice as long, same line weight',
          dr and abs(dr[0]['rect'].width - 4 * 72) < 0.01 and abs(dr[0]['width'] - 3) < 1e-6,
          dr and (dr[0]['rect'], dr[0]['width']))

    # the route, and the ways in
    res = client.post('/wrap-designer/customise', json={
        'template': 'ashforge-house', 'project': PID, 'settings': SETTINGS}).get_json()
    texts = [e['text'] for e in res['design']['elements'] if e['type'] == 'text'] if res['ok'] else []
    check("Customise lays a template out with the book's own title and back copy",
          res['ok'] and 'THE SALT ROAD' in texts and 'A road of salt.' in texts, (res.get('error'), texts))
    res = client.post('/wrap-designer/customise', json={'template': 'ashforge-house',
                                                        'settings': SETTINGS}).get_json()
    check('without a book it uses stand-in text',
          res['ok'] and any(e.get('text') == 'YOUR BOOK TITLE' for e in res['design']['elements']))
    res = client.post('/wrap-designer/customise', json={'template': 'no-such-cover'}).get_json()
    check('an unknown template is refused', not res['ok'] and 'template' in res['error'], res)
    res = client.post('/wrap-designer/customise', json={'project': PID}).get_json()
    check("a book whose cover is already a wrap design has no other cover to start from",
          not res['ok'], res)
    p = A.load_project(PID)
    A.save_project_file(PID, dict(p, cover_mode='designed', cover_template='minimal-noir'))
    res = client.post('/wrap-designer/customise', json={'project': PID, 'settings': SETTINGS}).get_json()
    check("“This book's own cover” starts from the template the book uses",
          res['ok'] and res['name'] == A.load_cover_template('minimal-noir')['name'], res.get('error'))
    A.save_project_file(PID, p)
    page = client.get('/covers').get_data(as_text=True)
    check('the covers page offers Customise on each template',
          page.count('/wrap-designer?from=') >= 24)
    page = client.get(f'/project/{PID}/edit').get_data(as_text=True)
    check("the book's template picker offers it too, for this book",
          f'/wrap-designer?project={PID}&amp;from=ashforge-house' in page
          or f'/wrap-designer?from=ashforge-house&amp;project={PID}' in page)
    page = client.get('/wrap-designer?from=photo-dusk').get_data(as_text=True)
    check('the designer is told which template to start from', '"startFrom": "photo-dusk"' in page)

    print('\n[justify, align, flaps (phase C leftovers)]')
    JUST = dict(DESIGN['elements'][3], id='j', align='justify',
                text=BLURB + '\n\nA second paragraph, short.')
    jl = WDm.text_layout(JUST)
    left = WDm.text_layout(dict(JUST, align='left'))
    box = JUST['w'] * 72
    check('justified text breaks into the same lines as left-aligned',
          [l[0] for l in jl] == [l[0] for l in left])
    ends = WDm.para_ends(JUST, [l[0] for l in jl])
    spread = [l for l, e in zip(jl, ends) if not e and l[3]]
    check('every line but a paragraph\'s last is spread to the full measure',
          spread and all(abs(l[3][-1][1] + WDm.line_width(l[3][-1][0], JUST) - box) < 1e-6
                         for l in spread) and len(spread) == ends.count(False), len(spread))
    check("a paragraph's last line is left as it is",
          all(l[3] is None for l, e in zip(jl, ends) if e))
    jp = os.path.join(tmp, 'justify.pdf')
    WDm.build_pdf({'elements': [JUST]}, A._wrap_dims({}, 320), jp)
    gj = engine.wrap_geometry(A._wrap_dims({}, 320))
    with fitz.open(jp) as doc:
        words = doc[0].get_text('words')
    first = spread[0][3]
    x0 = (WDm.el_rect(gj, JUST)[0]) * 72
    got = sorted(w_ for w_ in words if w_[4] in (first[0][0], first[-1][0]))
    check('the PDF sets a justified line\'s first word at the left and its last at the right edge',
          got and abs(min(w_[0] for w_ in got) - x0) < 0.5
          and abs(max(w_[2] for w_ in got) - (x0 + box)) < 0.5, got[:2])

    photo2 = os.path.join(A.PROJECT_MS_DIR, 'author-photo.jpg')
    Image.new('RGB', (300, 400), (90, 120, 150)).save(photo2)
    p = A.load_project(PID)
    A.save_project_file(PID, dict(p, print_flap_blurb='Jacket copy for the front flap.',
                                  print_flap_bio='Ellinor Vale lives by the sea.',
                                  print_back_file='author-photo.jpg'))
    info = client.get(f'/wrap-designer/project/{PID}').get_json()
    check("a book's flap copy and author photo reach the designer",
          info['flap_blurb'] == 'Jacket copy for the front flap.'
          and info['flap_bio'] == 'Ellinor Vale lives by the sea.'
          and info['photo'] and client.get('/wrap-designer/art/' + info['photo']).status_code == 200,
          {k: info.get(k) for k in ('flap_blurb', 'flap_bio', 'photo')})

    print('\n[the barcode, shapes, turns and hidden layers (phase D)]')
    from reportlab.graphics.barcode import eanbc

    def rl_bars(widget):
        """ReportLab's own EAN encoding of a value, as a string of modules."""
        m = widget.barWidth
        rects = sorted((r.x, r.width) for r in widget.draw().contents
                       if r.__class__.__name__ == 'Rect' and r.height > 5 and r.width < 4.5 * m)
        pat = ['0'] * 300
        for x_, w_ in rects:
            for k in range(int(round((x_ - rects[0][0]) / m)), int(round((x_ - rects[0][0] + w_) / m))):
                pat[k] = '1'
        return ''.join(pat).rstrip('0')
    codes = ('978030640615', '979123456789', '978186197271')
    check('the EAN-13 bars are ReportLab\'s, bar for bar',
          all(rl_bars(eanbc.Ean13BarcodeWidget(value=c)) ==
              WDm._ean13_modules(c + str(WDm._ean_check(c))).strip('0') for c in codes))
    check('and so is the price add-on',
          all(rl_bars(eanbc.Ean5BarcodeWidget(value=v)) == WDm._ean5_modules(v).strip('0')
              for v in ('90000', '52495', '12345')))
    check('an ISBN-10 becomes its ISBN-13; a mistyped one is caught',
          WDm.isbn13('0-306-40615-2') == ('9780306406157', None)
          and WDm.isbn13('9780306406158')[1] and WDm.isbn13('12345')[1])
    BC = {'id': 'bc', 'type': 'barcode', 'anchor': 'back', 'x': 3.75, 'y': 7.55, 'w': 2, 'h': 1.2,
          'isbn': '9780306406157', 'addon': '90000', 'font': 'Spectral-Regular.ttf'}
    parts = WDm.barcode_parts(BC, 2, 1.2)
    served = client.post('/wrap-designer/barcode', json=BC).get_json()
    check('a barcode with its price code: 30 bars and 16 more',
          len(parts['bars']) == 46 and not parts['error'], (len(parts['bars']), parts['error']))
    check('the editor is served the bars that print',
          served['bars'] == parts['bars'] and served['texts'] == parts['texts'])
    check('inside its box', all(0 <= b[0] and b[0] + b[2] <= 2 and 0 <= b[1] and b[1] + b[3] <= 1.2
                                for b in parts['bars']))
    bad = client.post('/wrap-designer/barcode', json=dict(BC, isbn='9780306406158')).get_json()
    check('a mistyped ISBN is reported, not drawn', bad['error'] and not bad['bars'], bad['error'])
    bp = os.path.join(tmp, 'barcode.pdf')
    hid = dict(DESIGN['elements'][2], id='hid', hidden=True, text='HIDDEN WORDS')
    shapes = [{'id': 'el', 'type': 'ellipse', 'anchor': 'front', 'x': 1, 'y': 1, 'w': 2, 'h': 1,
               'color': '', 'stroke': '#ff0000', 'stroke_w': 2},
              {'id': 'ru', 'type': 'rule', 'anchor': 'front', 'x': 1, 'y': 3, 'w': 2, 'weight': 4,
               'color': '#0000ff'}]
    WDm.build_pdf({'elements': [BC, hid] + shapes}, A._wrap_dims({}, 320), bp)
    with fitz.open(bp) as doc:
        txt = doc[0].get_text()
        draws = doc[0].get_drawings()
    check('the PDF carries the bars and the ISBN, and leaves the hidden text out',
          'ISBN 9780306406157' in txt and '90000' in txt and 'HIDDEN' not in txt)
    check('an outlined ellipse and a 4 pt rule are drawn as set',
          any(d_.get('color') and abs(d_['color'][0] - 1) < 0.01 and abs(d_['width'] - 2) < 1e-6
              for d_ in draws)
          and any(d_.get('color') and abs(d_['color'][2] - 1) < 0.01 and abs(d_['width'] - 4) < 1e-6
                  for d_ in draws))
    # a picture half red (left) and half blue, turned a quarter clockwise: red on top
    halves = Image.new('RGB', (200, 100), (255, 0, 0))
    halves.paste((0, 0, 255), (100, 0, 200, 100))
    halves.save(os.path.join(A.WRAP_DESIGN_DIR, 'halves.png'))
    tp = os.path.join(tmp, 'turn.pdf')
    gt = engine.wrap_geometry(A._wrap_dims({}, 320))
    WDm.build_pdf({'elements': [{'id': 't', 'type': 'image', 'anchor': 'front', 'x': 1, 'y': 1,
                                 'w': 1, 'h': 2, 'src': 'halves.png', 'turn': 90}]},
                  A._wrap_dims({}, 320), tp)
    with fitz.open(tp) as doc:
        pix = doc[0].get_pixmap(dpi=40)
    px_ = lambda xi, yi: pix.pixel(int((gt['front_x'] + xi) * 40), int((gt['edge'] + yi) * 40))
    check('a picture turned a quarter clockwise prints that way up',
          px_(1.5, 1.3)[0] > 200 and px_(1.5, 2.7)[2] > 200, (px_(1.5, 1.3), px_(1.5, 2.7)))
    check('and is measured for resolution the way it stands',
          WDm.placed_images({'elements': [{'type': 'image', 'anchor': 'front', 'x': 1, 'y': 1, 'w': 1,
                                           'h': 2, 'src': 'halves.png', 'turn': 90}]}, gt)[0][1:] == (2, 1))

    browser = find_browser()
    print('\n[the editor, in a browser]')
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
    else:
        server = make_server('127.0.0.1', 0, A.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser'),
                            '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_wd_harness'],
                           capture_output=True, timeout=300)
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser'),
                            '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_wd_harness2'],
                           capture_output=True, timeout=300)
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser'),
                            '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_wd_harness3'],
                           capture_output=True, timeout=300)
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser4'),
                            '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_wd_harness4'],
                           capture_output=True, timeout=300)
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser5'),
                            '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_wd_harness5'],
                           capture_output=True, timeout=300)
        finally:
            server.shutdown()
        check('the editor loaded and ran', bool(result), browser)
        if result:
            check('every text box breaks where the PDF does',
                  result['proof'].startswith('Built. All') and 'exactly' in result['proof'],
                  result['proof'])
            check('the proof offers the PDF to download', result['download'])
            check('more pages: the front panel moves by what the spine grew',
                  result['front_moved_with_spine'])
            check('a drag moves the title by the distance dragged', result['drag_ok'])
            check('Ctrl+Z undoes the drag', result['undo_ok'])
            check('Ctrl+Y redoes it', result['redo_ok'])
            check('a deleted layer comes back with undo', result['delete_undo_ok'])
            check('zooming a picture to 2x draws it twice as wide, pinned left',
                  result['zoom_ok'])
            check('the checks catch text outside the safe zone',
                  'Outside the safe zone' in result['checks'], result['checks'])
            check('and a character the font doesn\'t have',
                  'doesn\'t have' in result['checks'], result['checks'])
        check('a book opened by its link loads in the editor', bool(result2))
        if result2:
            check('with its saved design and its own settings',
                  result2['title'] == 'The Salt Road' and result2['paper'] == 'white'
                  and result2['trim_locked'], result2)
            check('and Save to book saves it', result2['save_shown']
                  and result2['status'].startswith('Saved'), result2)
        check("a template's Customise link opens it in the editor", bool(result3))
        if result3:
            check('as layers: frames and ornaments drawn as shapes, the title as text',
                  result3['vectors'] >= 4 and result3['paths'] > 10
                  and result3['title'] == 'THE SALT ROAD', result3)
            check('it says where it started from, and that it is not saved yet',
                  'Ashforge House' in result3['msg'] or 'not saved' in result3['msg'], result3['msg'])
            check('with the text on its front and back inside their safe zones',
                  result3['outside'] == [], result3['outside'])
            check('a shape layer recolours from its swatch', result3['swatch'] and result3['recoloured'])
            check('and every converted text box breaks where the PDF does',
                  result3['proof'].startswith('Built. All') and 'exactly' in result3['proof'],
                  result3['proof'])
            check('undo goes back to the design from before', result3['undone'])
        check('the editor ran the align, justify and flap checks', bool(result4))
        if result4:
            mine = WDm.text_layout(result4['justified'])
            theirs = result4['justified_layout']
            same = len(mine) == len(theirs) and all(
                a[0] == b[0] and abs(a[1] - b[1]) < 1e-6 and (a[3] is None) == (b[3] is None)
                and (a[3] is None or all(x[0] == y[0] and abs(x[1] - y[1]) < 1e-6
                                         for x, y in zip(a[3], b[3])))
                for a, b in zip(mine, theirs))
            check('the editor spreads a justified line exactly as the PDF does, word by word', same)
            check('Shift+click selects a second thing', result4['two_selected'])
            check('and a drag moves both by the same distance', result4['moved_together'])
            check('three line up by their left edges', result4['aligned_left'])
            check('and space evenly down the cover',
                  abs(result4['gaps'][0] - result4['gaps'][1]) < 1e-6, result4['gaps'])
            check('with the spacing tools offered for three or more', result4['tool_count'] == 8,
                  result4['tool_count'])
            check('one alone centres on its panel', result4['centred_on_panel'])
            check('a jacket offers the flap presets', result4['flaps_card'])
            added = result4['flap_added']
            check("they lay out the book's flap copy, bio and photo",
                  any('Jacket copy for the front flap' in a for a in added)
                  and any('Ellinor Vale lives by the sea' in a for a in added)
                  and any(a.startswith('image:imported-') for a in added)
                  and 'text:ABOUT THE AUTHOR' in added, added)
            check('on the flaps, inside their safe zones',
                  result4['on_flaps'] and result4['flap_inside'])
            check('and the PDF breaks them where the editor does',
                  result4['proof'].startswith('Built. All') and 'exactly' in result4['proof'],
                  result4['proof'])
        check('the editor ran the barcode, layer, shape and preset checks', bool(result5))
        if result5:
            r5 = result5
            check('a new design has a barcode box, locked', r5['barcode_locked'])
            check('kept clear for KDP, which prints its own', 'KDP prints its barcode there' in r5['checks_clear'],
                  r5['checks_clear'])
            check('an ISBN typed into it draws the barcode', r5['bars'] == 30 and
                  'carries the ISBN' in r5['checks_isbn'], (r5['bars'], r5['checks_isbn']))
            check('a mistyped ISBN is caught as you type', 'wrong check digit' in r5['checks_bad_isbn'],
                  r5['checks_bad_isbn'])
            check('text laid over the barcode is flagged', 'In the way of the barcode area' in r5['checks_over'],
                  r5['checks_over'])
            check('a hidden layer leaves the screen', r5['hidden_gone'])
            check('a picture that stops at the trim, and one too small for its size, are flagged',
                  'stops short of the bleed' in r5['checks_pic'] and 'dpi' in r5['checks_pic'],
                  r5['checks_pic'])
            check('ellipses and rules can be added', r5['shapes'])
            check('two grouped are picked up together by a click on one',
                  r5['group_offered'] and r5['group_click'])
            check('a box dropped near the front\'s middle snaps onto it', r5['snapped'])
            check('"Praise for…" adds a heading and three quotes, grouped, inside the safe zone',
                  r5['quotes'] == 7 and r5['quotes_grouped'] and r5['quotes_inside'], r5)
            check('the cover zooms', r5['zoomed'])
            check('and with all that, the PDF still breaks every box where the editor does',
                  r5['proof'].startswith('Built. All') and 'exactly' in r5['proof'], r5['proof'])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
