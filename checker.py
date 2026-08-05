"""Continuity checker — two-tier analysis of a parsed manuscript.

Tier 1: rule-based (stdlib only, no API cost).
Tier 2: LLM via Claude API (requires ANTHROPIC_API_KEY in environment).

Both tiers consume the dict returned by manuscript.parse_markdown() directly.
"""

import os
import re
import json
import html
import difflib
import collections

# ---------------------------------------------------------------------------
# Shared utilities

_TAG_RE = re.compile(r'<[^>]+>')

# Two markers stand for a gap between words rather than for formatting: the line
# break between verses, and the divider between table cells. Stripping them like
# a <b> tag runs the words either side together — "Ada|Lovelace" becomes
# "AdaLovelace", which then reads as a brand-new capitalised name to the variant
# check and reaches the LLM summary in that state.
_GAP_RE = re.compile(r'<br\s*/?>|' + re.escape('<cell/>'))


def _plain(markup: str) -> str:
    """Strip ReportLab XML tags and unescape HTML entities to get plain text."""
    return html.unescape(_TAG_RE.sub('', _GAP_RE.sub(' ', markup)))


def _chapter_paras(chapter: dict) -> list:
    """Return plain-text strings for every readable block in a chapter."""
    texts = []
    for block in chapter['blocks']:
        if block[0] in ('para', 'subhead'):
            texts.append(_plain(block[1]))
        elif block[0] == 'doc_block':
            for sub in block[1]:
                texts.append(_plain(sub[1]))
    return texts


def _loc(ch_idx: int, chapter: dict) -> str:
    title = chapter.get('title')
    label = f'Chapter {ch_idx + 1}'
    if title:
        label += f' · “{title}”'
    return label


# ---------------------------------------------------------------------------
# Tier 1 — rule-based checks

_STOPWORDS = {
    'about', 'after', 'also', 'away', 'back', 'been', 'before', 'both',
    'came', 'chapter', 'come', 'could', 'down', 'each', 'even', 'every',
    'from', 'have', 'here', 'into', 'just', 'know', 'like', 'made',
    'more', 'most', 'once', 'only', 'over', 'part', 'said', 'should',
    'some', 'still', 'such', 'than', 'that', 'them', 'then', 'there',
    'these', 'they', 'this', 'those', 'very', 'well', 'went', 'were',
    'what', 'when', 'where', 'which', 'while', 'will', 'with', 'would',
    'your',
}

_CAP_WORD_RE  = re.compile(r'\b([A-Z][a-z]{2,})\b')
_SENT_SPLIT   = re.compile(r'(?<=[.!?])\s+')


def _check_duplicate_titles(parsed: dict) -> list:
    issues = []
    seen: dict = {}
    for ch_idx, ch in enumerate(parsed['chapters']):
        title = (ch.get('title') or '').strip()
        if not title:
            continue
        key = title.lower()
        if key in seen:
            issues.append({
                'label':    f'Duplicate chapter title: “{title}”',
                'severity': 'warn',
                'detail':   f'Same title used in both Chapter {seen[key] + 1} and Chapter {ch_idx + 1}.',
                'location': _loc(ch_idx, ch),
                'tier': 1,
            })
        else:
            seen[key] = ch_idx
    return issues


def _check_thin_chapters(parsed: dict) -> list:
    issues = []
    for ch_idx, ch in enumerate(parsed['chapters']):
        # A chapter's text can live entirely inside a document block — a poem, a
        # letter, a table — and in a collection of verse every chapter does.
        # Counting only loose paragraphs called all of them empty.
        has_text = any(
            b[0] == 'para'
            or (b[0] == 'doc_block' and any((sub[1] or '').strip() for sub in b[1]))
            for b in ch['blocks'])
        if not has_text:
            issues.append({
                'label':    f'Empty chapter: {_loc(ch_idx, ch)}',
                'severity': 'warn',
                'detail':   'This chapter contains no paragraph text.',
                'location': _loc(ch_idx, ch),
                'tier': 1,
            })
    return issues


