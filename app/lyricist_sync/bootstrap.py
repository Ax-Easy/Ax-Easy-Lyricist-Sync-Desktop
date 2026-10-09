"""First-run setup: download (resumable, SHA256-verified) Python 3.11, the right PyTorch
build (CUDA 12.4 for NVIDIA GPUs, CPU otherwise; on a Mac the Apple Silicon build with Metal
(MPS) or the Intel build), the engine wheels and the models into %LOCALAPPDATA%\\Ax-Easy\\LyricistSync
(macOS: ~/Library/Application Support/Ax-Easy/LyricistSync), then install them.  No Qt here
(CLI and GUI share it)."""
import ctypes
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request

from . import macfx, paths

NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
UA = 'AxEasy-LyricistSync/1.0'


class Cancelled(Exception):
    pass


IS_MAC = sys.platform == 'darwin'
VARIANT_LABEL = {'cuda': 'CUDA', 'cpu': 'CPU', 'mps': 'Apple Silicon'}


def manifest(arch=None):
    """The download list. On macOS: manifest-mac.json, the section for this Mac's architecture
    (Apple Silicon or Intel), in the same shape as the Windows manifest."""
    if not IS_MAC and not arch:
        with open(paths.resource('manifest.json'), encoding='utf-8') as f:
            return json.load(f)
    with open(paths.resource('manifest-mac.json'), encoding='utf-8') as f:
        m = json.load(f)
    sec = m['arch'][arch or macfx.machine_arch()]
    out = {k: v for k, v in m.items() if k != 'arch'}
    out.update(sec)
    return out


def detect_gpu():
    """{'nvidia': bool, 'name', 'driver', 'cuda_driver' (e.g. 12040), 'vram_gb'} without importing torch."""
    info = {'nvidia': False, 'name': '', 'driver': '', 'cuda_driver': 0, 'vram_gb': 0.0}
    if IS_MAC:   # Apple Silicon: the GPU shares the unified memory; Intel Macs: CPU build
        arch = macfx.machine_arch()
        info.update(apple=arch == 'arm64', arch=arch, name=macfx.chip_name(), memory_gb=macfx.memory_gb(),
                    macos='.'.join(str(x) for x in macfx.macos_version()))
        return info
    if os.name == 'nt':
        try:
            nv = ctypes.WinDLL('nvcuda.dll')
            v = ctypes.c_int(0)
            if nv.cuDriverGetVersion(ctypes.byref(v)) == 0:
                info['cuda_driver'] = v.value
        except OSError:
            pass
    smi = shutil.which('nvidia-smi') or (os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'nvidia-smi.exe')
                                         if os.name == 'nt' else None)
    if smi and os.path.exists(smi):
        try:
            out = run([smi, '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader,nounits'],
                      text=True, timeout=15, creationflags=NO_WINDOW).stdout.strip().splitlines()
            if out:
                info.update(parse_smi(out[0]))
        except Exception:
            pass
    info['nvidia'] = bool(info['name']) or info['cuda_driver'] >= 12000
    return info


def parse_smi(line):
    """One line of nvidia-smi --query-gpu=name,driver_version,memory.total (MiB, nounits)."""
    parts = [x.strip() for x in line.split(',')]
    d = {'name': parts[0], 'driver': parts[1] if len(parts) > 1 else ''}
    if len(parts) > 2:
        try:
            d['vram_gb'] = round(float(parts[2].split()[0]) / 1024.0, 1)
        except ValueError:
            pass
    return d


# Whisper size by hardware (Transcribe accuracy vs memory). GiB thresholds have slack because
# the reported total is a little under the marketing size (an RTX 3090 "24 GB" shows 23.7 GiB in
# torch and 24.0 in nvidia-smi; a "12 GB" card 11.7-12.0; a "6 GB" card 5.8-6.0).
WHISPER_ORDER = ['small', 'medium', 'large-v3-turbo', 'large-v3']
TIERS = [(23.5, 'large-v3'), (11.5, 'large-v3-turbo'), (5.5, 'medium')]


