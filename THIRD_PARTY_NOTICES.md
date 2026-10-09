# Third-party notices

Ax-Easy Lyricist Sync Desktop is © 2026 Ax-Easy (Evangelos Makrydakis), all rights reserved (see [LICENSE](LICENSE)).
It is built on, and downloads, the third-party software and models below. **Each of them stays under its own
license**; the Lyricist Sync Desktop license does not change or restrict any of the rights those licenses give you.

There are two groups:

* **Bundled** – inside the Windows installer / the macOS app (`LyricistSync.exe` folder, `Lyricist Sync Desktop.app`).
* **Downloaded on first run** – fetched by the setup window straight from their official hosts (python-build-standalone
  on GitHub, PyPI, download.pytorch.org, Meta's and OpenAI's model servers), SHA-256 checked, and installed into
  your user folder (`%LOCALAPPDATA%\Ax-Easy\LyricistSync` on Windows, `~/Library/Application Support/Ax-Easy/LyricistSync`
  on macOS). Ax-Easy does not redistribute them.

## Bundled in the app

| Component | Version | License | Source |
|---|---|---|---|
| Qt for Python – PySide6 / Shiboken6 and the Qt 6 libraries | Windows 6.12.0, macOS 6.7.3 | **LGPL-3.0** (Qt also GPL / commercial) | https://code.qt.io/cgit/pyside/pyside-setup.git, https://download.qt.io/official_releases/qt/ |
| CPython (python.org) | 3.12 | PSF License 2.0 | https://www.python.org/downloads/source/ |
| PyInstaller bootloader | 6.22.3 | GPL-2.0 with the PyInstaller bootloader exception | https://github.com/pyinstaller/pyinstaller |
| tinytag (audio tag reading) | 2.3.2 | MIT | https://github.com/tinytag/tinytag |
| openai-whisper (wheel shipped for the offline install) | 20250625 | MIT | https://github.com/openai/whisper |

mutagen (GPL-2.0-or-later) was used for tag reading before 1.3.1. It is no longer used or bundled; tinytag replaced it.

### Qt / PySide6 (LGPL-3.0) – your rights

The official binaries use Qt and PySide6 **unmodified** and **dynamically linked**, as separate shared libraries, as the
LGPL-3.0 allows for an application under another license:

* **Windows:** `PySide6\Qt6*.dll`, `PySide6\plugins\…`, `shiboken6\…` in the install folder.
* **macOS:** `Lyricist Sync Desktop.app/Contents/Frameworks/PySide6/Qt/lib/Qt*.framework` and the Qt plugins next to them.

You may replace these libraries with your own build of the same Qt / PySide6 version (or a compatible one); the app
loads whatever is in that folder. On macOS, re-sign the bundle afterwards (for example `codesign --force --deep -s - "Lyricist Sync Desktop.app"`),
because changing a signed app breaks its Developer ID signature. The complete source of Qt and PySide6 is available from
the URLs above (Qt 6.12.0 / 6.7.3 and PySide6 6.12.0 / 6.7.3 tags); the LGPL-3.0 and GPL-3.0 texts are at
https://www.gnu.org/licenses/lgpl-3.0.html and https://www.gnu.org/licenses/gpl-3.0.html, and the Qt license
files ship inside the PySide6 folders of the app. No reverse-engineering restriction in the Lyricist Sync Desktop license applies to
debugging such a modification.

## Downloaded on first run (the engine)

| Component | License | Notes |
|---|---|---|
| python-build-standalone CPython 3.11 | PSF License 2.0 (+ the licenses of the bundled OpenSSL, SQLite, libffi, zlib, … listed in its `python/licenses` folder) | https://github.com/astral-sh/python-build-standalone |
| PyTorch / torchaudio | BSD-3-Clause (PyTorch), BSD-2-Clause (torchaudio); CUDA builds also carry the NVIDIA redistributable license terms | https://github.com/pytorch/pytorch |
| OpenAI Whisper (code) and the Whisper model weights (small, medium, large-v3-turbo, large-v3) | MIT | https://github.com/openai/whisper |
| Demucs (code) and the `htdemucs` model weights | MIT | https://github.com/adefossez/demucs |
| **MMS_FA forced-alignment model** (Meta, via torchaudio) | **CC BY-NC 4.0** – non-commercial use only, attribution required | Pratap et al., *Scaling Speech Technology to 1,000+ Languages* (2023). https://pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html, https://creativecommons.org/licenses/by-nc/4.0/ |
| uroman (universal romanizer) | MIT-style license with an attribution requirement (the PyPI classifier says Apache, but the license file is MIT-style; the license file governs) | "This project uses the universal romanizer software 'uroman' written by Ulf Hermjakob, USC Information Sciences Institute (2015-2020)". Hermjakob, May, Knight (2018), *Out-of-the-box universal romanization tool uroman*, ACL Demo Track. https://github.com/isi-nlp/uroman |
| PyAV (`av`) | BSD-3-Clause (code); the PyPI wheels bundle FFmpeg and codec libraries under LGPL-2.1+ / GPL-2.0+ terms | https://github.com/PyAV-Org/PyAV, https://github.com/PyAV-Org/pyav-ffmpeg |
| NumPy, Numba, llvmlite, SymPy, NetworkX, Jinja2, MarkupSafe, Click | BSD-3-Clause / BSD-2-Clause (llvmlite also includes LLVM, Apache-2.0 with LLVM exception) | PyPI |
| tiktoken, regex, more-itertools, julius, einops, tqdm, PyYAML, idna, h11, anyio, httpx2/httpcore2, huggingface-hub, hf-xet, safetensors, filelock, fsspec, packaging, typing-extensions, truststore, urllib3, requests, charset-normalizer, colorama, sphn, lameenc | MIT / Apache-2.0 / BSD / PSF (each package's own license, shipped in its `*.dist-info` folder) | PyPI |
| certifi | MPL-2.0 | PyPI |
| mpmath | BSD-3-Clause | PyPI |

The exact versions and SHA-256 hashes are in `app/lyricist_sync/manifest.json` (Windows) and
`app/lyricist_sync/manifest-mac.json` (macOS). After setup, every package's license text is in its
`site-packages/*.dist-info` folder under the engine runtime.

### MMS_FA is non-commercial

The forced aligner that places the lyric lines on the audio uses Meta's MMS_FA model under **CC BY-NC 4.0**. Lyricist Sync Desktop
is free and is meant for personal, non-commercial use; if you want to use it commercially, you are responsible for
complying with that license (or for using a different aligner).
