/* Wrap designer (#72): text measurement and line breaking.
 *
 * breakLines() is a port of engine._wrap_tracked, measuring with the width
 * tables ReportLab itself measures with (wrap_design.metrics), so the editor
 * breaks a blurb exactly where the PDF will. Not the browser's own measureText:
 * the phase A spike found it breaks differently in 5 of 17,640 cases, which is
 * the one thing a print-true editor can't do (spikes/wrap_designer/README.md).
 */
(function (global) {
  'use strict';
  var BASE = '/wrap-designer';
  var fontsLoaded = {}, metricsCache = {};

  function family(f) { return 'WD-' + f.replace(/\.ttf$/i, ''); }

  function loadFont(f) {
    if (fontsLoaded[f]) return fontsLoaded[f];
    var face = new FontFace(family(f), 'url(' + BASE + '/font/' + encodeURIComponent(f) + ')');
    fontsLoaded[f] = face.load().then(function (ff) { document.fonts.add(ff); return family(f); });
    return fontsLoaded[f];
  }

  function metrics(f) {
    if (!metricsCache[f])
      metricsCache[f] = fetch(BASE + '/metrics/' + encodeURIComponent(f)).then(function (r) { return r.json(); });
    return metricsCache[f];
  }

  // Code points, as Python counts them (a JS string length counts UTF-16 units).
  function chars(s) { return Array.from(s); }

  // ReportLab's stringWidth for a TTF, plus tracking between characters - the
  // same expression, in the same order, as engine._wrap_tracked evaluates.
  //
  // The sum has to be Python's sum, bit for bit, or a line that just fits can
  // break differently. Integer widths (most fonts) add exactly either way. A font
  // whose widths are floats (Crimson Pro: its em isn't 1000 units) is summed by
  // CPython >= 3.12 with Neumaier compensation, mirrored here from
  // bltinmodule.c (cs_add / cs_to_double).
  function width(s, m, size, tracking) {
    var cs = chars(s), hi = 0, lo = 0;
    for (var i = 0; i < cs.length; i++) {
      var w = m.widths[cs[i].codePointAt(0)];
      var x = (w === undefined ? m['default'] : w);
      if (!m['float']) { hi += x; continue; }
      var t = hi + x;
      if (Math.abs(hi) >= Math.abs(x)) lo += (hi - t) + x;
      else lo += (x - t) + hi;
      hi = t;
    }
    var sum = (lo && isFinite(lo)) ? hi + lo : hi;
    return 0.001 * size * sum + (tracking || 0) * Math.max(cs.length - 1, 0);
  }

  // Python's str.splitlines(): no empty last line for a trailing break.
  var LINE_BREAK = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;
  function splitlines(s) {
    if (!s) return [];
    var out = s.split(LINE_BREAK);
    if (out.length && out[out.length - 1] === '' && LINE_BREAK.test(s.slice(-1))) out.pop();
    return out;
  }
  // Python's str.split() with no argument: runs of whitespace, no empty words.
  var PY_SPACE = /[\s\x1c-\x1f\x85]+/;
  function words(s) { return s.split(PY_SPACE).filter(function (w) { return w; }); }

  function breakWith(measure, text, maxW) {
    var out = [], paras = splitlines(String(text));
    if (!paras.length) paras = [''];
    paras.forEach(function (para) {
      var ws = words(para);
      if (!ws.length) { out.push(''); return; }
      var cur = '';
      ws.forEach(function (wd) {
        var trial = cur ? cur + ' ' + wd : wd;
        if (measure(trial) <= maxW || !cur) cur = trial;
        else { out.push(cur); cur = wd; }
      });
      if (cur) out.push(cur);
    });
    return out;
  }

  function breakLines(text, m, size, maxW, tracking) {
    return breakWith(function (s) { return width(s, m, size, tracking); }, text, maxW);
  }

  global.WD = { family: family, loadFont: loadFont, metrics: metrics, width: width,
                breakLines: breakLines, breakWith: breakWith, chars: chars, splitlines: splitlines };
})(window);
