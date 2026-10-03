/* Wrap designer (#72, beta): an SVG editor over the whole cover wrap.
 *
 * The SVG's user units are inches, so the editor's coordinates are the design
 * document's (see wrap_design.py). Text is laid out by WD (wrap_text.js) with
 * ReportLab's own width tables, so it breaks where the PDF breaks it; Proof
 * builds the real PDF and checks that, box by box. The design is kept in this
 * browser (localStorage) as you work.
 */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var CFG = JSON.parse(document.getElementById('wd-config').textContent);
  var svg = document.getElementById('wd-svg');
  var STORE = 'ts-wrap-design-v1';
  var $ = function (id) { return document.getElementById(id); };

  var BLURB = 'Write the back-cover copy here. This box wraps its lines exactly where the ' +
    'printed cover will: drag the orange corner to make it wider or narrower and watch the ' +
    'lines move. Keep it inside the dashed safe zone so nothing is trimmed off.';

  // The example design, laid out for the panel it's going on: a fixed 6x9 layout
  // ran off a smaller trim, and a new design shouldn't open covered in warnings.
  // Spine text is only added where the printer allows it (geo.spine_text).
  function starter(book, geom) {
    book = book || {};
    var title = book.title || 'My Book', author = book.author || 'Author Name';
    var pw = geom ? geom.panel_w : 6, ph = geom ? geom.panel_h : 9, k = pw / 6;
    var els = [
      {id:'bg-back', type:'rect', fill:'back', color:'#20283b'},
      {id:'bg-spine', type:'rect', fill:'spine', color:'#7d2a26'},
      {id:'front-art', type:'image', fill:'front', src:CFG.standIn},
      {id:'title', type:'text', anchor:'front', x:0.5, y:0.9, w:round(pw - 1), text:title,
       font:pick('EBGaramond-Bold.ttf'), size:Math.round(46 * k), leading:1.05, color:'#fbf3e2',
       align:'center', tracking:0.5},
      {id:'author', type:'text', anchor:'front', x:0.5, y:round(ph - 1.1), w:round(pw - 1),
       text:author.toUpperCase(), font:pick('Spectral-Regular.ttf'), size:Math.round(16 * k),
       leading:1.2, color:'#fbf3e2', align:'center', tracking:3},
      {id:'blurb', type:'text', anchor:'back', x:0.6, y:1.0, w:round(pw - 1.2), text:book.blurb || BLURB,
       font:pick('EBGaramond-Regular.ttf'), size:12.5, leading:1.4, color:'#efe7d6', align:'left', tracking:0},
      {id:'barcode', type:'rect', anchor:'back', x:round(pw - 2.25), y:round(ph - 1.45), w:2, h:1.2,
       color:'#ffffff', label:'Barcode area'}
    ];
    if (!geom || geom.spine_text)
      els.splice(5, 0, {id:'spine-text', type:'text', anchor:'spine', cx:0.11, y:0.6, w:round(ph - 1.2),
        rotate:90, text:(title + '   ' + author).toUpperCase(), font:pick('Spectral-Regular.ttf'),
        size:12, leading:1.2, color:'#fbf3e2', align:'center', tracking:1.5});
    return {elements: els};
  }
  function pick(f) { return CFG.fonts.indexOf(f) !== -1 ? f : CFG.fonts[0]; }

  // ---- state ----------------------------------------------------------------
  var saved = null;
  try { saved = JSON.parse(localStorage.getItem(STORE) || 'null'); } catch (e) { saved = null; }
  var design = (saved && saved.design && saved.design.elements) ? saved.design : starter();
  var g = null, geo = null, sel = null, metrics = {}, drag = null, seq = Date.now() % 100000;
  var also = [];                        // further selected ids, shift-clicked alongside `sel`
  var SETTINGS = ['wd-project', 'wd-name', 'wd-retailer', 'wd-paper', 'wd-binding', 'wd-trim', 'wd-pages'];
  if (saved && saved.settings) SETTINGS.forEach(function (id) {
    if (saved.settings[id] != null && $(id)) $(id).value = saved.settings[id];
  });
  function persist() {
    var s = {};
    SETTINGS.forEach(function (id) { s[id] = $(id).value; });
    try { localStorage.setItem(STORE, JSON.stringify({design: design, settings: s})); } catch (e) {}
  }
  function settings() {
    var t = ($('wd-trim').value || '6x9').split('x');
    return { pages: +$('wd-pages').value || 320, wrap_retailer: $('wd-retailer').value,
             wrap_paper: $('wd-paper').value, wrap_binding: $('wd-binding').value,
             wrap_trim_w: +t[0], wrap_trim_h: +t[1] };
  }
  function find(id) { return design.elements.find(function (e) { return e.id === id; }); }
  // Selection: `sel` is the one the properties panel shows; Shift+click adds
  // others to `also`, for moving, aligning and deleting together.
  function choose(id) { sel = id; also = []; }
  function chosen() {
    return (sel ? [sel] : []).concat(also).map(find).filter(function (e) { return e; });
  }
  function toggle(id) {
    if (id === sel) { sel = also.shift() || null; return; }
    var i = also.indexOf(id);
    if (i !== -1) also.splice(i, 1);
    else if (sel) also.push(id);
    else sel = id;
  }
  function round(v) { return Math.round(v * 1000) / 1000; }

  // ---- geometry (mirrors wrap_design.py) ---------------------------------------
  function origin(a) {
    return a === 'back' ? [g.back_x, g.edge] : a === 'spine' ? [g.spine_x, g.edge]
         : a === 'front' ? [g.front_x, g.edge] : [0, 0];
  }
  function panelW(a) { return a === 'spine' ? g.spine_w : (a === 'front' || a === 'back') ? g.panel_w : g.wrap_w; }
  function fillRect(w) {
    if (w === 'front') return [g.front_x, 0, g.wrap_w - g.front_x, g.wrap_h];
    if (w === 'back') return [0, 0, g.back_x + g.panel_w, g.wrap_h];
    if (w === 'spine') return [g.spine_x, 0, g.spine_w, g.wrap_h];
    return [0, 0, g.wrap_w, g.wrap_h];
  }
  function elRect(el) {
    if (el.fill) return fillRect(el.fill);
    var o = origin(el.anchor || 'sheet');
    var x = ('cx' in el) ? panelW(el.anchor) / 2 + el.cx : (el.x || 0);
    return [o[0] + x, o[1] + (el.y || 0), el.w || 0, el.h || 0];
  }
  function layout(el) {                 // [(line, dx, base)] in points, as text_layout
    var m = metrics[el.font];
    if (!m) return [];
    var lines = el.w ? WD.breakLines(el.text, m, el.size, el.w * 72, el.tracking || 0)
                     : String(el.text).split(/\r?\n/);
    var asc = m.ascent / 1000 * el.size, box = (el.w || 0) * 72, down = 0;
    var step = el.size * (el.leading || 1.2), blank = blankOf(el);
    var ends = el.align === 'justify' && box ? paraEnds(el, m, lines) : null;
    return lines.map(function (ln, i) {
      var lw = WD.width(ln, m, el.size, el.tracking || 0), dx = 0, words = null;
      if (el.align === 'center') dx = box ? (box - lw) / 2 : -lw / 2;
      else if (el.align === 'right') dx = box ? box - lw : -lw;
      else if (ends && !ends[i]) words = justify(ln, el, m, box);
      var out = [ln, dx, asc + down, words];
      down += step * (ln.trim() ? 1 : blank);
      return out;
    });
  }
  // Whether each line ends its paragraph: a justified box leaves those ragged.
  // Mirrors wrap_design.para_ends.
  function paraEnds(el, m, lines) {
    var ends = [], paras = WD.splitlines(String(el.text));
    if (!paras.length) paras = [''];
    paras.forEach(function (p) {
      var n = WD.breakLines(p, m, el.size, el.w * 72, el.tracking || 0).length;
      for (var k = 1; k < n; k++) ends.push(false);
      ends.push(true);
    });
    return ends.length === lines.length ? ends : lines.map(function () { return true; });
  }
  // [(word, x)] spreading a line across the box, as wrap_design.justify.
  function justify(ln, el, m, box) {
    var words = ln.split(' '), tr = el.tracking || 0, lw = WD.width(ln, m, el.size, tr);
    if (words.length < 2 || lw >= box) return null;
    var extra = (box - lw) / (words.length - 1), k = 0;
    return words.map(function (wd, i) {
      var prefix = ln.slice(0, k);
      k += wd.length + 1;
      return [wd, WD.width(prefix, m, el.size, 0) + tr * WD.chars(prefix).length + extra * i];
    });
  }
  // an empty line's height in lines (a template's blurb leaves 0.6 between paragraphs)
  function blankOf(el) { return clamp(el.blank == null ? 1 : el.blank, 0, 2, 1); }
  function textHeight(el, lay) {        // inches
    var step = el.size * (el.leading || 1.2), blank = blankOf(el);
    return lay.reduce(function (h, l) { return h + step * (l[0].trim() ? 1 : blank); }, 0) / 72;
  }
  function bbox(el) {                   // on the sheet, inches: [x, y, w, h]
    var r = elRect(el);
    if (el.type !== 'text') return r;
    var lay = layout(el), m = metrics[el.font];
    var h = textHeight(el, lay);
    var w = el.w || (m ? Math.max.apply(null, lay.map(function (l) { return WD.width(l[0], m, el.size, el.tracking || 0); }).concat([0])) / 72 : 0);
    var x = r[0];
    if (!el.w && el.align === 'center') x -= w / 2; else if (!el.w && el.align === 'right') x -= w;
    return el.rotate === 90 ? [r[0] - h, r[1], h, w] : [x, r[1], w, h];
  }

  // ---- pictures -------------------------------------------------------------------
  // Cover-fit, then zoom (1 to 8), then the focal point fx/fy (0..1 across the
  // overflow, like CSS object-position). Mirrors wrap_design.image_fit.
  function clamp(v, lo, hi, dflt) { v = +v; return isFinite(v) ? Math.min(Math.max(v, lo), hi) : dflt; }
  function imageFit(iw, ih, bw, bh, el) {
    var s = Math.max(bw / iw, bh / ih) * clamp(el.zoom == null ? 1 : el.zoom, 1, 8, 1);
    var dw = iw * s, dh = ih * s;
    return [dw, dh, (bw - dw) * clamp(el.fx == null ? 0.5 : el.fx, 0, 1, 0.5),
                    (bh - dh) * clamp(el.fy == null ? 0.5 : el.fy, 0, 1, 0.5)];
  }
  var sizes = {};                     // natural pixel size of each picture, once loaded
  function imgSize(src) {
    if (sizes[src] !== undefined) return sizes[src];
    sizes[src] = null;
    var im = new Image();
    im.onload = function () { sizes[src] = [im.naturalWidth, im.naturalHeight]; render(); };
    im.src = '/wrap-designer/art/' + encodeURIComponent(src);
    return null;
  }

  // ---- undo -------------------------------------------------------------------------
  // Snapshots of the design, taken once an edit settles: a drag when it ends,
  // typing or a slider once it pauses. Opening a book starts a fresh history.
  var past = [], future = [], lastSnap = null, commitTimer = null;
  function snapshot() { return JSON.stringify(design); }
  function undoButtons() {
    $('wd-undo').disabled = !past.length && snapshot() === lastSnap;
    $('wd-redo').disabled = !future.length;
  }
  function resetHistory() { past = []; future = []; lastSnap = snapshot(); undoButtons(); }
  function commit() {
    clearTimeout(commitTimer);
    var now = snapshot();
    if (lastSnap === null) { lastSnap = now; return; }
    if (now === lastSnap) return;
    past.push(lastSnap);
    if (past.length > 200) past.shift();
    future = []; lastSnap = now; undoButtons();
  }
  function scheduleCommit() {
    clearTimeout(commitTimer);
    commitTimer = setTimeout(commit, 400);
    undoButtons();
  }
  function restore(snap) {
    lastSnap = snap; design = JSON.parse(snap);
    also = also.filter(find);
    if (sel && !find(sel)) sel = also.shift() || null;
    showProps(); loadFonts().then(render); undoButtons();
  }
  function undo() {
    commit();
    if (!past.length) return;
    future.push(lastSnap); restore(past.pop());
  }
  function redo() {
    commit();
    if (!future.length) return;
    past.push(lastSnap); restore(future.pop());
  }

  // ---- render -----------------------------------------------------------------
  function node(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function render() {
    if (!g) return;
    svg.setAttribute('viewBox', '0 0 ' + g.wrap_w + ' ' + g.wrap_h);
    svg.innerHTML = '';
    design.elements.forEach(function (el) {
      var r = elRect(el), grp = node('g', {'class': 'el', 'data-id': el.id}, svg);
      if (el.type === 'rect')
        node('rect', {x:r[0], y:r[1], width:Math.max(r[2], 0), height:Math.max(r[3], 0), fill:el.color || '#000',
                      opacity:el.opacity == null ? 1 : el.opacity}, grp);
      else if (el.type === 'image') {
        var href = '/wrap-designer/art/' + encodeURIComponent(el.src), sz = imgSize(el.src);
        var op = el.opacity == null ? 1 : el.opacity;
        if (sz && r[2] > 0 && r[3] > 0) {
          // a nested <svg> is a clipping viewport: the picture sized and placed
          // by imageFit, exactly as wrap_design.image_fit places it in the PDF
          var f = imageFit(sz[0], sz[1], r[2], r[3], el);
          var vp = node('svg', {x:r[0], y:r[1], width:r[2], height:r[3], overflow:'hidden'}, grp);
          node('image', {x:f[2], y:f[3], width:f[0], height:f[1], href:href,
                         preserveAspectRatio:'none', opacity:op}, vp);
        } else {
          node('image', {x:r[0], y:r[1], width:Math.max(r[2], 0), height:Math.max(r[3], 0), href:href,
                         preserveAspectRatio:'xMidYMid slice', opacity:op}, grp);
        }
      }
      else if (el.type === 'vector') drawVector(el, r, grp);
      else if (el.type === 'text') {
        var t = node('g', {transform:'translate(' + r[0] + ' ' + r[1] + ')' + (el.rotate === 90 ? ' rotate(90)' : '')}, grp);
        var lay = layout(el);
        // an invisible box under the text, so the gaps between letters can be grabbed
        var bb = bbox(el);
        node('rect', {x:bb[0], y:bb[1], width:bb[2], height:bb[3], fill:'transparent'}, grp);
        lay.forEach(function (l) {
          (l[3] || [[l[0], l[1]]]).forEach(function (run) {      // a justified line, word by word
            node('text', {x:run[1] / 72, y:l[2] / 72, 'font-family':WD.family(el.font),
                          'font-size':el.size / 72, 'letter-spacing':(el.tracking || 0) / 72,
                          fill:el.color, 'fill-opacity':el.opacity == null ? 1 : el.opacity,
                          'xml:space':'preserve', 'pointer-events':'none'}, t).textContent = run[0];
          });
        });
      }
    });
    if ($('wd-guides').checked) drawGuides();
    if (chosen().length) drawSelection();
    renderLayers();
    renderChecks();
    persist();
    markDirty();
    if (!drag && lastSnap !== null) scheduleCommit();
  }

  // A `vector` element: a template's own shapes (frame, ornament, shading),
  // drawn as wrap_design.draw_vector draws them - paths stretched to the box,
  // line widths not.
  var CAPS = ['butt', 'round', 'square'], JOINS = ['miter', 'round', 'bevel'];
  function drawVector(el, r, grp) {
    var sx = el.vw ? r[2] / el.vw : 1, sy = el.vh ? r[3] / el.vh : 1, a = el.opacity == null ? 1 : el.opacity;
    var X = function (x) { return r[0] + x * sx; }, Y = function (y) { return r[1] + y * sy; };
    // an invisible box under the drawing, so a thin frame can be grabbed anywhere inside it
    node('rect', {x:r[0], y:r[1], width:Math.max(r[2], 0), height:Math.max(r[3], 0), fill:'transparent'}, grp);
    (el.ops || []).forEach(function (op, i) {
      var st = op[op.length - 1] || {}, attrs = {'pointer-events':'none'};
      attrs.fill = st.fill || 'none';
      if (st.fill) { attrs['fill-opacity'] = a * (st.fa == null ? 1 : st.fa); attrs['fill-rule'] = 'evenodd'; }
      if (st.stroke) {
        attrs.stroke = st.stroke; attrs['stroke-width'] = (st.lw == null ? 1 : st.lw) / 72;
        attrs['stroke-opacity'] = a * (st.sa == null ? 1 : st.sa);
        attrs['stroke-linecap'] = CAPS[st.cap || 0]; attrs['stroke-linejoin'] = JOINS[st.join || 0];
        if (st.dash) attrs['stroke-dasharray'] = st.dash.map(function (v) { return v / 72; }).join(' ');
      }
      if (op[0] === 'path') {
        attrs.d = op[1].map(function (sg) {
          if (sg[0] === 'Z') return 'Z';
          var pts = [];
          for (var k = 1; k < sg.length; k += 2) pts.push(X(sg[k]) + ' ' + Y(sg[k + 1]));
          return sg[0] + pts.join(' ');
        }).join(' ');
        node('path', attrs, grp);
      } else if (op[0] === 'ellipse') {
        attrs.cx = X(op[1]); attrs.cy = Y(op[2]); attrs.rx = op[3] * sx; attrs.ry = op[4] * sy;
        node('ellipse', attrs, grp);
      } else if (op[0] === 'grad') {
        var id = 'wdg-' + el.id + '-' + i;
        var lg = node('linearGradient', {id:id, gradientUnits:'userSpaceOnUse', x1:0, x2:0, y1:Y(op[7]), y2:Y(op[8])},
                      node('defs', {}, grp));
        node('stop', {offset:0, 'stop-color':op[5]}, lg);
        node('stop', {offset:1, 'stop-color':op[6]}, lg);
        node('rect', {x:X(op[1]), y:Y(op[2]), width:op[3] * sx, height:op[4] * sy, fill:'url(#' + id + ')',
                      'fill-opacity':a * (st.fa == null ? 1 : st.fa), 'pointer-events':'none'}, grp);
      }
    });
  }
  // The colours a vector element is drawn in, each once, for recolouring.
  function vectorColours(el) {
    var seen = [];
    (el.ops || []).forEach(function (op) {
      var st = op[op.length - 1] || {};
      (op[0] === 'grad' ? [op[5], op[6]] : [st.fill, st.stroke]).forEach(function (c) {
        if (c && seen.indexOf(c) === -1) seen.push(c);
      });
    });
    return seen;
  }
  function recolour(el, from, to) {
    (el.ops || []).forEach(function (op) {
      var st = op[op.length - 1] || {};
      if (op[0] === 'grad') { if (op[5] === from) op[5] = to; if (op[6] === from) op[6] = to; }
      if (st.fill === from) st.fill = to;
      if (st.stroke === from) st.stroke = to;
    });
  }

  function drawGuides() {
    var gl = node('g', {'pointer-events':'none'}, svg), b = g.bleed, s = geo.safe;
    var line = function (x1, y1, x2, y2, c, dash) {
      node('line', {x1:x1, y1:y1, x2:x2, y2:y2, stroke:c, 'stroke-width':0.014, 'stroke-dasharray':dash || ''}, gl);
    };
    var box = function (x, y, w, h, c, dash) {
      node('rect', {x:x, y:y, width:w, height:h, fill:'none', stroke:c, 'stroke-width':0.014, 'stroke-dasharray':dash || ''}, gl);
    };
    var e = g.edge;
    box(e, e, g.wrap_w - 2 * e, g.wrap_h - 2 * e, '#e53935');                       // trim
    [g.spine_x, g.spine_x + g.spine_w].forEach(function (x) { line(x, 0, x, g.wrap_h, '#1e88e5'); });
    if (g.hinge) [g.spine_x - g.hinge, g.spine_x + g.spine_w + g.hinge].forEach(function (x) { line(x, 0, x, g.wrap_h, '#1e88e5', '0.05 0.05'); });
    if (g.flap) [g.back_x, g.front_x + g.panel_w].forEach(function (x) { line(x, 0, x, g.wrap_h, '#8e24aa', '0.08 0.04'); });
    ['back', 'front'].forEach(function (a) {
      var o = origin(a); box(o[0] + s, o[1] + s, g.panel_w - 2 * s, g.panel_h - 2 * s, '#00897b', '0.06 0.04');
    });
  }

  function drawSelection() {
    var els = chosen(), gs = node('g', {'pointer-events':'none'}, svg);
    els.forEach(function (e) {
      var b = bbox(e);
      node('rect', {x:b[0], y:b[1], width:b[2], height:b[3], fill:'none', stroke:'#ff6f00', 'stroke-width':0.022,
                    'stroke-dasharray':e.id === sel ? '' : '0.06 0.04'}, gs);
    });
    var el = find(sel), bb = el && bbox(el);
    if (el && els.length === 1 && !el.fill) {
      var hs = 0.14;
      node('rect', {x:bb[0] + bb[2] - hs / 2, y:bb[1] + bb[3] - hs / 2, width:hs, height:hs, fill:'#ff6f00',
                    'data-handle':'1', style:'cursor:nwse-resize'}, svg);
    }
  }

  // ---- layers and checks --------------------------------------------------------
  function label(el) {
    if (el.label) return el.label;
    if (el.type === 'text') return '"' + String(el.text).slice(0, 28) + '"';
    if (el.type === 'image') return (el.fill ? 'Picture (' + el.fill + ' cover)' : 'Picture') + ': ' + el.src;
    if (el.type === 'vector') return 'Shapes';
    return el.fill ? 'Colour (' + el.fill + ')' : 'Shape';
  }
  function renderLayers() {
    var ul = $('wd-layers');
    ul.innerHTML = '';
    design.elements.slice().reverse().forEach(function (el) {        // top layer first
      var li = document.createElement('li');
      if (el.id === sel || also.indexOf(el.id) !== -1) li.className = 'on';
      var span = document.createElement('span'); span.textContent = label(el); li.appendChild(span);
      [['up', '↑', 'Bring forward'], ['down', '↓', 'Send backward'], ['del', '×', 'Delete']].forEach(function (b) {
        var btn = document.createElement('button'); btn.type = 'button';
        btn.textContent = b[1]; btn.title = b[2];
        btn.addEventListener('click', function (e) { e.stopPropagation(); layerAct(el, b[0]); });
        li.appendChild(btn);
      });
      li.addEventListener('click', function (e) {
        if (e.shiftKey) toggle(el.id); else choose(el.id);
        showProps(); render();
      });
      ul.appendChild(li);
    });
  }
  function layerAct(el, act) {
    var i = design.elements.indexOf(el), a = design.elements;
    if (act === 'del') {
      a.splice(i, 1);
      if (sel === el.id) sel = also.shift() || null;
      also = also.filter(function (id) { return id !== el.id; });
      showProps();
    }
    else if (act === 'up' && i < a.length - 1) { a[i] = a[i + 1]; a[i + 1] = el; }
    else if (act === 'down' && i > 0) { a[i] = a[i - 1]; a[i - 1] = el; }
    render();
  }

  // The safe area an element is held to, on the sheet: [x0, y0, x1, y1]. Its
  // panel's, inset by the safe margin (the spine's own, smaller one on the
  // spine); on a jacket, the flap's when the element sits out on a flap.
  function safeBox(el) {
    var s = geo.safe, a = el.anchor && el.anchor !== 'sheet' ? el.anchor : 'front';
    var bb = bbox(el), o = origin(a), pw = panelW(a);
    var inset = a === 'spine' ? Math.min(geo.spine_safe, pw / 2) : s;
    var x0 = o[0] + inset, x1 = o[0] + pw - inset;
    var mid = bb[0] + bb[2] / 2;
    if (g.flap && mid < g.back_x) { x0 = g.edge + s; x1 = g.back_x - s; }
    else if (g.flap && mid > g.front_x + g.panel_w) {
      x0 = g.front_x + g.panel_w + s; x1 = g.front_x + g.panel_w + g.flap - s;
    }
    return [x0, g.edge + s, x1, g.edge + g.panel_h - s];
  }

  // What a printer would object to, worked out as you go.
  function renderChecks() {
    var out = [];
    (geo.warnings || []).forEach(function (w) { out.push(['bad', w]); });
    var spineText = design.elements.some(function (e) { return e.type === 'text' && e.anchor === 'spine'; });
    if (spineText && !g.spine_text) {
      var min = (CFG.retailers[$('wd-retailer').value] || {}).spine_text_min;
      out.push(['bad', 'This printer doesn\'t allow spine text on a book this thin' +
                       (min ? ' (from ' + min + ' pages).' : '.')]);
    }
    var outside = [], missing = [];
    design.elements.forEach(function (el) {
      if (el.type !== 'text') return;
      var m = metrics[el.font];
      if (m) {
        var gone = WD.chars(String(el.text)).filter(function (ch) {
          return !/\s/.test(ch) && m.widths[ch.codePointAt(0)] === undefined;
        });
        if (gone.length) missing.push(label(el) + ' (' + Array.from(new Set(gone)).join(' ') + ')');
      }
      if (!el.anchor || el.anchor === 'sheet') return;
      var bb = bbox(el), z = safeBox(el), eps = 0.005;
      if (bb[0] < z[0] - eps || bb[0] + bb[2] > z[2] + eps || bb[1] < z[1] - eps || bb[1] + bb[3] > z[3] + eps)
        outside.push(label(el));
    });
    if (outside.length) out.push(['bad', 'Outside the safe zone, may be trimmed: ' + outside.join(', ')]);
    else out.push(['ok', 'All text is inside the safe zones.']);
    if (missing.length) out.push(['bad', 'Characters the font doesn\'t have, which would print blank: ' + missing.join('; ')]);
    if (spineText && g.spine_text) out.push(['ok', 'The spine is wide enough for text.']);
    var ul = $('wd-checks');
    ul.innerHTML = '';
    out.forEach(function (c) { var li = document.createElement('li'); li.className = c[0]; li.textContent = c[1]; ul.appendChild(li); });
  }

  // ---- interaction ----------------------------------------------------------------
  function toInches(evt) {
    var pt = svg.createSVGPoint(); pt.x = evt.clientX; pt.y = evt.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }
  svg.addEventListener('pointerdown', function (e) {
    var p = toInches(e);
    if (e.target.getAttribute('data-handle')) {
      var el = find(sel);
      drag = {mode:'resize', el:el, p:p, w:el.w || 0, h:el.h || 0};
    } else {
      var grp = e.target.closest('.el'), hit = grp ? grp.getAttribute('data-id') : null;
      if (e.shiftKey) { if (hit) toggle(hit); drag = null; showProps(); render(); return; }
      if (!hit || (hit !== sel && also.indexOf(hit) === -1)) choose(hit);
      else if (hit !== sel) { also.splice(also.indexOf(hit), 1); also.unshift(sel); sel = hit; }
      var movers = chosen().filter(function (m) { return !m.fill; });
      drag = movers.length ? {mode:'move', p:p, start:movers.map(function (m) {
        return {el:m, x:m.x || 0, y:m.y || 0, cx:m.cx};
      })} : null;
      showProps();
    }
    try { svg.setPointerCapture(e.pointerId); } catch (err) {}
    render();
  });
  svg.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var p = toInches(e), dx = p.x - drag.p.x, dy = p.y - drag.p.y, el = drag.el;    // el: a resize
    if (drag.mode === 'resize') {
      el.w = Math.max(0.2, round(drag.w + (el.rotate === 90 ? dy : dx)));
      if (el.type !== 'text') el.h = Math.max(0.2, round(drag.h + dy));
    } else {
      // the distance rounded once, so everything dragged moves by the same amount
      var rdx = round(dx), rdy = round(dy);
      drag.start.forEach(function (st) {
        var m = st.el;
        if ('cx' in m) m.cx = st.cx + rdx; else m.x = st.x + rdx;
        m.y = st.y + rdy;
      });
      if (drag.start.length === 1) snap(drag.start[0].el);
    }
    render();
  });
  svg.addEventListener('pointerup', function () { if (drag) { drag = null; showProps(); commit(); } });
  // `exact` for align and distribute, whose positions are worked out to line up
  // exactly; a nudge rounds, as typing a position does.
  function moveBy(el, dx, dy, exact) {
    if (el.fill) return;
    var r = exact ? function (v) { return v; } : round;
    if ('cx' in el) el.cx = r(el.cx + dx); else el.x = r((el.x || 0) + dx);
    el.y = r((el.y || 0) + dy);
  }

  // Align and distribute. Several selected line up with each other (their
  // outer edges, or the middle of the span); one alone lines up with its
  // panel's safe area. Distribute spaces three or more evenly between the
  // outermost two. All by what you see: the boxes drawn round them.
  function align(how) {
    var els = chosen().filter(function (e) { return !e.fill; });
    if (!els.length) return;
    var boxes = els.map(bbox), ref;
    if (els.length === 1) ref = safeBox(els[0]);
    else ref = [Math.min.apply(null, boxes.map(function (b) { return b[0]; })),
                Math.min.apply(null, boxes.map(function (b) { return b[1]; })),
                Math.max.apply(null, boxes.map(function (b) { return b[0] + b[2]; })),
                Math.max.apply(null, boxes.map(function (b) { return b[1] + b[3]; }))];
    els.forEach(function (el, i) {
      var b = boxes[i], dx = 0, dy = 0;
      if (how === 'left') dx = ref[0] - b[0];
      else if (how === 'center') dx = (ref[0] + ref[2]) / 2 - (b[0] + b[2] / 2);
      else if (how === 'right') dx = ref[2] - (b[0] + b[2]);
      else if (how === 'top') dy = ref[1] - b[1];
      else if (how === 'middle') dy = (ref[1] + ref[3]) / 2 - (b[1] + b[3] / 2);
      else if (how === 'bottom') dy = ref[3] - (b[1] + b[3]);
      moveBy(el, dx, dy, true);
    });
    render(); commit();
  }
  function distribute(axis) {
    var k = axis === 'x' ? 0 : 1;
    var items = chosen().filter(function (e) { return !e.fill; })
      .map(function (el) { return {el:el, b:bbox(el)}; })
      .sort(function (p, q) { return p.b[k] - q.b[k]; });
    if (items.length < 3) return;
    var first = items[0].b, last = items[items.length - 1].b;
    var used = items.reduce(function (t, it) { return t + it.b[k + 2]; }, 0);
    var gap = (last[k] + last[k + 2] - first[k] - used) / (items.length - 1), at = first[k];
    items.forEach(function (it) {
      moveBy(it.el, k === 0 ? at - it.b[0] : 0, k === 1 ? at - it.b[1] : 0, true);
      at += it.b[k + 2] + gap;
    });
    render(); commit();
  }
  function alignTools(box, n) {
    var h = document.createElement('label');
    h.textContent = n > 1 ? 'Line them up' : 'Line up with the panel';
    box.appendChild(h);
    var row = document.createElement('div'); row.className = 'tools'; box.appendChild(row);
    var tools = [['left', 'Left'], ['center', 'Centre'], ['right', 'Right'],
                 ['top', 'Top'], ['middle', 'Middle'], ['bottom', 'Bottom']];
    if (n > 2) tools.push(['x', 'Space across'], ['y', 'Space down']);
    tools.forEach(function (t) {
      var b = document.createElement('button'); b.type = 'button'; b.className = 'btn btn-sm';
      b.textContent = t[1]; b.setAttribute('data-align', t[0]);
      b.addEventListener('click', function () {
        if (t[0] === 'x' || t[0] === 'y') distribute(t[0]); else align(t[0]);
      });
      row.appendChild(b);
    });
  }

  // centre a box on its panel when it comes within 0.08"
  function snap(el) {
    var pw = panelW(el.anchor);
    if ('cx' in el) { if (Math.abs(el.cx) < 0.08) el.cx = 0; return; }
    if (!el.w || el.rotate === 90) return;
    if (Math.abs(el.x + el.w / 2 - pw / 2) < 0.08) el.x = round(pw / 2 - el.w / 2);
  }
  document.addEventListener('keydown', function (e) {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;   // their own undo
    if ((e.ctrlKey || e.metaKey) && !e.altKey) {
      var k0 = e.key.toLowerCase();
      if (k0 === 'z' && !e.shiftKey) { e.preventDefault(); undo(); return; }
      if (k0 === 'y' || (k0 === 'z' && e.shiftKey)) { e.preventDefault(); redo(); return; }
    }
    var els = chosen();
    if (!els.length) return;
    var step = e.shiftKey ? 0.1 : 0.01;
    if (e.key === 'Delete' || e.key === 'Backspace') {
      els.forEach(function (el) { layerAct(el, 'del'); }); e.preventDefault(); return;
    }
    var d = {ArrowLeft:[-step, 0], ArrowRight:[step, 0], ArrowUp:[0, -step], ArrowDown:[0, step]}[e.key];
    if (!d) return;
    els.forEach(function (el) { moveBy(el, d[0], d[1]); });
    e.preventDefault(); render();
  });

  function showProps() {
    var box = $('wd-props'), el = sel && find(sel), n = chosen().length;
    box.innerHTML = '<h3>Selected</h3>';
    if (!el) {
      box.insertAdjacentHTML('beforeend', '<p>Click something on the cover. Shift+click to pick more than one.</p>');
      return;
    }
    if (n > 1) {
      var many = document.createElement('div'); many.className = 'id';
      many.textContent = n + ' selected. Drag or use the arrow keys to move them together.';
      box.appendChild(many);
      alignTools(box, n);
      return;
    }
    var id = document.createElement('div'); id.className = 'id';
    id.textContent = label(el) + (el.anchor ? ' · on the ' + el.anchor : '');
    box.appendChild(id);
    var row = null;
    var add = function (text, key, kind, opts, half) {
      var wrap = document.createElement('div');
      var l = document.createElement('label'); l.textContent = text; wrap.appendChild(l);
      var inp = document.createElement(kind === 'textarea' ? 'textarea' : kind === 'select' ? 'select' : 'input');
      if (kind === 'select') opts.forEach(function (o) {
        var op = document.createElement('option'); op.value = o[0]; op.textContent = o[1]; inp.appendChild(op);
      });
      else if (kind !== 'textarea') inp.type = kind;
      if (kind === 'number') inp.step = 'any';
      if (kind === 'range') { inp.min = opts.min; inp.max = opts.max; inp.step = opts.step; }
      inp.value = el[key] == null ? (kind === 'range' ? opts.dflt : '') : el[key];
      inp.addEventListener('input', function () {
        el[key] = (kind === 'number' || kind === 'range') ? (+inp.value || 0) : inp.value;
        (key === 'font' ? ensureFont(el.font) : Promise.resolve()).then(render);
      });
      wrap.appendChild(inp);
      if (half) {
        if (!row) { row = document.createElement('div'); row.className = 'row'; box.appendChild(row); }
        row.appendChild(wrap);
        if (row.children.length === 2) row = null;
      } else { row = null; box.appendChild(wrap); }
    };
    if (el.type === 'text') {
      add('Text', 'text', 'textarea');
      add('Font', 'font', 'select', CFG.fonts.map(function (f) { return [f, f.replace(/\.ttf$/i, '')]; }));
      add('Size (pt)', 'size', 'number', null, true); add('Line spacing', 'leading', 'number', null, true);
      add('Letter spacing (pt)', 'tracking', 'number', null, true);
      add('Align', 'align', 'select', [['left', 'Left'], ['center', 'Centre'], ['right', 'Right'],
                                       ['justify', 'Justified']], true);
      add('Box width (in)', 'w', 'number', null, true); add('Colour', 'color', 'color', null, true);
    } else if (el.type === 'rect') {
      add('Colour', 'color', 'color', null, true); add('Opacity', 'opacity', 'number', null, true);
      if (!el.fill) { add('Width (in)', 'w', 'number', null, true); add('Height (in)', 'h', 'number', null, true); }
    } else if (el.type === 'image') {
      add('Zoom', 'zoom', 'range', {min:1, max:4, step:0.01, dflt:1});
      add('Show more of the left ' + String.fromCharCode(8596) + ' right', 'fx', 'range',
          {min:0, max:1, step:0.01, dflt:0.5});
      add('Show more of the top ' + String.fromCharCode(8597) + ' bottom', 'fy', 'range',
          {min:0, max:1, step:0.01, dflt:0.5});
      add('Opacity', 'opacity', 'number', null, true);
      if (!el.fill) { add('Width (in)', 'w', 'number', null, true); add('Height (in)', 'h', 'number', null, true); }
    } else if (el.type === 'vector') {
      var cols = vectorColours(el);
      if (cols.length) {
        var lab = document.createElement('label');
        lab.textContent = cols.length > 1 ? 'Colours' : 'Colour';
        box.appendChild(lab);
        var sw = document.createElement('div'); sw.className = 'swatches'; box.appendChild(sw);
        cols.forEach(function (c) {
          var inp = document.createElement('input'); inp.type = 'color'; inp.value = c; inp.title = c;
          var cur = c;                          // follows the colour as it is changed
          inp.addEventListener('input', function () { recolour(el, cur, inp.value); cur = inp.value; render(); });
          sw.appendChild(inp);
        });
      }
      add('Opacity', 'opacity', 'number', null, true);
      if (!el.fill) { add('Width (in)', 'w', 'number', null, true); add('Height (in)', 'h', 'number', null, true); }
    }
    if (!el.fill) alignTools(box, 1);
  }

  // ---- adding things ------------------------------------------------------------
  function addEl(el) { el.id = el.type + '-' + (++seq); design.elements.push(el); choose(el.id); showProps(); }
  $('wd-add-text').addEventListener('click', function () {
    addEl({type:'text', anchor:'front', x:1, y:4, w:4, text:'New text', font:pick('EBGaramond-Regular.ttf'),
           size:20, leading:1.2, color:'#ffffff', align:'center', tracking:0});
    ensureFont(find(sel).font).then(render);
  });
  $('wd-add-rect').addEventListener('click', function () {
    addEl({type:'rect', anchor:'front', x:0.5, y:6.5, w:5, h:0.6, color:'#000000', opacity:0.4});
    render();
  });
  function useArt(where) {
    var src = $('wd-art-pick').value;
    if (where === 'place') { addEl({type:'image', anchor:'front', x:1.5, y:2, w:3, h:3, src:src}); render(); return; }
    var el = design.elements.find(function (e) { return e.type === 'image' && e.fill === where; });
    if (el) { el.src = src; choose(el.id); showProps(); }
    else {                                          // just above that panel's colour
      var bg = design.elements.findIndex(function (e) { return e.type === 'rect' && e.fill === where; });
      var img = {id:'image-' + (++seq), type:'image', fill:where, src:src};
      design.elements.splice(bg + 1, 0, img); choose(img.id); showProps();
    }
    render();
  }
  $('wd-art-front').addEventListener('click', function () { useArt('front'); });
  $('wd-art-back').addEventListener('click', function () { useArt('back'); });
  $('wd-art-place').addEventListener('click', function () { useArt('place'); });
  $('wd-art-upload').addEventListener('click', function () { $('wd-art-file').click(); });
  $('wd-art-file').addEventListener('change', function () {
    var f = this.files && this.files[0];
    if (!f) return;
    var fd = new FormData(); fd.append('asset', f);
    fetch('/cover/asset/upload', {method:'POST', body:fd}).then(function (r) { return r.json(); }).then(function (j) {
      if (!j.ok) { alert(j.error || 'That image could not be added.'); return; }
      var op = document.createElement('option'); op.value = op.textContent = j.filename;
      $('wd-art-pick').appendChild(op); $('wd-art-pick').value = j.filename;
    });
    this.value = '';
  });
  $('wd-reset').addEventListener('click', function () {
    if (!confirm('Start over with the example design? Your current design will be replaced.')) return;
    design = starter($('wd-project').value ? currentBook : null, g); choose(null); showProps();
    loadFonts().then(render);
  });
  $('wd-guides').addEventListener('change', render);

  // ---- jacket flaps ---------------------------------------------------------------
  // What a dust jacket carries on its flaps, laid out the way the template wraps
  // lay them out (engine._paint_flap): the title over the jacket copy in front,
  // "About the author" over the photo and bio at the back. Set in the design's
  // own faces and colours - its largest type for headings, its longest for text.
  var FLAP_COPY = 'The jacket copy goes here: what the book is about, in a paragraph or two ' +
    'that a reader takes in with the book open in their hands.';
  var FLAP_BIO = 'A few lines about the author: where they live, what else they have written, ' +
    'and why they wrote this one.';
  function designFaces() {
    var texts = design.elements.filter(function (e) { return e.type === 'text' && e.font; });
    var head = texts.slice().sort(function (a, b) { return b.size - a.size; })[0];
    var body = texts.slice().sort(function (a, b) { return String(b.text).length - String(a.text).length; })[0];
    return {head: head ? head.font : pick('EBGaramond-Bold.ttf'), headColor: head ? head.color : '#fbf3e2',
            body: body ? body.font : pick('EBGaramond-Regular.ttf'), bodyColor: body ? body.color : '#efe7d6'};
  }
  function flapPreset(side) {
    if (!g.flap) return Promise.resolve();
    var f = designFaces(), book = $('wd-project').value ? currentBook : null;
    var pad = Math.max(geo.safe, Math.min(0.42, g.flap * 0.14)), col = round(g.flap - 2 * pad);
    var anchor = side === 'front' ? 'front' : 'back';
    var x = round(side === 'front' ? g.panel_w + pad : -g.flap + pad);
    var head = {type:'text', anchor:anchor, x:x, y:0.75, w:col, leading:1.3, align:'center'};
    if (side === 'front')
      Object.assign(head, {text:((book && book.title) || 'My Book').toUpperCase(), font:f.head, size:13,
                           tracking:1.2, color:f.headColor});
    else
      Object.assign(head, {text:'ABOUT THE AUTHOR', font:f.body, size:8, tracking:2.6, color:f.headColor});
    var body = {type:'text', anchor:anchor, x:x, w:col, font:f.body, size:9.5, leading:1.42,
                color:f.bodyColor, align:'justify', tracking:0,
                text:side === 'front' ? (book && (book.flap_blurb || book.blurb)) || FLAP_COPY
                                      : (book && book.flap_bio) || FLAP_BIO};
    var photo = side === 'back' && book && book.photo ? {type:'image', anchor:anchor, src:book.photo} : null;
    return Promise.all([ensureFont(head.font), ensureFont(body.font)]).then(function () {
      // the preset fills the flap: what was on it goes (one undo brings it back)
      var onFlap = function (e) {
        if (e.fill) return false;
        var b = bbox(e), mid = b[0] + b[2] / 2;
        return side === 'front' ? mid > g.front_x + g.panel_w : mid < g.back_x;
      };
      design.elements = design.elements.filter(function (e) { return !onFlap(e); });
      [head, photo, body].forEach(function (el) { if (el) el.id = el.type + '-' + (++seq); });
      var y = head.y + bbox(head)[3] + 0.2;
      if (photo) {
        photo.w = round(Math.min(1.5, col)); photo.h = round(photo.w * 1.25);
        photo.x = round(x + (col - photo.w) / 2); photo.y = round(y); y += photo.h + 0.2;
      }
      body.y = round(y);
      [head, photo, body].forEach(function (el) { if (el) design.elements.push(el); });
      choose(head.id); also = [photo, body].filter(Boolean).map(function (el) { return el.id; });
      showProps(); render(); commit();
    });
  }
  $('wd-flap-front').addEventListener('click', function () { flapPreset('front'); });
  $('wd-flap-back').addEventListener('click', function () { flapPreset('back'); });

  // ---- start from a template ("Customise this design") ------------------------------
  // The template's wrap - or the book's own cover - converted by the server into
  // elements, laid out for this book and printer. One undo goes back.
  function customise(from) {
    var msg = $('wd-from-msg'), pid = $('wd-project').value;
    if (!from) return Promise.resolve();
    msg.textContent = 'Converting…';
    return post('/wrap-designer/customise', {template: from === '@book' ? '' : from, project: pid,
                                             settings: settings()})
      .then(function (res) {
        if (!res.ok) { msg.textContent = res.error; return; }
        commit();
        design = res.design; choose(null); showProps();
        return loadFonts().then(function () {
          render(); commit();
          msg.textContent = 'Started from ' + res.name + (pid ? ', not saved to the book yet.' : '.') +
            (res.notes.length ? ' ' + res.notes.join(' ') : '');
        });
      }).catch(function () { msg.textContent = 'No answer from the app.'; });
  }
  $('wd-from-btn').addEventListener('click', function () { customise($('wd-from').value); });

  // ---- a book's cover ---------------------------------------------------------------
  // With a book picked, its trim is its style's and its printer, paper and
  // binding are its Send to print settings; Save keeps the design with the book.
  var savedJSON = null;                 // the design as last saved to (or loaded from) the book
  var currentBook = null;
  function markDirty() {
    var pid = $('wd-project').value, st = $('wd-save-status');
    if (!pid || savedJSON === null) return;
    if (JSON.stringify(design) !== savedJSON) st.textContent = 'Unsaved changes';
  }
  function lockTrim(w, h) {
    var sel = $('wd-trim'), v = w + 'x' + h;
    if (!Array.prototype.some.call(sel.options, function (o) { return o.value === v; })) {
      var op = document.createElement('option'); op.value = v;
      op.textContent = w + ' × ' + h + ' in (this book’s style)'; sel.appendChild(op);
    }
    sel.value = v; sel.disabled = true;
  }
  function bookUi(on) {
    $('wd-save-group').style.display = on ? 'inline-flex' : 'none';
    if (!on) { $('wd-trim').disabled = false; $('wd-book-note').hidden = true; $('wd-save-status').textContent = ''; }
  }
  function openBook(pid, keepLocal) {
    bookUi(!!pid);
    if (!pid) { savedJSON = null; currentBook = null; persist(); return regeometry(); }
    return fetch('/wrap-designer/project/' + encodeURIComponent(pid)).then(function (r) { return r.json(); })
      .then(function (b) {
        var s = b.settings;
        $('wd-retailer').value = s.wrap_retailer; $('wd-paper').value = s.wrap_paper;
        $('wd-binding').value = s.wrap_binding; $('wd-pages').value = s.pages;
        lockTrim(s.wrap_trim_w, s.wrap_trim_h);
        $('wd-name').value = b.title || $('wd-name').value;
        $('wd-use-cover').checked = b.is_cover || !b.design;
        var note = $('wd-book-note');
        note.hidden = false;
        note.textContent = (b.pages_known
          ? 'Pages are from this book’s last build; Send to print sizes the spine from the real count.'
          : 'This book hasn’t been built yet, so the page count is a guess. Send to print sizes the spine from the real count.')
          + (b.is_cover ? ' This design is the book’s cover.' : '');
        savedJSON = b.design ? JSON.stringify(b.design) : null;
        currentBook = b;
        choose(null); showProps();
        $('wd-save-status').textContent = b.saved ? 'Saved ' + b.saved.replace('T', ' ') : 'Not saved to this book yet';
        // the geometry first, so an example design can be laid out for this book
        return fetchGeometry().then(function () {
          if (!keepLocal) design = b.design || starter(b, g);
          return loadFonts();
        }).then(function () { render(); resetHistory(); });
      });
  }
  $('wd-project').addEventListener('change', function () { openBook(this.value, false); });
  $('wd-save').addEventListener('click', function () {
    var pid = $('wd-project').value, st = $('wd-save-status');
    if (!pid) return;
    st.textContent = 'Saving…';
    post('/wrap-designer/project/' + encodeURIComponent(pid) + '/save',
         {design: design, settings: settings(), use_as_cover: $('wd-use-cover').checked})
      .then(function (res) {
        if (!res.ok) { st.textContent = res.error; return; }
        savedJSON = JSON.stringify(design);
        st.textContent = 'Saved ' + res.saved.replace('T', ' ') + (res.is_cover ? ' · the book’s cover' : '');
      }).catch(function () { st.textContent = 'Not saved: no answer from the app.'; });
  });

  // ---- server: geometry and the real PDF ------------------------------------------
  function post(url, body) {
    return fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})
      .then(function (r) { return r.json(); });
  }
  function fetchGeometry() {
    return post('/wrap-designer/geometry', settings()).then(function (res) {
      geo = res; g = res.geometry;
      $('wd-flaps').hidden = !g.flap;      // flap presets only where there are flaps
    });
  }
  function regeometry() { return fetchGeometry().then(render); }
  SETTINGS.forEach(function (id) { $(id).addEventListener('change', function () { persist(); regeometry(); }); });
  $('wd-pages').addEventListener('input', regeometry);

  $('wd-proof-btn').addEventListener('click', function () {
    var msg = $('wd-proof-msg');
    msg.className = ''; msg.textContent = 'Building the PDF…';
    post('/wrap-designer/build', {design:design, settings:settings(), name:$('wd-name').value}).then(function (res) {
      if (!res.ok) { msg.className = 'bad'; msg.textContent = res.error; return; }
      var bad = [], count = 0;
      design.elements.forEach(function (el) {
        if (el.type !== 'text' || !metrics[el.font]) return;
        count++;
        var mine = layout(el).map(function (l) { return l[0]; });
        if (JSON.stringify(mine) !== JSON.stringify(res.lines[el.id])) bad.push(label(el));
      });
      msg.className = bad.length ? 'bad' : 'ok';
      msg.textContent = bad.length
        ? 'These break into lines differently in the PDF than on screen: ' + bad.join(', ')
        : 'Built. All ' + count + ' text boxes break into lines exactly as they do here.';
      $('wd-proof').innerHTML = '';
      if (res.png) { var img = new Image(); img.alt = 'The wrap as printed'; img.src = res.png; $('wd-proof').appendChild(img); }
      var a = document.createElement('a'); a.className = 'btn btn-sm'; a.href = res.pdf;
      a.textContent = 'Download the PDF'; a.style.marginTop = '8px';
      $('wd-proof').appendChild(a);
    }).catch(function () { msg.className = 'bad'; msg.textContent = 'No answer from the app. Is it still running?'; });
  });

  function ensureFont(f) {
    if (!f) return Promise.resolve();
    return Promise.all([WD.loadFont(f), WD.metrics(f).then(function (m) { metrics[f] = m; })])
      .catch(function () {});
  }
  function loadFonts() {
    var used = design.elements.filter(function (e) { return e.font; }).map(function (e) { return e.font; });
    return Promise.all(used.filter(function (f, i) { return used.indexOf(f) === i; }).map(ensureFont));
  }
  var start = CFG.startProject || '';
  var startPromise;
  if (start && Array.prototype.some.call($('wd-project').options, function (o) { return o.value === start; })) {
    $('wd-project').value = start;
    startPromise = openBook(start, saved && saved.settings && saved.settings['wd-project'] === start);
  } else if ($('wd-project').value) {
    startPromise = openBook($('wd-project').value, true);   // carry on with the local working copy
  } else {
    startPromise = loadFonts().then(regeometry);
  }
  startPromise.then(function () {
    resetHistory();
    var from = CFG.startFrom;             // arrived from a template's "Customise"
    if (from && Array.prototype.some.call($('wd-from').options, function (o) { return o.value === from; })) {
      $('wd-from').value = from;
      return customise(from);
    }
  }).then(function () { window.WD_READY = true; });
  $('wd-undo').addEventListener('click', undo);
  $('wd-redo').addEventListener('click', redo);

  // for the browser test: the live design and the geometry it is drawn against
  window.WD_EDITOR = { design: function () { return design; }, geometry: function () { return g; },
                       layout: layout, regeometry: regeometry, commit: commit, imageFit: imageFit,
                       undo: undo, redo: redo, customise: customise, bbox: bbox, safeBox: safeBox,
                       align: align, distribute: distribute, flapPreset: flapPreset,
                       select: function (ids) { choose(ids[0] || null); also = ids.slice(1); showProps(); render(); } };
})();