# Apple Silicon: Whisper runs on the GPU (MPS) out of the unified memory, which macOS and the
# other apps share, so the steps are one size class lower than the same amount of NVIDIA VRAM:
# 8 GB -> small, 16 GB -> medium, 24 GB -> large-v3-turbo, 32 GB and up -> large-v3.
MAC_TIERS = [(30.0, 'large-v3'), (22.0, 'large-v3-turbo'), (15.0, 'medium')]
# Intel Macs run on the CPU (fp32): medium only with plenty of memory (it is ~3x slower than small).
INTEL_TIERS = [(30.0, 'medium')]


def whisper_tier(vram_gb=None, variant='cuda'):
    """CPU or < 6 GB -> small, 6-11 GB -> medium, 12-23 GB -> large-v3-turbo, >= 24 GB -> large-v3.
    variant 'mps' (Apple Silicon) and 'mac-cpu' (Intel Mac) read vram_gb as the memory size."""
    tiers = {'cuda': TIERS, 'mps': MAC_TIERS, 'mac-cpu': INTEL_TIERS}.get(variant)
    if not tiers or not vram_gb:
        return 'small'
    for gb, name in tiers:
        if vram_gb >= gb:
            return name
    return 'small'


def tier_variant(variant):
    """The whisper_tier() variant for this platform (an Intel Mac's 'cpu' is tiered by memory)."""
    return 'mac-cpu' if IS_MAC and variant == 'cpu' else variant


def state_tier(st=None):
    """The hardware Whisper tier from state.json (after setup): VRAM on CUDA, memory on a Mac."""
    st = st if st is not None else (state() or {})
    eng = st.get('engine') or {}
    variant = st.get('variant', 'cpu')
    if IS_MAC:
        return whisper_tier(eng.get('memory_gb') or macfx.memory_gb(), tier_variant(variant))
    return whisper_tier(eng.get('vram_gb') if eng.get('device') == 'cuda' else None, variant)


def whisper_models(man=None):
    """{name: manifest entry} in WHISPER_ORDER."""
    man = man or manifest()
    by = {m['name']: m for m in man.get('whisper_models', [])}
    return {n: by[n] for n in WHISPER_ORDER if n in by}


def whisper_path(name, home=None):
    m = whisper_models()[name]
    return os.path.join(home or paths.home(), *m['dest'].split('/'))


def whisper_installed(home=None):
    """Sizes whose .pt is complete (right size; .ok marker or the file that 1.2.0 installed)."""
    out = []
    for n, m in whisper_models().items():
        p = whisper_path(n, home)
        if os.path.exists(p) and os.path.getsize(p) == m['size']:
            out.append(n)
    return out


def effective_whisper(choice, tier, installed):
    """What the engine will use: the user's pick (or the hardware tier for 'auto') when installed,
    else the best installed size that is not bigger than that, else the best installed."""
    want = tier if choice in (None, '', 'auto') else choice
    if want in installed or not installed:
        return want
    order = WHISPER_ORDER
    smaller = [n for n in installed if order.index(n) <= order.index(want)] if want in order else []
    return max(smaller or installed, key=order.index)


def delete_whisper(name, in_use, home=None):
    """Remove a downloaded size (never the one in use or the last one). Returns bytes freed."""
    inst = whisper_installed(home)
    if name == in_use:
        raise RuntimeError('Whisper %s is in use; pick another model first.' % name)
    if name in inst and len(inst) <= 1:
        raise RuntimeError('This is the only Whisper model installed.')
    p = whisper_path(name, home)
    freed = 0
    for q in (p, p + '.ok', p + '.part'):
        if os.path.exists(q):
            freed += os.path.getsize(q)
            os.remove(q)
    return freed


def variants():
    """The PyTorch builds this platform can install, recommended first on a Mac."""
    if IS_MAC:
        return ['mps'] if macfx.machine_arch() == 'arm64' else ['cpu']
    return ['cuda', 'cpu']


def recommended_variant(gpu=None):
    if IS_MAC:
        return variants()[0]
    gpu = gpu or detect_gpu()
    # cu124 wheels need a CUDA 12.x capable driver (>= 525); otherwise fall back to CPU.
    if gpu['nvidia'] and (gpu['cuda_driver'] >= 12000 or (gpu['cuda_driver'] == 0 and gpu['name'])):
        return 'cuda'
    return 'cpu'


