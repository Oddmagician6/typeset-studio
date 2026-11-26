/* Editor document model <-> canonical Markdown, client side.
 *
 * A faithful port of doc_model.py in its smartquotes=False mode (the manuscript
 * editor stores raw source, so no smart-quote normalization here). Kept in lockstep
 * with the Python by test_doc_model_js.html, which round-trips the same corpus and
 * compares serializations against Python-generated expectations.
 *
 * Public API (global `DocModel`):
 *     DocModel.fromMarkdown(raw)  -> [block, ...]
 *     DocModel.toMarkdown(blocks) -> string
 *
 * Block / run schema matches doc_model.py exactly:
 *     {type:"chapter",  title:str|null, byline:str|null, tagline:str (only when set)}
 *     {type:"part",     title:str|null}
 *     {type:"subhead",  runs:[run,...], level:3|4 (only on ### / ####)}
 *     {type:"para",     runs:[run,...]}
 *     {type:"scene"}
 *     {type:"docblock", block_type:str, attrs:{k:v}, children:[para,...]}
 *     run = {text:str, bold:bool, italic:bool, link:str}
 *     note run = {..., text:label, note:true}   -- an endnote reference `[^label]`
 *     index run = {..., text:term, index:true}  -- an index marker `{index: term}`
 *     anchor run = {..., text:name, anchor:true}   -- a link target `{#name}`
 *     pageref run = {..., text:name, pageref:true} -- a page reference `{page: name}`
 */
