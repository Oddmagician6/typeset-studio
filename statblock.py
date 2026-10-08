"""Reading a `~~~ statblock` fence into one model, whatever format it was written in.

A stat block is pasted from wherever it was written — a Word bestiary, a PDF, the
Homebrewery, a forum post, the 2024 books, an old-school module — so the reader
accepts all of their shapes and reads them into the same model; the style then
prints that model in its one look. The source itself is never rewritten: the fence
is line-oriented, so the manuscript keeps every line exactly as it was typed, and
only the *reading* is normalised.

The model (every string is raw Markdown, inlined later by the caller):

    {'name': str, 'meta': str,
     'fields':   [{'label': str, 'value': str}, ...],
     'scores':   [{'name': str, 'score': str, 'mod': str, 'save': str}, ...],
     'auto':     bool,           # every modifier was worked out, none written
     'scores_at': int,           # how many fields come before the score row
     'sections': [{'name': str, 'entries': [{'name': str, 'text': str}, ...]}, ...]}

Entries before the first section heading sit in a section named ''. A section
line with no name (`---`) is a bare rule, and also a section named ''. Modifiers
and saves use a true minus sign.

The rules, the formats they serve and their priority are in
`test_fixtures/ttrpg/statblock_formats.json`; `statblock_lines.json` checks them a
line at a time. Lines are classified on their *raw* text, before inline markup
and smart punctuation: `--- Actions` must be seen before `---` becomes an em dash,
the way a table's cells are split before `_inline`.
"""

import re

MINUS = '−'

# Labels read as fields with no markup at all (a block pasted from a PDF). Longest
# first, so "Damage Immunities" is not read as an unknown "Damage".
KNOWN_LABELS = sorted((
    'Armor Class', 'AC', 'Hit Points', 'HP', 'Speed', 'Initiative', 'Saving Throws',
    'Skills', 'Damage Vulnerabilities', 'Damage Resistances', 'Damage Immunities',
    'Vulnerabilities', 'Resistances', 'Immunities', 'Condition Immunities', 'Gear',
    'Senses', 'Languages', 'Challenge', 'CR', 'Proficiency Bonus',
), key=len, reverse=True)

# A field with one of these labels is the last line of the head.
HEAD_ENDS = ('challenge', 'cr', 'proficiency bonus')

KNOWN_SECTIONS = ('Traits', 'Actions', 'Bonus Actions', 'Reactions',
                  'Legendary Actions', 'Mythic Actions', 'Lair Actions',
                  'Regional Effects', 'Spellcasting')

FIVE_E = ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')

SIZES = ('Tiny', 'Small', 'Medium', 'Large', 'Huge', 'Gargantuan')

# The old-school stat line's abbreviations; a comma or semicolon splits the line
# only when one of these follows it, so the commas inside a value stay there.
OSR_ABBR = ('No. Appearing', 'Attacks', 'Treasure', 'Morale', 'THAC0', 'Move',
            'Save', 'Att', 'AC', 'HD', 'MV', 'SV', 'ML', 'AL', 'XP', 'NA', 'TT')

_MINOR = {'a', 'an', 'the', 'and', 'or', 'of', 'by', 'in', 'on', 'to', 'with',
          'for', 'at', 'from'}

_NAME = r'(?:[A-Z]{2,5}|[A-Z][a-z]{1,4})'          # STR or Str, never str
_SIGNED = r'[+\-−–]\d+'
# a score is a number, or a dash where a template leaves it to the creature it
# copies ("STR —")
_SCORE = r'(\d+|[—–-])'
_MOD_PAREN = r'\(\s*(' + _SIGNED + r')\s*\)'
_CELL_RE = re.compile(
    r'^(' + _NAME + r')\s+' + _SCORE +
    r'(?:\s*' + _MOD_PAREN + r'|\s+(' + _SIGNED + r')\s+(' + _SIGNED + r'))?$')
_INLINE_CELL_RE = re.compile(
    r'(' + _NAME + r')\s+' + _SCORE + r'(?:\s*' + _MOD_PAREN + r')?')
_NAMES_LINE_RE = re.compile(r'^' + _NAME + r'(?:\s+' + _NAME + r')+$')
_VALUE_RE = re.compile(r'(\d+)(?:\s*' + _MOD_PAREN + r')?')

