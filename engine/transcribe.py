"""Transcribe mode: Whisper segments/words -> lyric lines (pure Python, no torch; unit-tested).

Anti-hallucination, on top of the Whisper options the engine uses (VAD-gated clips,
condition_on_previous_text=False, temperature fallback, compression/logprob/no-speech thresholds):
  * a segment is dropped when the vocals stem is (almost) silent under it, when Whisper itself
    thinks there is no speech and is unsure, when it is a known filler/credit phrase ("Thank you
    for watching", "Subtitles by ...", "Υπότιτλοι ..."), when it has no letters, or when it is the
    same text again and again in a row (the classic loop) beyond what a chorus would do;
  * words falling outside vocal activity are dropped.
Lines follow the singing: a new line at every Whisper segment, at pauses longer than PAUSE, and
before a line would get longer than MAX_CHARS (preferring a split after punctuation).
"""
import math
import re
import unicodedata

PAUSE = 0.6
MAX_CHARS = 42
LOW_WORD = 0.45      # word probability below this: amber word
LOW_LINE = 0.6       # line confidence below this: amber line (like the aligner's 'check')

FILLER = [
    r'thank(s| you) (so much )?for watching', r'subtitles? (by|created|made)', r'subscribe', r'amara\.org',
    r'transcribed by', r'captions? by', r'www\.', r'\.com\b', r'υπότιτλοι', r'ευχαριστώ (πολύ )?(που|για)',
    r'please like', r'see you next time', r'^\W*(music|applause|laughter)\W*$', r'^\W*(μουσική)\W*$',
]
_FILLER = [re.compile(p, re.I) for p in FILLER]


def norm(text):
    """Lowercase letters/digits only (accents removed): for WER and repeat checks."""
    t = unicodedata.normalize('NFKD', text.lower())
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = t.replace('’', "'").replace('ς', 'σ')
    return [w.strip("'") for w in re.sub(r"[^\w' ]+", ' ', t).replace('_', ' ').split() if w.strip("'")]


def overlap(a, b, regions):
    """Seconds of vocal activity inside [a, b]."""
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in regions or ())


HUM = re.compile(r"^(h*m+h*|h+m+|m+|hm+|mm+h*m*|uh+|um+|hmm+)$", re.I)


VOCALISE = re.compile(r"^(\s*(i|a|ah+|oh+|uh+|o+|e+)\s*(\.\.\.|…)\s*)+$", re.I)


def is_filler(text):
    t = text.strip()
    if not any(c.isalpha() for c in t):
        return True
    toks = norm(t)
    if toks and all(HUM.match(x) for x in toks):   # humming ("Hmmm mmm") is not lyrics
        return True
    if VOCALISE.match(t):   # "I... I..." / "Ah…": what Whisper writes for a sung vowel
        return True
    return any(p.search(t) for p in _FILLER)


def _mean_p(s):
    ps = [w.get('probability', 1.0) for w in s.get('words') or []]
    return sum(ps) / len(ps) if ps else 1.0


def filter_segments(segments, vocals=None, log=None):
    """Keep the segments that look sung. Returns (kept, dropped[(segment, reason)])."""
    kept, dropped = [], []
    run_text, run_n = None, 0
    for s in segments:
        text = s.get('text', '').strip()
        dur = max(0.01, s['end'] - s['start'])
        reason = None
        if is_filler(text):
            reason = 'filler or no words'
        elif vocals is not None and overlap(s['start'], s['end'], vocals) / dur < 0.2:
            reason = 'no vocals under it'
        elif s.get('no_speech_prob', 0) > 0.6 and s.get('avg_logprob', 0) < -0.8:
            reason = 'no speech (Whisper)'
        elif s.get('avg_logprob', 0) < -1.5 or (_mean_p(s) < 0.25 and s.get('avg_logprob', 0) < -0.7):
            reason = 'gibberish (avg log-prob %.2f, word probability %.2f)' % (s.get('avg_logprob', 0), _mean_p(s))
        elif s.get('compression_ratio', 1) > 2.6:
            reason = 'repetitive (compression %.1f)' % s['compression_ratio']
        key = ' '.join(norm(text))
        if reason is None:
            if key and key == run_text:
                run_n += 1
                # a chorus line sung 2-3 times in a row is normal; more than 4 identical short
                # segments back to back is Whisper looping
                if run_n >= 4 and len(key) < 40:
                    reason = 'repeated %d times in a row' % (run_n + 1)
            else:
                run_text, run_n = key, 0
        if reason:
            dropped.append((s, reason))
            if log:
                log('transcribe: dropped %.1f-%.1f "%s" (%s)' % (s['start'], s['end'], text[:50], reason))
        else:
            kept.append(s)
    return kept, dropped


def _words_of(seg, vocals=None):
    out = []
    for w in seg.get('words') or []:
        t = w['word'].strip()
        if not t:
            continue
        # Whisper marks a new word with a leading space; '-cold' after ' steel' belongs to it
        out.append({'w': t, 's': float(w['start']), 'e': float(w['end']), 'p': float(w.get('probability', 1.0)),
                    'sp': w['word'][:1].isspace() or not out})
    if not out and seg.get('text', '').strip():   # no word timestamps: spread the text over the segment
        toks = seg['text'].split()
        step = (seg['end'] - seg['start']) / max(1, len(toks))
        out = [{'w': t, 's': seg['start'] + i * step, 'e': seg['start'] + (i + 1) * step, 'p': 0.5} for i, t in enumerate(toks)]
    return out