(function (global) {
  'use strict';

  // ---- block-level patterns (mirror manuscript.py) -------------------------
  // Fenced blocks whose content is line-oriented — one source line per item /
  // per line / per table row, not wrapped into a paragraph. A table's `|` cell
  // separators are ordinary text at this level; only the two builders split on
  // them. Mirrors manuscript.LINE_BLOCKS.
  var LINE_BLOCKS = ['list', 'center', 'centre', 'right', 'left', 'table', 'statblock'];
  // A link target is restricted to unambiguous forms, so ordinary prose like
  // "[sic](ibid)" never becomes a link. Mirrors manuscript.LINK_RE.
  var LINK_RE = /\[([^\[\]]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+|#[A-Za-z0-9][\p{L}\p{N}_\-]*)\)/gu;
  // `[^label]: …` — an endnote's text. Kept as a plain paragraph here, but it
  // must start a new one. Mirrors manuscript.NOTE_DEF_RE.
  var NOTE_DEF_RE = /^\s*\[\^([\p{L}\p{N}_\-]+)\]:\s*(.*)$/u;
  // `[^label]` — an endnote reference. Mirrors manuscript.NOTE_REF_RE.
  var NOTE_REF_RE = /\[\^([\p{L}\p{N}_\-]+)\]/gu;
  // `{index: term}` — an index marker. Mirrors manuscript.INDEX_RE.
  var INDEX_RE = /\{index:[ \t]*([^{}\[\]\x00-\x08]*[^{}\[\]\s\x00-\x08])[ \t]*\}/g;
  // `{#name}` and `{page: name}` — a link target and a page reference (#74
  // Phase 5b). Mirror manuscript.ANCHOR_RE / PAGE_RE.
  var ANCHOR_RE = /\{#([A-Za-z0-9][\p{L}\p{N}_\-]*)\}/gu;
  var PAGE_RE = /\{page:[ \t]*#?([A-Za-z0-9][\p{L}\p{N}_\-]*)[ \t]*\}/gu;
  var SCENE_BREAK_RE = /^\s*(\*\s*\*\s*\*|\*{3,}|-{3,}|#{3,})\s*$/;
  var CHAPTER_RE     = /^#\s+(.*)$/;
  // `#* Prologue` — a chapter that takes no number. Mirrors manuscript.UNNUMBERED_RE.
  var UNNUMBERED_RE  = /^#\*\s+(.*)$/;
  var SUBHEAD_RE     = /^##\s+(.*)$/;
  // `###` / `####` — section and sub-section (mirror manuscript.SECTION_RE /
  // SUBSECTION_RE); a bare `###` is a scene break, matched first.
  var SECTION_RE     = /^###\s+(.*)$/;
  var SUBSECTION_RE  = /^####\s+(.*)$/;
  // `#> …` — the tagline under a chapter title, only on the line after `# Title`.
  // Mirrors manuscript.TAGLINE_RE.
  var TAGLINE_RE     = /^#>\s+(.*)$/;
  var DOCBLOCK_RE    = /^\s*~~~(.*)/;
  var PART_RE        = /^\s*===\s*(.*)/;
  // straight or curly quotes (pasted from a word processor); mirrors manuscript._ATTR_RE
  // A value may hold quotes (a poem titled `The "Blue" Hour`): it ends at the
  // quote followed by the next `key="` or the end; else at its first quote.
  var ATTR_RE        = /([\p{L}\p{N}_]+)=["“”]((?:(?!\s[\p{L}\p{N}_]+=["“”]).)*?)["“”](?=\s+[\p{L}\p{N}_]+=["“”]|\s*$)|([\p{L}\p{N}_]+)=["“”]([^"“”]*)["“”]/gu;
  var BYLINE_SEP     = ' | ';   // "# Title | Author" anthology byline (mirror manuscript.py)

  function splitByline(titleLine) {
    // "The Lottery | Shirley Jackson" -> {title, byline}; no separator -> byline null.
    if (titleLine == null) return { title: null, byline: null };
    var i = titleLine.indexOf(BYLINE_SEP);
    if (i !== -1) {
      var title = titleLine.slice(0, i).trim();
      var byline = titleLine.slice(i + BYLINE_SEP.length).trim();
      return { title: title || null, byline: byline || null };
    }
    return { title: titleLine.trim() || null, byline: null };
  }

  // ---- inline emphasis patterns (mirror doc_model.py; bold-italic, then bold,
  // then italic). ***both*** is one run carrying both flags.
  var BOLDITAL_RE     = /\*\*\*(?!\s)(.+?)(?<!\s)\*\*\*|___(?!\s)(.+?)(?<!\s)___/g;
  var BOLD_RE         = /\*\*(.+?)\*\*/g;
  var ITALIC_STAR_RE  = /(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g;
  var ITALIC_UNDER_RE = /_(?!\s)(.+?)(?<!\s)_/g;

  // ---- escape layer (private-use codepoints, same scheme as Python) --------
  var BSL = '\\';
  var PARK_STAR = '', PARK_UNDER = '', PARK_BSL = '', PARK_BRK = '';
  var PARK_NOTE = '';      // stands in for one `[^label]` during emphasis
  var PARK_BRACE = '\uE005';
  var PARK_INDEX = '\uE006';   // stands in for one `{index: term}` likewise
  var PARK_ANCHOR = '', PARK_PAGE = '';   // one `{#name}`, one `{page: name}`
  var MARK_SPLIT = new RegExp('([' + PARK_NOTE + PARK_INDEX + PARK_ANCHOR + PARK_PAGE + '])');
  // a literal `{index:`, `{#` or `{page:` escaped, so it reads back as text
  function escapeMarks(text) {
    return text.split('{index:').join(BSL + '{index:')
               .split('{#').join(BSL + '{#')
               .split('{page:').join(BSL + '{page:');
  }

  function parkEscapes(text) {
    return text.split(BSL + BSL).join(PARK_BSL)   // \\ -> literal backslash
               .split(BSL + '*').join(PARK_STAR)  // \* -> literal *
               .split(BSL + '_').join(PARK_UNDER)  // \_ -> literal _
               .split(BSL + '[').join(PARK_BRK)    // \[ -> literal [
               .split(BSL + '{').join(PARK_BRACE); // \{ -> literal {
  }
  function restoreEscapes(text) {
    return text.split(PARK_STAR).join('*')
               .split(PARK_UNDER).join('_')
               .split(PARK_BRK).join('[')
               .split(PARK_BRACE).join('{')
               .split(PARK_BSL).join(BSL);
  }
  function escapeAll(text) {
    return escapeMarks(text.split(BSL).join(BSL + BSL)
               .split('*').join(BSL + '*')
               .split('_').join(BSL + '_')
               .split('[').join(BSL + '['));
  }

  function run(text, bold, italic, link) {
    return { text: text, bold: !!bold, italic: !!italic, link: link || '' };
  }
  // An endnote reference: a run of its own, so a literal `\[^label]` (a plain run
  // reading "[^label]") can never be mistaken for one. `note` is only present on
  // note runs, matching doc_model.py.
  function noteRun(label, bold, italic) {
    return { text: label, bold: !!bold, italic: !!italic, link: '', note: true };
  }
  // An index marker `{index: term}`: a run of its own for the same reason. It
  // prints nothing; `text` is the term as written. Matches doc_model.py.
  function indexRun(term, bold, italic) {
    return { text: term, bold: !!bold, italic: !!italic, link: '', index: true };
  }
  // A link target `{#name}` and a page reference `{page: name}`: runs of their
  // own likewise. Match doc_model.py.
  function anchorRun(name, bold, italic) {
    return { text: name, bold: !!bold, italic: !!italic, link: '', anchor: true };
  }
  function pagerefRun(name, bold, italic) {
    return { text: name, bold: !!bold, italic: !!italic, link: '', pageref: true };
  }
  function isMark(r) { return !!(r.note || r.index || r.anchor || r.pageref); }
  function copyRun(r) {
    var c = { text: r.text, bold: r.bold, italic: r.italic, link: r.link || '' };
    if (r.note) c.note = true;
    if (r.index) c.index = true;
    if (r.anchor) c.anchor = true;
    if (r.pageref) c.pageref = true;
    return c;
  }

  // ---- inline: markdown <-> runs -------------------------------------------

  function eachMatch(re, str, fn) {
    re.lastIndex = 0;
    var m;
    while ((m = re.exec(str)) !== null) {
      fn(m);
      if (m.index === re.lastIndex) re.lastIndex++;  // guard zero-width
    }
  }

  function splitBySpans(str, re) {
    // returns [{hit:bool, text:str}, ...] carving out regex group-1 spans
    var out = [], pos = 0;
    eachMatch(re, str, function (m) {
      if (m.index > pos) out.push({ hit: false, text: str.slice(pos, m.index) });
      // m[2] is the second alternative's group (BOLDITAL_RE's ___ form)
      out.push({ hit: true, text: m[1] !== undefined ? m[1] : m[2] });
      pos = m.index + m[0].length;
    });
    if (pos < str.length) out.push({ hit: false, text: str.slice(pos) });
    return out;
  }

  function splitItalics(seg) {
    // *...* first, then _..._ inside still-plain pieces
    var out = [];
    splitBySpans(seg, ITALIC_STAR_RE).forEach(function (p) {
      if (p.hit) { out.push({ italic: true, text: p.text }); return; }
      splitBySpans(p.text, ITALIC_UNDER_RE).forEach(function (q) {
        out.push({ italic: q.hit, text: q.text });
      });
    });
    return out;
  }

  function coalesce(runs) {
    var out = [];
    runs.forEach(function (r) {
      var last = out[out.length - 1];
      if (last && last.bold === r.bold && last.italic === r.italic
          && (last.link || '') === (r.link || '')
          && !isMark(last) && !isMark(r)) last.text += r.text;
      else out.push(copyRun(r));
    });
    return out.filter(function (r) { return r.text !== ''; });
  }

  function emphasisRuns(text) {
    var runs = [];
    // ***both*** is carved out first, so the ** pass cannot claim the first two
    // stars of a *** marker and strand the third as literal text.
    splitBySpans(text, BOLDITAL_RE).forEach(function (outer) {
      if (outer.hit) { runs.push(run(outer.text, true, true)); return; }
      splitBySpans(outer.text, BOLD_RE).forEach(function (seg) {
        if (seg.hit) { runs.push(run(seg.text, true, false)); return; }
        splitItalics(seg.text).forEach(function (it) {
          if (it.text) runs.push(run(it.text, false, it.italic));
        });
      });
    });
    runs = coalesce(runs);
    runs.forEach(function (r) { r.text = restoreEscapes(r.text); });
    return runs;
  }

  // Links are carved out before the emphasis passes: a target may contain _ or *.
  function parseInline(text) {
    text = parkEscapes(text);
    var out = [], pos = 0;
    eachMatch(LINK_RE, text, function (m) {
      if (m.index > pos) out = out.concat(noteRuns(text.slice(pos, m.index)));
      var target = restoreEscapes(m[2]);
      // a link's words can be indexed (a note can't sit there: no brackets)
      noteRuns(m[1]).forEach(function (r) { r.link = target; out.push(r); });
      pos = m.index + m[0].length;
    });
    if (pos < text.length) out = out.concat(noteRuns(text.slice(pos)));
    return coalesce(out);
  }

  // Emphasis runs for a link-free stretch, with its note references split out.
  // References are swapped for a placeholder first — what the engine does with
  // its own marker — so one inside **bold** comes out as a bold note run.
  // Index markers are split out the same way.
  function noteRuns(text) {
    var labels = [], terms = [], anchors = [], pages = [];
    text = text.replace(NOTE_REF_RE, function (_, label) { labels.push(label); return PARK_NOTE; });
    text = text.replace(INDEX_RE, function (_, term) { terms.push(term); return PARK_INDEX; });
    text = text.replace(ANCHOR_RE, function (_, name) { anchors.push(name); return PARK_ANCHOR; });
    text = text.replace(PAGE_RE, function (_, name) { pages.push(name); return PARK_PAGE; });
    if (!labels.length && !terms.length && !anchors.length && !pages.length) return emphasisRuns(text);
    var out = [], q = 0, t = 0, a = 0, p = 0;
    emphasisRuns(text).forEach(function (r) {
      r.text.split(MARK_SPLIT).forEach(function (piece) {
        if (piece === PARK_NOTE) out.push(noteRun(labels[q++], r.bold, r.italic));
        else if (piece === PARK_INDEX) out.push(indexRun(restoreEscapes(terms[t++]), r.bold, r.italic));
        else if (piece === PARK_ANCHOR) out.push(anchorRun(anchors[a++], r.bold, r.italic));
        else if (piece === PARK_PAGE) out.push(pagerefRun(pages[p++], r.bold, r.italic));
        else if (piece) out.push({ text: piece, bold: r.bold, italic: r.italic, link: r.link || '' });
      });
    });
    return out;
  }

  // Runs sharing one emphasis are written as a single span. They only sit side
  // by side when a note reference splits them, and `**a**` + `**[^n]**` would join
  // into `**a****[^n]**`, which does not read back. A reference is written bare.
  // Other spellings of italic and bold-italic, for when the usual ones collide
  // with a neighbour: `*red*` + `**blue**` writes `*red***blue**`, which reads
  // back wrong; `_red_**blue**` doesn't. Mirrors doc_model._ALT_MARKS.
  var ALT_MARKS = [{}, { bi: '___', i: '_' }, { bi: '___' }, { i: '_' }];

  function emphMd(group, forceEscape, marks) {
    var g = group[0];
    marks = marks || {};
    var mark = g.bold && g.italic ? (marks.bi || '***') : g.bold ? '**'
             : g.italic ? (marks.i || '*') : '';
    return mark + group.map(function (r) {
      if (r.note) return '[^' + r.text + ']';
      // the term is written bare, but for the three characters that would end it early
      if (r.index) return '{index: ' + r.text.split(BSL).join(BSL + BSL)
                            .split('{').join(BSL + '{').split('[').join(BSL + '[') + '}';
      if (r.anchor) return '{#' + r.text + '}';          // a name: nothing to escape
      if (r.pageref) return '{page: ' + r.text + '}';
      return (mark || forceEscape) ? escapeAll(r.text) : escapePlain(r.text);
    }).join('') + mark;
  }

  function emitRuns(runs, forceEscape, marks) {
    var parts = [], i = 0;
    while (i < runs.length) {
      var link = runs[i].link || '', j = i;
      while (j < runs.length && (runs[j].link || '') === link) j++;
      var inner = [], k = i;
      while (k < j) {                       // one span per emphasis
        var m = k;
        while (m < j && runs[m].bold === runs[k].bold && runs[m].italic === runs[k].italic) m++;
        inner.push(emphMd(runs.slice(k, m), forceEscape, marks));
        k = m;
      }
      parts.push(link ? '[' + inner.join('') + '](' + link + ')' : inner.join(''));
      i = j;
    }
    return parts.join('');
  }

  // escapePlain only asks whether a run survives a parse on its own, which is not
  // enough: a plain "*" next to an italic "*y*" joins into "**y*" and re-reads as
  // bold. Check the assembled line, and re-emit fully escaped if it drifted.
  // Escaping can't help two emphasis spans whose markers run together, so each
  // other spelling of the markers is tried in turn too.
  function runsToMd(runs) {
    var want = coalesce(runs.map(copyRun));
    for (var a = 0; a < ALT_MARKS.length; a++) {
      for (var f = 0; f < 2; f++) {
        var md = emitRuns(runs, !!f, ALT_MARKS[a]);
        if (sameRuns(parseInline(md), want)) return md;
      }
    }
    return emitRuns(runs, true);
  }

  // A table row's runs, a cell at a time: the typesetter splits a row on `|`
  // before it reads emphasis, and read whole `a_b | c_d` came back `a*b | c*d`.
  // Mirrors doc_model._table_row / _table_row_md.
  function tableRow(text) {
    var runs = [];
    text.split('|').forEach(function (cell, i) {
      if (i) runs.push(run('|'));
      runs = runs.concat(parseInline(cell));
    });
    return coalesce(runs);
  }
  function tableRowMd(runs) {
    var cells = [[]];
    runs.forEach(function (r) {
      if (isMark(r)) { cells[cells.length - 1].push(r); return; }
      r.text.split('|').forEach(function (piece, j) {
        if (j) cells.push([]);
        if (piece) { var c = copyRun(r); c.text = piece; cells[cells.length - 1].push(c); }
      });
    });
    return cells.map(runsToMd).join('|');
  }
  // A line inside a fenced block, guarded if it would read as a fence: `\~~~`
  // is text, where a bare `~~~` closed the block early. Mirrors doc_model._in_block.
  // guarded when it would end the block: a fence, or a `# ` chapter heading
  // (not a stat block's first line, where `# Name` is its name)
  function inBlockLine(line, nameOk) {
    return DOCBLOCK_RE.test(line) || (!nameOk && CHAPTER_RE.test(line)) ? BSL + line : line;
  }

  function sameRuns(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i].text !== b[i].text || a[i].bold !== b[i].bold || a[i].italic !== b[i].italic
          || (a[i].link || '') !== (b[i].link || '') || !a[i].note !== !b[i].note
          || !a[i].index !== !b[i].index || !a[i].anchor !== !b[i].anchor
          || !a[i].pageref !== !b[i].pageref)
        return false;
    }
    return true;
  }

  function escapePlain(text) {
    // Escape only if the literal text would otherwise re-parse as emphasis.
    var escapedBsl = text.split(BSL).join(BSL + BSL);
    if (sameRuns(parseInline(escapedBsl), [run(text, false, false)])) return escapedBsl;
    return escapeMarks(escapedBsl.split('*').join(BSL + '*').split('_').join(BSL + '_')
                     .split('[').join(BSL + '['));
  }

  function isBlockLine(line) {
    return SCENE_BREAK_RE.test(line) || CHAPTER_RE.test(line) || UNNUMBERED_RE.test(line)
        || SUBHEAD_RE.test(line) || SECTION_RE.test(line) || SUBSECTION_RE.test(line)
        || TAGLINE_RE.test(line) || DOCBLOCK_RE.test(line) || PART_RE.test(line);
  }

  // [level, text] for a `##`, `###` or `####` line, else null (mirror
  // manuscript.heading_match)
  function headingMatch(line) {
    var rxs = [SUBHEAD_RE, SECTION_RE, SUBSECTION_RE];
    for (var i = 0; i < rxs.length; i++) {
      var m = rxs[i].exec(line);
      if (m) return [i + 2, m[1].trim()];
    }
    return null;
  }

  function parseBlockHeader(header) {
    var parts = header.trim().split(/\s+/);
    if (!header.trim()) return { blockType: '', attrs: {} };
    var blockType = parts[0].toLowerCase();
    var rest = header.trim().slice(parts[0].length);
    var attrs = {}, m;
    ATTR_RE.lastIndex = 0;
    while ((m = ATTR_RE.exec(rest)) !== null) {
      if (m[1] !== undefined) attrs[m[1]] = m[2]; else attrs[m[3]] = m[4];
    }
    return { blockType: blockType, attrs: attrs };
  }

  // ---- markdown -> document model ------------------------------------------

  function fromMarkdown(raw) {
    var lines = raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
    var blocks = [];
    var paraBuf = [];
    var inBlock = false, blockChildren = [], blockParaBuf = [], blockType = '', blockAttrs = {};

    function flushPara() {
      if (paraBuf.length) {
        var joined = paraBuf.map(function (s) { return s.trim(); }).join(' ').trim();
        if (joined) blocks.push({ type: 'para', runs: parseInline(joined) });
        paraBuf = [];
      }
    }
    function flushBlockPara() {
      if (blockParaBuf.length) {
        if (blockType === 'poem') {
          // Verse: each source line is a line; the group is one stanza.
          var lines = [];
          blockParaBuf.forEach(function (s) {
            if (s.trim()) lines.push({ runs: parseInline(s.trim()) });
          });
          if (lines.length) blockChildren.push({ type: 'stanza', lines: lines });
        } else if (blockType === 'statblock') {
          // A stat block's source is kept exactly as written, one plain run per
          // line (its `___` rules and `--- Actions` must survive an edit).
          // Its blank lines are kept too, one for a run of them (as doc_model):
          // they keep a names line apart from a values line.
          var prevBlank = true;
          blockParaBuf.forEach(function (s) {
            if (s.trim()) { blockChildren.push({ type: 'para', runs: [run(s.trim())] }); prevBlank = false; }
            else if (!prevBlank) { blockChildren.push({ type: 'para', runs: [] }); prevBlank = true; }
          });
          while (blockChildren.length && !blockChildren[blockChildren.length - 1].runs.length)
            blockChildren.pop();
        } else if (blockType === 'table') {
          blockParaBuf.forEach(function (s) {            // one row per line
            if (s.trim()) blockChildren.push({ type: 'para', runs: tableRow(s.trim()) });
          });
        } else if (LINE_BLOCKS.indexOf(blockType) !== -1) {
          // One line = one child (a list item, or a line of an aligned block)
          blockParaBuf.forEach(function (s) {
            if (s.trim()) blockChildren.push({ type: 'para', runs: parseInline(s.trim()) });
          });
        } else {
          var joined = blockParaBuf.map(function (s) { return s.trim(); }).join(' ').trim();
          if (joined) blockChildren.push({ type: 'para', runs: parseInline(joined) });
        }
        blockParaBuf = [];
      }
    }
    function closeBlock() {
      flushBlockPara();
      blocks.push({ type: 'docblock', block_type: blockType,
                    attrs: shallow(blockAttrs), children: blockChildren.slice() });
      blockChildren = []; blockType = ''; blockAttrs = {}; inBlock = false;
    }

    // closedAhead[i]: the first fence at or after line i is a bare closing
    // `~~~` (manuscript.closed_ahead): a `# ` line then is text in its block
    var closedAhead = new Array(lines.length), nextBare = false;
    for (var ck = lines.length - 1; ck >= 0; ck--) {
      var cm = DOCBLOCK_RE.exec(lines[ck]);
      if (cm) nextBare = !cm[1].trim();
      closedAhead[ck] = nextBare;
    }
    var tagOk = false;                 // the line after `# Title` may be `#> …`
    for (var li = 0; li < lines.length; li++) {
      var line = lines[li];

      if (tagOk && !inBlock && line.trim()) {
        tagOk = false;
        var mTag = TAGLINE_RE.exec(line);
        if (mTag) {
          if (mTag[1].trim()) blocks[blocks.length - 1].tagline = mTag[1].trim();
          continue;
        }
      }
      if (!inBlock && line.charAt(0) === BSL && isBlockLine(line.slice(1))) {
        paraBuf.push(line.slice(1));
        continue;
      }
      if (!inBlock) {
        var mPart = PART_RE.exec(line);
        if (mPart) {
          flushPara();
          blocks.push({ type: 'part', title: mPart[1].trim() || null });
          continue;
        }
      }
      var mDoc = DOCBLOCK_RE.exec(line);
      // an opening fence inside a block: its ~~~ is missing (as manuscript)
      if (mDoc && inBlock && mDoc[1].trim()) closeBlock();
      // a chapter heading inside a block likewise, but for a stat block's `# Name`
      if (!mDoc && inBlock && CHAPTER_RE.test(line) && !closedAhead[li] && !(blockType === 'statblock'
          && !blockParaBuf.some(function (s) { return s.trim(); }))) closeBlock();
      if (mDoc) {
        if (inBlock) { closeBlock(); }
        else {
          flushPara();
          var hdr = parseBlockHeader(mDoc[1]);
          blockType = hdr.blockType; blockAttrs = hdr.attrs; inBlock = true;
        }
        continue;
      }
      if (inBlock) {
        // `\~~~` is a line of text (inBlockLine)
        if (line.charAt(0) === BSL && (DOCBLOCK_RE.test(line.slice(1))
            || CHAPTER_RE.test(line.slice(1)))) line = line.slice(1);
        if (line.trim() === '' && blockType !== 'statblock') flushBlockPara();
        else blockParaBuf.push(line);
        continue;
      }
      var mUn = UNNUMBERED_RE.exec(line);
      var mCh = mUn || CHAPTER_RE.exec(line), mSub = headingMatch(line);
      if (mCh) {
        flushPara();
        var sb = splitByline(mCh[1]);
        var chBlock = { type: 'chapter', title: sb.title, byline: sb.byline };
        if (mUn) chBlock.unnumbered = true;   // only carried when set
        blocks.push(chBlock);
        tagOk = true;
        continue;
      }
      if (SCENE_BREAK_RE.test(line)) { flushPara(); blocks.push({ type: 'scene' }); continue; }
      if (mSub) {
        flushPara();
        var sh = { type: 'subhead', runs: parseInline(mSub[1]) };
        if (mSub[0] > 2) sh.level = mSub[0];   // only carried when not `##`
        blocks.push(sh);
        continue;
      }
      if (line.trim() === '') flushPara();
      else {
        // a note definition must not merge with the line above it
        if (NOTE_DEF_RE.test(line)) flushPara();
        paraBuf.push(line);
      }
    }
    if (inBlock) closeBlock();
    flushPara();
    return blocks;
  }

  function shallow(o) { var r = {}; for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) r[k] = o[k]; return r; }

  // ---- document model -> markdown ------------------------------------------

  // A stat block line back to its source: plain runs are the source text itself,
  // written with no escaping; emphasis put on by the editor is written as markers.
  // Mirrors doc_model._statblock_line.
  function statblockLine(runs) {
    return runs.map(function (r) {
      // a note, index marker, anchor or page reference is written as its
      // marker: its text alone is only the label
      // a link is written [label](address) (as doc_model): its label alone lost it
      var text = (r.bold || r.italic || isMark(r)) ? emphMd([r], false) : r.text;
      return r.link ? '[' + text + '](' + r.link + ')' : text;
    }).join('');
  }

  function toMarkdown(blocks) {
    var out = [];
    blocks.forEach(function (b) {
      if (b.type === 'chapter') {
        var title = b.title || '';
        var mark = b.unnumbered ? '#* ' : '# ';
        if (title && b.byline) out.push(mark + title + BYLINE_SEP + b.byline);
        else out.push(mark + title);
        if (b.tagline) out.push('#> ' + b.tagline);
      } else if (b.type === 'part') {
        out.push('=== ' + (b.title || ''));
      } else if (b.type === 'subhead') {
        out.push(new Array((b.level || 2) + 1).join('#') + ' ' + runsToMd(b.runs));
      } else if (b.type === 'para') {
        var line = runsToMd(b.runs);
        if (isBlockLine(line)) line = BSL + line;
        out.push(line);
      } else if (b.type === 'scene') {
        out.push('* * *');
      } else if (b.type === 'docblock') {
        var header = '~~~';
        if (b.block_type) {
          header += ' ' + b.block_type;
          for (var k in b.attrs) if (Object.prototype.hasOwnProperty.call(b.attrs, k)) header += ' ' + k + '="' + b.attrs[k] + '"';
        }
        out.push(header);
        var kids = b.children || [];
        if (b.block_type === 'poem') {
          for (var si = 0; si < kids.length; si++) {     // stanzas of verse lines
            if (si > 0) out.push('');                    // blank line between stanzas
            kids[si].lines.forEach(function (ln) { out.push(inBlockLine(runsToMd(ln.runs))); });
          }
        } else if (b.block_type === 'statblock') {
          for (var sl = 0; sl < kids.length; sl++)
            out.push(inBlockLine(statblockLine(kids[sl].runs), sl === 0));
        } else if (b.block_type === 'table') {
          for (var tr = 0; tr < kids.length; tr++) out.push(inBlockLine(tableRowMd(kids[tr].runs)));
        } else if (LINE_BLOCKS.indexOf(b.block_type) !== -1) {
          for (var li = 0; li < kids.length; li++) out.push(inBlockLine(runsToMd(kids[li].runs)));
        } else {
          for (var i = 0; i < kids.length; i++) {
            out.push(inBlockLine(runsToMd(kids[i].runs)));
            if (i < kids.length - 1) out.push('');
          }
        }
        out.push('~~~');
      } else {
        throw new Error('unknown block type: ' + b.type);
      }
      out.push('');
    });
    return out.join('\n');
  }

  // ---- Homebrewery stat blocks pasted with no fence ------------------------
  // Mirrors statblock.wrap_unfenced: a `{{monster …}}` block (to its `}}`), or a
  // `___` line followed by `> ## Name` (to the last `>` line), is wrapped in a
  // `~~~ statblock` fence. Only the paste does this, never the parser: a `>`
  // line or a `___` rule in a novel must not become a stat block.
  var V3_OPEN_RE = /^\s*\{\{\s*monster\b/;
  var LEGACY_HEAD_RE = /^\s*>\s*##\s+\S/;
  var FENCE_RE = /^\s*~~~/;
  function wrapUnfenced(markdown) {
    var lines = markdown.split('\n'), out = [], i = 0, inFence = false, j;
    while (i < lines.length) {
      var line = lines[i];
      if (FENCE_RE.test(line)) { inFence = !inFence; out.push(line); i++; continue; }
      if (!inFence && V3_OPEN_RE.test(line)) {
        j = i + 1;
        // not past another monster's opening, a fence or a chapter heading
        // (as statblock.wrap_unfenced)
        while (j < lines.length && lines[j].trim() !== '}}' && !FENCE_RE.test(lines[j])
               && !V3_OPEN_RE.test(lines[j]) && !/^#\s/.test(lines[j])) j++;
        if (j < lines.length && lines[j].trim() === '}}') {
          out = out.concat(['~~~ statblock'], lines.slice(i, j + 1), ['~~~']);
          i = j + 1;
          continue;
        }
      }
      // the rule, then `> ## Name`: blank lines between them allowed (looked
      // for only after a rule: a long blank run was rescanned from every line)
      var isRule = !inFence && /^_{3,}$/.test(line.trim());
      var k = i + 1;
      while (isRule && k < lines.length && !lines[k].trim()) k++;
      if (isRule && k < lines.length && LEGACY_HEAD_RE.test(lines[k])) {
        j = k;
        while (j < lines.length && /^\s*>/.test(lines[j])) j++;
        out = out.concat(['~~~ statblock', line], lines.slice(k, j), ['~~~']);
        i = j;
        continue;
      }
      out.push(line);
      i++;
    }
    return out.join('\n');
  }

  global.DocModel = {
    fromMarkdown: fromMarkdown,
    toMarkdown: toMarkdown,
    wrapUnfenced: wrapUnfenced,
    // exposed for tests
    _parseInline: parseInline,
    _run: run,
    _noteRun: noteRun,
    _indexRun: indexRun
  };
})(typeof window !== 'undefined' ? window : this);