def _check_name_variants(parsed: dict) -> list:
    """Flag capitalized tokens with suspiciously similar spellings."""
    token_count: collections.Counter = collections.Counter()
    token_first_loc: dict = {}

    for ch_idx, ch in enumerate(parsed['chapters']):
        loc = _loc(ch_idx, ch)
        for para in _chapter_paras(ch):
            for word in _CAP_WORD_RE.findall(para):
                if word.lower() in _STOPWORDS:
                    continue
                token_count[word] += 1
                if word not in token_first_loc:
                    token_first_loc[word] = loc

    # Only examine tokens that appear 2+ times to reduce sentence-start noise
    candidates = [t for t, c in token_count.items() if c >= 2][:200]

    issues = []
    seen_pairs: set = set()

    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            if abs(len(a) - len(b)) > 4:
                continue
            a_low, b_low = a.lower(), b.lower()
            if a_low == b_low:
                continue
            if difflib.SequenceMatcher(None, a_low, b_low).ratio() >= 0.85:
                pair = frozenset({a, b})
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    issues.append({
                        'label':    f'Name variant: “{a}” / “{b}”',
                        'severity': 'warn',
                        'detail':   (
                            f'“{a}” appears {token_count[a]}×'
                            f' (first at {token_first_loc[a]}); '
                            f'“{b}” appears {token_count[b]}×'
                            f' (first at {token_first_loc[b]}). '
                            f'Possible misspelling of the same name.'
                        ),
                        'location': token_first_loc[a],
                        'tier': 1,
                    })
    return issues


def _check_pov_drift(parsed: dict) -> list:
    """Flag chapters whose pronoun distribution diverges from the book-wide dominant POV."""
    _HE_RE   = re.compile(r'\b(he|him|his)\b',             re.I)
    _SHE_RE  = re.compile(r'\b(she|her|hers)\b',           re.I)
    _THEY_RE = re.compile(r'\b(they|them|their|theirs)\b', re.I)

    def _counts(text):
        return (len(_HE_RE.findall(text)),
                len(_SHE_RE.findall(text)),
                len(_THEY_RE.findall(text)))

    chapter_data = []
    totals = [0, 0, 0]
    for ch_idx, ch in enumerate(parsed['chapters']):
        text = ' '.join(_chapter_paras(ch))
        c = _counts(text)
        chapter_data.append((ch_idx, ch, c))
        for i in range(3):
            totals[i] += c[i]

    book_total = sum(totals)
    if book_total < 20:
        return []

    labels = ['he/him/his', 'she/her/hers', 'they/them/their']
    book_dom = totals.index(max(totals))
    if totals[book_dom] / book_total < 0.55:
        return []  # no single dominant POV — might be omniscient/multi-POV by design

    issues = []
    for ch_idx, ch, c in chapter_data:
        ch_total = sum(c)
        if ch_total < 10:
            continue
        ch_dom = c.index(max(c))
        if ch_dom != book_dom and c[ch_dom] / ch_total > 0.60:
            issues.append({
                'label':    f'POV pronoun shift in {_loc(ch_idx, ch)}',
                'severity': 'warn',
                'detail':   (
                    f'Book-wide dominant: {labels[book_dom]}'
                    f' ({totals[book_dom]} uses,'
                    f' {round(100 * totals[book_dom] / book_total)} %). '
                    f'This chapter: {labels[ch_dom]}'
                    f' ({c[ch_dom]} uses,'
                    f' {round(100 * c[ch_dom] / ch_total)} %). '
                    f'Possible POV inconsistency.'
                ),
                'location': _loc(ch_idx, ch),
                'tier': 1,
            })
    return issues


