// Driven by test_manuscript_editor.py: one throwaway book per scenario, each
// opened in its own iframe of the real editor page. Results go back as one JSON
// object; most checks read the files on disk afterwards, in Python.
var R = {};
function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
function frame(url){
  return new Promise(function(res){
    var f = document.createElement('iframe');
    f.style.width = '1100px'; f.style.height = '800px';
    // all in view: Chrome holds back animation frames in an iframe scrolled out
    // of sight, and the editor paints its highlighting in one
    f.style.position = 'fixed'; f.style.left = '0'; f.style.top = '0';
    f.onload = function(){ f.onload = null; res(f); };
    f.src = url; document.body.appendChild(f);
  });
}
// two animation frames in the page: its highlighting is painted in one
function frames(f){
  return new Promise(function(res){
    f.contentWindow.requestAnimationFrame(function(){ f.contentWindow.requestAnimationFrame(res); });
  });
}
function nextLoad(f){
  return new Promise(function(res){ f.onload = function(){ f.onload = null; res(f); }; });
}
async function open(pid, mode){
  // the mode a page opens in is remembered across pages (same origin)
  localStorage.setItem('ts-write-mode', mode || 'markdown');
  return frame('/project/' + pid + '/write');
}
async function disk(pid){ return (await fetch('/_ed_disk/' + pid)).text(); }
function $(f, id){ return f.contentDocument.getElementById(id); }
function typeMd(f, s){
  var w = f.contentWindow, ta = $(f, 'ms');
  ta.value = ta.value + s;
  ta.dispatchEvent(new w.Event('input', {bubbles: true}));
}
function typeRich(f, s){
  var w = f.contentWindow, rich = $(f, 'ms-rich');
  var ps = rich.querySelectorAll('.wb-para');
  var p = ps[ps.length - 1];
  p.textContent = p.textContent + s;
  rich.dispatchEvent(new w.InputEvent('input', {bubbles: true, inputType: 'insertText',
                                                data: s.slice(-1)}));
}
function leave(f){ f.src = 'about:blank'; return nextLoad(f); }
function beforeUnloadBlocks(f){
  var w = f.contentWindow, ev = new w.Event('beforeunload', {cancelable: true});
  w.dispatchEvent(ev);
  return ev.defaultPrevented;
}

