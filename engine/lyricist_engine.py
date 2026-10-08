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


def expand_repeats(line_words, transcript_words, jump_cost=4.0, min_words=3):
    """Sung order of the lyric lines, found by aligning the free transcript to the lyrics
    with a DP that may jump back to an earlier line start at a line end (cost jump_cost).
    A jump means the singer repeated lines that are written only once (e.g. a chorus).
    Lines Whisper did not hear stay in their written place. Extra transcript words
    (intro ad-libs, hallucinations) cost the same on every path, so they don't bias it.
    Returns (sung order as line indices, list of repeats)."""
    L, owner = [], []
    for k, ws in enumerate(line_words):
        for w in ws:
            L.append(w); owner.append(k)
    n, m = len(L), len(transcript_words)
    nlines = len(line_words)
    if not n or not m:
        return list(range(nlines)), []
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
    seq, repeats = [], []
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
                seq.append(k); last_line = k
    # lines without words never appear in the path: keep them in written order
    for k in range(nlines):
        if k not in seq:
            pos = next((x for x, v in enumerate(seq) if v > k), len(seq))
            seq.insert(pos, k)
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
class Engine:
    def __init__(self, models, device='auto'):
        import torch
        self.torch = torch
        self.models = models
        os.environ.setdefault('TORCH_HOME', os.path.join(models, 'torch'))
        if device == 'auto':
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        if device == 'cuda' and not torch.cuda.is_available():
            log('CUDA requested but not available; using CPU')
            device = 'cpu'
        self.device = device
        if device == 'cpu':
            torch.set_num_threads(max(1, os.cpu_count() or 1))
        self._demucs = self._whisper = self._mms = None

    def info(self):
        t = self.torch
        name = t.cuda.get_device_name(0) if self.device == 'cuda' else (platform_cpu() or 'CPU')
        return {'device': self.device, 'device_name': name, 'torch': t.__version__,
                'cuda': t.version.cuda if self.device == 'cuda' else None,
                'vram_gb': round(t.cuda.get_device_properties(0).total_memory / 2**30, 1) if self.device == 'cuda' else None}

    # -- models
    def demucs(self):
        if self._demucs is None:
            from pathlib import Path
            from demucs.pretrained import get_model
            d = os.path.join(self.models, 'demucs')
            y = os.path.join(d, 'htdemucs.yaml')
            if not os.path.exists(y):
                with open(y, 'w') as f:
                    f.write("models: ['955717e8']\n")
            m = get_model('htdemucs', repo=Path(d))
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
            self._mms = (b, b.get_model(with_star=False).to(self.device).eval(), b.get_tokenizer(), b.get_aligner())
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

    def align(self, vocals16, sung_words, cb):
        """MMS_FA on 16 kHz mono vocals; emissions in 30 s chunks with 2 s context."""
        torch = self.torch
        bundle, model, tokenizer, aligner = self.mms()
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
                ems.append(em[:, s_off:e_off].float().cpu())
                pos += chunk
                cb(min(1.0, pos / n) * 0.9)
        emission = torch.cat(ems, 1)
        frame_sec = (n / SR) / emission.shape[1]
        words = [w for ws in sung_words for w in ws]
        if not words:
            raise RuntimeError('No alignable words in the lyrics.')
        spans = aligner(emission[0], tokenizer(words))
        cb(1.0)
        res, k = [], 0
        for ws in sung_words:
            sp = spans[k:k + len(ws)]
            k += len(ws)
            if sp:
                res.append((sp[0][0].start * frame_sec, sp[-1][-1].end * frame_sec,
                            [(w, s[0].start * frame_sec, s[-1].end * frame_sec) for w, s in zip(ws, sp)]))
            else:
                res.append(None)
        return res

    # -- full job
    def sync(self, job, progress):
        t = {}
        T0 = time.time()
        lines = [l for l in job['lines'] if l.strip()]
        if not lines:
            raise RuntimeError('No lyrics lines.')
        iso = job.get('iso') or ''
        stage_w = {'decode': (0.0, 0.03), 'separate': (0.03, 0.55), 'transcribe': (0.55, 0.85), 'align': (0.85, 1.0)}

        def stage(name):
            a, b = stage_w[name]
            progress(name, a)
            return lambda f: progress(name, a + (b - a) * f)

        cb = stage('decode')
        import torchaudio.functional as AF
        model_sr = 44100
        wav = self.decode(job['audio'], model_sr)
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

        t1 = time.time()
        rom_lines = romanize(lines, iso)
        line_words = [ctc_words(r) for r in rom_lines]
        repeats, seq, lang = [], list(range(len(lines))), job.get('lang')
        segments = []
        if job.get('repeats', True):
            words, lang, segments = self.transcribe(v16, job.get('lang'), stage('transcribe'))
            tw_text = romanize([w for w, s, e in words], iso)
            tw = [(x, s, e) for (w, s, e), r in zip(words, tw_text) for x in ctc_words(r)]
            seq, repeats = expand_repeats(line_words, tw)
            for r in repeats:
                log('repeat found: lines %s sung again (at ~%ss)' % ([i + 1 for i in r['lines']], r['time']))
        t['transcribe'] = time.time() - t1

        t1 = time.time()
        al = self.align(v16, [line_words[i] for i in seq], stage('align'))
        t['align'] = time.time() - t1

        # Lines without alignable words (e.g. only digits): place them between their neighbours.
        out = []
        for k, i in enumerate(seq):
            a = al[k]
            out.append({'idx': i, 'text': lines[i], 'start': a[0] if a else None, 'end': a[1] if a else None,
                        'repeat': seq.index(i) != k})
        for k, o in enumerate(out):
            if o['start'] is None:
                prev_end = next((out[j]['end'] for j in range(k - 1, -1, -1) if out[j]['end'] is not None), 0.0)
                nxt = next((out[j]['start'] for j in range(k + 1, len(out)) if out[j]['start'] is not None), duration)
                o['start'], o['end'], o['guessed'] = prev_end, max(prev_end, min(nxt, prev_end + 2.0)), True
        for o in out:
            dur = o['end'] - o['start']
            nw = max(1, len(o['text'].split()))
            o['flag'] = ('too long' if dur > max(8.0, nw * 1.2) else 'too short' if dur < 0.25 + 0.08 * nw else '')
            o['start'], o['end'] = round(o['start'], 3), round(o['end'], 3)
        t['total'] = time.time() - T0
        return {'lines': out, 'duration': round(duration, 3), 'language': lang, 'repeats': repeats,
                'device': self.device, 'timings': {k: round(v, 2) for k, v in t.items()}, 'transcript': segments}


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
    ap.add_argument('cmd', choices=['serve', 'check', 'sync'])
    ap.add_argument('args', nargs='*')
    a = ap.parse_args()
    os.environ['TORCH_HOME'] = os.path.join(a.models, 'torch')
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    try:
        eng = Engine(a.models, a.device)
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
            res = eng.sync(job, lambda s, f, jid=jid: emit(event='progress', id=jid, stage=s, pct=round(f, 3)))
            emit(event='result', id=jid, result=res)
        except Exception as e:  # report and keep serving the queue
            emit(event='error', id=jid, error=str(e) or e.__class__.__name__, trace=traceback.format_exc())
            if eng.device == 'cuda':
                eng.torch.cuda.empty_cache()
    return 0


if __name__ == '__main__':
    sys.exit(main())
