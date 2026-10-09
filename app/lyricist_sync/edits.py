"""Editing the lines of a synced / transcribed song (the review list), with undo/redo.

Every edit works on song.result['lines'] in place and keeps the lyrics box text (song.lyrics) in
step: the lyric lines (sung, non-repeat lines in order) are written back into the lyrics text,
keeping section tags like [Chorus], blank lines and lines the user added to the box by hand.

* Editing the words keeps the times. An edited line loses its amber "check" flag and the amber
  words (they described what Whisper heard, not the new text); the note column shows "✎ edited".
* A repeat (the same lyric line sung again, found by Auto-sync) shares its lyric line: changing
  the words of one occurrence changes all of them.
* History keeps snapshots per song for Ctrl+Z / Ctrl+Y.
Pure Python, no Qt: the app and the tests share it.
"""
import copy
import difflib
import re
import time

from . import instrumental as I

LOW_CONF = 0.6
_TAG = re.compile(r'\[[^\]]*\]|\([^)]*\)|\{[^}]*\}')
MIN_LEN = 0.2


# ---------------------------------------------------------------------------- history
def capture(song):
    res = song.result
    if res is not None:
        res = dict(res)
        res['lines'] = copy.deepcopy(res.get('lines') or [])
        if 'inst_deleted' in res:
            res['inst_deleted'] = list(res['inst_deleted'])
    return {'result': res, 'lyrics': song.lyrics, 'edited': bool(getattr(song, 'edited', False)),
            'status': getattr(song, 'status', '')}


def restore(song, state):
    song.result = state['result']
    song.lyrics = state['lyrics']
    song.edited = state['edited']
    if state.get('status'):
        song.status = state['status']
    song.dirty = True


class History:
    """Undo/redo snapshots of one song. push() before an edit; similar edits in a row (the same
    `tag`, e.g. nudging one line with the arrow keys) within `merge_s` share one undo step."""

    def __init__(self, limit=200, merge_s=1.5):
        self.undo_stack, self.redo_stack = [], []
        self.limit, self.merge_s = limit, merge_s
        self._last = (None, 0.0)

    def push(self, song, label='', tag=None, now=None):
        now = time.monotonic() if now is None else now
        if tag is not None and self._last[0] == tag and now - self._last[1] < self.merge_s and self.undo_stack:
            self._last = (tag, now)
            self.redo_stack.clear()
            return False
        self._last = (tag, now)
        st = capture(song)
        st['label'] = label
        self.undo_stack.append(st)
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()
        return True

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self, song):
        if not self.undo_stack:
            return None
        st = self.undo_stack.pop()
        cur = capture(song)
        cur['label'] = st.get('label', '')
        self.redo_stack.append(cur)
        restore(song, st)
        self._last = (None, 0.0)
        return st.get('label', '')

    def redo(self, song):
        if not self.redo_stack:
            return None
        st = self.redo_stack.pop()
        cur = capture(song)
        cur['label'] = st.get('label', '')
        self.undo_stack.append(cur)
        restore(song, st)
        self._last = (None, 0.0)
        return st.get('label', '')


def history(song):
    h = getattr(song, 'history', None)
    if h is None:
        h = song.history = History()
    return h


# ---------------------------------------------------------------------------- lyrics box
def lyric_lines(lines):
    """The lyric lines the result stands for: sung, non-repeat lines in order."""
    return [l['text'] for l in lines if not l.get('inst') and not l.get('repeat')]


def _is_lyric(raw):
    s = raw.strip()
    return bool(s) and not _TAG.fullmatch(s)