async function run(){
  var f, f1, f2;

  // The Markdown toolbar's Table button did nothing.
  f = await open('table');
  $(f, 'ms').setSelectionRange(14, 14);
  f.contentDocument.querySelector('[data-act=table]').click();
  $(f, 'save-btn').click(); await sleep(1500);

  // Ctrl+F in rich mode searched the Markdown as it was before the last edits.
  f = await open('find', 'rich');
  var w = f.contentWindow;
  typeRich(f, ' Zebra here.');
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'f', ctrlKey: true,
                                                          bubbles: true}));
  $(f, 'f-find').value = 'Zebra';
  $(f, 'f-find').dispatchEvent(new w.Event('input'));
  R.find_count = $(f, 'f-count').textContent;
  R.find_rich = $(f, 'ms-wrap').classList.contains('rich-on');
  await sleep(2000);

  // Leaving straight after an edit: rich mode's half-second sync used to mean
  // the page didn't know it had anything to save.
  f = await open('richleave', 'rich');
  typeRich(f, ' RICHQUICK'); await sleep(100); await leave(f);
  f = await open('mdleave');
  typeMd(f, ' MDQUICK'); await sleep(100); await leave(f);
  f = await open('richswitch', 'rich');
  typeRich(f, ' SWITCHQUICK'); $(f, 'mode-toggle').click(); await leave(f);
  await sleep(1000);

  // Too big for a beacon (64 KB): it was sent, refused, and the edit lost.
  f = await open('big');
  typeMd(f, ' BIGTAIL');
  R.guard_big = beforeUnloadBlocks(f);
  $(f, 'save-btn').click(); await sleep(1500);
  R.guard_clean = beforeUnloadBlocks(f);

  // Typeset and Book settings went before the last edit was saved.
  f = await open('typeset');
  typeMd(f, ' TYPESETNOW');
  var go = nextLoad(f);
  f.contentDocument.querySelector('#typeset-form button[type=submit]').click();
  await go;
  f = await open('settings');
  typeMd(f, ' SETTINGSNOW');
  go = nextLoad(f);
  f.contentDocument.querySelector('a[data-save-first]').click();
  await go;

  // The same book in two tabs: the second's save wrote over the first's.
  f1 = await open('tabs'); f2 = await open('tabs');
  typeMd(f1, '\nTAB-ONE\n'); await sleep(2500);
  typeMd(f2, '\nTAB-TWO\n'); await sleep(2500);
  R.tabs_banner = !$(f2, 'conflict').hidden;
  R.tabs_disk_after_clash = await disk('tabs');
  typeMd(f1, ' MORE-ONE'); await sleep(2500);
  R.tabs_one_more = (await disk('tabs')).indexOf('MORE-ONE') >= 0;
  $(f2, 'cf-mine').click(); await sleep(1500);
  var d = await disk('tabs');
  R.tabs_mine = d.indexOf('TAB-TWO') >= 0 && d.indexOf('MORE-ONE') < 0
                && $(f2, 'conflict').hidden;
  typeMd(f1, ' AGAIN'); await sleep(2500);
  R.tabs_one_banner = !$(f1, 'conflict').hidden;
  go = nextLoad(f1);
  $(f1, 'cf-load').click();
  await go;
  R.tabs_loaded_text = $(f1, 'ms').value;
  R.tabs_loaded = R.tabs_loaded_text === (await disk('tabs')) && $(f1, 'conflict').hidden;

  // A failed save said "Save failed" and was never tried again.
  f = await open('retry');
  w = f.contentWindow;
  var realFetch = w.fetch, failures = 1;
  w.fetch = function(u, o){
    if (String(u).indexOf('/write/save') >= 0 && failures-- > 0)
      return Promise.reject(new TypeError('Failed to fetch'));
    return realFetch.call(w, u, o);
  };
  typeMd(f, ' RETRYME'); await sleep(2000);
  R.retry_status = $(f, 'save-status').textContent;
  await sleep(10000);

  // Switching modes mid-edit, before any autosave.
  f = await open('modes');
  typeMd(f, ' MD-EDIT');
  $(f, 'mode-toggle').click();
  typeRich(f, ' RICH-EDIT');
  $(f, 'mode-toggle').click();
  $(f, 'save-btn').click(); await sleep(1500);

  // Restore with unsaved work: the server kept the text on disk, not the page's.
  f = await open('restore');
  await sleep(500);                         // the history panel loads
  typeMd(f, ' UNSAVED');
  var btn = f.contentDocument.querySelector('#history .snap button');
  btn.click(); btn.click();
  await sleep(2500);

  // The preview renders what is on the page, saved or not.
  f = await open('preview');
  typeMd(f, '\n# Second\n\nMore.\n');
  $(f, 'pv-btn').click();
  for (var i = 0; i < 40 && !/page/.test($(f, 'pv-status').textContent); i++) await sleep(250);
  R.preview = $(f, 'pv-status').textContent;
  await sleep(1500);

  // Awkward text: what the page opens with is what is on disk.
  f = await open('odd');
  R.odd_text = $(f, 'ms').value;
  R.odd_same = R.odd_text === (await disk('odd'));
  typeMd(f, 'x');
  $(f, 'ms').value = $(f, 'ms').value.slice(0, -1);
  $(f, 'ms').dispatchEvent(new f.contentWindow.Event('input', {bubbles: true}));
  $(f, 'save-btn').click(); await sleep(1500);

  f = await open('cyr');
  typeMd(f, ' ещё');
  await sleep(500);                         // the count waits for a pause
  R.cyr_words = $(f, 'st-words').textContent;

  // The painted Markdown sits under the textarea's own (transparent) text, so
  // it has to lay out line for line the same: compare the heights, on awkward
  // text and on a whole novel, as opened and after an edit in the middle.
  R.aligned = {};
  var local = await (await fetch('/_ed_local')).json();
  for (var pid of ['oddhl', 'novel', 'sample'].concat(local)){
    f = await open(pid);
    var ta = $(f, 'ms'), hl = $(f, 'ms-hl');
    // shrink the textarea to nothing, so its scrollHeight is its text's height
    ta.style.minHeight = '0'; ta.style.height = '40px';
    f.contentWindow.dispatchEvent(new f.contentWindow.Event('resize'));
    await frames(f);
    R.aligned[pid] = [hl.offsetHeight, ta.scrollHeight];
    var half = ta.value.indexOf('\n', ta.value.length >> 1) + 1;
    ta.value = ta.value.slice(0, half) + '\n# Inserted\n\nA *new* line.\n\n'
               + ta.value.slice(half);
    ta.dispatchEvent(new f.contentWindow.Event('input', {bubbles: true}));
    await frames(f);
    R.aligned[pid].push(hl.offsetHeight, ta.scrollHeight,
                        hl.textContent === ta.value.replace(/\n/g, ''));
    f.remove();
  }
  await sleep(2000);
}

(async function(){
  try { await run(); }
  catch(e){ R.error = String(e && e.stack || e); }
  await fetch('/_ed_result', {method: 'POST', body: JSON.stringify(R)});
})();