def plan(variant, man=None, whisper=None):
    """Files to fetch for a variant. Only ONE Whisper size is in the plan: `whisper` (default: the
    manifest's small entry; the GUI passes the hardware tier)."""
    man = man or manifest()
    h = paths.home()
    dl = os.path.join(h, 'downloads')
    items = [dict(man['python'], dest=os.path.join(dl, man['python']['name']), kind='python', label='Python 3.11 runtime')]
    for w in man['torch'][variant]:
        items.append(dict(w, dest=os.path.join(dl, w['name']), kind='wheel',
                          label=w['name'].split('-')[0] + ' (' + VARIANT_LABEL.get(variant, variant.upper()) + ')'))
    for w in man['wheels']:
        items.append(dict(w, dest=os.path.join(dl, w['name']), kind='wheel', label=w['name'].split('-')[0]))
    wm = {m['name']: m for m in man.get('whisper_models', [])}
    for m in man['models']:
        if m['id'] == 'whisper' and whisper and whisper in wm:
            m = dict(wm[whisper], id='whisper')
        items.append(dict(m, dest=os.path.join(h, *m['dest'].split('/')), kind='model'))
    return items


def total_size(variant, whisper=None):
    return sum(i['size'] for i in plan(variant, whisper=whisper))


def state():
    p = os.path.join(paths.home(), 'state.json')
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def is_ready():
    s = state()
    return bool(s and s.get('ok') and os.path.exists(paths.runtime_python())) or bool(os.environ.get('LYRICIST_SYNC_PYTHON'))


BELOW_NORMAL = 0x00004000 if os.name == 'nt' else 0  # BELOW_NORMAL_PRIORITY_CLASS


def popen(args, **kw):
    """subprocess.Popen without PyInstaller's DLL directory leaking into the child
    (the child is a different Python and must load its own python311.dll)."""
    frozen = os.name == 'nt' and getattr(sys, 'frozen', False)
    if frozen:
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        return subprocess.Popen(args, **kw)
    finally:
        if frozen:
            ctypes.windll.kernel32.SetDllDirectoryW(getattr(sys, '_MEIPASS', None))


def run(args, timeout=None, **kw):
    p = popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    out, err = p.communicate(timeout=timeout)
    return subprocess.CompletedProcess(args, p.returncode, out, err)


def engine_env():
    env = dict(os.environ)
    env.update(PYTHONNOUSERSITE='1', PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               TORCH_HOME=os.path.join(paths.models_dir(), 'torch'), HF_HUB_OFFLINE='1', KMP_DUPLICATE_LIB_OK='TRUE',
               PYTORCH_ENABLE_MPS_FALLBACK='1')   # Apple Silicon: ops MPS lacks run on the CPU
    for k in list(env):
        if k in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'TCL_LIBRARY', 'TK_LIBRARY') \
                or k.startswith('_PYI') or k.startswith('_MEI'):
            env.pop(k, None)
    return env


def model_group(m):
    d = m['dest'].replace('\\', '/')  # plan() turns dest into a native path (backslashes on Windows)
    return 'demucs' if '/demucs/' in d else 'whisper' if '/whisper/' in d else 'mms'


STEP_DEFS = [
    ('dl_torch', 'Download PyTorch ({V}) and Python packages'),
    ('install', 'Install PyTorch and the engine'),
    ('dl_demucs', 'Download Demucs vocal model'),
    ('dl_whisper', 'Download Whisper model'),
    ('dl_mms', 'Download MMS alignment model'),
    ('verify', 'Verify files (SHA256)'),
    ('check', '{CHECK}'),
]


def mirror(url, name):
    """Test hook: LYRICIST_SYNC_MIRROR=http://127.0.0.1:port/ serves every file by name
    (CI: throttled local server). Only loopback mirrors are honoured."""
    m = os.environ.get('LYRICIST_SYNC_MIRROR', '')
    if m.startswith(('http://127.0.0.1', 'http://localhost')):
        return m.rstrip('/') + '/' + urllib.request.quote(name)
    return url


