"""Build app/lyricist_sync/manifest-mac.json: every first-run download of the Mac engine, per
architecture, with URL, size and SHA256 (the same Setup machinery as Windows reads it).

  python tools/make_manifest_mac.py <arm64 wheel dir> <x86_64 wheel dir>

The wheel dirs come from the hash-pinned locks (pip download --no-deps --only-binary :all:):
  arm64:  --platform macosx_11_0_arm64  -r tools/engine-lock-mac-arm64.txt   (macOS 11 Big Sur+)
  x86_64: --platform macosx_12_0_x86_64 -r tools/engine-lock-mac-x86_64.txt  (macOS 12 Monterey+)

Why two stacks: PyTorch stopped publishing Intel Mac wheels after 2.2.2, so Intel Macs get
torch/torchaudio 2.2.2 with numpy 1.26 (numba 0.62 / llvmlite 0.45, the last with Intel Mac
wheels); Apple Silicon gets the same 2.5.1 as Windows (MPS on macOS 12.3+, CPU on Big Sur).
demucs 4.1.0 declares sphn, which has no Intel Mac wheel; the engine never imports demucs.api
(the only user of sphn), and the setup installs with --no-deps, so it is left out there."""
import hashlib, json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_manifest import MODELS, pypi_file  # noqa: E402

PBS = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261003/'
PY = {
    'arm64': {'name': 'cpython-3.11.17+20261003-aarch64-apple-darwin-install_only_stripped.tar.gz',
              'sha256': '0c9fbd0b2ddfbb6877493a650259bf379ee71a91b17f0f5f06dd2dcd52fbcade', 'size': 26974674},
    'x86_64': {'name': 'cpython-3.11.17+20261003-x86_64-apple-darwin-install_only_stripped.tar.gz',
               'sha256': 'ba62d0fb634c4e347341a4f3e29d7fb0b27920be6326c614d541c316e4da7693', 'size': 26888478},
}
VARIANT = {'arm64': 'mps', 'x86_64': 'cpu'}


def arch_section(arch, wheel_dir):
    py = dict(PY[arch])
    py['url'] = PBS + py['name'].replace('+', '%2B')
    torch, wheels = [], []
    for fn in sorted(os.listdir(wheel_dir)):
        if not fn.endswith('.whl'):
            continue
        w = pypi_file(fn)
        h = hashlib.sha256(open(os.path.join(wheel_dir, fn), 'rb').read()).hexdigest()
        assert h == w['sha256'], fn
        (torch if fn.startswith(('torch-', 'torchaudio-')) else wheels).append(w)
    return {'python': py, 'torch': {VARIANT[arch]: torch}, 'wheels': wheels}


def main(arm_dir, x86_dir):
    win = json.load(open(os.path.join(HERE, '..', 'app', 'lyricist_sync', 'manifest.json'), encoding='utf-8'))
    man = {'version': 1, 'platform': 'macos',
           'arch': {'arm64': arch_section('arm64', arm_dir), 'x86_64': arch_section('x86_64', x86_dir)},
           'models': win['models'], 'local_wheels': win['local_wheels'], 'whisper_models': win['whisper_models']}
    out = os.path.join(HERE, '..', 'app', 'lyricist_sync', 'manifest-mac.json')
    json.dump(man, open(out, 'w'), indent=1)
    for a, s in man['arch'].items():
        tot = s['python']['size'] + sum(x['size'] for v in s['torch'].values() for x in v) + sum(x['size'] for x in s['wheels'])
        print('%s: %d wheels, runtime %.0f MB (+ models)' % (a, len(s['wheels']), tot / 1e6))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