def _check_repeated_sentences(parsed: dict) -> list:
    """Flag sentences (≥10 words) that appear verbatim in 2+ different chapters."""
    sentence_chapters: dict = collections.defaultdict(list)

    for ch_idx, ch in enumerate(parsed['chapters']):
        for para in _chapter_paras(ch):
            for sent in _SENT_SPLIT.split(para):
                words = sent.split()
                if len(words) < 10:
                    continue
                key = ' '.join(w.lower().strip('.,!?;:"\'') for w in words)
                if ch_idx not in sentence_chapters[key]:
                    sentence_chapters[key].append(ch_idx)

    issues = []
    for sent_key, ch_list in sentence_chapters.items():
        if len(ch_list) >= 2:
            titles = [_loc(idx, parsed['chapters'][idx]) for idx in ch_list[:3]]
            display = sent_key[:72] + '…' if len(sent_key) > 72 else sent_key
            issues.append({
                'label':    f'Repeated sentence: “{display}”',
                'severity': 'warn',
                'detail':   (
                    f'Identical text in: {", ".join(titles)}'
                    f'{"…" if len(ch_list) > 3 else ""}. Possible copy-paste.'
                ),
                'location': titles[0],
                'tier': 1,
            })
    return issues[:10]


def run_tier1(parsed: dict) -> list:
    """Run all rule-based checks. Returns a list of issue dicts."""
    issues = []
    issues += _check_thin_chapters(parsed)
    issues += _check_duplicate_titles(parsed)
    issues += _check_name_variants(parsed)
    issues += _check_pov_drift(parsed)
    issues += _check_repeated_sentences(parsed)
    return issues


# ---------------------------------------------------------------------------
# Tier 2 — LLM analysis via Claude

_DEFAULT_MODEL = 'claude-haiku-4-5-20251001'

_SYSTEM_PROMPT = """\
You are a professional continuity editor reviewing a book manuscript.
Analyze the chapter summaries and identify continuity issues such as:
- Character physical description contradictions across chapters
- Timeline or chronology contradictions
- Location or setting description conflicts
- Character name, role, or relationship inconsistencies
- Any other notable continuity problems a copyeditor would flag

Respond ONLY with a valid JSON array. Each element must be an object with:
  "label": short title (max 80 chars)
  "detail": clear explanation citing which chapters conflict
  "location": e.g. "Chapter 2 vs. Chapter 5"

If you find no issues, return an empty array: []
Do not include markdown fencing, explanation, or anything outside the JSON array.\
"""


def _build_summary(parsed: dict, words_per_chapter: int = 150) -> str:
    lines = [f'{len(parsed["chapters"])} chapters total\n']
    for ch_idx, ch in enumerate(parsed['chapters']):
        part = ch.get('part')
        if part:
            part_label = f'Part {part["number"]}'
            if part.get('title'):
                part_label += f': {part["title"]}'
            lines.append(f'[{part_label}]')
        title = ch.get('title') or '(untitled)'
        lines.append(f'Chapter {ch_idx + 1}: {title}')
        paras = _chapter_paras(ch)
        if paras:
            excerpt = ' '.join(' '.join(paras).split()[:words_per_chapter])
            lines.append(excerpt)
        else:
            lines.append('(no content)')
        lines.append('')
    return '\n'.join(lines)


def run_tier2(parsed: dict, api_key: str) -> list:
    """Run LLM-based continuity analysis. Returns a list of issue dicts."""
    model = os.environ.get('CONTINUITY_MODEL', _DEFAULT_MODEL)

    try:
        import anthropic
    except ImportError:
        return [{
            'label':    'anthropic package not installed',
            'severity': 'info',
            'detail':   'Run: pip install anthropic  (then restart the app)',
            'location': '',
            'tier': 2,
        }]

    summary = _build_summary(parsed)
    user_msg = f'Manuscript summary:\n\n{summary}\n\nIdentify all continuity issues.'

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': user_msg}],
        )
        raw = response.content[0].text.strip()
        # Tolerate accidental markdown fencing
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$',          '', raw, flags=re.MULTILINE)
        findings = json.loads(raw)
        issues = []
        for f in findings:
            if isinstance(f, dict) and 'label' in f:
                issues.append({
                    'label':    str(f.get('label', ''))[:120],
                    'severity': 'warn',
                    'detail':   str(f.get('detail', '')),
                    'location': str(f.get('location', '')),
                    'tier': 2,
                })
        return issues
    except Exception as exc:
        return [{
            'label':    'Claude analysis failed',
            'severity': 'info',
            'detail':   f'{type(exc).__name__}: {exc}',
            'location': '',
            'tier': 2,
        }]
