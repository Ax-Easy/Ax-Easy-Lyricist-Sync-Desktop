"""Ax-Easy Lyricist Sync engine: Demucs vocals -> Whisper repeat detection -> MMS_FA alignment.

Runs inside the downloaded runtime (Python 3.11 + PyTorch); the GUI talks to it over
JSON lines:  stdin  {"cmd": "sync", "id": ..., "audio": ..., "lines": [...], "lang": "el"|null, "iso": "ell"|""}
             stdout {"event": "hello"|"progress"|"result"|"error"|"log", ...}
Usage: python lyricist_engine.py --models DIR [--device auto|cuda|cpu] (serve|check|sync AUDIO LYRICS.txt OUT.json)
"""
import argparse, difflib, io, json, math, os, re, sys, threading, time, traceback, unicodedata

PROTO = None  # real stdout (JSON protocol); sys.stdout is redirected to stderr so library prints never corrupt it.
_lock = threading.Lock()


def emit(**ev):
    with _lock:
        PROTO.write(json.dumps(ev, ensure_ascii=False) + '\n')
        PROTO.flush()


def log(msg):
    sys.stderr.write(str(msg) + '\n')
    sys.stderr.flush()


# ---------------------------------------------------------------- text helpers
_UROMAN = None


def _uroman():
    global _UROMAN
    if _UROMAN is None:
        import uroman
        _UROMAN = uroman.Uroman()
    return _UROMAN


def needs_roman(text):
    return any(ord(c) > 0x24F and unicodedata.category(c).startswith('L') for c in text)


def romanize(texts, iso=''):
    """uroman for non-Latin scripts (Greek etc.); Latin text is left as is."""
    out = []
    for t in texts:
        t = t.replace('\u2019', "'").replace('\u2018', "'").replace('\u02bc', "'")
        if needs_roman(t):
            t = str(_uroman().romanize_string(t, lcode=iso or None))
        out.append(t)
    return out


def ctc_words(s):
    """Romanized text -> lowercase a-z/apostrophe words for MMS_FA."""
    s = unicodedata.normalize('NFKD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z' ]+", ' ', s)
    return [w.strip("'") for w in s.split() if w.strip("'")]


# ---------------------------------------------------------------- repeats
def _word_cost(a, b, cache={}):
    if a == b:
        return 0.0
    k = (a, b)
    if k not in cache:
        r = difflib.SequenceMatcher(None, a, b).ratio()
        cache[k] = 0.4 if r >= 0.75 else 0.75 if r >= 0.5 else 1.2
    return cache[k]


