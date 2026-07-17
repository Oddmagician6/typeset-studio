/* WYSIWYG view: document model <-> contenteditable DOM.
 *
 * The pure, testable core of the rich editor. `render(blocks)` builds DOM for the
 * editable surface; `read(rootEl)` walks that surface back into the document model.
 * `read(render(model))` is the identity (verified by _wystest.html over the corpus),
 * so editing the DOM and reading it back never corrupts structure -- and the model
 * serializes to Markdown via DocModel (doc_model.js), which the engine consumes.
 *
 * The editor stores raw Markdown as source of truth; this surface is a *view* the
 * template keeps synced into the textarea. Doc-block headers (type + attrs) are held
 * on data-attributes and not edited in place in this version -- their prose is
 * editable, their metadata is edited in Markdown mode. Everything round-trips losslessly.
 */
(function (global) {
  'use strict';

  // ---- model -> DOM ---------------------------------------------------------

  function appendInline(el, runs) {
    (runs || []).forEach(function (r) {
      var node = document.createTextNode(r.text);
      if (r.bold && r.italic) {
        var s = document.createElement('strong'), e = document.createElement('em');
        e.appendChild(node); s.appendChild(e); el.appendChild(s);
      } else if (r.bold) {
        var b = document.createElement('strong'); b.appendChild(node); el.appendChild(b);
      } else if (r.italic) {
        var i = document.createElement('em'); i.appendChild(node); el.appendChild(i);
      } else {
        el.appendChild(node);
      }
    });
    if (!el.childNodes.length) el.appendChild(document.createElement('br'));
  }

  function docHeadLabel(blockType, attrs) {
    var parts = [blockType || 'block'];
    for (var k in attrs) if (attrs.hasOwnProperty(k)) parts.push(k + ': ' + attrs[k]);
    return parts.join('  ·  ');
  }

  function makeVerse(runs) {
    var v = document.createElement('div');
    v.className = 'wb-verse';
    appendInline(v, runs || []);            // appendInline adds a <br> when empty
    return v;
  }

  function renderPoem(b) {
    var el = document.createElement('div');
    el.className = 'wb wb-poem'; el.dataset.block = 'poem';
    // title is edited inline; any other attrs ride along on data-attrs
    var other = {};
    for (var k in (b.attrs || {}))
      if (b.attrs.hasOwnProperty(k) && k !== 'title') other[k] = b.attrs[k];
    el.dataset.attrs = JSON.stringify(other);

    var title = document.createElement('div');
    title.className = 'wb-poem-title'; title.dataset.poem = 'title';
    title.textContent = (b.attrs && b.attrs.title) || '';
    if (!title.textContent) title.appendChild(document.createElement('br'));
    el.appendChild(title);

    var body = document.createElement('div');
    body.className = 'wb-poem-body'; body.dataset.poem = 'body';
    (b.children || []).forEach(function (stanza, si) {
      if (si > 0) body.appendChild(makeVerse(null));   // empty verse = stanza break
      (stanza.lines || []).forEach(function (ln) { body.appendChild(makeVerse(ln.runs)); });
    });
    if (!body.firstChild) body.appendChild(makeVerse(null));
    el.appendChild(body);
    return el;
  }

  function renderBlock(b) {
    var el;
    if (b.type === 'chapter') {
      el = document.createElement('h1');
      el.className = 'wb wb-chapter'; el.dataset.block = 'chapter';
      el.textContent = b.title || '';
      // Byline rides on a data-attr (shown under the title via CSS ::after) and
      // round-trips through read(); its text is edited in Markdown mode, like
      // doc-block metadata. Kept out of textContent so title stays clean.
      if (b.byline) el.dataset.byline = b.byline;
      if (!el.textContent) el.appendChild(document.createElement('br'));
    } else if (b.type === 'part') {
      el = document.createElement('h2');
      el.className = 'wb wb-part'; el.dataset.block = 'part';
      el.textContent = b.title || '';
      if (!el.textContent) el.appendChild(document.createElement('br'));
    } else if (b.type === 'subhead') {
      el = document.createElement('p');
      el.className = 'wb wb-subhead'; el.dataset.block = 'subhead';
      appendInline(el, b.runs);
    } else if (b.type === 'para') {
      el = document.createElement('p');
      el.className = 'wb wb-para'; el.dataset.block = 'para';
      appendInline(el, b.runs);
    } else if (b.type === 'scene') {
      el = document.createElement('div');
      el.className = 'wb wb-scene'; el.dataset.block = 'scene';
      el.setAttribute('contenteditable', 'false');
      el.textContent = '* * *';
    } else if (b.type === 'docblock' && b.block_type === 'poem') {
      el = renderPoem(b);
    } else if (b.type === 'docblock') {
      el = document.createElement('div');
      el.className = 'wb wb-doc'; el.dataset.block = 'docblock';
      el.dataset.btype = b.block_type || '';
      el.dataset.attrs = JSON.stringify(b.attrs || {});
      var head = document.createElement('div');
      head.className = 'wb-doc-head';
      head.setAttribute('contenteditable', 'false');
      head.textContent = docHeadLabel(b.block_type, b.attrs || {});
      el.appendChild(head);
      var body = document.createElement('div');
      body.className = 'wb-doc-body';
      (b.children || []).forEach(function (kid) {
        var p = document.createElement('p');
        p.className = 'wb-doc-para'; p.dataset.block = 'para';
        appendInline(p, kid.runs);
        body.appendChild(p);
      });
      el.appendChild(body);
    } else {
      el = document.createElement('p');
      el.className = 'wb wb-para'; el.dataset.block = 'para';
      appendInline(el, []);
    }
    return el;
  }

  function render(blocks) {
    var frag = document.createDocumentFragment();
    (blocks || []).forEach(function (b) { frag.appendChild(renderBlock(b)); });
    return frag;
  }

  // ---- DOM -> model ---------------------------------------------------------

  function isBoldEl(el) {
    var t = el.tagName;
    if (t === 'B' || t === 'STRONG') return true;
    var w = el.style && el.style.fontWeight;
    return w === 'bold' || w === 'bolder' || (/^\d+$/.test(w) && parseInt(w, 10) >= 600);
  }
  function isItalicEl(el) {
    var t = el.tagName;
    if (t === 'I' || t === 'EM') return true;
    return el.style && el.style.fontStyle === 'italic';
  }

  function collectRuns(node, bold, italic, runs) {
    node.childNodes.forEach(function (child) {
      if (child.nodeType === 3) {                       // text
        if (child.data) runs.push({ text: child.data, bold: bold, italic: italic });
      } else if (child.nodeType === 1) {                // element
        if (child.tagName === 'BR') return;             // soft breaks -> ignored
        collectRuns(child, bold || isBoldEl(child), italic || isItalicEl(child), runs);
      }
    });
  }

  function coalesce(runs) {
    var out = [];
    runs.forEach(function (r) {
      var last = out[out.length - 1];
      if (last && last.bold === r.bold && last.italic === r.italic) last.text += r.text;
      else out.push({ text: r.text, bold: r.bold, italic: r.italic });
    });
    return out.filter(function (r) { return r.text !== ''; });
  }

  function readInline(el) {
    var runs = [];
    collectRuns(el, false, false, runs);
    return coalesce(runs);
  }

  function titleOrNull(el) {
    var t = (el.textContent || '').trim();
    return t || null;
  }

  function blockTypeOf(el) {
    if (el.dataset && el.dataset.block) return el.dataset.block;
    var t = el.tagName;
    if (t === 'H1') return 'chapter';
    if (t === 'H2') return 'subhead';
    return 'para';                                       // P, DIV, or anything else
  }

  function readPoem(el) {
    var attrs = {};
    var titleEl = el.querySelector('.wb-poem-title');
    var title = titleEl ? (titleEl.textContent || '').trim() : '';
    if (title) attrs.title = title;                      // title first (attr order)
    var other = {};
    try { other = JSON.parse(el.dataset.attrs || '{}'); } catch (e) { other = {}; }
    for (var k in other) if (other.hasOwnProperty(k) && k !== 'title') attrs[k] = other[k];

    var body = el.querySelector('.wb-poem-body');
    var stanzas = [], cur = [];
    if (body) {
      Array.prototype.forEach.call(body.querySelectorAll('.wb-verse'), function (v) {
        var runs = readInline(v);
        if (!runs.length) {                              // empty verse = stanza break
          if (cur.length) { stanzas.push({ type: 'stanza', lines: cur }); cur = []; }
        } else {
          cur.push({ runs: runs });
        }
      });
    }
    if (cur.length) stanzas.push({ type: 'stanza', lines: cur });
    return { type: 'docblock', block_type: 'poem', attrs: attrs, children: stanzas };
  }

  function readBlockEl(el) {
    var type = blockTypeOf(el);
    if (type === 'chapter') return { type: 'chapter', title: titleOrNull(el),
                                     byline: (el.dataset && el.dataset.byline) || null };
    if (type === 'part')    return { type: 'part', title: titleOrNull(el) };
    if (type === 'subhead') return { type: 'subhead', runs: readInline(el) };
    if (type === 'scene')   return { type: 'scene' };
    if (type === 'poem')    return readPoem(el);
    if (type === 'docblock') {
      var attrs = {};
      try { attrs = JSON.parse(el.dataset.attrs || '{}'); } catch (e) { attrs = {}; }
      var body = el.querySelector('.wb-doc-body');
      var kids = [];
      if (body) {
        Array.prototype.forEach.call(body.children, function (p) {
          kids.push({ type: 'para', runs: readInline(p) });
        });
      }
      return { type: 'docblock', block_type: el.dataset.btype || '', attrs: attrs, children: kids };
    }
    return { type: 'para', runs: readInline(el) };       // default
  }

  function read(root) {
    var blocks = [];
    Array.prototype.forEach.call(root.children, function (el) {
      // skip stray empty text-only wrappers the browser may leave behind
      var b = readBlockEl(el);
      if (b.type === 'para' || b.type === 'subhead') {
        if (!b.runs.length) return;                      // drop truly empty paragraphs
      }
      blocks.push(b);
    });
    return blocks;
  }

  global.WYS = { render: render, read: read, renderBlock: renderBlock, readInline: readInline };
})(typeof window !== 'undefined' ? window : this);