def rebuild_lyrics(box_text, old, new):
    """Apply the change old -> new (lists of lyric lines) to the lyrics box text, keeping tags,
    blank lines and lines that are only in the box. Returns the new text."""
    if old == new:
        return box_text
    raw = str(box_text or '').replace('\ufeff', '').splitlines()
    pos = [r for r, s in enumerate(raw) if _is_lyric(s)]
    L = [raw[r].strip() for r in pos]
    where = {}          # old index -> raw index
    for a, b, n in difflib.SequenceMatcher(None, L, old, autojunk=False).get_matching_blocks():
        for k in range(n):
            where[b + k] = pos[a + k]
    repl, before, after, tail = {}, {}, {}, []

    def put_after(i, items):
        """after the old line i-1 (or before the first mapped old line >= i, or at the end)"""
        if not items:
            return
        for j in range(i - 1, -1, -1):
            if j in where:
                after.setdefault(where[j], []).extend(items)
                return
        for j in range(i, len(old)):
            if j in where:
                before.setdefault(where[j], []).extend(items)
                return
        tail.extend(items)

    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == 'equal':
            continue
        olds, news = list(range(i1, i2)), new[j1:j2]
        pending = []
        last = None
        for k, i in enumerate(olds):
            item = [news[k]] if k < len(news) else []
            if i in where:
                repl[where[i]] = pending + item
                pending = []
                last = where[i]
            else:
                pending += item
        extra = news[len(olds):] if len(news) > len(olds) else []
        if last is not None:
            repl[last] = repl[last] + pending + extra
        else:
            put_after(i1, pending + extra)
    out = []
    for r, s in enumerate(raw):
        out += before.get(r, [])
        out += repl[r] if r in repl else [s]
        out += after.get(r, [])
    out += tail
    return '\n'.join(out)


def renumber(lines):
    """idx = position of the line in the lyric lines; repeats follow their first occurrence."""
    first = {}
    k = 0
    for l in lines:
        if l.get('inst'):
            continue
        if not l.get('repeat'):
            if l.get('idx') is not None:
                first.setdefault(l['idx'], k)
            l['_new'] = k
            k += 1
    for l in lines:
        if l.get('inst'):
            continue
        if l.get('repeat'):
            n = first.get(l.get('idx'))
            if n is None:
                l['repeat'] = False
                l['_new'] = k
                k += 1
                n = l['_new']
            l['idx'] = n
        else:
            l['idx'] = l.pop('_new')
        l.pop('_new', None)


def sync_lyrics(song, before_lines):
    """Write the lyric lines of song.result back into song.lyrics (old lyric lines: before_lines)."""
    lines = song.result['lines']
    song.lyrics = rebuild_lyrics(song.lyrics, before_lines, lyric_lines(lines))
    renumber(lines)
    song.edited = True
    song.dirty = True


# ---------------------------------------------------------------------------- line helpers
def mark_edited(l, why='edited by hand'):
    l['edited'] = True
    l['conf'] = 1.0
    l['why'] = [why]
    l['flag'] = ''
    l.pop('guessed', None)
    l.pop('words', None)        # amber words described Whisper's text, not this one


def new_line(text, start, end, **kw):
    l = {'text': text, 'start': round(max(0.0, start), 3), 'end': round(max(end, start), 3), 'idx': None,
         'repeat': False, 'flag': '', 'conf': 1.0, 'why': ['added by hand'], 'edited': True}
    l.update(kw)
    return l