def expand_repeats(line_words, transcript_words, jump_cost=4.0, min_words=3, with_anchors=False):
    """Sung order of the lyric lines, found by aligning the free transcript to the lyrics
    with a DP that may jump back to an earlier line start at a line end (cost jump_cost).
    A jump means the singer repeated lines that are written only once (e.g. a chorus).
    Lines Whisper did not hear stay in their written place. Extra transcript words
    (intro ad-libs, hallucinations) cost the same on every path, so they don't bias it.
    Returns (sung order as line indices, list of repeats) and, with with_anchors, for every
    sung line the Whisper words matched to it: [(word index in line, start, end, cost)]."""
    L, owner = [], []
    for k, ws in enumerate(line_words):
        for w in ws:
            L.append(w); owner.append(k)
    n, m = len(L), len(transcript_words)
    nlines = len(line_words)
    if not n or not m:
        return (list(range(nlines)), [], [[] for _ in range(nlines)]) if with_anchors else (list(range(nlines)), [])
    starts = {}
    for i, k in enumerate(owner):
        starts.setdefault(k, i)
    ends = sorted({i + 1 for i in range(n) if i + 1 == n or owner[i + 1] != owner[i]})  # positions after a line
    line_start_pos = sorted(set(starts.values()))
    # A jump may only land at least min_words before where it came from.
    ends = sorted({e for e in ends if any(e - s >= min_words for s in line_start_pos)})
    T = [w for w, _s, _e in transcript_words]
    INF = float('inf')
    cost = [[INF] * (n + 1) for _ in range(m + 1)]
    back = [[None] * (n + 1) for _ in range(m + 1)]

    def relax_layer(j):
        row, br = cost[j], back[j]
        for i in range(n):  # lyric word not heard (deletion)
            c = row[i] + 1.0
            if c < row[i + 1]:
                row[i + 1] = c; br[i + 1] = (j, i, 'del')
        best_after = INF; arg = None  # jump back: from a line end e to an earlier line start s (s < e)
        jumped = False
        ends_desc = sorted(ends, reverse=True)
        ei = 0
        for s in sorted(line_start_pos, reverse=True):
            while ei < len(ends_desc) and ends_desc[ei] >= s + min_words:
                e = ends_desc[ei]
                if row[e] < best_after:
                    best_after, arg = row[e], e
                ei += 1
            if arg is not None and best_after + jump_cost < row[s]:
                row[s] = best_after + jump_cost; br[s] = (j, arg, 'jump'); jumped = True
        # finish early: from a line end straight to the end of the lyrics (a chorus repeated
        # at the very end is followed by nothing); the skipped lines keep their written place.
        be = min((row[e], e) for e in ends if e < n) if any(e < n for e in ends) else (INF, None)
        if be[1] is not None and be[0] + jump_cost < row[n]:
            row[n] = be[0] + jump_cost; br[n] = (j, be[1], 'skip')
        if jumped:
            for i in range(n):
                c = row[i] + 1.0
                if c < row[i + 1]:
                    row[i + 1] = c; br[i + 1] = (j, i, 'del')

    for j in range(m + 1):
        if j == 0:
            cost[0][0] = 0.0
        relax_layer(j)
        if j == m:
            break
        row, nrow, nb = cost[j], cost[j + 1], back[j + 1]
        tj = T[j]
        for i in range(n + 1):
            c0 = row[i]
            if c0 == INF:
                continue
            if i < n:
                c = c0 + _word_cost(tj, L[i])
                if c < nrow[i + 1]:
                    nrow[i + 1] = c; nb[i + 1] = (j, i, 'match')
            c = c0 + 1.0  # extra transcript word (intro ad-libs, hallucinations...)
            if c < nrow[i]:
                nrow[i] = c; nb[i] = (j, i, 'ins')
    # trace back from the end (all lyric words passed, all transcript words consumed)
    path = []
    j, i = m, n
    while back[j][i] is not None:
        pj, pi, op = back[j][i]
        path.append((pj, pi, op))
        j, i = pj, pi
    path.reverse()
    seq, repeats, anchors = [], [], []
    last_line = None
    for pj, pi, op in path:
        if op == 'jump':
            # pi is the line end we jumped from; next traversed line starts the repeat
            last_line = None
            repeats.append({'after_line': owner[pi - 1], 'time': transcript_words[min(pj, m - 1)][1]})
            continue
        if op in ('match', 'del') and pi < n:
            k = owner[pi]
            if k != last_line:
                seq.append(k); anchors.append([]); last_line = k
            if op == 'match':
                c = _word_cost(T[pj], L[pi])
                if c <= 0.75:
                    anchors[-1].append((pi - starts[k], transcript_words[pj][1], transcript_words[pj][2], c))
    # lines without words never appear in the path: keep them in written order
    for k in range(nlines):
        if k not in seq:
            pos = next((x for x, v in enumerate(seq) if v > k), len(seq))
            seq.insert(pos, k); anchors.insert(pos, [])
    for r in repeats:
        r['ratio'] = None
    # describe each repeat as the block of lines sung again
    out_rep = []
    seen = set()
    for x, k in enumerate(seq):
        if k in seen:
            if not out_rep or out_rep[-1]['end_pos'] != x - 1 or k != seq[x - 1] + 1:
                out_rep.append({'lines': [k], 'end_pos': x, 'before': seq[x + 1] if x + 1 < len(seq) else nlines})
            else:
                out_rep[-1]['lines'].append(k); out_rep[-1]['end_pos'] = x
                out_rep[-1]['before'] = seq[x + 1] if x + 1 < len(seq) else nlines
        seen.add(k)
    for r, rr in zip(out_rep, repeats + [{}] * len(out_rep)):
        r['time'] = rr.get('time')
        r.pop('end_pos')
    if with_anchors:
        return seq, out_rep, anchors
    return seq, out_rep


