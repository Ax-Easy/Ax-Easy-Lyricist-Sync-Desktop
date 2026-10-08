"""Build app/manifest.json: every first-run download with URL, size and SHA256.

Usage: python tools/make_manifest.py <dir with the downloaded Windows wheels>
The wheels dir is produced by:
  pip download --no-deps --only-binary :all: --platform win_amd64 --python-version 3.11 \
      --implementation cp --require-hashes -r tools/engine-lock-win.txt (minus torch) -d <dir>
"""
import hashlib, json, os, sys, urllib.request

PY = {
    "name": "cpython-3.11.17+20261003-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
    "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.11.17%2B20261003-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
    "sha256": "861f9a03b0c4ca537da1754ed0556e0628dd2114a1be36e8aae6b1e2bb1304a0",
    "size": 25222085,
}
R2 = "https://download-r2.pytorch.org/whl/"
TORCH = {
    "cuda": [
        {"name": "torch-2.5.1+cu124-cp311-cp311-win_amd64.whl", "url": R2 + "cu124/torch-2.5.1%2Bcu124-cp311-cp311-win_amd64.whl",
         "sha256": "6c8a7003ef1327479ede284b6e5ab3527d3900c2b2d401af15bcc50f2245a59f", "size": 2510750521},
        {"name": "torchaudio-2.5.1+cu124-cp311-cp311-win_amd64.whl", "url": R2 + "cu124/torchaudio-2.5.1%2Bcu124-cp311-cp311-win_amd64.whl",
         "sha256": "b3d75f4e6efc5412fe78c7f2787ee4f39cea1317652e1a47785879cde109f5c4", "size": 4143920},
    ],
    "cpu": [
        {"name": "torch-2.5.1+cpu-cp311-cp311-win_amd64.whl", "url": R2 + "cpu/torch-2.5.1%2Bcpu-cp311-cp311-win_amd64.whl",
         "sha256": "81531d4d5ca74163dc9574b87396531e546a60cceb6253303c7db6a21e867fdf", "size": 205462169},
        {"name": "torchaudio-2.5.1+cpu-cp311-cp311-win_amd64.whl", "url": R2 + "cpu/torchaudio-2.5.1%2Bcpu-cp311-cp311-win_amd64.whl",
         "sha256": "e08047b9f1997bd303ea6528e5b8009719665a55516a49b6acc359dac20c474d", "size": 2424379},
    ],
}
MODELS = [
    {"id": "demucs", "label": "Demucs htdemucs (vocal separation)", "dest": "models/demucs/955717e8-8726e21a.th",
     "url": "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th",
     "sha256": "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4", "size": 84141911},
    {"id": "whisper", "label": "Whisper small (repeat detection)", "dest": "models/whisper/small.pt",
     "url": "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
     "sha256": "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794", "size": 483617219},
    {"id": "mms", "label": "MMS_FA forced aligner", "dest": "models/torch/hub/checkpoints/model.pt",
     "url": "https://dl.fbaipublicfiles.com/mms/torchaudio/ctc_alignment_mling_uroman/model.pt",
     "sha256": "20ef12963ab4924bef49ac4fc7f58ad5da2ee43b2c11bc8c853c9b90ecdbc680", "size": 1262047414},
]


def pypi_file(fn):
    name, ver = fn.split('-')[:2]
    meta = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=60))
    for f in meta['urls']:
        if f['filename'] == fn:
            return {"name": fn, "url": f['url'], "sha256": f['digests']['sha256'], "size": f['size']}
    raise SystemExit('not on PyPI: ' + fn)


def main(wheel_dir):
    wheels = []
    for fn in sorted(os.listdir(wheel_dir)):
        if not fn.endswith('.whl'):
            continue
        w = pypi_file(fn)
        h = hashlib.sha256(open(os.path.join(wheel_dir, fn), 'rb').read()).hexdigest()
        assert h == w['sha256'], fn
        wheels.append(w)
    man = {"version": 1, "python": PY, "torch": TORCH, "wheels": wheels, "models": MODELS,
           "local_wheels": ["openai_whisper-20250625-py3-none-any.whl"]}
    out = os.path.join(os.path.dirname(__file__), '..', 'app', 'lyricist_sync', 'manifest.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(man, open(out, 'w'), indent=1)
    tot = lambda v: sum(x['size'] for x in v)
    common = PY['size'] + tot(wheels) + tot(MODELS)
    print(f"wheels={len(wheels)} common={common/1e6:.0f} MB  cuda total={(common+tot(TORCH['cuda']))/1e9:.2f} GB  cpu total={(common+tot(TORCH['cpu']))/1e9:.2f} GB")


if __name__ == '__main__':
    main(sys.argv[1])