_RULE_RE = re.compile(r'^_{3,}$')
_SECTION_RE = re.compile(r'^-{3,}(?:\s+(.*?))?\s*$')
_HASH_RE = re.compile(r'^#{1,4}\s+(.*?)\s*#*\s*$')
_BOLD_ONLY_RE = re.compile(r'^\*\*(?!\*)(.+?)(?<!\*)\*\*:?$')
_ITALIC_ONLY_RE = re.compile(r'^(?:\*(?!\*)(.+?)(?<!\*)\*|_(?!_)(.+?)(?<!_)_)$')
_COLON_RE = re.compile(r'^([^:*\[\]/|]{1,40}?):(?:\s+(.*)|\s*)$')
_BOLD_LABEL_RE = re.compile(r'\*\*(?!\*)([^*]+?)(?<!\*)\*\*')
_ENTRY_MARKED_RE = re.compile(
    r'^(\*\*\*(?!\*)(.+?)(?<!\*)\*\*\*|\*\*(?!\*)(.+?)(?<!\*)\*\*'
    r'|_\*\*(.+?)\*\*_|\*\*_(.+?)_\*\*)\s*(.*)$')
_ENTRY_PLAIN_RE = re.compile(r'^([^.()]+?(?:\s*\([^()]*\))?\.)\s+(\S.*)$')
_TABLE_ROW_RE = re.compile(r'^\|.*\|$')
_ALIGN_ROW_RE = re.compile(r'^\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?$')
_OSR_SPLIT_RE = re.compile(
    r'[,;]\s+(?=(?:' + '|'.join(re.escape(a) for a in OSR_ABBR) + r')\b)')
_OSR_HEAD_RE = re.compile(
    r'^(' + '|'.join(re.escape(a) for a in OSR_ABBR) + r')\s+(\S.*)$')


def minus(text):
    """A hyphen or en dash used as a minus sign -> a true minus."""
    return re.sub(r'^[\-–]', MINUS, text.strip())


def modifier(score):
    """The 5e modifier for a score: 18 -> '+4', 3 -> '−4'. 0 is −5, the formula's
    floor rather than an error."""
    m = (int(score) - 10) // 2
    return f'+{m}' if m >= 0 else f'{MINUS}{-m}'


# --------------------------------------------------------------------- lines

def clean(line):
    """Strip a line's wrapper: trailing space, a leading `>` and a `- ` bullet.

    Returns None for a line that is only wrapper (the Homebrewery's `___` rules,
    `{{monster…`, `}}`, a lone `:` or `>`, a blank line).
    """
    s = line.strip()
    if s.startswith('>'):
        s = s[1:].strip()
    if s.startswith('- '):
        s = s[2:].strip()
    if not s or s == ':' or s == '}}' or s.startswith('{{') or _RULE_RE.match(s):
        return None
    return s


def _is_name_word(word, first):
    w = word.strip('"\'“”‘’')
    if not w:
        return True
    if not first and w.lower() in _MINOR:
        return True
    return w[0].isupper() or w[0].isdigit() and not first


def _plain_entry_name(s):
    """'Called by the Bell. While …' -> ('Called by the Bell.', 'While …'), or None.

    A name is a title-case phrase of up to six words at the start of the line,
    ending in a full stop (optionally after a parenthesis, as in
    'Toll (Recharge 5–6).'), with more text after it. Sentence case is never a
    name: 'Drowned voices whisper…' is prose.
    """
    m = _ENTRY_PLAIN_RE.match(s)
    if not m:
        return None
    name = m.group(1)
    head = re.sub(r'\([^()]*\)', '', name).rstrip('.').strip()
    words = head.split()
    if not words or len(words) > 6:
        return None
    if not all(_is_name_word(w, i == 0) for i, w in enumerate(words)):
        return None
    return name, m.group(2)


