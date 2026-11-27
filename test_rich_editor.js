/* Rich-editor scenarios, run by test_rich_editor.py in a headless browser.
 *
 * Loaded into a harness page that frames the real manuscript editor. Each
 * scenario loads Markdown, edits the rich surface the way a writer would (typed
 * text, Enter, Backspace, the toolbar, a paste event carrying clipboard data),
 * then switches to Markdown mode and records what the manuscript became. The
 * corpus pass records every document after a plain rich-mode round trip.
 */
var f = document.getElementById('f');
f.onload = function () {
  var d = f.contentDocument, w = f.contentWindow;
  var ta = d.getElementById('ms'), rich = d.getElementById('ms-rich');
  var toggle = d.getElementById('mode-toggle');
  function on() { return toggle.classList.contains('on'); }
  function loadMd(md) { if (on()) toggle.click(); ta.value = md; toggle.click(); }
  function getMd() { toggle.click(); var v = ta.value; toggle.click(); return v; }
  function sel() { return w.getSelection(); }
  function caret(el, atEnd) {
    rich.focus();
    var r = d.createRange(); r.selectNodeContents(el); r.collapse(!atEnd);
    sel().removeAllRanges(); sel().addRange(r);
  }
  function caretAfter(node) {
    rich.focus();
    var r = d.createRange(); r.setStartAfter(node); r.collapse(true);
    sel().removeAllRanges(); sel().addRange(r);
  }
  function type(s) { for (var i = 0; i < s.length; i++) d.execCommand('insertText', false, s[i]); }
  function enter(shift) {
    var ev = new w.KeyboardEvent('keydown', {key: 'Enter', shiftKey: !!shift, bubbles: true, cancelable: true});
    var go = rich.dispatchEvent(ev);
    if (go) d.execCommand(shift ? 'insertLineBreak' : 'insertParagraph');
  }
  function act(name) { d.querySelector('.toolbar button[data-act="' + name + '"]').click(); }
  function q(s) { return rich.querySelector(s); }
  function paste(h, t) {
    var dt = new w.DataTransfer();
    if (h) dt.setData('text/html', h);
    dt.setData('text/plain', t || '');
    rich.dispatchEvent(new w.ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  }
  function key(k) {
    var ev = new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true});
    if (rich.dispatchEvent(ev)) d.execCommand(k === 'Backspace' ? 'delete' : 'forwardDelete');
  }

  var out = {roundtrip: {}, scenarios: {}};
  Object.keys(CORPUS).forEach(function (k) { loadMd(CORPUS[k]); out.roundtrip[k] = getMd(); });
  // the paste's Homebrewery wrapper, to compare with statblock.wrap_unfenced
  out.wrapped = w.DocModel.wrapUnfenced(CORPUS['test_fixtures/ttrpg/statblock_formats.md']);

  var S = out.scenarios;
  function run(name, fn) {
    try { S[name] = fn(); } catch (e) { S[name] = 'ERROR ' + e; }
  }
  run('enter-after-subhead', function () {
    loadMd('# One\n\n## Sub\n\nPara.\n'); caret(q('.wb-subhead'), true); enter(); type('New text');
    return getMd();
  });
  run('type-in-empty', function () {
    loadMd(''); caret(rich.firstChild, true); type('Hello'); return getMd();
  });
  run('shift-enter', function () {
    loadMd('# One\n\nFirst half\n'); caret(q('.wb-para'), true); enter(true); type('second half');
    return getMd();
  });
  run('convert-bold-to-subhead', function () {
    loadMd('# One\n\nSome **bold** and *it* and [a link](https://x.example) and a note.[^a]\n\n[^a]: N.\n');
    caret(q('.wb-para'), true); act('subhead'); return getMd();
  });
  run('convert-in-letter', function () {
    loadMd('# One\n\n~~~ letter from="A"\nDear B,\n\nBody.\n~~~\n\nAfter.\n');
    caret(q('.wb-doc-para'), true); act('chapter'); return getMd();
  });
  run('convert-in-poem', function () {
    loadMd('# One\n\n~~~ poem title="T"\nverse one\nverse two\n~~~\n');
    caret(q('.wb-verse'), true); act('subhead'); return getMd();
  });
  run('paste-divs', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true); enter();
    paste('<div><p>Pasted one.</p><p>Pasted two.</p></div>'); return getMd();
  });
  run('paste-list', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true); enter();
    paste('<ul><li>alpha</li><li>beta</li></ul>'); return getMd();
  });
  run('paste-links', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true);
    paste(' <a href="/relative">rel</a> and <a href="javascript:alert(1)">js</a> and <a href="https://ok.example/">ok</a>');
    return getMd();
  });
  run('paste-styled-spans', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true);
    paste(' <span style="font-weight:700">heavy</span> <span style="font-style:italic">slanted</span>');
    return getMd();
  });
  run('paste-heading', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true); enter();
    paste('<h2>Pasted heading</h2><p>after it</p>'); return getMd();
  });
  run('paste-plain-lines', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true); enter();
    paste('', 'line one\nwrapped here\n\nline two'); return getMd();
  });
  run('trailing-space', function () {
    loadMd('# One\n\nWord\n'); caret(q('.wb-para'), true); type(' '); return getMd();
  });
  run('space-after-note', function () {
    loadMd('# One\n\nA note[^a]\n\n[^a]: N.\n'); caretAfter(q('sup.wb-note')); type(' then more');
    return getMd();
  });
  run('space-after-link', function () {
    loadMd('# One\n\nSee [this](https://x.example)\n'); caret(q('.wb-para'), true); type(' then more');
    return getMd();
  });
  run('double-space', function () {
    loadMd('# One\n\nWord\n'); caret(q('.wb-para'), true); type('  two'); return getMd();
  });
  run('backspace-after-scene', function () {
    loadMd('# One\n\nA.\n\n* * *\n\nB.\n'); caret(rich.querySelectorAll('.wb-para')[1], false);
    key('Backspace'); return getMd();
  });
  run('enter-end-of-list', function () {
    loadMd('# One\n\n~~~ list\none\ntwo\n~~~\n');
    var items = rich.querySelectorAll('.wb-doc-para'); caret(items[items.length - 1], true);
    enter(); type('three'); return getMd();
  });
  run('enter-twice-end-of-letter', function () {
    loadMd('# One\n\n~~~ letter from="A"\nDear B,\n~~~\n');
    caret(q('.wb-doc-para'), true); enter(); enter(); type('outside?'); return getMd();
  });
  run('poem-enter', function () {
    loadMd('# One\n\n~~~ poem title="T"\nverse one\nverse two\n~~~\n');
    caret(q('.wb-verse'), true); enter(); type('inserted'); return getMd();
  });
  run('bold-button', function () {
    loadMd('# One\n\nmake this bold please\n');
    var t = q('.wb-para').firstChild, r = d.createRange(); r.setStart(t, 5); r.setEnd(t, 9);
    rich.focus(); sel().removeAllRanges(); sel().addRange(r); act('bold'); return getMd();
  });
  run('bold-across-note', function () {
    loadMd('# One\n\nmake[^a] this bold\n\n[^a]: N.\n');
    var p = q('.wb-para'), r = d.createRange(); r.setStart(p.firstChild, 0);
    r.setEnd(p.lastChild, 5); rich.focus(); sel().removeAllRanges(); sel().addRange(r);
    act('bold'); return getMd();
  });
  run('figure-caption-enter', function () {
    loadMd('# One\n\n~~~ figure src="m.png"\nCap one.\n~~~\n');
    caret(q('.wb-figure-para'), true); enter(); type('Cap two.'); return getMd();
  });
  run('scene-button', function () {
    loadMd('# One\n\nText.\n'); caret(q('.wb-para'), true); act('scene'); type('After'); return getMd();
  });
  run('statblock-button', function () {
    loadMd('# One\n\nText.\n'); caret(q('.wb-para'), true); act('statblock'); return getMd();
  });
  run('readaloud-button', function () {
    loadMd('# One\n\nText.\n'); caret(q('.wb-para'), true); act('readaloud'); type('Boxed.');
    return getMd();
  });
  run('section-button', function () {
    loadMd('# One\n\nText.\n\nMore.\n'); caret(q('.wb-para'), true); act('section');
    return getMd();
  });
  run('subsection-from-section', function () {
    loadMd('# One\n\n### A1. Hall\n'); caret(q('.wb-subhead'), true); act('subsection');
    return getMd();
  });
  run('levels-survive-an-edit', function () {
    loadMd('# One\n#> Tag *line*.\n\n## Sub\n\n### Sec\n\n#### Detail\n\nText\n');
    caret(q('.wb-para'), true); type(' added'); return getMd();
  });
  run('statblock-line-edit', function () {
    // a section line and a Homebrewery rule must come back exactly as typed
    loadMd('# One\n\n~~~ statblock\n___\n**AC** 9\n--- Actions\n~~~\n');
    var lines = rich.querySelectorAll('.wb-doc-para'); caret(lines[1], true);
    enter(); type('**HP** 4 (1d8)'); return getMd();
  });
  run('paste-homebrewery', function () {
    // a V3 monster block copied with no fence gets one; the text around it stays
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true); enter();
    paste('<p>{{monster,frame</p>', 'Intro line.\n\n{{monster,frame\n## Bog-Thrall\n**AC** :: 9\n}}\n\nAfter line.');
    return getMd();
  });
  run('list-button-in-letter', function () {
    loadMd('# One\n\n~~~ letter from="A"\nDear B,\n~~~\n'); caret(q('.wb-doc-para'), true);
    act('list'); type('item'); return getMd();
  });

  run('delete-before-scene', function () {
    loadMd('# One\n\nA.\n\n* * *\n\nB.\n'); caret(q('.wb-para'), true); key('Delete'); return getMd();
  });
  run('backspace-mid-para-next-to-scene', function () {
    loadMd('# One\n\nA.\n\n* * *\n\nBee.\n'); var p = rich.querySelectorAll('.wb-para')[1];
    var r = d.createRange(); r.setStart(p.firstChild, 2); r.collapse(true); rich.focus();
    sel().removeAllRanges(); sel().addRange(r); key('Backspace'); return getMd();
  });
  run('exit-list', function () {
    loadMd('# One\n\n~~~ list\none\ntwo\n~~~\n');
    var items = rich.querySelectorAll('.wb-doc-para'); caret(items[items.length - 1], true);
    enter(); enter(); type('outside'); return getMd();
  });
  run('poem-stanza-then-exit', function () {
    loadMd('# One\n\n~~~ poem title="T"\nverse one\n~~~\n');
    caret(q('.wb-verse'), true); enter(); enter(); type('stanza two');
    enter(); enter(); enter(); type('after the poem'); return getMd();
  });
  run('exit-caption', function () {
    loadMd('# One\n\n~~~ figure src="m.png"\nCap.\n~~~\n');
    caret(q('.wb-figure-para'), true); enter(); enter(); type('after'); return getMd();
  });
  run('paste-gdocs', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true); enter();
    paste('<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1"><p dir="ltr"><span style="font-weight:400;font-style:italic">It</span><span style="font-weight:400"> was late.</span></p><br><p dir="ltr"><span style="font-weight:700">Next</span><span style="font-weight:400"> para.</span></p></b>');
    return getMd();
  });
  run('paste-word', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true); enter();
    paste('<html xmlns:o="urn:schemas-microsoft-com:office:office"><head><style>p.MsoNormal{margin:0}</style></head><body><!--StartFragment--><p class=MsoNormal>The&nbsp;<i>first</i>\r\nparagraph.<o:p></o:p></p>\r\n<p class=MsoNormal><b>Second</b> one.<o:p>&nbsp;</o:p></p><!--EndFragment--></body></html>');
    return getMd();
  });
  run('paste-mid-para', function () {
    loadMd('# One\n\nStart end.\n'); var t = q('.wb-para').firstChild;
    var r = d.createRange(); r.setStart(t, 6); r.collapse(true); rich.focus();
    sel().removeAllRanges(); sel().addRange(r);
    paste('<p>middle one</p><p>middle two </p>', 'middle one\n\nmiddle two '); return getMd();
  });
  run('paste-into-list', function () {
    loadMd('# One\n\n~~~ list\none\n~~~\n'); caret(q('.wb-doc-para'), true);
    paste('<p> and more</p><p>second item</p><p>third item</p>',
          ' and more\nsecond item\nthird item'); return getMd();
  });
  run('paste-into-title', function () {
    loadMd('# One\n\nText.\n'); caret(q('.wb-chapter'), true);
    paste('<p><b>Two</b></p><p>Three</p>'); return getMd();
  });
  run('paste-over-selection', function () {
    loadMd('# One\n\nKeep this replace that keep.\n'); var t = q('.wb-para').firstChild;
    var r = d.createRange(); r.setStart(t, 10); r.setEnd(t, 22); rich.focus();
    sel().removeAllRanges(); sel().addRange(r); paste('<i>swapped</i> '); return getMd();
  });
  run('paste-scene-from-editor', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true);
    paste('<p class="wb wb-para" data-block="para">Copied.</p><div class="wb wb-scene" data-block="scene" contenteditable="false">* * *</div><p class="wb wb-para" data-block="para">After <sup class="wb-note" data-note="a" contenteditable="false">a</sup>.</p>');
    return getMd();
  });
  run('nbsp-survives', function () {
    loadMd('# One\n\nMr.\u00a0Smith came.\n'); caret(q('.wb-para'), true); type(' Then left.'); return getMd();
  });
  run('nbsp-in-paste', function () {
    loadMd('# One\n\nX.\n'); caret(q('.wb-para'), true); paste('<p>A&nbsp;B</p>'); return getMd();
  });

  // ---- bug hunt 6: the round trip and the paste
  run('verse-of-tildes', function () {
    loadMd('# One\n\n~~~ poem\nFirst line\nLast line\n~~~\n\n# Two\n\nText\n');
    caret(q('.wb-verse'), true); enter(); type('~~~'); return getMd();
  });
  run('table-cells-kept', function () {
    loadMd('# One\n\n~~~ table\na_b | c_d\n~~~\n\nPara.\n');
    caret(q('.wb-para'), true); type('!'); return getMd();
  });
  run('italic-then-bold', function () {
    loadMd('# One\n\n_red_**blue**\n\nPara.\n');
    caret(rich.querySelectorAll('.wb-para')[1], true); type('!'); return getMd();
  });
  run('accented-note-labels', function () {
    loadMd('# One\n\nSee both.[^é][^ñ]\n\n[^é]: First.\n[^ñ]: Second.\n');
    caret(q('.wb-para'), true); type('!'); return getMd();
  });
  run('poem-title-quotes', function () {
    loadMd('# One\n\n~~~ poem title="The"\nverse\n~~~\n');
    caret(q('.wb-poem-title'), true); type(' "Blue" Hour'); return getMd();
  });
  run('rejected-paste-keeps-selection', function () {
    loadMd('# One\n\n~~~ poem\na red kite\n~~~\n');
    rich.focus();
    var t = q('.wb-verse').firstChild, r = d.createRange();
    r.setStart(t, 2); r.setEnd(t, 5); sel().removeAllRanges(); sel().addRange(r);
    paste('', '{{monster\n## Fox\n}}'); return getMd();
  });
  run('paste-lines-into-verse', function () {
    loadMd('# One\n\n~~~ poem\nX\n~~~\n');
    caret(q('.wb-verse'), true); paste('', 'First line\nSecond line\n\nThird line'); return getMd();
  });
  run('note-in-statblock', function () {
    loadMd('# One\n\n~~~ statblock\nHit Points: 12\n~~~\n\n[^roll]: Roll again.\n');
    caret(q('.wb-doc-para'), true); type('[^roll]'); return getMd();
  });
  run('attr-named-like-a-method', function () {
    loadMd('# One\n\n~~~ quote hasOwnProperty="yes"\nWords.\n~~~\n'); return getMd();
  });
  run('enter-over-selected-verse-words', function () {
    loadMd('# One\n\n~~~ poem\na red kite\n~~~\n');
    rich.focus();
    var t = q('.wb-verse').firstChild, r = d.createRange();
    r.setStart(t, 2); r.setEnd(t, 5); sel().removeAllRanges(); sel().addRange(r);
    enter(); return getMd();
  });
  run('outline-jumps-in-rich', function () {
    loadMd('# One\n\nA.\n\n#* Interlude\n\nB.\n\n# Two\n\nC.\n'); getMd();
    d.querySelectorAll('#outline a')[2].click();
    var n = sel().anchorNode;
    while (n && !(n.classList && n.classList.contains('wb'))) n = n.parentNode;
    return n ? n.textContent : 'no caret';
  });
  run('replace-all-after-dotted-i', function () {
    if (on()) toggle.click();
    ta.value = 'İxa';
    d.getElementById('f-find').value = 'x'; d.getElementById('f-repl').value = 'Y';
    d.getElementById('f-case').checked = false;
    d.getElementById('f-all').click();
    var v = ta.value; toggle.click(); return v;
  });

  run('paste-word-with-space', function () {
    loadMd('# One\n\nSay and go.\n'); var t = q('.wb-para').firstChild;
    var r = d.createRange(); r.setStart(t, 4); r.collapse(true); rich.focus();
    sel().removeAllRanges(); sel().addRange(r);
    paste('<span>hello </span>', 'hello '); return getMd();
  });

  // "across both columns": the button writes span="yes" and takes it out again
  run('span-figure-on', function () {
    loadMd('# One\n\n~~~ figure src="m.png" width="0.5"\nCap.\n~~~\n');
    q('.wb-figure .wb-span').click(); return getMd();
  });
  run('span-table-on-then-type', function () {
    loadMd('# One\n\n~~~ table\nA | B\n1 | 2\n~~~\n');
    q('.wb-doc[data-btype="table"] .wb-span').click();
    var rows = rich.querySelectorAll('.wb-doc-para'); caret(rows[rows.length - 1], true); type('0');
    return getMd();
  });
  run('span-table-off', function () {
    loadMd('# One\n\n~~~ table span="yes" caption="C"\nA | B\n1 | 2\n~~~\n');
    var b = q('.wb-doc[data-btype="table"] .wb-span');
    var was = b.classList.contains('on'); b.click();
    return (was ? '' : 'NOT SHOWN ON ') + getMd();
  });
  run('span-no-button-elsewhere', function () {
    loadMd('# One\n\n~~~ letter from="A"\nDear B,\n~~~\n\n~~~ sidebar title="T"\nText.\n~~~\n');
    return String(rich.querySelectorAll('.wb-span').length);
  });
  // #74 Phase 5a: index markers
  run('index-survives-edit', function () {
    loadMd('# One\n\nThe owlbear{index: Owlbear} attacks\n');
    var chip = q('.wb-index');
    if (!chip || chip.dataset.index !== 'Owlbear') return 'NO CHIP';
    caret(q('.wb-para'), true); type(' here'); return getMd();
  });
  run('index-typed', function () {
    loadMd('# One\n\nThe owlbear\n'); caret(q('.wb-para'), true);
    type('{index: Monsters > Owlbear}');
    if (rich.querySelectorAll('.wb-index').length !== 1) return 'NO CHIP';
    type(' attacks'); return getMd();
  });
  run('index-deleted-whole', function () {
    loadMd('# One\n\nThe owlbear{index: Owlbear} attacks\n');
    q('.wb-index').remove(); rich.dispatchEvent(new w.Event('input', {bubbles: true}));
    return getMd();
  });
  run('index-literal-stays', function () {
    loadMd('# One\n\nA \\{index: literal} here\n');
    if (rich.querySelectorAll('.wb-index').length) return 'A CHIP';
    caret(q('.wb-para'), true); type(' now'); return getMd();
  });
  // #74 Phase 5b: a link target and a page reference are chips likewise
  run('ref-survives-edit', function () {
    loadMd('# One\n\nThe vault{#a3} is on page {page: a3}\n');
    var a = q('.wb-anchor'), p = q('.wb-pageref');
    if (!a || a.dataset.anchor !== 'a3' || !p || p.dataset.pageref !== 'a3') return 'NO CHIP';
    caret(q('.wb-para'), true); type(' here'); return getMd();
  });
  run('ref-typed', function () {
    loadMd('# One\n\nThe vault\n'); caret(q('.wb-para'), true);
    type('{#a3}');
    if (rich.querySelectorAll('.wb-anchor').length !== 1) return 'NO ANCHOR CHIP';
    type(' see page {page: a3}');
    if (rich.querySelectorAll('.wb-pageref').length !== 1) return 'NO PAGE CHIP';
    type(' now'); return getMd();
  });
  run('ref-literal-stays', function () {
    loadMd('# One\n\nA \\{#a3} and \\{page: a3} here\n');
    if (rich.querySelectorAll('.wb-anchor, .wb-pageref').length) return 'A CHIP';
    caret(q('.wb-para'), true); type(' now'); return getMd();
  });

  // ---- bug hunt round 5, section 22: game blocks in the editor
  run('bh22-unclosed-block', function () {
    // a stat block missing its ~~~ ends at the chapter after it; the sidebar
    // further on keeps its type and attributes
    loadMd('# One\n\n~~~ statblock\n## Ash Drake\nAC: 15\n\n# Next Room\n\nProse here.\n\n'
           + '~~~ sidebar title="Pacing" style="note"\nKeep it moving.\n~~~\n\nAfter.\n');
    return getMd();
  });
  run('bh22-paste-fenced-statblock', function () {
    loadMd('# One\n\nBefore.\n'); caret(q('.wb-para'), true); enter();
    paste('', '~~~ statblock name="Ash Drake" cr="2"\nAC: 15\nHP: 30\n~~~');
    return getMd();
  });
  run('bh22-statblock-blank-line', function () {
    loadMd('# One\n\n~~~ statblock\n## Ash Drake\nSTR DEX CON INT WIS CHA\n\n14 8 15 3 8 5\n~~~\n');
    return getMd();
  });
  run('bh22-statblock-link', function () {
    loadMd('# One\n\n~~~ statblock\n## Ash Drake\nLanguages: Common\n~~~\n');
    var lines = rich.querySelectorAll('.wb-doc-para'); caret(lines[1], true); type(', ');
    paste('<a href="https://example.com/aquan">Aquan</a>', 'Aquan');
    return getMd();
  });
  run('bh22-markdown-paste-midline', function () {
    if (on()) toggle.click();
    ta.value = '# One\n\nThe door opens. It is dark.\n\n# Two\n\nText.\n';
    ta.focus(); ta.selectionStart = ta.selectionEnd = ta.value.indexOf(' It is dark.');
    var dt = new w.DataTransfer();
    dt.setData('text/plain', '{{monster,frame\n## Bog-Thrall\n**AC** :: 9\n}}');
    ta.dispatchEvent(new w.ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
    var v = ta.value; toggle.click(); return v;
  });
  run('bh22-wrap-unterminated', function () {
    return w.DocModel.wrapUnfenced('{{monster,frame\n## Ash Drake\n**AC** :: 15\n\nSome prose between.\n\n'
                                   + '{{monster,frame\n## Bog-Thrall\n**AC** :: 9\n}}\n');
  });

  // ---- bug hunt round 6, section 26: regressions from rounds 4-5
  run('bh26-poem-hash-line', function () {
    // a `# ` line in a poem whose closing ~~~ is there stays a verse
    loadMd('# One\n\n~~~ poem\nA line\n# 7 on the door\nB line\n~~~\n\nAfter.\n');
    return getMd();
  });
  run('bh26-blank-run', function () {
    // a long run of blank lines is not scanned again from every line
    var t0 = Date.now();
    var out = w.DocModel.wrapUnfenced('Prose.' + new Array(50001).join('\n') + 'More.');
    return (Date.now() - t0 < 2000 ? 'fast ' : 'SLOW ') + out.split('\n').length;
  });
  // ---- bug hunt round 7, section 29: regressions from 1.16.0
  run('bh29-nested-emphasis', function () {
    // italics round a bold span show as italics, as the PDF sets them, and
    // are written back as typed
    loadMd('# One\n\n*before **bold** after*\n');
    var p = rich.querySelector('p');
    var shown = (p ? p.textContent : '') + ' | ' + rich.querySelectorAll('em, i').length
                + ' em | ' + rich.querySelectorAll('strong, b').length + ' strong';
    return shown + ' | ' + getMd();
  });
  run('bh22-wrap-legacy-blank', function () {
    return w.DocModel.wrapUnfenced('___\n\n> ## Ash Drake\n> *Large dragon*\n> - **AC** 15\n\nAfter.\n');
  });

  var x = new XMLHttpRequest();
  x.open('POST', '/_rich_result', false); x.send(JSON.stringify(out));
};