# ---------------------------------------------------------------- progress shims
class _Bar:
    def __init__(self, cb, iterable=None, total=None):
        self.cb, self.it = cb, iterable
        self.total = total if total is not None else (len(iterable) if iterable is not None and hasattr(iterable, '__len__') else 0)
        self.n = 0

    def __iter__(self):
        for x in self.it:
            yield x
            self.update(1)

    def update(self, k=1):
        self.n += k
        if self.total:
            self.cb(min(1.0, self.n / self.total))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass

    def set_description(self, *a, **k):
        pass


class _TqdmModule:
    def __init__(self, cb):
        self.cb = cb

    def tqdm(self, iterable=None, total=None, **kw):
        return _Bar(self.cb, iterable, total)


# ---------------------------------------------------------------- engine
import timing as TM  # noqa: E402  (engine/timing.py next to this script)

STEMS = {  # vocal separation models: name -> (yaml models line, weights file)
    'htdemucs': ("models: ['955717e8']\n", '955717e8-8726e21a.th'),
    'htdemucs_ft': ("models: ['04573f0d']\n", '04573f0d-f3cf25b2.th'),  # the vocals model of htdemucs_ft
}
CACHE_VERSION = 2


class Engine:
    def __init__(self, models, device='auto', cache=None):
        import torch
        self.torch = torch
        self.models = models
        self.cache = cache or os.path.join(os.path.dirname(os.path.abspath(models)), 'cache')
        os.environ.setdefault('TORCH_HOME', os.path.join(models, 'torch'))
        if device == 'auto':
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        if device == 'cuda' and not torch.cuda.is_available():
            log('CUDA requested but not available; using CPU')
            device = 'cpu'
        self.device = device
        if device == 'cpu':
            torch.set_num_threads(max(1, os.cpu_count() or 1))
        self.stem = self._pick_stem()
        self._demucs = self._whisper = self._mms = None

    def _pick_stem(self):
        """htdemucs by default. The htdemucs_ft vocals model was evaluated for 1.1.0 (choir and
        backing-vocal fixtures, Stoned) and gave no measurable gain, so it is opt-in only:
        LYRICIST_SYNC_STEM=htdemucs_ft with its weights placed in models/demucs."""
        want = os.environ.get('LYRICIST_SYNC_STEM', 'htdemucs')
        if want in STEMS and os.path.exists(os.path.join(self.models, 'demucs', STEMS[want][1])):
            return want
        return 'htdemucs'

    def info(self):
        t = self.torch
        name = t.cuda.get_device_name(0) if self.device == 'cuda' else (platform_cpu() or 'CPU')
        return {'device': self.device, 'device_name': name, 'torch': t.__version__, 'stem': self.stem,
                'cuda': t.version.cuda if self.device == 'cuda' else None,
                'vram_gb': round(t.cuda.get_device_properties(0).total_memory / 2**30, 1) if self.device == 'cuda' else None}

    # -- models
    def demucs(self):
        if self._demucs is None:
            from pathlib import Path
            from demucs.pretrained import get_model
            d = os.path.join(self.models, 'demucs')
            y = os.path.join(d, self.stem + '.yaml')
            if not os.path.exists(y):
                with open(y, 'w') as f:
                    f.write(STEMS[self.stem][0])
            m = get_model(self.stem, repo=Path(d))
            self._demucs = m.to(self.device).eval()
        return self._demucs

    def whisper(self):
        if self._whisper is None:
            import whisper
            self._whisper = whisper.load_model('small', device=self.device, download_root=os.path.join(self.models, 'whisper'))
        return self._whisper

    def mms(self):
        if self._mms is None:
            import torchaudio
            b = torchaudio.pipelines.MMS_FA
            vocab = b.get_dict(star='*')
            self._mms = (b, b.get_model(with_star=True).to(self.device).eval(), vocab, vocab['*'])
        return self._mms

    # -- steps
    def decode(self, path, sr):
        """Any audio (MP3/WAV/FLAC/M4A...) -> float32 tensor [2, n] at sr, via PyAV."""
        import av, numpy as np
        chunks = []
        with av.open(path) as c:
            st = next(s for s in c.streams if s.type == 'audio')
            rs = av.AudioResampler(format='fltp', layout='stereo', rate=sr)
            for frame in c.decode(st):
                for f in rs.resample(frame):
                    chunks.append(f.to_ndarray())
            for f in rs.resample(None):
                chunks.append(f.to_ndarray())
        a = np.concatenate(chunks, axis=1).astype('float32')
        return self.torch.from_numpy(a)

    def separate(self, wav, cb):
        import demucs.apply as dapply
        model = self.demucs()
        old = dapply.tqdm
        dapply.tqdm = _TqdmModule(cb)
        try:
            ref = wav.mean(0)
            mean, std = ref.mean(), ref.std() + 1e-8
            x = ((wav - mean) / std).to(self.device)
            with self.torch.inference_mode():
                src = dapply.apply_model(model, x[None], device=self.device, shifts=1, split=True, overlap=0.25,
                                         progress=True, num_workers=0)[0]
            vocals = src[model.sources.index('vocals')] * std + mean
        finally:
            dapply.tqdm = old
        return vocals.float().cpu()

    def transcribe(self, vocals16, lang, cb):
        import whisper  # noqa: F401
        wt = sys.modules['whisper.transcribe']  # the package attribute is shadowed by the function
        old = wt.tqdm
        wt.tqdm = _TqdmModule(cb)
        try:
            r = self.whisper().transcribe(vocals16.numpy(), language=lang, word_timestamps=True,
                                          condition_on_previous_text=False, fp16=(self.device == 'cuda'), verbose=False)
        finally:
            wt.tqdm = old
        words = [(w['word'], round(w['start'], 2), round(w['end'], 2)) for s in r['segments'] for w in s.get('words', [])]
        return words, r.get('language'), [{'start': s['start'], 'end': s['end'], 'text': s['text']} for s in r['segments']]

    def emissions(self, vocals16, cb):
        """MMS_FA log-probs [frames, vocab+star] on 16 kHz mono vocals, 30 s chunks with 2 s context."""
        torch = self.torch
        bundle, model, _vocab, _star = self.mms()
        SR = bundle.sample_rate
        wav = vocals16[None]
        chunk, ctx = 30 * SR, 2 * SR
        ems = []
        n = wav.shape[1]
        pos = 0
        with torch.inference_mode():
            while pos < n:
                a, b = max(0, pos - ctx), min(n, pos + chunk + ctx)
                em, _ = model(wav[:, a:b].to(self.device))
                fps = em.shape[1] / ((b - a) / SR)
                s_off = round((pos - a) / SR * fps)
                e_off = s_off + round((min(n, pos + chunk) - pos) / SR * fps)
                ems.append(em[0, s_off:e_off].float().cpu())
                pos += chunk
                cb(min(1.0, pos / n))
        emission = torch.cat(ems, 0)
        return emission, (n / SR) / emission.shape[0]

    # -- analysis cache (emissions + vocal activity + transcript), so 'Re-sync from this line' is instant
    def _key(self, path):
        import hashlib
        st = os.stat(path)
        k = '%s|%d|%d|%s|%d' % (os.path.abspath(path), st.st_size, int(st.st_mtime), self.stem, CACHE_VERSION)
        return hashlib.sha1(k.encode('utf-8')).hexdigest()[:20]

    def save_analysis(self, path, an):
        import numpy as np
        try:
            os.makedirs(self.cache, exist_ok=True)
            f = os.path.join(self.cache, self._key(path) + '.npz')
            np.savez_compressed(f + '.tmp.npz', em=an['em'].numpy().astype('float16'), fs=an['fs'], db=an['vad'].db,
                                duration=an['duration'], words=json.dumps(an.get('words') or [], ensure_ascii=False))
            os.replace(f + '.tmp.npz', f)
            files = sorted((os.path.join(self.cache, x) for x in os.listdir(self.cache) if x.endswith('.npz')),
                           key=os.path.getmtime, reverse=True)
            for old in files[40:]:
                os.remove(old)
        except OSError as e:
            log('cache not written: %s' % e)

    def load_analysis(self, path):
        import numpy as np
        f = os.path.join(self.cache, self._key(path) + '.npz')
        if not os.path.exists(f):
            return None
        try:
            d = np.load(f)
            return {'em': self.torch.from_numpy(d['em'].astype('float32')), 'fs': float(d['fs']),
                    'vad': TM.Vad(db=d['db']), 'duration': float(d['duration']),
                    'words': [tuple(w) for w in json.loads(str(d['words']))]}
        except Exception as e:  # corrupt cache: recompute
            log('cache unreadable (%s); recomputing' % e)
            return None

    def analyse(self, path, lang, progress, transcript=True):
        """decode -> vocals -> (Whisper words) -> emissions + vocal activity."""
        t = {}
        T0 = time.time()
        stage_w = {'decode': (0.0, 0.03), 'separate': (0.03, 0.55), 'transcribe': (0.55, 0.85), 'align': (0.85, 1.0)}
        if not transcript:
            stage_w = {'decode': (0.0, 0.04), 'separate': (0.04, 0.85), 'align': (0.85, 1.0)}

        def stage(name):
            a, b = stage_w[name]
            progress(name, a)
            return lambda f: progress(name, a + (b - a) * f)

        stage('decode')
        import torchaudio.functional as AF
        model_sr = 44100
        wav = self.decode(path, model_sr)
        duration = wav.shape[1] / model_sr
        t['decode'] = time.time() - T0
        if duration < 1:
            raise RuntimeError('Audio is empty or too short.')
        t1 = time.time()
        vocals = self.separate(wav, stage('separate'))
        del wav
        v16 = AF.resample(vocals.mean(0), model_sr, 16000).contiguous()
        del vocals
        if self.device == 'cuda':
            self.torch.cuda.empty_cache()
        t['separate'] = time.time() - t1
        words, wlang, segments = [], lang, []
        if transcript:
            t1 = time.time()
            words, wlang, segments = self.transcribe(v16, lang, stage('transcribe'))
            t['transcribe'] = time.time() - t1
        t1 = time.time()
        cb = stage('align')
        em, fs = self.emissions(v16, lambda f: cb(0.8 * f))
        vad = TM.Vad(v16.numpy())
        t['emissions'] = time.time() - t1
        an = {'em': em, 'fs': fs, 'vad': vad, 'duration': duration, 'words': words, 'language': wlang,
              'segments': segments, 'timings': t, 'align_cb': cb}
        return an

    def _occ_words(self, texts, iso):
        return [ctc_words(r) for r in romanize(texts, iso)]

    def _finish(self, occ, occ_texts, seq, an, anchors, have_transcript, first=0):
        """occ (aligned dicts) -> result lines with flags and confidence."""
        out = []
        duration = an['duration']
        for k, o in enumerate(occ):
            if o is None:
                out.append({'idx': seq[k], 'text': occ_texts[k], 'start': None, 'end': None})
                continue
            out.append({'idx': seq[k], 'text': occ_texts[k], 'start': o['start'], 'end': o['end'], '_o': o})
        for k, o in enumerate(out):  # lines without alignable words: place them between their neighbours
            if o['start'] is None:
                prev_end = next((out[j]['end'] for j in range(k - 1, -1, -1) if out[j]['end'] is not None), 0.0)
                nxt = next((out[j]['start'] for j in range(k + 1, len(out)) if out[j]['start'] is not None), duration)
                o['start'], o['end'], o['guessed'] = prev_end, max(prev_end, min(nxt, prev_end + 2.0)), True
        for k, o in enumerate(out):
            o['repeat'] = seq.index(seq[k]) != k
            dur = o['end'] - o['start']
            nw = max(1, len(o['text'].split()))
            o['flag'] = ('too long' if dur > max(8.0, nw * 1.2) else 'too short' if dur < 0.25 + 0.08 * nw else '')
            al = o.pop('_o', None)
            if al is not None:
                conf, why = TM.confidence(al, al['words'] and [None] * len(al['words']) or [], an['vad'],
                                          anchors[k] if anchors and k < len(anchors) else [], have_transcript)
                o['conf'], o['why'] = conf, why
            else:
                o['conf'], o['why'] = 0.0, ['no alignable words (placed between neighbours)']
            o['start'], o['end'] = round(o['start'], 3), round(o['end'], 3)
        return out

    # -- full job
    def sync(self, job, progress):
        T0 = time.time()
        lines = [l for l in job['lines'] if l.strip()]
        if not lines:
            raise RuntimeError('No lyrics lines.')
        iso = job.get('iso') or ''
        an = self.analyse(job['audio'], job.get('lang'), progress, transcript=job.get('repeats', True))
        t = an['timings']
        t1 = time.time()
        line_words = self._occ_words(lines, iso)
        seq, repeats, anchors = list(range(len(lines))), [], None
        have_tr = bool(an['words'])
        if have_tr:
            tw_text = romanize([w for w, s, e in an['words']], iso)
            tw = [(x, s, e) for (w, s, e), r in zip(an['words'], tw_text) for x in ctc_words(r)]
            seq, repeats, anchors = expand_repeats(line_words, tw, with_anchors=True)
            for r in repeats:
                log('repeat found: lines %s sung again (at ~%ss)' % ([i + 1 for i in r['lines']], r['time']))
        occ_words = [line_words[i] for i in seq]
        if not any(occ_words):
            raise RuntimeError('No alignable words in the lyrics.')
        _b, _m, vocab, star = self.mms()
        em, fs = an['em'], an['fs']
        occ = TM.align_window(em, fs, occ_words, 0, em.shape[0], vocab, star)
        if occ is None:
            raise RuntimeError('The song is too short for these lyrics.')
        TM.refine(occ, occ_words, em, fs, an['vad'], anchors, an['duration'], vocab, star, log=log)
        TM.monotonic(occ, an['duration'])
        an['align_cb'](1.0)
        out = self._finish(occ, [lines[i] for i in seq], seq, an, anchors, have_tr)
        t['align'] = time.time() - t1
        self.save_analysis(job['audio'], an)
        t['total'] = time.time() - T0
        low = sum(1 for o in out if o.get('conf', 1) < TM.LOW_CONF)
        return {'lines': out, 'duration': round(an['duration'], 3), 'language': an['language'], 'repeats': repeats,
                'device': self.device, 'stem': self.stem, 'low_conf': low, 'version': 2,
                'timings': {k: round(v, 2) for k, v in t.items()}, 'transcript': an['segments']}

    def resync(self, job, progress):
        """Re-align only the lines after job['from'], anchored at job['anchor'] (seconds) for
        that line. job['lines'] = the sung lines in order (texts), job['idx'] their lyric indices."""
        T0 = time.time()
        texts = job['lines']
        k0 = int(job['from'])
        anchor = float(job['anchor'])
        iso = job.get('iso') or ''
        an = self.load_analysis(job['audio'])
        if an is None:
            an = self.analyse(job['audio'], job.get('lang'), progress, transcript=False)
            self.save_analysis(job['audio'], an)
        progress('align', 0.9)
        occ_words = self._occ_words(texts, iso)
        _b, _m, vocab, star = self.mms() if self._mms else (None, None, *self._vocab())
        em, fs = an['em'], an['fs']
        f0 = max(0, int(anchor / fs) - 1)
        part = TM.align_window(em, fs, occ_words[k0:], f0, em.shape[0], vocab, star, lead=False)
        if part is None:
            raise RuntimeError('Not enough audio after %.2f s for the remaining lines.' % anchor)
        if part[0] is not None:
            part[0]['start'] = anchor
            part[0]['fix'] = ['manual']
        occ = [None] * k0 + part
        # earlier lines are fixed; give refine/monotonic their times as context
        prev = [{'start': s, 'end': e, 'words': [], 'score': 1.0} for s, e in zip(job.get('starts', [])[:k0], job.get('ends', [])[:k0])]
        occ[:k0] = prev + [None] * (k0 - len(prev))
        TM.refine(occ, occ_words, em, fs, an['vad'], None, an['duration'], vocab, star, first=k0 + 1, log=log)
        if occ[k0]:
            occ[k0]['start'] = anchor
        TM.monotonic(occ, an['duration'], first=k0 + 1)
        seq = list(job.get('idx') or range(len(texts)))
        out = self._finish(occ, texts, seq, an, None, False)
        progress('align', 1.0)
        return {'from': k0, 'lines': out[k0:], 'timings': {'total': round(time.time() - T0, 2)}}

    def _vocab(self):
        import torchaudio
        v = torchaudio.pipelines.MMS_FA.get_dict(star='*')
        return v, v['*']