class SetupState:
    """Shared between the worker thread and the UI. The UI polls snapshot() ~10x/s, so the
    worker never floods the event loop with signals."""

    def __init__(self, steps):
        self.lock = threading.Lock()
        self.steps = {k: {'id': k, 'label': lbl, 'status': 'waiting', 'done': 0, 'total': 0, 'unit': 'bytes',
                          'detail': '', 'speed': 0.0, 't0': None, 't1': None, 'last': time.time(), 'indeterminate': False,
                          'error': ''} for k, lbl in steps}
        self.order = [k for k, _ in steps]
        self.current = None
        self.logs = []
        self.t0 = time.time()
        self.finished = False
        self.failed = None
        self.result = None

    def update(self, sid, **kw):
        with self.lock:
            st = self.steps[sid]
            if 'status' in kw and kw['status'] == 'running' and st['t0'] is None:
                st['t0'] = time.time()
            if kw.get('status') in ('done', 'failed', 'skipped'):
                st['t1'] = time.time()
            st.update(kw)
            st['last'] = time.time()
            if kw.get('status') == 'running':
                self.current = sid

    def log(self, line):
        with self.lock:
            self.logs.append(line)
            if len(self.logs) > 2000:
                del self.logs[:500]

    def snapshot(self, log_from=0):
        with self.lock:
            return ({k: dict(v) for k, v in self.steps.items()}, self.current, list(self.logs[log_from:]), len(self.logs))


