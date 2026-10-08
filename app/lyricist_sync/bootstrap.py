"""First-run setup: download (resumable, SHA256-verified) Python 3.11, the right PyTorch
build (CUDA 12.4 for NVIDIA GPUs, CPU otherwise), the engine wheels and the models into
%LOCALAPPDATA%\\Ax-Easy\\LyricistSync, then install them.  No Qt here (CLI and GUI share it)."""
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

from . import paths

NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
UA = 'AxEasy-LyricistSync/1.0'


class Cancelled(Exception):
    pass


def manifest():
    with open(paths.resource('manifest.json'), encoding='utf-8') as f:
        return json.load(f)


def detect_gpu():
    """{'nvidia': bool, 'name', 'driver', 'cuda_driver' (e.g. 12040)} without importing torch."""
    info = {'nvidia': False, 'name': '', 'driver': '', 'cuda_driver': 0}
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
            out = run([smi, '--query-gpu=name,driver_version', '--format=csv,noheader'],
                      text=True, timeout=15, creationflags=NO_WINDOW).stdout.strip().splitlines()
            if out:
                name, drv = [x.strip() for x in out[0].split(',')[:2]]
                info.update(name=name, driver=drv)
        except Exception:
            pass
    info['nvidia'] = bool(info['name']) or info['cuda_driver'] >= 12000
    return info


def recommended_variant(gpu=None):
    gpu = gpu or detect_gpu()
    # cu124 wheels need a CUDA 12.x capable driver (>= 525); otherwise fall back to CPU.
    if gpu['nvidia'] and (gpu['cuda_driver'] >= 12000 or (gpu['cuda_driver'] == 0 and gpu['name'])):
        return 'cuda'
    return 'cpu'


def plan(variant, man=None):
    man = man or manifest()
    h = paths.home()
    dl = os.path.join(h, 'downloads')
    items = [dict(man['python'], dest=os.path.join(dl, man['python']['name']), kind='python', label='Python 3.11 runtime')]
    for w in man['torch'][variant]:
        items.append(dict(w, dest=os.path.join(dl, w['name']), kind='wheel', label=w['name'].split('-')[0] + ' (' + variant.upper() + ')'))
    for w in man['wheels']:
        items.append(dict(w, dest=os.path.join(dl, w['name']), kind='wheel', label=w['name'].split('-')[0]))
    for m in man['models']:
        items.append(dict(m, dest=os.path.join(h, *m['dest'].split('/')), kind='model'))
    return items


def total_size(variant):
    return sum(i['size'] for i in plan(variant))


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
               TORCH_HOME=os.path.join(paths.models_dir(), 'torch'), HF_HUB_OFFLINE='1', KMP_DUPLICATE_LIB_OK='TRUE')
    for k in list(env):
        if k in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'TCL_LIBRARY', 'TK_LIBRARY') \
                or k.startswith('_PYI') or k.startswith('_MEI'):
            env.pop(k, None)
    return env


