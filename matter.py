"""The book's front- and back-matter vocabulary, in one place.

Every named section — dedication, foreword, afterword, bibliography … — is a
per-book block of text carried on the `meta` dict. Each one used to be wired by
hand in about a dozen places (the compose form, the project form, the result
page's hidden fields, five meta dicts in app.py, project load/save, the engine's
page list, the EPUB's manifest / spine / nav), so adding one was a scavenger hunt
and forgetting a site was silent.

This table is the single definition. app.py builds its forms and meta from it,
engine.py lays the pages out from it, epub.py manifests them from it. Adding a
section is one row.

Stdlib-only and importing nothing from the project, so both builders can use it
without dragging anything else in.

Fields
------
key        the meta key, the form field name, and the project key
label      the page heading. `{author}` is filled in from the book's author.
where      'front' (after the copyright / contents) or 'back' (after the story)
style      how the page is set — see engine._matter_page / epub's CSS map:
           'body' | 'dedication' | 'epigraph' | 'contributors' | 'also_by'
eid        short id used in the EPUB manifest/spine
href       the EPUB filename
hint       one-line guidance shown under the form field
"""

SECTIONS = [
    # ---- front matter, in the order a book presents it -------------------
    dict(key='dedication', label='', where='front', style='dedication',
         eid='ded', href='dedication.xhtml',
         hint='A short inscription. Set on its own page, centred.'),
    dict(key='epigraph', label='', where='front', style='epigraph',
         eid='epi', href='epigraph.xhtml',
         hint='A quotation opening the book. A last line starting — is set as the attribution.'),
    dict(key='foreword', label='Foreword', where='front', style='body',
         eid='fwd', href='foreword.xhtml',
         hint='An introduction written by someone other than the author.'),
    dict(key='preface', label='Preface', where='front', style='body',
         eid='pfc', href='preface.xhtml',
         hint='The author on how or why the book came about.'),
    dict(key='introduction', label='Introduction', where='front', style='body',
         eid='int', href='introduction.xhtml',
         hint='Introduces the subject or scope. Part of the book proper, not the story.'),

    # ---- back matter ------------------------------------------------------
    dict(key='afterword', label='Afterword', where='back', style='body',
         eid='aft', href='afterword.xhtml',
         hint='A closing note — history, sources, what happened next.'),
    dict(key='bibliography', label='Bibliography', where='back', style='body',
         eid='bib', href='bibliography.xhtml',
         hint='Works cited or consulted. One per blank-line-separated block.'),
    dict(key='acknowledgments', label='Acknowledgments', where='back', style='body',
         eid='ack', href='acknowledgments.xhtml',
         hint='Thanks to the people behind the book.'),
    dict(key='contributors', label='Contributors', where='back', style='contributors',
         eid='con', href='contributors.xhtml',
         hint='For anthologies: one contributor per block, name before an em dash.'),
    dict(key='about_author', label='About the Author', where='back', style='body',
         eid='abt', href='about.xhtml',
         hint='A short biography. A good place for a newsletter link.'),
    dict(key='also_by', label='Also by {author}', where='back', style='also_by',
         eid='aby', href='alsoby.xhtml',
         hint='One title per line. Link them to sell them.'),
    dict(key='blurbs', label='Praise', where='back', style='epigraph',
         eid='blb', href='blurbs.xhtml',
         hint='Review quotes. A last line starting — is set as the source.'),
]

KEYS = [s['key'] for s in SECTIONS]
FRONT = [s for s in SECTIONS if s['where'] == 'front']
BACK = [s for s in SECTIONS if s['where'] == 'back']


def heading(section, author=''):
    """The page heading for a section, with `{author}` filled in.

    An empty label means the page carries no heading at all (a dedication and an
    epigraph are set without one).
    """
    label = section['label']
    if not label:
        return ''
    return label.format(author=author).strip() or section['key'].title()


def present(meta, where=None):
    """The sections this book actually has text for, in presentation order."""
    pool = SECTIONS if where is None else [s for s in SECTIONS if s['where'] == where]
    return [s for s in pool if (meta.get(s['key']) or '').strip()]


def blank():
    """A meta fragment with every section empty — for previews and stubs."""
    return {k: '' for k in KEYS}