def _cap(w):
    t = w.lstrip('"\'(¿¡')
    return bool(t) and t[0].isupper() and t not in ('I', "I'm", "I'll", "I've", "I'd")


def _break_scores(ws, pause):
    """Reward for a line break after word i (between i and i+1)."""
    sc = []
    for i in range(len(ws) - 1):
        a, b = ws[i], ws[i + 1]
        gap = b['s'] - a['e']
        v = min(1.5, max(0.0, gap) * 3.0)
        if a['seg'] != b['seg']:
            # Whisper often ends a segment with the first word of the next sung line ("...the sound You |
            # killed your drive"): then the real break is one word earlier
            v += 0.3 if (_cap(a['w']) and i > 0 and a['seg'] == ws[i - 1]['seg'] and not _cap(b['w'])) else 2.5
        if re.search(r'[,.;:!?…]["\')]*$', a['w']):
            v += 2.0
        if _cap(b['w']):
            v += 1.6
        if gap > pause:
            v += 3.0
        sc.append(v)
    return sc


def _segment_words(ws, pause, max_chars):
    """Optimal line breaks (dynamic programming): reward natural breaks (pauses, Whisper segment
    ends, punctuation, a capital letter starting the next line), keep lines <= max_chars, avoid
    very short lines. Pauses > 2 * pause always break."""
    n = len(ws)
    sc = _break_scores(ws, pause)
    INF = 1e18
    best = [INF] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):           # line = ws[i:j]
        length = -1
        for i in range(j - 1, -1, -1):
            length += len(ws[i]['w']) + 1
            if i < j - 1 and ws[i + 1]['s'] - ws[i]['e'] > 2 * pause:
                break                   # a line never spans a long pause
            if length > max_chars and i < j - 1:
                if length > max_chars + 8:
                    break
                over = 3.0 + (length - max_chars)
            else:
                over = 0.0
            short = max(0, 16 - length) / 3.0
            reward = sc[j - 1] if j < n else 2.0
            c = best[i] + 3.0 + over + short ** 2 - reward
            if c < best[j]:
                best[j], back[j] = c, i
    cuts = []
    j = n
    while j > 0:
        cuts.append((back[j], j))
        j = back[j]
    return [ws[a:b] for a, b in reversed(cuts)]


def build_lines(segments, vocals=None, pause=PAUSE, max_chars=MAX_CHARS):
    """Whisper segments (already filtered) -> [{'text','start','end','conf','words','why'}]."""
    ws = []
    for k, s in enumerate(segments):
        for w in _words_of(s, vocals):
            w['seg'] = k
            ws.append(w)
    if not ws:
        return []
    out = []
    for chunk in _segment_words(ws, pause, max_chars):
        seg = segments[chunk[0]['seg']]
        text = ''.join((' ' if (k and w.get('sp', True)) else '') + w['w'] for k, w in enumerate(chunk))
        text = re.sub(r'\s+([,.;:!?…])', r'\1', text).strip()
        text = text[:1].upper() + text[1:] if text else text
        probs = [w['p'] for w in chunk]
        conf = 0.75 * sum(probs) / len(probs) + 0.25 * min(probs)
        why = []
        low_words = [w['w'] for w in chunk if w['p'] < LOW_WORD]
        if low_words:
            why.append('unsure words: ' + ', '.join(low_words[:6]))
        segs = {w['seg'] for w in chunk}
        nsp = max(segments[k].get('no_speech_prob', 0) for k in segs)
        lp = min(segments[k].get('avg_logprob', 0) for k in segs)
        if nsp > 0.5:
            why.append('Whisper not sure this is singing (no-speech %.0f%%)' % (100 * nsp))
            conf = min(conf, 1 - nsp)
        if lp < -1.0:
            why.append('low transcript score (avg log-prob %.2f)' % lp)
            conf = min(conf, math.exp(lp) * 1.6)
        out.append({'text': text, 'start': round(chunk[0]['s'], 3), 'end': round(max(chunk[-1]['e'], chunk[0]['s'] + 0.2), 3),
                    'conf': round(max(0.0, min(1.0, conf)), 3), 'why': why,
                    'words': [[w['w'], round(w['s'], 3), round(w['e'], 3), round(w['p'], 3)] for w in chunk]})
    for a, b in zip(out, out[1:]):   # starts in order, no overlap
        if b['start'] < a['start']:
            b['start'] = a['start'] + 0.01
        if a['end'] > b['start']:
            a['end'] = b['start']
    for k, l in enumerate(out):
        l['idx'] = k
    return out


def snap_starts(lines, regions, window=0.35):
    """Move a line start to the start of a vocal region (the singer coming in after a breath) when one
    is within `window` s: Whisper word times are often a little early or late."""
    starts = [a for a, _b in regions or ()]
    for l in lines:
        near = [a for a in starts if abs(a - l['start']) <= window]
        if near:
            t = min(near, key=lambda a: abs(a - l['start']))
            l['start'] = round(t, 3)
            if l['words']:
                l['words'][0][1] = l['start']
    return lines


def wer(ref, hyp):
    """Word error rate (normalized words, Levenshtein): (S + D + I) / N, plus the counts."""
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r)), d[len(h)], len(r)