class Setup:
    """Runs the whole first-run install. Callbacks are called from the worker thread."""

    def __init__(self, variant, on_progress=None, on_status=None, on_log=None, cancel=None):
        self.variant = variant
        self.items = plan(variant)
        self.total = sum(i['size'] for i in self.items)
        self.on_progress = on_progress or (lambda *a: None)
        self.on_status = on_status or (lambda *a: None)
        self.on_log = on_log or (lambda *a: None)
        self.cancel = cancel or threading.Event()
        self.home = paths.home()
        self.logf = open(os.path.join(self.home, 'setup.log'), 'a', encoding='utf-8')

    def log(self, msg):
        line = time.strftime('%H:%M:%S ') + str(msg)
        self.logf.write(line + '\n')
        self.logf.flush()
        self.on_log(line)

    # ---- downloads
    def _verified(self, it):
        return os.path.exists(it['dest']) and os.path.getsize(it['dest']) == it['size'] and os.path.exists(it['dest'] + '.ok')

    def download_all(self):
        need = shutil.disk_usage(self.home).free
        remaining = sum(i['size'] for i in self.items if not self._verified(i))
        want = remaining * 2.2 + 1e9 if self.variant == 'cuda' else remaining * 2 + 5e8
        if need < want:
            raise RuntimeError('Not enough disk space in %s: %.1f GB free, about %.1f GB needed.' % (self.home, need / 1e9, want / 1e9))
        done_before = 0
        self._t0, self._b0 = time.time(), 0
        for n, it in enumerate(self.items):
            if self.cancel.is_set():
                raise Cancelled()
            if self._verified(it):
                done_before += it['size']
                self.on_progress(done_before, self.total, it, 0)
                continue
            self.on_status('Downloading %s (%d/%d)' % (it['label'], n + 1, len(self.items)))
            self._download(it, done_before)
            done_before += it['size']

    def _download(self, it, done_before):
        os.makedirs(os.path.dirname(it['dest']), exist_ok=True)
        part = it['dest'] + '.part'
        for attempt in range(8):
            if self.cancel.is_set():
                raise Cancelled()
            have = os.path.getsize(part) if os.path.exists(part) else 0
            if have > it['size']:
                os.remove(part)
                have = 0
            h = hashlib.sha256()
            if have:
                with open(part, 'rb') as f:
                    for b in iter(lambda: f.read(1 << 22), b''):
                        h.update(b)
            try:
                if have < it['size']:
                    req = urllib.request.Request(it['url'], headers={'User-Agent': UA, **({'Range': 'bytes=%d-' % have} if have else {})})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        if have and r.status != 206:  # server ignored Range: start over
                            have, h = 0, hashlib.sha256()
                            mode = 'wb'
                        else:
                            mode = 'ab' if have else 'wb'
                        if have:
                            self.log('Resuming %s at %.1f MB' % (it['name'] if 'name' in it else it['label'], have / 1e6))
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
                                    self.on_progress(done_before + have, self.total, it, spd)
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
                self.on_status('Network problem, retrying %s in %d s…' % (it['label'], wait))
                for _ in range(wait * 4):
                    if self.cancel.is_set():
                        raise Cancelled()
                    time.sleep(0.25)
        raise RuntimeError('Could not download %s. Check the connection and press Retry; finished parts are kept.' % it['label'])

    # ---- install
    def _run(self, args, what):
        self.log('$ ' + ' '.join(args[:6]) + (' …' if len(args) > 6 else ''))
        p = popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                  env=engine_env(), creationflags=NO_WINDOW)
        tail = []
        for line in p.stdout:
            line = line.rstrip()
            if line:
                tail = (tail + [line])[-30:]
                self.logf.write(line + '\n')
                if self.cancel.is_set():
                    p.kill()
        p.wait()
        if p.returncode != 0:
            raise RuntimeError('%s failed (exit %s):\n%s' % (what, p.returncode, '\n'.join(tail[-12:])))
        return tail

    def install(self):
        man = manifest()
        py = paths.runtime_python(self.home)
        rt = os.path.join(self.home, 'runtime')
        if not (os.path.exists(py) and os.path.exists(os.path.join(rt, 'python', '.complete'))):
            self.on_status('Unpacking Python…')
            shutil.rmtree(rt, ignore_errors=True)
            tmp = rt + '.tmp'
            shutil.rmtree(tmp, ignore_errors=True)
            with tarfile.open(os.path.join(self.home, 'downloads', man['python']['name'])) as t:
                if hasattr(tarfile, 'data_filter'):
                    t.extractall(tmp, filter='data')
                else:
                    t.extractall(tmp)
            os.replace(tmp, rt)
            open(os.path.join(rt, 'python', '.complete'), 'w').close()
            self.log('Python unpacked to ' + rt)
        if self.cancel.is_set():
            raise Cancelled()
        self.on_status('Installing PyTorch (%s) and the engine packages… (a few minutes)' % self.variant.upper())
        wheels = [i['dest'] for i in self.items if i['kind'] == 'wheel']
        local = [os.path.join(paths.app_dir(), 'wheels', w) for w in man.get('local_wheels', [])]
        for w in local:
            if not os.path.exists(w):
                raise RuntimeError('Missing bundled wheel: ' + w)
        self._run([py, '-m', 'pip', 'install', '--no-index', '--no-deps', '--force-reinstall', '--disable-pip-version-check',
                   '--no-warn-script-location'] + wheels + local, 'Package install')
        self.on_status('Checking the engine…')
        info = self.check(py)
        st = {'ok': True, 'variant': self.variant, 'manifest': man['version'], 'installed': time.strftime('%Y-%m-%d %H:%M'),
              'engine': info}
        with open(os.path.join(self.home, 'state.json'), 'w', encoding='utf-8') as f:
            json.dump(st, f, indent=1)
        # The wheels are installed; drop them to save ~%s of disk (models stay).
        for w in wheels:
            for p in (w, w + '.ok'):
                try:
                    os.remove(p)
                except OSError:
                    pass
        self.log('Setup complete: %s' % json.dumps(info))
        return st

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
        try:
            self.log('Setup started: variant=%s, %d files, %.2f GB' % (self.variant, len(self.items), self.total / 1e9))
            self.download_all()
            return self.install()
        finally:
            self.logf.flush()


def cleanup_partial():
    for p in glob.glob(os.path.join(paths.home(), 'downloads', '*.part')):
        os.remove(p)
