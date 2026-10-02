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

  run('paste-word-with-space', function () {
    loadMd('# One\n\nSay and go.\n'); var t = q('.wb-para').firstChild;
    var r = d.createRange(); r.setStart(t, 4); r.collapse(true); rich.focus();
    sel().removeAllRanges(); sel().addRange(r);
    paste('<span>hello </span>', 'hello '); return getMd();
  });

  var x = new XMLHttpRequest();
  x.open('POST', '/_rich_result', false); x.send(JSON.stringify(out));
};
