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
 *     {type:"chapter",  title:str|null, byline:str|null}
 *     {type:"part",     title:str|null}
 *     {type:"subhead",  runs:[run,...]}
 *     {type:"para",     runs:[run,...]}
 *     {type:"scene"}
 *     {type:"docblock", block_type:str, attrs:{k:v}, children:[para,...]}
 *     run = {text:str, bold:bool, italic:bool}
 */
(function (global) {
  'use strict';

  // ---- block-level patterns (mirror manuscript.py) -------------------------
  // Fenced blocks whose content is line-oriented — one source line per item /
  // per line, not wrapped into a paragraph. Mirrors manuscript.LINE_BLOCKS.
  var LINE_BLOCKS = ['list', 'center', 'centre', 'right', 'left'];
  var SCENE_BREAK_RE = /^\s*(\*\s*\*\s*\*|\*{3,}|-{3,}|#{3,})\s*$/;
  var CHAPTER_RE     = /^#\s+(.*)$/;
  var SUBHEAD_RE     = /^##\s+(.*)$/;
  var DOCBLOCK_RE    = /^\s*~~~(.*)/;
  var PART_RE        = /^\s*===\s*(.*)/;
  var ATTR_RE        = /(\w+)="([^"]*)"/g;
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

  // ---- inline emphasis patterns (mirror doc_model.py; bold before italic) --
  var BOLD_RE         = /\*\*(.+?)\*\*/g;
  var ITALIC_STAR_RE  = /(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g;
  var ITALIC_UNDER_RE = /_(?!\s)(.+?)(?<!\s)_/g;

  // ---- escape layer (private-use codepoints, same scheme as Python) --------
  var BSL = '\\';
  var PARK_STAR = '', PARK_UNDER = '', PARK_BSL = '';

  function parkEscapes(text) {
    return text.split(BSL + BSL).join(PARK_BSL)   // \\ -> literal backslash
               .split(BSL + '*').join(PARK_STAR)  // \* -> literal *
               .split(BSL + '_').join(PARK_UNDER); // \_ -> literal _
  }
  function restoreEscapes(text) {
    return text.split(PARK_STAR).join('*')
               .split(PARK_UNDER).join('_')
               .split(PARK_BSL).join(BSL);
  }
  function escapeAll(text) {
    return text.split(BSL).join(BSL + BSL)
               .split('*').join(BSL + '*')
               .split('_').join(BSL + '_');
  }

  function run(text, bold, italic) {
    return { text: text, bold: !!bold, italic: !!italic };
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
      out.push({ hit: true, text: m[1] });
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
      if (last && last.bold === r.bold && last.italic === r.italic) last.text += r.text;
      else out.push({ text: r.text, bold: r.bold, italic: r.italic });
    });
    return out.filter(function (r) { return r.text !== ''; });
  }

  function parseInline(text) {
    text = parkEscapes(text);
    var runs = [];
    splitBySpans(text, BOLD_RE).forEach(function (seg) {
      if (seg.hit) { runs.push(run(seg.text, true, false)); return; }
      splitItalics(seg.text).forEach(function (it) {
        if (it.text) runs.push(run(it.text, false, it.italic));
      });
    });
    runs = coalesce(runs);
    runs.forEach(function (r) { r.text = restoreEscapes(r.text); });
    return runs;
  }

  function runsToMd(runs) {
    return runs.map(function (r) {
      if (r.bold)   return '**' + escapeAll(r.text) + '**';
      if (r.italic) return '*' + escapeAll(r.text) + '*';
      return escapePlain(r.text);
    }).join('');
  }

  function sameRuns(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i].text !== b[i].text || a[i].bold !== b[i].bold || a[i].italic !== b[i].italic)
        return false;
    }
    return true;
  }

  function escapePlain(text) {
    // Escape only if the literal text would otherwise re-parse as emphasis.
    var escapedBsl = text.split(BSL).join(BSL + BSL);
    if (sameRuns(parseInline(escapedBsl), [run(text, false, false)])) return escapedBsl;
    return escapedBsl.split('*').join(BSL + '*').split('_').join(BSL + '_');
  }

  function isBlockLine(line) {
    return SCENE_BREAK_RE.test(line) || CHAPTER_RE.test(line)
        || SUBHEAD_RE.test(line) || DOCBLOCK_RE.test(line) || PART_RE.test(line);
  }

  function parseBlockHeader(header) {
    var parts = header.trim().split(/\s+/);
    if (!header.trim()) return { blockType: '', attrs: {} };
    var blockType = parts[0].toLowerCase();
    var rest = header.trim().slice(parts[0].length);
    var attrs = {}, m;
    ATTR_RE.lastIndex = 0;
    while ((m = ATTR_RE.exec(rest)) !== null) attrs[m[1]] = m[2];
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

    for (var li = 0; li < lines.length; li++) {
      var line = lines[li];

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
        if (line.trim() === '') flushBlockPara();
        else blockParaBuf.push(line);
        continue;
      }
      var mCh = CHAPTER_RE.exec(line), mSub = SUBHEAD_RE.exec(line);
      if (mCh) {
        flushPara();
        var sb = splitByline(mCh[1]);
        blocks.push({ type: 'chapter', title: sb.title, byline: sb.byline });
        continue;
      }
      if (SCENE_BREAK_RE.test(line)) { flushPara(); blocks.push({ type: 'scene' }); continue; }
      if (mSub) { flushPara(); blocks.push({ type: 'subhead', runs: parseInline(mSub[1].trim()) }); continue; }
      if (line.trim() === '') flushPara();
      else paraBuf.push(line);
    }
    if (inBlock) closeBlock();
    flushPara();
    return blocks;
  }

  function shallow(o) { var r = {}; for (var k in o) if (o.hasOwnProperty(k)) r[k] = o[k]; return r; }

  // ---- document model -> markdown ------------------------------------------

  function toMarkdown(blocks) {
    var out = [];
    blocks.forEach(function (b) {
      if (b.type === 'chapter') {
        var title = b.title || '';
        if (title && b.byline) out.push('# ' + title + BYLINE_SEP + b.byline);
        else out.push('# ' + title);
      } else if (b.type === 'part') {
        out.push('=== ' + (b.title || ''));
      } else if (b.type === 'subhead') {
        out.push('## ' + runsToMd(b.runs));
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
          for (var k in b.attrs) if (b.attrs.hasOwnProperty(k)) header += ' ' + k + '="' + b.attrs[k] + '"';
        }
        out.push(header);
        var kids = b.children || [];
        if (b.block_type === 'poem') {
          for (var si = 0; si < kids.length; si++) {     // stanzas of verse lines
            if (si > 0) out.push('');                    // blank line between stanzas
            kids[si].lines.forEach(function (ln) { out.push(runsToMd(ln.runs)); });
          }
        } else if (LINE_BLOCKS.indexOf(b.block_type) !== -1) {
          for (var li = 0; li < kids.length; li++) out.push(runsToMd(kids[li].runs));
        } else {
          for (var i = 0; i < kids.length; i++) {
            out.push(runsToMd(kids[i].runs));
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

  global.DocModel = {
    fromMarkdown: fromMarkdown,
    toMarkdown: toMarkdown,
    // exposed for tests
    _parseInline: parseInline,
    _run: run
  };
})(typeof window !== 'undefined' ? window : this);