def entry(s, plain_names=True):
    """An entry line -> {'name', 'text'}: the name is pulled out of a leading
    `***Name.***` (or `**Name.**`), or found by its title case and full stop."""
    m = _ENTRY_MARKED_RE.match(s)
    if m:
        name = next(g for g in m.group(2, 3, 4, 5) if g is not None).strip()
        if name.endswith('.') or name.endswith('.)') or m.group(2) is not None:
            return {'name': name, 'text': m.group(6).strip()}
    if plain_names:
        found = _plain_entry_name(s)
        if found:
            return {'name': found[0], 'text': found[1].strip()}
    return {'name': '', 'text': s}


def _score_cells(s):
    """A line of scores -> [cell, ...] or None. Two or more cells make a row."""
    if '|' in s:
        pieces = [p.strip() for p in s.strip('|').split('|')]
        cells = []
        for p in pieces:
            m = _CELL_RE.match(p)
            if not m:
                return None
            name, score, mod, mod2, save = m.groups()
            cells.append({'name': name, 'score': score,
                          'mod': minus(mod or mod2 or ''),
                          'save': minus(save or '')})
        return cells if len(cells) >= 2 else None
    # no pipes: the cells are found by their names, and must cover the line
    cells, pos = [], 0
    for m in _INLINE_CELL_RE.finditer(s):
        if s[pos:m.start()].strip():
            return None
        cells.append({'name': m.group(1), 'score': m.group(2),
                      'mod': minus(m.group(3) or ''), 'save': ''})
        pos = m.end()
    if s[pos:].strip() or len(cells) < 2:
        return None
    return cells


def _colon_field(s):
    m = _COLON_RE.match(s)
    if not m:
        return None
    label = m.group(1).strip()
    if not label or len(label.split()) > 6:
        return None
    return {'label': label, 'value': (m.group(2) or '').strip()}


def _bold_fields(s):
    """'**AC** 9    **Initiative** −1 (9)' -> two fields; '**Speed** :: 25 ft.' -> one."""
    if not s.startswith('**') or s.startswith('***'):
        return None
    marks = list(_BOLD_LABEL_RE.finditer(s))
    if not marks or marks[0].start() != 0:
        return None
    first = marks[0].group(1).strip()
    if first.endswith('.'):
        return None                       # '**Wing Attack.** …' is an entry
    # a later bold span starts a new field only when it is a known label or set
    # off by a wide gap, so bold inside a value ("Common, **Draconic**") stays
    starts = [marks[0]]
    for m in marks[1:]:
        lab = m.group(1).strip().rstrip(':').strip()
        if (re.search(r'\s{2,}$', s[:m.start()])
                or any(lab == k for k in KNOWN_LABELS)) and not lab.endswith('.'):
            starts.append(m)
    fields = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(s)
        label = m.group(1).strip().rstrip(':').strip()
        value = s[m.end():end].strip()
        value = re.sub(r'^::?\s*', '', value).strip()
        fields.append({'label': label, 'value': value})
    return fields


def _known_field(s):
    for lab in KNOWN_LABELS:
        if s == lab:
            return {'label': lab, 'value': ''}
        if s.startswith(lab + ' ') or s.startswith(lab + '\t'):
            return {'label': lab, 'value': s[len(lab):].strip()}
    return None


def _osr_fields(s):
    if not _OSR_HEAD_RE.match(s):
        return None
    pieces = _OSR_SPLIT_RE.split(s)
    if len(pieces) < 3:
        return None
    out = []
    for p in pieces:
        m = _OSR_HEAD_RE.match(p.strip())
        if not m:
            return None
        out.append({'label': m.group(1), 'value': m.group(2).strip()})
    return out


def _section_name(s, after_name):
    m = _SECTION_RE.match(s)
    if m:
        return (m.group(1) or '').strip()
    if after_name:
        m = _HASH_RE.match(s)
        if m and s.startswith('##'):
            return m.group(1).strip()
    m = _BOLD_ONLY_RE.match(s)
    if m and not m.group(1).strip().endswith('.'):
        return m.group(1).strip().rstrip(':').strip()
    if s in KNOWN_SECTIONS:
        return s
    return None