class Setup:
    """The first-run install as 7 visible steps, run on a worker thread. Each step is
    resumable: finished downloads carry a .ok marker, finished steps are recorded in
    setup_progress.json, so an interrupted setup continues at the first incomplete step."""

    def __init__(self, variant, on_progress=None, on_status=None, on_log=None, cancel=None, state=None, whisper=None):
        self.variant = variant
        self.whisper = whisper or 'small'
        self.items = plan(variant, whisper=self.whisper)
        self.total = sum(i['size'] for i in self.items)
        self.on_progress = on_progress or (lambda *a: None)
        self.on_status = on_status or (lambda *a: None)
        self.on_log = on_log or (lambda *a: None)
        self.cancel = cancel or threading.Event()
        self.home = paths.home()
        self.logf = open(os.path.join(self.home, 'setup.log'), 'a', encoding='utf-8')
        self.state = state or SetupState(self.steps())
        self._done_bytes = {}

    def steps(self):
        check = {'cuda': 'GPU check / warm-up', 'mps': 'Apple GPU (Metal) check / warm-up'}.get(self.variant, 'Engine check / warm-up (CPU)')
        v = VARIANT_LABEL.get(self.variant, self.variant.upper())
        return [(k, lbl.replace('{V}', v).replace('{CHECK}', check)) for k, lbl in STEP_DEFS]

    def step_items(self, sid):
        if sid == 'dl_torch':
            return [i for i in self.items if i['kind'] in ('python', 'wheel')]
        if sid.startswith('dl_'):
            return [i for i in self.items if i['kind'] == 'model' and model_group(i) == sid[3:]]
        return []

    def log(self, msg):
        line = time.strftime('%H:%M:%S ') + str(msg)
        self.logf.write(line + '\n')
        self.logf.flush()
        self.state.log(line)
        self.on_log(line)

    # ---- progress bookkeeping
    def _progress_path(self):
        return os.path.join(self.home, 'setup_progress.json')

    def progress_file(self):
        try:
            with open(self._progress_path(), encoding='utf-8') as f:
                d = json.load(f)
            return d if d.get('variant') == self.variant and d.get('manifest') == manifest()['version'] else {}
        except (OSError, ValueError):
            return {}

    def _mark(self, sid):
        d = self.progress_file() or {'variant': self.variant, 'manifest': manifest()['version'], 'done': []}
        if sid not in d['done']:
            d['done'].append(sid)
        with open(self._progress_path(), 'w', encoding='utf-8') as f:
            json.dump(d, f)

    # ---- downloads
    def _verified(self, it):
        return os.path.exists(it['dest']) and os.path.getsize(it['dest']) == it['size'] and os.path.exists(it['dest'] + '.ok')

    def check_space(self):
        free = shutil.disk_usage(self.home).free
        remaining = sum(i['size'] for i in self.items if not self._verified(i))
        want = remaining * 2.2 + 1e9 if self.variant == 'cuda' else remaining * 2 + 5e8
        if free < want:
            raise RuntimeError('Not enough disk space in %s: %.1f GB free, about %.1f GB needed.' % (self.home, free / 1e9, want / 1e9))

    def download_step(self, sid):
        items = self.step_items(sid)
        total = sum(i['size'] for i in items)
        done = sum(i['size'] for i in items if self._verified(i))
        self.state.update(sid, status='running', done=done, total=total, unit='bytes', indeterminate=False)
        for n, it in enumerate(items):
            if self.cancel.is_set():
                raise Cancelled()
            if self._verified(it):
                continue
            self.state.update(sid, detail='%s (%d of %d)' % (it['label'], n + 1, len(items)))
            self.on_status('Downloading %s (%d/%d)' % (it['label'], n + 1, len(items)))
            self._download(it, done, sid, total)
            done += it['size']
            self.state.update(sid, done=done)
        self.state.update(sid, status='done', done=total, speed=0.0, detail='%d file%s, %.2f GB, SHA256 checked while downloading' % (
            len(items), '' if len(items) == 1 else 's', total / 1e9))

    def download_all(self):  # CLI/back-compat
        self.check_space()
        for sid in ('dl_torch', 'dl_demucs', 'dl_whisper', 'dl_mms'):
            self.download_step(sid)

    def _download(self, it, done_before, sid=None, step_total=None):
        os.makedirs(os.path.dirname(it['dest']), exist_ok=True)
        part = it['dest'] + '.part'
        url = mirror(it['url'], os.path.basename(it['dest']))
        for attempt in range(8):
            if self.cancel.is_set():
                raise Cancelled()
            have = os.path.getsize(part) if os.path.exists(part) else 0
            if have > it['size']:
                os.remove(part)
                have = 0
            h = hashlib.sha256()
            if have:
                if sid:
                    self.state.update(sid, detail='Checking the part already downloaded of %s…' % it['label'])
                with open(part, 'rb') as f:
                    for b in iter(lambda: f.read(1 << 22), b''):
                        if self.cancel.is_set():
                            raise Cancelled()
                        h.update(b)
            try:
                if have < it['size']:
                    req = urllib.request.Request(url, headers={'User-Agent': UA, **({'Range': 'bytes=%d-' % have} if have else {})})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        if have and r.status != 206:  # server ignored Range: start over
                            have, h = 0, hashlib.sha256()
                            mode = 'wb'
                        else:
                            mode = 'ab' if have else 'wb'
                        if have:
                            self.log('Resuming %s at %.1f MB' % (it['label'], have / 1e6))
                        with open(part, mode) as f:
                            last = 0
                            t_start, b_start = time.time(), have
                            while True:
                                if self.cancel.is_set():
                                    raise Cancelled()
                                b = r.read(1 << 20)
                                if not b:
                                    break
                                f.write(b)
                                h.update(b)
                                have += len(b)
                                now = time.time()
                                if now - last > 0.25:
                                    last = now
                                    spd = (have - b_start) / max(0.001, now - t_start)
                                    if sid:
                                        self.state.update(sid, done=done_before + have, speed=spd,
                                                          detail='%s · %.0f of %.0f MB' % (it['label'], have / 1e6, it['size'] / 1e6))
                                    self.on_progress(done_before + have, step_total or self.total, it, spd)
                if have != it['size']:
                    raise IOError('incomplete download (%d of %d bytes)' % (have, it['size']))
                if h.hexdigest() != it['sha256']:
                    os.remove(part)
                    raise IOError('checksum mismatch for %s, downloading again' % it['label'])
                os.replace(part, it['dest'])
                open(it['dest'] + '.ok', 'w').close()
                self.log('Downloaded %s (%.1f MB, SHA256 OK)' % (it['label'], it['size'] / 1e6))
                return
            except Cancelled:
                raise
            except (urllib.error.URLError, IOError, OSError, TimeoutError) as e:
                wait = min(60, 3 * 2 ** attempt)
                self.log('Download problem (%s); retrying in %d s' % (e, wait))
                if sid:
                    self.state.update(sid, detail='Network problem, retrying %s in %d s…' % (it['label'], wait))
                self.on_status('Network problem, retrying %s in %d s…' % (it['label'], wait))
                for _ in range(wait * 4):
                    if self.cancel.is_set():
                        raise Cancelled()
                    time.sleep(0.25)
        raise RuntimeError('Could not download %s. Check the connection and press Retry step; finished parts are kept.' % it['label'])

    # ---- install
    def _run(self, args, what, sid=None):
        # pip unpacks and byte-compiles thousands of files: below-normal priority keeps the
        # window responsive on busy machines (it only yields to interactive work)
        """Run a child with its output streamed line by line to setup.log (never an unread pipe)."""
        self.log('$ ' + ' '.join(os.path.basename(a) if os.path.isabs(a) else a for a in args[:8]) + (' …' if len(args) > 8 else ''))
        p = popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                  encoding='utf-8', errors='replace', env=engine_env(), creationflags=NO_WINDOW | BELOW_NORMAL)
        tail = []
        for line in p.stdout:  # this worker is the reader: the pipe never fills up
            line = line.rstrip()
            if line:
                tail = (tail + [line])[-30:]
                self.logf.write(line + '\n')
                self.state.log(line)
                if sid:
                    self.state.update(sid, detail=line[:140])
            if self.cancel.is_set():
                p.kill()
        p.wait()
        self.logf.flush()
        if self.cancel.is_set():
            raise Cancelled()
        if p.returncode != 0:
            raise RuntimeError('%s failed (exit %s):\n%s' % (what, p.returncode, '\n'.join(tail[-12:])))
        return tail

    def install_step(self):
        sid = 'install'
        man = manifest()
        py = paths.runtime_python(self.home)
        rt = os.path.join(self.home, 'runtime')
        wheels = [i for i in self.items if i['kind'] == 'wheel']
        torch_w = [i for i in wheels if i['name'].startswith(('torch-', 'torchaudio-'))]
        other_w = [i for i in wheels if i not in torch_w]
        local = [os.path.join(paths.app_dir(), 'wheels', w) for w in man.get('local_wheels', [])]
        for w in local:
            if not os.path.exists(w):
                raise RuntimeError('Missing bundled wheel: ' + w)
        # weights for one determinate bar: python files, torch (by size), the rest
        units = {'python': 25e6, 'torch': sum(i['size'] for i in torch_w), 'other': sum(i['size'] for i in other_w) + 5e6}
        total = sum(units.values())
        self.state.update(sid, status='running', done=0, total=total, unit='work', indeterminate=False)
        done = 0
        if not (os.path.exists(py) and os.path.exists(os.path.join(rt, 'python', '.complete'))):
            shutil.rmtree(rt, ignore_errors=True)
            tmp = rt + '.tmp'
            shutil.rmtree(tmp, ignore_errors=True)
            with tarfile.open(os.path.join(self.home, 'downloads', man['python']['name'])) as t:
                members = t.getmembers()
                for n, mem in enumerate(members):
                    if self.cancel.is_set():
                        raise Cancelled()
                    if hasattr(tarfile, 'data_filter'):
                        t.extract(mem, tmp, filter='data')
                    else:
                        t.extract(mem, tmp)
                    if n % 50 == 0:
                        self.state.update(sid, done=units['python'] * n / len(members),
                                          detail='Unpacking Python · %d of %d files · %s' % (n, len(members), mem.name[-60:]))
            os.replace(tmp, rt)
            open(os.path.join(rt, 'python', '.complete'), 'w').close()
            self.log('Python unpacked to ' + rt)
            if IS_MAC:   # the app downloads itself, so nothing is quarantined; checked anyway
                n = macfx.strip_quarantine(rt)
                self.log('Quarantine check: %s' % ('%d files had com.apple.quarantine (removed)' % n if n else 'none'))
        done += units['python']
        pipargs = [py, '-m', 'pip', 'install', '--no-index', '--no-deps', '--force-reinstall', '--disable-pip-version-check',
                   '--no-warn-script-location', '--progress-bar', 'off']
        self.state.update(sid, done=done, indeterminate=True,
                          detail='Installing PyTorch (%.1f GB unpacked from %d wheels)…' % (units['torch'] / 1e9 * 1.6, len(torch_w)))
        self._run(pipargs + [i['dest'] for i in torch_w], 'PyTorch install', sid)
        done += units['torch']
        self.state.update(sid, done=done, indeterminate=True, detail='Installing %d engine packages…' % (len(other_w) + len(local)))
        self._run(pipargs + [i['dest'] for i in other_w] + local, 'Package install', sid)
        if IS_MAC and macfx.strip_quarantine(rt):
            self.log('Removed com.apple.quarantine from installed packages')
        self.state.update(sid, status='done', done=total, indeterminate=False, detail='PyTorch %s and %d packages installed' % (
            VARIANT_LABEL.get(self.variant, self.variant.upper()), len(wheels) + len(local)))
        for w in wheels:  # installed: drop the wheels to save disk (models stay)
            for p in (w['dest'], w['dest'] + '.ok'):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def verify_step(self):
        sid = 'verify'
        items = [i for i in self.items if i['kind'] == 'model']
        total = sum(i['size'] for i in items)
        self.state.update(sid, status='running', done=0, total=total, unit='bytes')
        done = 0
        for n, it in enumerate(items):
            h = hashlib.sha256()
            got = 0
            last = 0
            with open(it['dest'], 'rb') as f:
                for b in iter(lambda: f.read(1 << 22), b''):  # hashlib releases the GIL on big blocks
                    if self.cancel.is_set():
                        raise Cancelled()
                    h.update(b)
                    got += len(b)
                    if time.time() - last > 0.2:
                        last = time.time()
                        self.state.update(sid, done=done + got, detail='%s · %d of %d · %.0f%%' % (
                            it['label'], n + 1, len(items), 100.0 * got / max(1, it['size'])))
            if h.hexdigest() != it['sha256']:
                for p in (it['dest'], it['dest'] + '.ok'):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                raise RuntimeError('%s failed the SHA256 check and was deleted. Press Retry step to download it again.' % it['label'])
            done += it['size']
            self.log('Verified %s (SHA256 OK)' % it['label'])
        self.state.update(sid, status='done', done=total, detail='%d model files OK' % len(items))

    def check_step(self):
        sid = 'check'
        self.state.update(sid, status='running', indeterminate=True, detail='Starting the engine (loading PyTorch)…', unit='work')
        info = self.check(paths.runtime_python(self.home))
        if info.get('device') == 'cuda':
            d = 'CUDA OK · %s · %s GB' % (info.get('device_name', 'NVIDIA GPU'), ('%g' % info['vram_gb']) if info.get('vram_gb') else '?')
        elif info.get('device') == 'mps':
            d = 'Metal (MPS) OK · %s%s' % (info.get('device_name') or 'Apple GPU',
                                          (' · %g GB unified memory' % info['memory_gb']) if info.get('memory_gb') else '')
        elif self.variant == 'mps':
            d = 'CPU OK · %s (Metal needs macOS 12.3 or later; the engine uses the CPU)' % (info.get('device_name') or 'CPU')
        else:
            d = 'CPU OK · %s' % (info.get('device_name') or 'CPU')
            if self.variant == 'cuda':
                d += ' (no usable GPU found)'
        self.state.update(sid, status='done', indeterminate=False, detail=d, done=1, total=1)
        man = manifest()
        st = {'ok': True, 'variant': self.variant, 'manifest': man['version'], 'installed': time.strftime('%Y-%m-%d %H:%M'),
              'engine': info, 'whisper': self.whisper}
        with open(os.path.join(self.home, 'state.json'), 'w', encoding='utf-8') as f:
            json.dump(st, f, indent=1)
        self.log('Setup complete: %s' % json.dumps(info))
        return st

    def install(self):  # back-compat (CLI)
        self.install_step()
        self.verify_step()
        return self.check_step()

    def check(self, py):
        out = run([py, paths.engine_script(), '--models', paths.models_dir(), 'check'], text=True,
                  encoding='utf-8', errors='replace', env=engine_env(), creationflags=NO_WINDOW, timeout=900)
        self.logf.write(out.stderr[-4000:] + '\n')
        info = {}
        for line in out.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get('event') == 'hello':
                info = ev
            if ev.get('event') == 'error':
                raise RuntimeError(ev.get('error'))
        if out.returncode != 0 or not info:
            raise RuntimeError('Engine check failed:\n' + out.stderr[-1500:])
        if self.variant == 'cuda' and info.get('device') != 'cuda':
            self.log('Warning: CUDA build installed but no usable GPU found; the engine will use the CPU.')
        return info

    def run(self):
        """All steps; finished steps (from an earlier, interrupted run) are skipped."""
        done = set(self.progress_file().get('done', []))
        try:
            self.log('Setup started: variant=%s, %d files, %.2f GB%s' % (
                self.variant, len(self.items), self.total / 1e9, (' (resuming; done: %s)' % ', '.join(sorted(done))) if done else ''))
            self.check_space()
            res = None
            for sid in self.state.order:
                if self.cancel.is_set():
                    raise Cancelled()
                if sid in done and sid != 'check':
                    if sid.startswith('dl_') and not all(self._verified(i) for i in self.step_items(sid)):
                        pass  # files went missing: do it again
                    else:
                        self.state.update(sid, status='done', detail='Done earlier', done=1, total=1)
                        continue
                try:
                    if sid.startswith('dl_'):
                        self.download_step(sid)
                    elif sid == 'install':
                        self.install_step()
                    elif sid == 'verify':
                        self.verify_step()
                    else:
                        res = self.check_step()
                except Cancelled:
                    self.state.update(sid, status='paused')
                    raise
                except Exception as e:
                    self.state.update(sid, status='failed', error=str(e), indeterminate=False)
                    self.log('Step failed: %s: %s' % (sid, e))
                    raise
                self._mark(sid)
            self.state.result = res
            return res
        finally:
            self.logf.flush()