def _clean(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def _fix_neighbours(lines, row):
    """After a time change of lines[row]: no overlap with the lines around it."""
    l = lines[row]
    l['end'] = round(max(l['end'], l['start']), 3)
    if row > 0 and lines[row - 1]['end'] > l['start']:
        p = lines[row - 1]
        p['end'] = round(max(p['start'], l['start']), 3)
        p.pop('end0', None)
    if row + 1 < len(lines) and l['end'] > lines[row + 1]['start'] and lines[row + 1]['start'] >= l['start']:
        l['end'] = round(lines[row + 1]['start'], 3)


# ---------------------------------------------------------------------------- edits
def set_text(song, row, text):
    """New words for line `row` (times kept). Repeats of the same lyric line change too.
    Returns the number of lines changed (0 when nothing changed or the text is empty)."""
    lines = song.result['lines']
    text = _clean(text)
    l = lines[row]
    if not text or text == l['text'] or l.get('inst'):
        return 0
    before = lyric_lines(lines)
    old, idx = l['text'], l.get('idx')
    same = [x for x in lines if not x.get('inst') and x is not l and idx is not None and x.get('idx') == idx
            and x['text'] == old and (x.get('repeat') or l.get('repeat'))]
    n = 0
    for x in [l] + same:
        x['text'] = text
        mark_edited(x)
        n += 1
    sync_lyrics(song, before)
    return n


def set_times(song, row, start=None, end=None):
    """New start and/or end for line `row` (seconds). The lines around it are kept from overlapping."""
    lines = song.result['lines']
    l = lines[row]
    if start is not None:
        l['start'] = round(max(0.0, start), 3)
    if end is not None:
        l['end'] = round(max(end, l['start']), 3)
        l.pop('end0', None)
    elif row + 1 < len(lines):
        l['end'] = min(l['end'], max(l['start'], lines[row + 1]['start']))
    if l.get('inst'):
        l['auto'] = False
    else:
        l['manual'] = True
    _fix_neighbours(lines, row)
    song.edited = True
    song.dirty = True


def split_point(text, cursor=None):
    """Character position to split `text` at: the text cursor if given (moved to a word
    boundary), else the word boundary closest to the middle. None when it can't be split."""
    text = text.strip()
    bounds = [m.start() for m in re.finditer(r'\s+', text)]
    if not bounds:
        return None
    target = len(text) / 2 if cursor is None else cursor
    return min(bounds, key=lambda b: (abs(b - target), b))


def split(song, row, cursor=None, at_time=None):
    """Split line `row` into two lines at the text position `cursor` (or the middle word).
    The time is divided in proportion to the characters, or at `at_time` when it is inside the
    line. Returns the row of the second line, or None."""
    lines = song.result['lines']
    l = lines[row]
    if l.get('inst'):
        return None
    k = split_point(l['text'], cursor)
    if k is None:
        return None
    a, b = l['text'][:k].strip(), l['text'][k:].strip()
    if not a or not b:
        return None
    before = lyric_lines(lines)
    s, e = l['start'], l['end']
    if at_time is not None and s + MIN_LEN / 2 < at_time < e - MIN_LEN / 2:
        t = at_time
    else:
        t = s + (e - s) * len(a) / float(len(a) + len(b))
    t = round(t, 3)
    second = new_line(b, t, e, why=['split by hand'])
    l['text'], l['end'] = a, t
    l.pop('end0', None)
    mark_edited(l, 'split by hand')
    l['repeat'] = False
    lines.insert(row + 1, second)
    sync_lyrics(song, before)
    return row + 1


def can_merge(lines, row):
    return 0 <= row < len(lines) - 1 and not lines[row].get('inst') and not lines[row + 1].get('inst')


def merge(song, row):
    """Merge line `row` with the next one (start of the first, end of the second)."""
    lines = song.result['lines']
    if not can_merge(lines, row):
        return False
    before = lyric_lines(lines)
    a, b = lines[row], lines[row + 1]
    a['text'] = _clean(a['text'] + ' ' + b['text'])
    a['end'] = max(a['end'], b['end'])
    a.pop('end0', None)
    a['repeat'] = False
    mark_edited(a, 'merged by hand')
    del lines[row + 1]
    sync_lyrics(song, before)
    return True


def insert(song, row, below=True, text='New line', duration=None):
    """A new sung line above or below `row` in the gap there (or in the second / first half of
    `row` when there is no gap). Returns the new row."""
    lines = song.result['lines']
    dur = duration or song.result.get('duration') or 0.0
    before = lyric_lines(lines)
    if not lines:
        lines.append(new_line(text, 0.0, min(dur or 2.0, 2.0)))
        sync_lyrics(song, before)
        return 0
    ref = lines[row]
    if below:
        nxt = lines[row + 1]['start'] if row + 1 < len(lines) else (dur or ref['end'] + 2.0)
        s, e = ref['end'], min(nxt, ref['end'] + 3.0)
        if e - s < 0.3:     # no gap: take the second half of `row`
            s = round((ref['start'] + ref['end']) / 2, 3)
            e = max(ref['end'], s + 0.1)
            ref['end'] = s
            ref.pop('end0', None)
        at = row + 1
    else:
        prv = lines[row - 1]['end'] if row > 0 else 0.0
        s, e = max(prv, ref['start'] - 3.0), ref['start']
        if e - s < 0.3:     # no gap: take the first half of `row`
            s = ref['start']
            e = round((ref['start'] + ref['end']) / 2, 3)
            ref['start'] = e
        at = row
    lines.insert(at, new_line(text, s, e))
    sync_lyrics(song, before)
    return at


def delete(song, row):
    """Delete any line (an auto ♪ line is remembered, so it stays deleted)."""
    lines = song.result['lines']
    if not (0 <= row < len(lines)):
        return False
    before = lyric_lines(lines)
    if lines[row].get('inst'):
        I.delete(song.result, row)
    else:
        l = lines.pop(row)
        if not l.get('repeat') and l.get('idx') is not None:   # its repeats go with it from the lyrics
            for x in lines:
                if x.get('repeat') and x.get('idx') == l['idx'] and x['text'] == l['text']:
                    x['repeat'] = False      # the next occurrence becomes the lyric line
                    break
    sync_lyrics(song, before)
    return True


def mark_inst(song, row, settings=None):
    """Make a sung line a ♪ line (kept by hand; the words are remembered for Unmark)."""
    lines = song.result['lines']
    l = lines[row]
    if l.get('inst'):
        return False
    before = lyric_lines(lines)
    sym = I.settings_of(settings)['inst_symbol']
    lines[row] = I.make_line(sym, l['start'], l['end'], auto=False, kind='manual')
    lines[row]['text0'] = l['text']
    sync_lyrics(song, before)
    return True


def unmark_inst(song, row, text='New line'):
    """Make a ♪ line a sung line again (its old words, or `text`). Returns the text used."""
    lines = song.result['lines']
    l = lines[row]
    if not l.get('inst'):
        return None
    before = lyric_lines(lines)
    if l.get('auto') and l.get('key'):
        song.result.setdefault('inst_deleted', []).append(l['key'])
    t = l.get('text0') or text
    lines[row] = new_line(t, l['start'], l['end'], why=['was a ♪ line'])
    sync_lyrics(song, before)
    return t


# ---------------------------------------------------------------------------- re-align one line
def realign_window(lines, row, duration):
    """(lo, hi) seconds the aligner may place line `row` in: from the end of the line before to
    the start of the line after (widened to their start / end when that is shorter than 0.6 s)."""
    prev = lines[row - 1] if row > 0 else None
    nxt = lines[row + 1] if row + 1 < len(lines) else None
    lo = prev['end'] if prev else 0.0
    hi = nxt['start'] if nxt else (duration or lines[row]['end'] + 5.0)
    if hi - lo < 0.6:
        lo = prev['start'] + 0.05 if prev else 0.0
        hi = nxt['end'] if nxt else hi
    lo = min(lo, lines[row]['start'])
    hi = max(hi, lines[row]['end'])
    return round(max(0.0, lo), 3), round(hi, 3)


def apply_realign(song, row, start, end, conf=None, why=None):
    lines = song.result['lines']
    l = lines[row]
    l['start'], l['end'] = round(start, 3), round(max(end, start + 0.1), 3)
    l.pop('end0', None)
    l['manual'] = True
    if conf is not None:
        l['conf'] = conf
        l['why'] = ['re-aligned'] + list(why or [])
    _fix_neighbours(lines, row)
    song.edited = True
    song.dirty = True


def is_low(l):
    c = l.get('conf')
    return c is not None and c < LOW_CONF