def classify(line, at='head'):
    """One raw line, where it sits ('head' or 'section') -> its reading.

    {'kind': 'ignore'} | {'kind': 'section', 'name'}
    | {'kind': 'scores', 'cells'} | {'kind': 'fields', 'fields'}
    | {'kind': 'entry', 'name', 'text'}
    """
    raw = line.strip()
    if raw.startswith('\\') and re.match(r'^\\-{3,}', raw):
        # `\---` is a literal line: an entry, never a section
        return {'kind': 'entry', 'name': '', 'text': raw[1:]}
    s = clean(line)
    if s is None:
        return {'kind': 'ignore'}
    name = _section_name(s, after_name=True)
    if name is not None:
        if at == 'head' and _BOLD_ONLY_RE.match(s):
            inner = _BOLD_ONLY_RE.match(s).group(1).strip().rstrip(':').strip()
            if inner in KNOWN_LABELS:
                return {'kind': 'fields', 'fields': [{'label': inner, 'value': ''}]}
        return {'kind': 'section', 'name': name}
    if at == 'head':
        cells = _score_cells(s)
        if cells:
            return {'kind': 'scores', 'cells': cells}
        fields = _osr_fields(s)
        if fields:
            return {'kind': 'fields', 'fields': fields}
        fields = _bold_fields(s)
        if fields:
            return {'kind': 'fields', 'fields': fields}
        if not s.startswith('*'):
            if '|' in s:
                pieces = [_colon_field(p.strip()) for p in s.split('|')]
                if len(pieces) >= 2 and all(pieces):
                    return {'kind': 'fields', 'fields': pieces}
            f = _colon_field(s) or _known_field(s)
            if f:
                return {'kind': 'fields', 'fields': [f]}
    e = entry(s)
    return {'kind': 'entry', 'name': e['name'], 'text': e['text']}


# --------------------------------------------------------------------- blocks

def _join_score_lines(lines):
    """Turn the two multi-line score shapes into one `NAME n (m) | …` line each:
    a Markdown table (names row, alignment row, values row), and a line of names
    over a line of values (how a PDF pastes)."""
    out, i = [], 0
    while i < len(lines):
        s = clean(lines[i]) or ''
        nxt = [clean(x) or '' for x in lines[i + 1:i + 3]]
        if (_TABLE_ROW_RE.match(s) and len(nxt) == 2 and _ALIGN_ROW_RE.match(nxt[0])
                and _TABLE_ROW_RE.match(nxt[1])):
            names = [c.strip() for c in s.strip('|').split('|')]
            vals = [c.strip() for c in nxt[1].strip('|').split('|')]
            if (len(names) == len(vals) >= 2
                    and all(re.fullmatch(_NAME, n) for n in names)
                    and all(_VALUE_RE.fullmatch(v) for v in vals)):
                out.append(' | '.join(f'{n} {v}' for n, v in zip(names, vals)))
                i += 3
                continue
        if _NAMES_LINE_RE.match(s) and nxt and nxt[0]:
            names = s.split()
            vals = [m.group(0) for m in _VALUE_RE.finditer(nxt[0])]
            covered = re.sub(_VALUE_RE.pattern, '', nxt[0]).strip()
            if len(names) == len(vals) and not covered:
                out.append(' | '.join(f'{n} {v}' for n, v in zip(names, vals)))
                i += 2
                continue
        out.append(lines[i])
        i += 1
    return out


def _finish_scores(cells):
    """Fill in missing modifiers — only for the six 5e scores — and report
    whether every one was worked out."""
    names = [c['name'].upper() for c in cells]
    five_e = sorted(names) == sorted(FIVE_E)
    written = any(c['mod'] for c in cells)
    for c in cells:
        if not c['mod'] and five_e and c['score'].isdigit():
            c['mod'] = modifier(c['score'])
    return five_e and not written