def platform_cpu():
    try:
        import platform
        return platform.processor() or platform.machine()
    except Exception:
        return ''


def main():
    global PROTO
    PROTO = io.TextIOWrapper(os.fdopen(os.dup(1), 'wb'), encoding='utf-8', newline='\n')
    sys.stdout = sys.stderr
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', required=True)
    ap.add_argument('--device', default='auto')
    ap.add_argument('--cache', default=None)
    ap.add_argument('cmd', choices=['serve', 'check', 'sync'])
    ap.add_argument('args', nargs='*')
    a = ap.parse_args()
    os.environ['TORCH_HOME'] = os.path.join(a.models, 'torch')
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    try:
        eng = Engine(a.models, a.device, a.cache)
    except Exception as e:
        emit(event='error', error='Engine failed to start: %s' % e, trace=traceback.format_exc())
        return 2
    emit(event='hello', **eng.info())
    if a.cmd == 'check':
        import demucs, whisper, torchaudio, uroman, av  # noqa: F401  (import check)
        emit(event='ok', torchaudio=torchaudio.__version__)
        return 0
    if a.cmd == 'sync':
        audio, lyrics, out = a.args[:3]
        lines = [l.strip() for l in open(lyrics, encoding='utf-8-sig').read().splitlines()
                 if l.strip() and not re.fullmatch(r'\[[^\]]*\]|\([^)]*\)', l.strip())]
        lang = a.args[3] if len(a.args) > 3 else None
        iso = {'el': 'ell', 'en': 'eng'}.get(lang or '', '')
        res = eng.sync({'audio': audio, 'lines': lines, 'lang': lang, 'iso': iso},
                       lambda s, f: emit(event='progress', stage=s, pct=round(f, 3)))
        json.dump(res, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        emit(event='result', id='cli', result=res)
        return 0
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except ValueError:
            continue
        if job.get('cmd') == 'quit':
            break
        jid = job.get('id')
        try:
            fn = eng.resync if job.get('cmd') == 'resync' else eng.sync
            res = fn(job, lambda s, f, jid=jid: emit(event='progress', id=jid, stage=s, pct=round(f, 3)))
            emit(event='result', id=jid, result=res, cmd=job.get('cmd', 'sync'))
        except Exception as e:  # report and keep serving the queue
            emit(event='error', id=jid, error=str(e) or e.__class__.__name__, trace=traceback.format_exc())
            if eng.device == 'cuda':
                eng.torch.cuda.empty_cache()
    return 0


if __name__ == '__main__':
    sys.exit(main())
