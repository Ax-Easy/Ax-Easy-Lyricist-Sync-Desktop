"""Instrumental (♪) lines.

After a sync the engine reports where the vocals stem is active (result['vocals']). A gap
between two sung lines (or before the first / after the last line) that is longer than the
threshold gets a ♪ line, so a lyric display shows "♪" during intros, solos and breaks instead
of the previous line hanging on screen.

* The gap starts where the previous line's singing really stops: the end of the vocal-activity
  region its last word is in (a held note), at most HOLD seconds past the aligned end. The
  previous line's end is moved there.
* Short sounds without a lyric line in the gap (hums, ad-libs, backing "ohh"s) don't break it:
  the ♪ marks the part with no lyric line to show.
* The ♪ line ends LEAD seconds before the next sung line; an outro ♪ runs to the end of the song.
* ♪ lines live in result['lines'] with 'inst': True ('auto' for generated ones). They are never
  sent to the aligner. Manual ♪ lines are kept; deleted auto ones are remembered in
  result['inst_deleted'] so a re-apply doesn't bring them back.
Pure Python, no Qt: the CLI, the app and the tests share it.
"""

SYMBOLS = ['♪', '♪♪', '♫', '♪ instrumental ♪']
DEFAULTS = {'inst_on': True, 'inst_symbol': '♪', 'inst_gap': 8.0, 'inst_edges': True}
GAP_MIN, GAP_MAX = 3.0, 30.0
LEAD = 0.3   # the ♪ ends this long before the next sung line
HOLD = 3.0   # a held last note may extend a line by at most this much
MIN_LEN = 1.0


def is_inst(line):
    return bool(line.get('inst'))


def sung(lines):
    return [l for l in lines if not l.get('inst')]


def settings_of(settings=None):
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (settings or {}).items() if k in DEFAULTS and v is not None})
    try:
        s['inst_gap'] = min(GAP_MAX, max(GAP_MIN, float(s['inst_gap'])))
    except (TypeError, ValueError):
        s['inst_gap'] = DEFAULTS['inst_gap']
    if s['inst_symbol'] not in SYMBOLS and not str(s['inst_symbol']).strip():
        s['inst_symbol'] = DEFAULTS['inst_symbol']
    return s


def vocal_end(end, limit, vocals, hold=HOLD):
    """Where singing that is going on at `end` stops (the end of its vocal-activity region),
    clamped to [end, min(end + hold, limit)]."""
    g = end
    for a, b in vocals or ():
        if a <= end + 0.1 and b >= end - 0.1:
            g = max(g, min(b, end + hold))
    return min(g, limit) if limit is not None else g


def find_gaps(lines, vocals, duration, settings=None):
    """[(kind, start, end, prev_index)] for the instrumental gaps between sung `lines`
    (sorted by start). kind is 'intro', 'break' or 'outro'; prev_index the sung line before."""
    st = settings_of(settings)
    thr = st['inst_gap']
    s = sorted(sung(lines), key=lambda l: l['start'])
    if not s:
        return []
    out = []
    if st['inst_edges'] and s[0]['start'] >= thr:
        out.append(('intro', 0.0, s[0]['start'], None))
    for i in range(len(s) - 1):
        g0 = vocal_end(s[i]['end'], s[i + 1]['start'], vocals)
        if s[i + 1]['start'] - g0 >= thr:
            out.append(('break', g0, s[i + 1]['start'], i))
    if st['inst_edges'] and duration:
        g0 = vocal_end(s[-1]['end'], duration, vocals)
        if duration - g0 >= thr:
            out.append(('outro', g0, duration, len(s) - 1))
    return out


def gap_key(kind, prev_index):
    """Stable name of a gap (survives nudging the lines around it): 'intro', 'outro', or
    'break@N' for the gap before the N-th sung line (1-based)."""
    return kind if kind in ('intro', 'outro') else 'break@%d' % (prev_index + 2)


def make_line(symbol, start, end, auto=True, kind='manual', key=None):
    return {'text': symbol, 'start': round(start, 3), 'end': round(max(end, start + 0.1), 3), 'inst': True,
            'auto': auto, 'kind': kind, 'key': key, 'conf': None, 'why': []}


def apply(result, settings=None):
    """Recompute the auto ♪ lines of `result` in place (manual ♪ lines are kept, sung lines
    keep their order). Returns the number of ♪ lines now in the result."""
    if not result or not result.get('lines'):
        return 0
    st = settings_of(settings)
    lines = result['lines']
    s = sorted(sung(lines), key=lambda l: l['start'])
    manual = [l for l in lines if l.get('inst') and not l.get('auto')]
    for l in s:  # undo the end changes of a previous apply
        if 'end0' in l:
            l['end'] = l.pop('end0')
    for m in manual:
        m['text'] = st['inst_symbol']
    new = []
    if st['inst_on']:
        deleted = set(result.get('inst_deleted') or ())
        for kind, g0, g1, i in find_gaps(s, result.get('vocals'), result.get('duration'), st):
            key = gap_key(kind, i)
            if key in deleted or any(m['start'] < g1 and m['end'] > g0 for m in manual):
                continue
            end = g1 if kind == 'outro' else g1 - LEAD
            if end - g0 < MIN_LEN:
                continue
            if i is not None and abs(s[i]['end'] - g0) > 0.0005:
                s[i]['end0'] = s[i]['end']
                s[i]['end'] = round(g0, 3)
            new.append(make_line(st['inst_symbol'], g0, end, True, kind, key))
    # sung lines keep their own order (a repeat may start before the line listed above it
    # only after a hand edit); ♪ lines are slotted in by start time
    inst = sorted(manual + new, key=lambda l: l['start'])
    out, k = [], 0
    for l in sung(lines):
        while k < len(inst) and inst[k]['start'] <= l['start']:
            out.append(inst[k])
            k += 1
        out.append(l)
    out.extend(inst[k:])
    result['lines'] = out
    return len(inst)


def delete(result, row):
    """Remove the ♪ line at `row`; an auto one is remembered so it stays deleted."""
    l = result['lines'][row]
    if not l.get('inst'):
        return False
    if l.get('auto') and l.get('key'):
        result.setdefault('inst_deleted', []).append(l['key'])
    del result['lines'][row]
    return True


def insert(result, at, settings=None, length=None):
    """Add a manual ♪ line starting at `at` seconds, ending just before the next sung line
    (or after `length` s / at the end of the song). The sung line playing at `at` is ended there.
    Returns the new row."""
    st = settings_of(settings)
    lines = result['lines']
    nxt = min((l['start'] for l in lines if l['start'] > at + 0.05), default=None)
    end = (nxt - LEAD) if nxt is not None else (result.get('duration') or at + (length or 4.0))
    if length:
        end = min(end, at + length)
    if end - at < 0.2:
        end = at + 0.2 if nxt is None else max(at + 0.1, nxt - 0.05)
    for l in sung(lines):
        if l['start'] < at < l['end']:
            l['end'] = round(at, 3)
    line = make_line(st['inst_symbol'], at, end, auto=False)
    lines.append(line)
    apply(result, st)
    return result['lines'].index(line)


def summary(result):
    return [(l.get('kind'), l['start'], l['end']) for l in (result or {}).get('lines', []) if l.get('inst')]