def read(lines, name='', meta=''):
    """Raw fence lines (and the fence's `name=` / `meta=`) -> the model."""
    lines = _join_score_lines([ln for ln in lines])
    model = {'name': (name or '').strip(), 'meta': (meta or '').strip(),
             'fields': [], 'scores': [], 'auto': False, 'scores_at': 0,
             'sections': [{'name': '', 'entries': []}]}
    content = [ln for ln in lines if clean(ln) is not None or ln.strip().startswith('\\')]

    # the name, then the meta, from the first lines when the fence doesn't give them
    i = 0
    if content and not model['name']:
        s = clean(content[0]) or ''
        bare = s
        m = _HASH_RE.match(s)
        if m:
            bare = m.group(1)
        elif _BOLD_ONLY_RE.match(s):
            bare = _BOLD_ONLY_RE.match(s).group(1)
        reading = classify(content[0], 'head')
        is_name = (m is not None or _BOLD_ONLY_RE.match(s)
                   or (reading['kind'] == 'entry' and not reading['name']))
        if (is_name and bare.strip() and len(bare.split()) <= 8
                and bare.strip() not in KNOWN_SECTIONS
                and not bare.strip().rstrip(':') in KNOWN_LABELS):
            model['name'] = bare.strip()
            i = 1
    elif content and model['name']:
        s = clean(content[0]) or ''
        bare = (_BOLD_ONLY_RE.match(s) or _HASH_RE.match(s))
        if bare and bare.group(1).strip() == model['name']:
            i = 1                          # the name written twice: once is enough
    if i < len(content) and not model['meta']:
        s = clean(content[i]) or ''
        m = _ITALIC_ONLY_RE.match(s)
        if m:
            model['meta'] = (m.group(1) or m.group(2)).strip()
            i += 1
        elif (s.split()[:1] and s.split()[0].rstrip(',') in SIZES
                and classify(content[i], 'head')['kind'] == 'entry'):
            model['meta'] = s
            i += 1

    at = 'head'
    ended_by_field = False
    for line in content[i:]:
        r = classify(line, at)
        if ended_by_field and r['kind'] == 'entry':
            # Challenge then Proficiency Bonus: the head ends after the last of them
            again = classify(line, 'head')
            if again['kind'] == 'fields' and all(
                    f['label'].lower() in HEAD_ENDS for f in again['fields']):
                r = again
        kind = r['kind']
        if kind == 'ignore':
            continue
        ended_by_field = False
        if kind == 'scores':
            if not model['scores']:
                model['scores_at'] = len(model['fields'])   # where the row prints
            model['scores'].extend(r['cells'])
            continue
        if kind == 'fields':
            model['fields'].extend(r['fields'])
            if any(f['label'].lower() in HEAD_ENDS for f in r['fields']):
                at = 'section'
                ended_by_field = True
        elif kind == 'section':
            model['sections'].append({'name': r['name'], 'entries': []})
            at = 'section'
        else:
            model['sections'][-1]['entries'].append(
                {'name': r['name'], 'text': r['text']})
            if r['name']:
                at = 'section'

    if model['scores']:
        model['auto'] = _finish_scores(model['scores'])
    if not model['sections'][0]['entries'] and len(model['sections']) > 1:
        model['sections'].pop(0)
    elif not model['sections'][0]['entries'] and len(model['sections']) == 1:
        model['sections'] = []
    return model


# ------------------------------------------------------- unfenced Homebrewery

_V3_OPEN_RE = re.compile(r'^\s*\{\{\s*monster\b')
_LEGACY_HEAD_RE = re.compile(r'^\s*>\s*##\s+\S')


def wrap_unfenced(markdown):
    """Find Homebrewery stat blocks pasted with no fence and wrap each in one.

    Used only by the paste and import converter, never by the parser: a `>`
    line or a `___` rule in a novel must not become a stat block. V3's
    `{{monster …}}` runs to its `}}`; the legacy form is a `___` line followed
    by `> ## Name` and runs to the last `>` line.
    """
    lines = markdown.split('\n')
    out, i, in_fence = [], 0, False
    while i < len(lines):
        line = lines[i]
        if re.match(r'^\s*~~~', line):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if not in_fence and _V3_OPEN_RE.match(line):
            j = i + 1
            while j < len(lines) and lines[j].strip() != '}}':
                if re.match(r'^\s*~~~', lines[j]):
                    break
                j += 1
            if j < len(lines) and lines[j].strip() == '}}':
                out += ['~~~ statblock'] + lines[i:j + 1] + ['~~~']
                i = j + 1
                continue
        if (not in_fence and _RULE_RE.match(line.strip())
                and i + 1 < len(lines) and _LEGACY_HEAD_RE.match(lines[i + 1])):
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith('>'):
                j += 1
            out += ['~~~ statblock'] + lines[i:j] + ['~~~']
            i = j
            continue
        out.append(line)
        i += 1
    return '\n'.join(out)
