"""Record what the app does today with the TTRPG fixtures (ROADMAP #74).

    python test_fixtures/ttrpg/make_baseline.py

Run from the repo root (or anywhere: it finds the repo from its own path).
Builds each fixture with the current code and writes baseline/baseline.json:
for each file, the blocks the parser makes of every fence (type, attributes,
paragraph count), whether the Markdown round trip is byte-identical, the PDF's
page count and build time (6 x 9, the default style), and whether the EPUB
builds. Run make_long_book.py first for the generated files to be included.

This is the "before" for Phase 1: today the three new fence types fall back to
a plain document block, which joins a stat block's lines into one paragraph,
and smart punctuation turns its `---` section lines into em dashes. After
Phase 1 the same files should parse into the new blocks; diff the two runs.
"""

import copy
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
os.chdir(REPO)
import logging; logging.disable(logging.INFO)

import manuscript
import doc_model
import engine
import epub
import app as A

FILES = ['adventure.md', 'statblocks.md', 'statblock_formats.md', 'edge_cases.md',
         'generated/long_book.md', 'generated/long_statblock.md']
NEW_TYPES = ('statblock', 'readaloud', 'sidebar')


def fences(ms):
    """Each typed block the parser made, in order: (type, attrs, paragraph count)."""
    out = []
    for ch in ms['chapters']:
        for b in ch['blocks']:
            if b[0] == 'doc_block':
                meta = b[2] if len(b) > 2 else {}
                out.append({'type': meta.get('_type', ''),
                            'attrs': {k: v for k, v in meta.items() if k != '_type'},
                            'paras': len(b[1])})
    return out


def main():
    out_dir = os.path.join(HERE, 'baseline')
    os.makedirs(out_dir, exist_ok=True)
    preset = copy.deepcopy(A.DEFAULTS)
    meta = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'year': '2026',
            'front_matter': 'none', 'include_toc': False, 'smartquotes': True}
    report = {'_about': __doc__.strip().splitlines()[0],
              'version': open(os.path.join(REPO, 'VERSION')).read().strip(),
              'files': {}}
    for name in FILES:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            print('skip (not generated):', name)
            continue
        raw = open(path, encoding='utf-8').read()
        ms = manuscript.parse_markdown(raw)
        fl = fences(ms)
        rec = {
            'chapters': len(ms['chapters']),
            'fences': len(fl),
            'new_type_fences': sum(1 for f in fl if f['type'] in NEW_TYPES),
            'statblocks_with_one_para': sum(1 for f in fl
                                            if f['type'] == 'statblock' and f['paras'] == 1),
            'round_trip_identical': doc_model.to_markdown(
                doc_model.from_markdown(raw, smartquotes=False)) == raw,
        }
        if not name.startswith('generated/'):
            rec['fence_detail'] = fl
        pdf = os.path.join(out_dir, os.path.basename(name).replace('.md', '.pdf'))
        t = time.time()
        try:
            engine.build_pdf(ms, preset, pdf, dict(meta))
            import fitz
            with fitz.open(pdf) as d:
                rec['pdf_pages'] = d.page_count
            rec['pdf_seconds'] = round(time.time() - t, 2)
        except Exception as exc:                       # record, don't stop
            rec['pdf_error'] = '%s: %s' % (type(exc).__name__, exc)
        try:
            ep = pdf.replace('.pdf', '.epub')
            epub.build_epub(ms, preset, ep, dict(meta))
            rec['epub'] = 'ok'
        except Exception as exc:
            rec['epub'] = '%s: %s' % (type(exc).__name__, exc)
        report['files'][name] = rec
        print(name, {k: v for k, v in rec.items() if k != 'fence_detail'})
    with open(os.path.join(out_dir, 'baseline.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
