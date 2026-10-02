/* WYSIWYG view: document model <-> contenteditable DOM.
 *
 * The pure, testable core of the rich editor. `render(blocks)` builds DOM for the
 * editable surface; `read(rootEl)` walks that surface back into the document model.
 * `read(render(model))` is the identity, so editing the DOM and reading it back never
 * corrupts structure -- and the model serializes to Markdown via DocModel
 * (doc_model.js), which the engine consumes. test_rich_editor.py checks both that
 * and real edits (Enter, Backspace, paste, the toolbar) in a headless browser.
 *
 * The editor stores raw Markdown as source of truth; this surface is a *view* the
 * template keeps synced into the textarea. Doc-block headers (type + attrs) are held
 * on data-attributes and not edited in place in this version -- their prose is
 * editable, their metadata is edited in Markdown mode. Everything round-trips losslessly.
 */
(function (global) {
  'use strict';

  // ---- model -> DOM ---------------------------------------------------------

  // An endnote reference is one uneditable superscript, so the writer can see it,
  // delete it whole, and can't type into the middle of its label. The label rides
  // on data-note; the text is only what shows.
  function noteEl(label) {
    var s = document.createElement('sup');
    s.className = 'wb-note';
    s.setAttribute('contenteditable', 'false');
    s.dataset.note = label;
    s.title = 'Endnote: ' + label;
    s.textContent = label;
    return s;
  }

  // A non-breaking space the manuscript really has (a Word import's U+00A0 in
  // "Mr. Smith") is wrapped in a marked span. The browser makes its own, for a typed space it
  // would otherwise collapse — after a note or a link, or a second space — and
  // those are read back as plain spaces; only a marked one survives as itself.
  var NBSP = '\u00a0';
  function textNode(text) {
    if (text.indexOf(NBSP) === -1) return document.createTextNode(text);
    var frag = document.createDocumentFragment();
    text.split(NBSP).forEach(function (piece, i) {
      if (i) {
        var s = document.createElement('span');
        s.className = 'wb-nbsp'; s.dataset.nbsp = '1'; s.textContent = NBSP;
        frag.appendChild(s);
      }
      if (piece) frag.appendChild(document.createTextNode(piece));
    });
    return frag;
  }

  function appendInline(el, runs) {
    (runs || []).forEach(function (r) {
      var node = r.note ? noteEl(r.text) : textNode(r.text);
      if (r.bold && r.italic) {
        var s = document.createElement('strong'), e = document.createElement('em');
        e.appendChild(node); s.appendChild(e); node = s;
      } else if (r.bold) {
        var b = document.createElement('strong'); b.appendChild(node); node = b;
      } else if (r.italic) {
        var i = document.createElement('em'); i.appendChild(node); node = i;
      }
      if (r.link) {                        // the link wraps whatever emphasis it has
        var a = document.createElement('a');
        a.setAttribute('href', r.link);
        a.appendChild(node);
        node = a;
      }
      el.appendChild(node);
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

  // A figure shows its actual image with an editable caption under it. Placement
  // attrs (src / alt / width / align / full) ride on data-attrs and are edited in
  // Markdown mode, like other doc-block metadata.
  function renderFigure(b) {
    var attrs = b.attrs || {};
    var el = document.createElement('div');
    el.className = 'wb wb-figure'; el.dataset.block = 'figure';
    el.dataset.attrs = JSON.stringify(attrs);

    var frame = document.createElement('div');
    frame.className = 'wb-figure-img';
    frame.setAttribute('contenteditable', 'false');
    var src = (attrs.src || '').trim();
    // only library images can be previewed; an absolute path isn't servable
    if (src && !/^([a-zA-Z]:[\\/]|[\\/])/.test(src)) {
      var img = document.createElement('img');
      img.src = '/figures/file/' + encodeURIComponent(src);
      img.alt = attrs.alt || src;
      img.onerror = function () {
        frame.textContent = 'missing image: ' + src;
        frame.className = 'wb-figure-img wb-figure-gone';
      };
      frame.appendChild(img);
    } else {
      frame.textContent = src ? src : 'no image chosen';
      frame.className = 'wb-figure-img wb-figure-gone';
    }
    el.appendChild(frame);

    var note = document.createElement('div');
    note.className = 'wb-figure-note';
    note.setAttribute('contenteditable', 'false');
    note.textContent = docHeadLabel('figure', attrs);
    el.appendChild(note);

    var cap = document.createElement('div');
    cap.className = 'wb-figure-cap'; cap.dataset.figure = 'caption';
    (b.children || []).forEach(function (kid) {
      var p = document.createElement('p');
      p.className = 'wb-figure-para'; p.dataset.block = 'para';
      appendInline(p, kid.runs);
      cap.appendChild(p);
    });
    if (!cap.firstChild) {
      var empty = document.createElement('p');
      empty.className = 'wb-figure-para'; empty.dataset.block = 'para';
      appendInline(empty, []);
      cap.appendChild(empty);
    }
    el.appendChild(cap);
    return el;
  }

  function readFigure(el) {
    var attrs = {};
    try { attrs = JSON.parse(el.dataset.attrs || '{}'); } catch (e) { attrs = {}; }
    var kids = [];
    var cap = el.querySelector('.wb-figure-cap');
    if (cap) {
      Array.prototype.forEach.call(cap.children, function (p) {
        var runs = readInline(p);
        if (runs.length) kids.push({ type: 'para', runs: runs });
      });
    }
    return { type: 'docblock', block_type: 'figure', attrs: attrs, children: kids };
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
      // `#* Prologue` takes no number; the flag rides along the same way
      if (b.unnumbered) el.dataset.unnumbered = 'yes';
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
    } else if (b.type === 'docblock' && b.block_type === 'figure') {
      el = renderFigure(b);
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

  // Emphasis an element sets, given what it sits in. An explicit style wins over
  // the tag: Google Docs wraps a whole paste in <b style="font-weight:normal">,
  // and reading the tag alone made every pasted word bold.
  function boldOf(el, inherited) {
    var w = el.style && el.style.fontWeight;
    if (w === 'normal' || w === 'lighter' || (/^\d+$/.test(w) && parseInt(w, 10) < 600))
      return false;
    if (w === 'bold' || w === 'bolder' || /^\d+$/.test(w)) return true;
    return inherited || el.tagName === 'B' || el.tagName === 'STRONG';
  }
  function italicOf(el, inherited) {
    var st = el.style && el.style.fontStyle;
    if (st === 'normal') return false;
    if (st === 'italic' || st === 'oblique') return true;
    return inherited || el.tagName === 'I' || el.tagName === 'EM';
  }

  // Only what the engine reads as a link is kept as one — mirrors
  // manuscript.LINK_TARGET. Anything else (a pasted "/relative" or "javascript:")
  // would be written as [text](target) and printed as those literal brackets.
  var LINK_TARGET_RE = /^(?:https?:\/\/[^\s)]+|mailto:[^\s)]+|#[A-Za-z0-9][\w\-]*)$/;

  // Anything a writing-aid extension (Grammarly, LanguageTool, ProWritingAid)
  // draws into the editor. They render their underlines and cards by injecting
  // custom elements — always hyphenated, per the custom-element rules — and
  // mark their own UI uneditable. The editor emits neither, so both are foreign
  // by definition: any text inside one is the extension talking, not the book,
  // and reading it back saved the suggestion into the manuscript.
  function isForeignEl(el) {
    return (el.tagName || '').indexOf('-') !== -1
        || el.getAttribute('contenteditable') === 'false';
  }

  function collectRuns(node, bold, italic, runs, link, keepNbsp) {
    node.childNodes.forEach(function (child) {
      if (child.nodeType === 3) {                       // text
        var text = keepNbsp ? child.data : child.data.split(NBSP).join(' ');
        if (text) runs.push({ text: text, bold: bold, italic: italic, link: link || '' });
      } else if (child.nodeType === 1) {                // element
        // A line break inside a paragraph (Shift+Enter, or pasted) is a space:
        // a paragraph is one line in the manuscript, and ignoring it glued the
        // last word of one line to the first of the next.
        if (child.tagName === 'BR') {
          runs.push({ text: ' ', bold: bold, italic: italic, link: link || '' });
          return;
        }
        if (child.dataset && child.dataset.note) {      // an endnote reference
          runs.push({ text: child.dataset.note, bold: bold, italic: italic,
                      link: '', note: true });
          return;
        }
        if (isForeignEl(child)) return;                 // an extension's own overlay
        var href = link || '';
        if (child.tagName === 'A') {
          var h = (child.getAttribute('href') || '').trim();
          if (LINK_TARGET_RE.test(h)) href = h;
        }
        collectRuns(child, boldOf(child, bold), italicOf(child, italic), runs, href,
                    keepNbsp || !!(child.dataset && child.dataset.nbsp));
      }
    });
  }

  function coalesce(runs) {
    var out = [];
    runs.forEach(function (r) {
      var last = out[out.length - 1];
      if (last && last.bold === r.bold && last.italic === r.italic
          && (last.link || '') === (r.link || '')
          && !last.note && !r.note) last.text += r.text;
      else {
        var c = { text: r.text, bold: r.bold, italic: r.italic, link: r.link || '' };
        if (r.note) c.note = true;
        out.push(c);
      }
    });
    return out.filter(function (r) { return r.text !== ''; });
  }

  // Typing the `]` that closes `[^label]` turns it into a reference, which is how
  // a note is added in rich mode. Only the text just typed is looked at, so a
  // literal "[^label]" already on the page (a `\[^label]` in the Markdown) stays
  // literal. Returns true if it made one.
  var TYPED_NOTE_RE = /\[\^([\w\-]+)\]$/;
  function noteInputRule(root) {
    var sel = root.ownerDocument.getSelection();
    if (!sel || !sel.rangeCount || !sel.isCollapsed) return false;
    var node = sel.anchorNode, off = sel.anchorOffset;
    if (!node || node.nodeType !== 3 || !root.contains(node)) return false;
    var m = TYPED_NOTE_RE.exec(node.data.slice(0, off));
    if (!m) return false;
    var after = node.splitText(off);                  // text after the caret
    node.data = node.data.slice(0, off - m[0].length);
    var sup = noteEl(m[1]);
    node.parentNode.insertBefore(sup, after);
    var r = root.ownerDocument.createRange();
    r.setStart(after, 0); r.collapse(true);
    sel.removeAllRanges(); sel.addRange(r);
    return true;
  }

  // A line never starts or ends with a space in the manuscript, so the edges are
  // trimmed — which is also what turns an empty line's placeholder <br> back
  // into nothing.
  function trimEdges(runs) {
    while (runs.length && !runs[0].note && !(runs[0].text = runs[0].text.replace(/^\s+/, '')))
      runs.shift();
    var n = runs.length - 1;
    while (n >= 0 && !runs[n].note && !(runs[n].text = runs[n].text.replace(/\s+$/, ''))) {
      runs.pop(); n--;
    }
    return runs;
  }

  function readInline(el) {
    var runs = [];
    collectRuns(el, false, false, runs, '', false);
    return trimEdges(coalesce(runs));
  }

  // ---- paste ---------------------------------------------------------------
  // The browser's own paste drops the source's markup in as-is: a Word or web
  // page's <div>s and <li>s read back as one paragraph with the words glued
  // together. So a paste is turned into blocks of runs here, by the same rules as
  // reading the page, and inserted as the editor's own elements.

  var PASTE_BLOCK_RE = /^(P|DIV|LI|UL|OL|H[1-6]|BLOCKQUOTE|PRE|TABLE|TBODY|THEAD|TR|DL|DT|DD|SECTION|ARTICLE|HEADER|FOOTER|FIGURE|FIGCAPTION|ASIDE|NAV|MAIN)$/;

  // [{runs:[...]}, {scene:true}, ...] from clipboard HTML, or from plain text when
  // there is none. Plain text follows the manuscript's own rule: a blank line
  // starts a paragraph, a single line break is a space.
  function pasteBlocks(html, text) {
    var blocks = [];
    if (html) {
      var doc = new DOMParser().parseFromString(html, 'text/html');
      Array.prototype.forEach.call(
        doc.querySelectorAll('style, script, meta, title, link, noscript, template'),
        function (n) { n.remove(); });
      var cur = [];
      var flush = function () {
        var runs = trimEdges(coalesce(cur));
        if (runs.length) blocks.push({ runs: runs });
        cur = [];
      };
      var walk = function (node, bold, italic, link, keepNbsp) {
        node.childNodes.forEach(function (child) {
          if (child.nodeType === 3) {
            // HTML whitespace: source line breaks and indentation are one space
            var t = child.data.replace(keepNbsp ? /[ \t\r\n\f]+/g : /\s+/g, ' ');
            if (t) cur.push({ text: t, bold: bold, italic: italic, link: link });
            return;
          }
          if (child.nodeType !== 1) return;
          if (child.tagName === 'BR') { cur.push({ text: ' ', bold: bold, italic: italic, link: link }); return; }
          if (child.dataset && child.dataset.note) {          // copied from this editor
            cur.push({ text: child.dataset.note, bold: bold, italic: italic, link: '', note: true });
            return;
          }
          if (child.dataset && child.dataset.block === 'scene') { flush(); blocks.push({ scene: true }); return; }
          if (isForeignEl(child)) return;
          var block = PASTE_BLOCK_RE.test(child.tagName);
          if (block) flush();
          var href = link;
          if (child.tagName === 'A') {
            var h = (child.getAttribute('href') || '').trim();
            if (LINK_TARGET_RE.test(h)) href = h;
          }
          walk(child, boldOf(child, bold), italicOf(child, italic), href,
               keepNbsp || !!(child.dataset && child.dataset.nbsp));
          if (block) flush();
        });
      };
      walk(doc.body, false, false, '', false);
      flush();
    }
    if (!blocks.length && text) {
      text.replace(/\r\n?/g, '\n').split(/\n\s*\n/).forEach(function (para) {
        var t = para.replace(/\s+/g, ' ').trim();
        if (t) blocks.push({ runs: [{ text: t, bold: false, italic: false, link: '' }] });
      });
    }
    // Every line was trimmed, but a copied word often carries a space at its
    // edge (a double-click takes the one after it), and dropping that glues the
    // word to its neighbour. The plain-text copy says whether there was one.
    var firstB = blocks[0], lastB = blocks[blocks.length - 1];
    if (text && firstB && firstB.runs && /^[ \t]/.test(text) && !firstB.runs[0].note)
      firstB.runs[0].text = ' ' + firstB.runs[0].text;
    if (text && lastB && lastB.runs && /[ \t]$/.test(text)) {
      var lr = lastB.runs[lastB.runs.length - 1];
      if (!lr.note) lr.text += ' ';
    }
    return blocks;
  }

  // The line a caret is on: a verse, a line of a block, a caption, a poem title,
  // or a top-level block of the page.
  function lineOf(root, node) {
    var n = node && node.nodeType === 3 ? node.parentNode : node;
    while (n && n !== root) {
      var c = n.classList;
      if (c && (c.contains('wb-verse') || c.contains('wb-doc-para') || c.contains('wb-figure-para')
                || c.contains('wb-poem-title'))) return n;
      if (n.parentNode === root) return n;
      n = n.parentNode;
    }
    return null;
  }

  // Insert pasted blocks at the caret. The first block joins the line the caret
  // is on, each further one becomes a new line of the same kind (a paragraph at
  // the top level, a verse in a poem, a line in a list), and whatever followed
  // the caret ends up after the last. Headings take plain text only — a title is
  // one line with no emphasis. Returns true if it inserted anything.
  function insertPaste(root, blocks) {
    var doc = root.ownerDocument, sel = doc.getSelection();
    if (!sel || !sel.rangeCount || !blocks.length) return false;
    if (!sel.isCollapsed) doc.execCommand('delete');   // replaces a selection, merging lines
    var range = sel.getRangeAt(0);
    var line = lineOf(root, range.startContainer);
    if (!line) return false;
    var c = line.classList, top = line.parentNode === root;
    var asText = c.contains('wb-chapter') || c.contains('wb-part') || c.contains('wb-poem-title');
    if (top && !(asText || c.contains('wb-para') || c.contains('wb-subhead'))) return false;

    if (asText) {
      var plain = blocks.filter(function (b) { return b.runs; }).map(function (b) {
        return b.runs.map(function (r) { return r.text; }).join('');
      }).join(' ');
      doc.execCommand('insertText', false, plain);
      return true;
    }
    if (!top) blocks = blocks.filter(function (b) { return b.runs; });  // no scene inside a block
    if (!blocks.length) return false;

    var tail = doc.createRange();
    tail.setStart(range.startContainer, range.startOffset);
    tail.setEnd(line, line.childNodes.length);
    var rest = tail.extractContents();
    if (line.childNodes.length === 1 && line.firstChild.nodeName === 'BR') line.innerHTML = '';

    var first = blocks[0].runs ? blocks.shift().runs : [];
    var frag = doc.createDocumentFragment();
    appendInline(frag, first);
    if (frag.lastChild && frag.lastChild.nodeName === 'BR') frag.removeChild(frag.lastChild);
    line.appendChild(frag);

    var last = line;
    blocks.forEach(function (b) {
      var el;
      if (b.scene) el = renderBlock({ type: 'scene' });
      else if (top) { el = renderBlock({ type: 'para', runs: b.runs }); }
      else { el = line.cloneNode(false); appendInline(el, b.runs); }
      last.after(el); last = el;
    });
    if (last.dataset && last.dataset.block === 'scene') {
      var p = renderBlock({ type: 'para', runs: [] }); last.after(p); last = p;
    }
    if (last !== line && last.childNodes.length === 1 && last.firstChild.nodeName === 'BR')
      last.innerHTML = '';
    var mark = doc.createTextNode('');                     // where the caret goes
    last.appendChild(mark);
    last.appendChild(rest);
    if (!last.childNodes.length || !last.textContent && !last.querySelector('sup'))
      last.appendChild(doc.createElement('br'));
    var r = doc.createRange(); r.setStart(mark, 0); r.collapse(true);
    sel.removeAllRanges(); sel.addRange(r);
    return true;
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
    if (type === 'chapter') {
      var ch = { type: 'chapter', title: titleOrNull(el),
                 byline: (el.dataset && el.dataset.byline) || null };
      if (el.dataset && el.dataset.unnumbered) ch.unnumbered = true;   // `#*`
      return ch;
    }
    if (type === 'part')    return { type: 'part', title: titleOrNull(el) };
    if (type === 'subhead') return { type: 'subhead', runs: readInline(el) };
    if (type === 'scene')   return { type: 'scene' };
    if (type === 'poem')    return readPoem(el);
    if (type === 'figure')  return readFigure(el);
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
      // An extension's overlay, not a block. Our own blocks are let through first:
      // a scene break is contenteditable="false" too, and skipping it saved the
      // book without a single one of its breaks.
      if (!(el.dataset && el.dataset.block) && isForeignEl(el)) return;
      // skip stray empty text-only wrappers the browser may leave behind
      var b = readBlockEl(el);
      if (b.type === 'para' || b.type === 'subhead') {
        if (!b.runs.length) return;                      // drop truly empty paragraphs
      }
      blocks.push(b);
    });
    return blocks;
  }

  global.WYS = { render: render, read: read, renderBlock: renderBlock, readInline: readInline,
                 noteInputRule: noteInputRule, pasteBlocks: pasteBlocks,
                 insertPaste: insertPaste, lineOf: lineOf };
})(typeof window !== 'undefined' ? window : this);
