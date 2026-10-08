"""Line timing on top of MMS_FA emissions (Ax-Easy Lyricist Sync 1.1.0).

- vocal activity on the Demucs vocals stem (energy relative to the stem's own loudness),
- forced alignment with <star> wildcard tokens before, between and after lines, so intro
  hums, ad-libs, choir echoes and backing words are absorbed instead of pulling a line,
- first-word onsets snapped to real vocal onsets, cross-checked with Whisper word times,
- monotonic, non-overlapping starts, per-line confidence, and re-alignment of a range of
  lines inside a time window (used by 'Re-sync from this line').
Only numpy/torch/torchaudio; no models are loaded here."""
import math

import numpy as np

HOP = 0.01             # VAD frame hop (s)
REL_DB = 30.0          # vocal threshold below the stem's loud level (95th percentile)
STAR_LOGP = -1.5       # log-prob of the <star> wildcard per frame (0 would swallow lyrics)
WHISPER_AHEAD = 1.0    # aligned start this far before Whisper's matching word -> trust Whisper
MIN_STEP = 0.10        # minimum distance between consecutive line starts (s)
SNAP_MAX = 2.5         # snap a start forward to a vocal onset at most this far (s)
LOW_CONF = 0.6


# ---------------------------------------------------------------- vocal activity
def _runs(v):
    """[(start, end)) index runs of True in a bool array."""
    if not len(v):
        return []
    d = np.diff(np.concatenate([[0], v.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


class Vad:
    """Vocal activity of the vocals stem at 100 frames/s: frame RMS (30 ms) above
    max(loud - REL_DB, floor + 6 dB, -65 dB); gaps < 0.3 s are closed, blips < 0.12 s dropped."""

    def __init__(self, v16=None, sr=16000, rel_db=REL_DB, db=None):
        if db is None:
            x = np.asarray(v16, dtype=np.float64)
            hop, win = int(sr * HOP), int(sr * 0.03)
            n = max(1, (len(x) - win) // hop + 1)
            c = np.concatenate([[0.0], np.cumsum(x * x)])
            idx = np.arange(n) * hop
            e = (c[np.minimum(idx + win, len(x))] - c[idx]) / win
            db = 10 * np.log10(e + 1e-12)
        self.db = np.asarray(db, dtype=np.float32)
        loud = self.db[self.db > -90]
        if not len(loud):
            self.thr = 0.0
            self.v = np.zeros(len(self.db), bool)
            return
        ref = float(np.percentile(loud, 95))
        floor = float(np.percentile(self.db, 10))
        self.ref = ref
        self.thr = max(ref - rel_db, floor + 6.0, -65.0)
        v = self.db > self.thr
        for a, b in _runs(~v):  # close short gaps
            if 0 < a and b < len(v) and (b - a) * HOP < 0.3:
                v[a:b] = True
        for a, b in _runs(v):  # drop blips
            if (b - a) * HOP < 0.12:
                v[a:b] = False
        self.v = v

    def _i(self, t):
        return int(min(max(0, round(t / HOP)), len(self.v) - 1))

    def active(self, t, look=0.05):
        i = self._i(t)
        return bool(self.v[i:i + max(1, int(look / HOP))].any())

    def next_onset(self, t, limit):
        """First vocal frame at or after t (and before limit), or None."""
        i, j = self._i(t), self._i(limit)
        if j <= i:
            return None
        nz = np.nonzero(self.v[i:j + 1])[0]
        return None if not len(nz) else (i + int(nz[0])) * HOP

    def last_active(self, t, floor):
        i, j = self._i(floor), self._i(t)
        nz = np.nonzero(self.v[i:j + 1])[0]
        return None if not len(nz) else (i + int(nz[-1]) + 1) * HOP

    def silent_run(self, a, b, min_len):
        """(start, end) of the last run of >= min_len s without vocals inside [a, b], or None."""
        i, j = self._i(a), self._i(b)
        best = None
        for x, y in _runs(~self.v[i:j + 1]):
            if (y - x) * HOP >= min_len:
                best = ((i + x) * HOP, (i + y) * HOP)
        return best

    def overlap(self, a, b):
        i, j = self._i(a), self._i(b)
        return float(self.v[i:max(i + 1, j)].mean()) if j >= i else 0.0

    def regions(self):
        return [(a * HOP, b * HOP) for a, b in _runs(self.v)]


# ---------------------------------------------------------------- forced alignment
def align_window(emission, frame_sec, occ_words, f0, f1, vocab, star_id, lead=True, trail=True, star_logp=STAR_LOGP):
    """Force-align the words of consecutive sung lines inside emission frames [f0, f1),
    with <star> wildcards before (lead), between, and after (trail) the lines.
    Returns one dict per line: {'start', 'end', 'score', 'words': [(start, end, score)]}
    (None for lines without alignable words), or None if the window is too short."""
    import torch
    import torchaudio.functional as F
    f0, f1 = max(0, int(f0)), min(int(f1), emission.shape[0])
    em = emission[f0:f1].clone().float()
    em[:, star_id] = star_logp
    toks, own = [], []

    def star():
        if not toks or toks[-1] != star_id:
            toks.append(star_id)
            own.append(None)

    if lead:
        star()
    for k, ws in enumerate(occ_words):
        if not ws:
            continue
        for wi, w in enumerate(ws):
            for ch in w:
                toks.append(vocab[ch])
                own.append((k, wi))
        star()
    if not trail and toks and toks[-1] == star_id:
        toks.pop()
        own.pop()
    reps = sum(1 for a, b in zip(toks, toks[1:]) if a == b)
    if not toks or em.shape[0] < len(toks) + reps + 2:
        return None
    ali, sc = F.forced_align(em[None], torch.tensor([toks], dtype=torch.int32), blank=0)
    spans = F.merge_tokens(ali[0], sc[0].exp())
    if len(spans) != len(toks):
        return None
    words = {}
    for sp, o in zip(spans, own):
        if o is None:
            continue
        words.setdefault(o, []).append(sp)
    out = []
    for k, ws in enumerate(occ_words):
        if not ws:
            out.append(None)
            continue
        wl = []
        for wi in range(len(ws)):
            sps = words[(k, wi)]
            wl.append(((f0 + sps[0].start) * frame_sec, (f0 + sps[-1].end) * frame_sec,
                       float(np.mean([s.score for s in sps])), [((f0 + s.start) * frame_sec, float(s.score)) for s in sps]))
        out.append({'start': wl[0][0], 'end': wl[-1][1], 'words': wl,
                    'score': float(np.mean([s.score for (kk, _wi), sps in words.items() if kk == k for s in sps]))})
    return out


# ---------------------------------------------------------------- refinement
def _neighbours(occ, k, duration):
    prev_end = next((occ[j]['end'] for j in range(k - 1, -1, -1) if occ[j]), 0.0)
    prev_start = next((occ[j]['start'] for j in range(k - 1, -1, -1) if occ[j]), -1.0)
    nxt = next((occ[j]['start'] for j in range(k + 1, len(occ)) if occ[j]), duration)
    return prev_start, prev_end, nxt


def refine(occ, occ_words, emission, frame_sec, vad, anchors, duration, vocab, star_id, first=0, log=None):
    """Fix line starts in place (lines >= first): Whisper cross-check, vocal-onset snap,
    trimmed silent ends. Records what changed in occ[k]['fix']."""
    for k in range(first, len(occ)):
        o = occ[k]
        if not o:
            continue
        o.setdefault('fix', [])
        prev_start, prev_end, nxt = _neighbours(occ, k, duration)
        # 1. Whisper: the line's first word heard clearly much later than aligned -> realign there.
        if anchors and k < len(anchors):
            w0 = next((a for a in anchors[k] if a[0] == 0 and a[3] <= 0.4), None)
            if w0 is not None and o['start'] < w0[1] - WHISPER_AHEAD:
                lo = max(prev_end, w0[1] - 0.6)
                hi = max(nxt, lo + 1.0)
                r = align_window(emission, frame_sec, [occ_words[k]], lo / frame_sec, hi / frame_sec, vocab, star_id)
                if r and r[0] and r[0]['start'] >= lo and r[0]['start'] < nxt - MIN_STEP:
                    if log:
                        log('line %d: aligned %.2f s, Whisper hears it at %.2f s -> %.2f s' % (k + 1, o['start'], w0[1], r[0]['start']))
                    r[0]['fix'] = o['fix'] + ['whisper']
                    occ[k] = o = r[0]
        # 2. Leading sounds latched onto the intro: the first token(s) of the line sit far ahead of
        #    the rest, with a stretch of no vocals in between and a much weaker acoustic match
        #    (instrument bleed, a hum). Start after that silence instead.
        if vad is not None and o.get('words'):
            toks = [(tk[0], tk[1], wi) for wi, w in enumerate(o['words']) for tk in w[3]]
            lim = max(2, int(len(toks) * 0.35))
            cut = None
            for i in range(1, min(lim, len(toks) - 1) + 1):
                a, b = toks[i - 1][0], toks[i][0]
                if b - a > 1.0 and vad.silent_run(a, b, 0.3):
                    split_word = toks[i - 1][2] == toks[i][2]   # one word never has >1 s of silence inside
                    lead = np.mean([x[1] for x in toks[:i]])
                    rest = np.mean([x[1] for x in toks[i:]])
                    if split_word or lead < 0.5 * rest or lead < 0.15:
                        cut = i
            if cut is not None:
                on = vad.next_onset(vad.silent_run(toks[cut - 1][0], toks[cut][0], 0.3)[1], toks[cut][0] + 0.05) or toks[cut][0]
                on = min(on, toks[cut][0])
                if on > o['start'] and on < nxt - MIN_STEP:
                    if log:
                        log('line %d: %d leading sound(s) at %.2f s look like intro bleed -> %.2f s' % (k + 1, cut, o['start'], on))
                    o['start'] = on
                    o['fix'].append('stretch')
        # 3. No line starts in a region without vocals: snap to the next vocal onset.
        if vad is not None and not vad.active(o['start']):
            limit = min(o['start'] + SNAP_MAX, o['end'], nxt - MIN_STEP)
            on = vad.next_onset(o['start'], limit)
            if on is not None and on > o['start']:
                if log:
                    log('line %d: start %.2f s is in a no-vocal region -> vocal onset %.2f s' % (k + 1, o['start'], on))
                o['start'] = on
                o['fix'].append('onset')
            elif on is None:
                o['fix'].append('novocal')
        # 4. Ends that run into silence come back to the last vocal frame.
        if vad is not None and not vad.active(o['end'] - 0.05):
            la = vad.last_active(o['end'], o['start'] + 0.2)
            if la is not None and la < o['end']:
                o['end'] = la
    return occ


def monotonic(occ, duration, first=0):
    """Starts strictly increasing (>= MIN_STEP apart), no line ends after the next starts."""
    last = None
    for k, o in enumerate(occ):
        if not o:
            continue
        if last is not None and k >= first and o['start'] < last + MIN_STEP:
            o['start'] = last + MIN_STEP
            o.setdefault('fix', []).append('order')
        last = o['start']
    for k, o in enumerate(occ):
        if not o:
            continue
        _ps, _pe, nxt = _neighbours(occ, k, duration)
        o['end'] = max(o['start'] + 0.05, min(o['end'], nxt))
    return occ


def confidence(o, occ_words_k, vad, anchors_k, have_transcript):
    """0..1 from emission scores, agreement with Whisper's words and vocal-activity overlap.
    Returns (conf, reasons)."""
    reasons = []
    c_em = min(1.0, max(0.0, (o['score'] - 0.08) / 0.42))
    parts = [(0.5, c_em)]
    if c_em < 0.5:
        reasons.append('weak acoustic match')
    if vad is not None:
        ov = np.mean([vad.overlap(s, e) for s, e, _sc, _t in o['words']]) if o['words'] else 0.0
        parts.append((0.25, float(ov)))
        if ov < 0.6:
            reasons.append('little vocal energy under the words')
    if have_transcript:
        n = max(1, len(occ_words_k))
        agree = 0
        for wi, (s, _e, _sc, _t) in enumerate(o['words']):
            if any(a[0] == wi and abs(a[1] - s) <= 1.0 for a in anchors_k):
                agree += 1
        wa = agree / n
        parts.append((0.25, wa))
        if wa < 0.34:
            reasons.append('Whisper heard different words here')
    if 'whisper' in o.get('fix', []):
        reasons.append('moved to where Whisper heard the first word')
    if 'stretch' in o.get('fix', []):
        reasons.append('ignored a weak early sound before the line (intro bleed/hum)')
    if 'onset' in o.get('fix', []):
        reasons.append('start snapped to the vocal onset')
    if 'novocal' in o.get('fix', []):
        reasons.append('no vocals detected at the start')
    if 'order' in o.get('fix', []):
        reasons.append('pushed after the previous line (overlap)')
    conf = sum(w * v for w, v in parts) / sum(w for w, _v in parts)
    return round(conf, 2), reasons