class ModelDownload:
    """Engine settings: fetch one more Whisper size with the setup machinery (resumable .part,
    SHA256 while downloading, .ok marker, retries) as two visible steps, then re-check SHA256."""
    STEPS = [('dl_whisper', 'Download Whisper {N}'), ('verify', 'Verify file (SHA256)')]

    def __init__(self, name, cancel=None, state=None):
        self.name = name
        steps = [(k, lbl.replace('{N}', name)) for k, lbl in self.STEPS]
        self.state = state or SetupState(steps)
        self.setup = Setup('cpu', cancel=cancel, state=self.state, whisper=name)
        self.setup.items = [i for i in self.setup.items if i['kind'] == 'model' and model_group(i) == 'whisper']
        self.cancel = self.setup.cancel

    def run(self):
        s = self.setup
        it = s.items[0]
        free = shutil.disk_usage(s.home).free
        need = 0 if s._verified(it) else it['size'] - (os.path.getsize(it['dest'] + '.part') if os.path.exists(it['dest'] + '.part') else 0)
        if free < need + 5e8:
            raise RuntimeError('Not enough disk space: %.1f GB free, %.1f GB needed.' % (free / 1e9, (need + 5e8) / 1e9))
        for sid in ('dl_whisper', 'verify'):
            try:
                s.download_step(sid) if sid == 'dl_whisper' else s.verify_step()
            except Cancelled:
                self.state.update(sid, status='paused')
                raise
            except Exception as e:
                self.state.update(sid, status='failed', error=str(e), indeterminate=False)
                s.log('Model download failed: %s: %s' % (sid, e))
                raise
        s.log('Whisper %s installed' % self.name)
        self.state.result = self.name
        return self.name


def cleanup_partial():
    for p in glob.glob(os.path.join(paths.home(), 'downloads', '*.part')):
        os.remove(p)
