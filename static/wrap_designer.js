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
    var asc = m.ascent / 1000 * el.size, box = (el.w || 0) * 72;
    return lines.map(function (ln, i) {
      var lw = WD.width(ln, m, el.size, el.tracking || 0), dx = 0;
      if (el.align === 'center') dx = box ? (box - lw) / 2 : -lw / 2;
      else if (el.align === 'right') dx = box ? box - lw : -lw;
      return [ln, dx, asc + i * el.size * (el.leading || 1.2)];
    });
  }
  function bbox(el) {                   // on the sheet, inches: [x, y, w, h]
    var r = elRect(el);
    if (el.type !== 'text') return r;
    var lay = layout(el), m = metrics[el.font];
    var h = lay.length * el.size * (el.leading || 1.2) / 72;
    var w = el.w || (m ? Math.max.apply(null, lay.map(function (l) { return WD.width(l[0], m, el.size, el.tracking || 0); }).concat([0])) / 72 : 0);
    var x = r[0];
    if (!el.w && el.align === 'center') x -= w / 2; else if (!el.w && el.align === 'right') x -= w;
    return el.rotate === 90 ? [r[0] - h, r[1], h, w] : [x, r[1], w, h];
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
      else if (el.type === 'image')
        node('image', {x:r[0], y:r[1], width:Math.max(r[2], 0), height:Math.max(r[3], 0),
                       href:'/wrap-designer/art/' + encodeURIComponent(el.src),
                       preserveAspectRatio:'xMidYMid slice', opacity:el.opacity == null ? 1 : el.opacity}, grp);
      else if (el.type === 'text') {
        var t = node('g', {transform:'translate(' + r[0] + ' ' + r[1] + ')' + (el.rotate === 90 ? ' rotate(90)' : '')}, grp);
        var lay = layout(el);
        // an invisible box under the text, so the gaps between letters can be grabbed
        var bb = bbox(el);
        node('rect', {x:bb[0], y:bb[1], width:bb[2], height:bb[3], fill:'transparent'}, grp);
        lay.forEach(function (l) {
          node('text', {x:l[1] / 72, y:l[2] / 72, 'font-family':WD.family(el.font),
                        'font-size':el.size / 72, 'letter-spacing':(el.tracking || 0) / 72,
                        fill:el.color, 'xml:space':'preserve', 'pointer-events':'none'}, t).textContent = l[0];
        });
      }
    });
    if ($('wd-guides').checked) drawGuides();
    if (sel && find(sel)) drawSelection();
    renderLayers();
    renderChecks();
    persist();
    markDirty();
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
    var el = find(sel), bb = bbox(el), gs = node('g', {'pointer-events':'none'}, svg);
    node('rect', {x:bb[0], y:bb[1], width:bb[2], height:bb[3], fill:'none', stroke:'#ff6f00', 'stroke-width':0.022}, gs);
    if (!el.fill) {
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
    return el.fill ? 'Colour (' + el.fill + ')' : 'Shape';
  }
  function renderLayers() {
    var ul = $('wd-layers');
    ul.innerHTML = '';
    design.elements.slice().reverse().forEach(function (el) {        // top layer first
      var li = document.createElement('li');
      if (el.id === sel) li.className = 'on';
      var span = document.createElement('span'); span.textContent = label(el); li.appendChild(span);
      [['up', '↑', 'Bring forward'], ['down', '↓', 'Send backward'], ['del', '×', 'Delete']].forEach(function (b) {
        var btn = document.createElement('button'); btn.type = 'button';
        btn.textContent = b[1]; btn.title = b[2];
        btn.addEventListener('click', function (e) { e.stopPropagation(); layerAct(el, b[0]); });
        li.appendChild(btn);
      });
      li.addEventListener('click', function () { sel = el.id; showProps(); render(); });
      ul.appendChild(li);
    });
  }
  function layerAct(el, act) {
    var i = design.elements.indexOf(el), a = design.elements;
    if (act === 'del') { a.splice(i, 1); if (sel === el.id) sel = null; showProps(); }
    else if (act === 'up' && i < a.length - 1) { a[i] = a[i + 1]; a[i + 1] = el; }
    else if (act === 'down' && i > 0) { a[i] = a[i - 1]; a[i - 1] = el; }
    render();
  }

  // What a printer would object to, worked out as you go.
  function renderChecks() {
    var out = [], s = geo.safe, spineSafe = geo.spine_safe;
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
      var bb = bbox(el), o = origin(el.anchor), pw = panelW(el.anchor);
      var inset = el.anchor === 'spine' ? spineSafe : s;
      var x0 = o[0] + (el.anchor === 'spine' ? Math.min(inset, pw / 2) : inset);
      var x1 = o[0] + pw - (el.anchor === 'spine' ? Math.min(inset, pw / 2) : inset);
      var y0 = o[1] + s, y1 = o[1] + g.panel_h - s, eps = 0.005;
      if (bb[0] < x0 - eps || bb[0] + bb[2] > x1 + eps || bb[1] < y0 - eps || bb[1] + bb[3] > y1 + eps)
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
      var grp = e.target.closest('.el');
      sel = grp ? grp.getAttribute('data-id') : null;
      var el2 = sel && find(sel);
      drag = el2 && !el2.fill ? {mode:'move', el:el2, p:p, x:el2.x || 0, y:el2.y || 0, cx:el2.cx} : null;
      showProps();
    }
    try { svg.setPointerCapture(e.pointerId); } catch (err) {}
    render();
  });
  svg.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var p = toInches(e), dx = p.x - drag.p.x, dy = p.y - drag.p.y, el = drag.el;
    if (drag.mode === 'resize') {
      el.w = Math.max(0.2, round(drag.w + (el.rotate === 90 ? dy : dx)));
      if (el.type !== 'text') el.h = Math.max(0.2, round(drag.h + dy));
    } else {
      if ('cx' in el) el.cx = round(drag.cx + dx); else el.x = round(drag.x + dx);
      el.y = round(drag.y + dy);
      snap(el);
    }
    render();
  });
  svg.addEventListener('pointerup', function () { if (drag) { drag = null; showProps(); } });
  // centre a box on its panel when it comes within 0.08"
  function snap(el) {
    var pw = panelW(el.anchor);
    if ('cx' in el) { if (Math.abs(el.cx) < 0.08) el.cx = 0; return; }
    if (!el.w || el.rotate === 90) return;
    if (Math.abs(el.x + el.w / 2 - pw / 2) < 0.08) el.x = round(pw / 2 - el.w / 2);
  }
  document.addEventListener('keydown', function (e) {
    if (!sel || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    var el = find(sel);
    if (!el) return;
    var step = e.shiftKey ? 0.1 : 0.01, k = 'cx' in el ? 'cx' : 'x';
    if (e.key === 'Delete' || e.key === 'Backspace') { layerAct(el, 'del'); e.preventDefault(); return; }
    if (el.fill) return;
    if (e.key === 'ArrowLeft') el[k] = round((el[k] || 0) - step);
    else if (e.key === 'ArrowRight') el[k] = round((el[k] || 0) + step);
    else if (e.key === 'ArrowUp') el.y = round((el.y || 0) - step);
    else if (e.key === 'ArrowDown') el.y = round((el.y || 0) + step);
    else return;
    e.preventDefault(); render();
  });

  function showProps() {
    var box = $('wd-props'), el = sel && find(sel);
    box.innerHTML = '<h3>Selected</h3>';
    if (!el) { box.insertAdjacentHTML('beforeend', '<p>Click something on the cover.</p>'); return; }
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
      inp.value = el[key] == null ? '' : el[key];
      inp.addEventListener('input', function () {
        el[key] = kind === 'number' ? (+inp.value || 0) : inp.value;
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
      add('Align', 'align', 'select', [['left', 'Left'], ['center', 'Centre'], ['right', 'Right']], true);
      add('Box width (in)', 'w', 'number', null, true); add('Colour', 'color', 'color', null, true);
    } else if (el.type === 'rect') {
      add('Colour', 'color', 'color', null, true); add('Opacity', 'opacity', 'number', null, true);
      if (!el.fill) { add('Width (in)', 'w', 'number', null, true); add('Height (in)', 'h', 'number', null, true); }
    } else if (el.type === 'image') {
      add('Opacity', 'opacity', 'number', null, true);
      if (!el.fill) { add('Width (in)', 'w', 'number', null, true); add('Height (in)', 'h', 'number', null, true); }
    }
  }

  // ---- adding things ------------------------------------------------------------
  function addEl(el) { el.id = el.type + '-' + (++seq); design.elements.push(el); sel = el.id; showProps(); }
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
    if (el) { el.src = src; sel = el.id; showProps(); }
    else {                                          // just above that panel's colour
      var bg = design.elements.findIndex(function (e) { return e.type === 'rect' && e.fill === where; });
      var img = {id:'image-' + (++seq), type:'image', fill:where, src:src};
      design.elements.splice(bg + 1, 0, img); sel = img.id; showProps();
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
    design = starter($('wd-project').value ? currentBook : null, g); sel = null; showProps();
    loadFonts().then(render);
  });
  $('wd-guides').addEventListener('change', render);

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
        sel = null; showProps();
        $('wd-save-status').textContent = b.saved ? 'Saved ' + b.saved.replace('T', ' ') : 'Not saved to this book yet';
        // the geometry first, so an example design can be laid out for this book
        return fetchGeometry().then(function () {
          if (!keepLocal) design = b.design || starter(b, g);
          return loadFonts();
        }).then(render);
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
    return post('/wrap-designer/geometry', settings()).then(function (res) { geo = res; g = res.geometry; });
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
  startPromise.then(function () { window.WD_READY = true; });

  // for the browser test: the live design and the geometry it is drawn against
  window.WD_EDITOR = { design: function () { return design; }, geometry: function () { return g; },
                       layout: layout, regeometry: regeometry };
})();
