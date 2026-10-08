# Ax-Easy Lyricist Sync

A standalone Windows desktop tool that **auto-syncs pasted lyrics to a song** and exports
**TTML, LRC, SRT and VTT** in the exact formats of the Ax-Easy Lyricist 1.1.0 WordPress plugin.
It is a separate app with no link to the plugin. Upload the MP3 and the generated `.ttml` to your web player.

Made by [Ax-Easy](https://www.ax-easy.com) with the help of [Grok](https://grok.com)
Inspired by the music of [Monitored](https://www.monitored.gr)

---

## How it works

For each song:

1. **Demucs (htdemucs)** separates the vocals from the music.
2. **Whisper small** listens to the vocals and finds lines that are **sung more often than they are written**
   (for example a chorus written once but sung twice, or lines 15–16 of *Stoned*). A dynamic-programming alignment
   of the transcript to the lyrics may jump back to an earlier line; every jump becomes a repeated block.
3. **MMS_FA** (torchaudio forced aligner) aligns every sung line to the vocals and gives each line a start and end time.
   Non-Latin lyrics such as **Greek** are romanized with **uroman** first.

Tags such as `[Chorus]`, `[Ρεφρέν]` or `(x2)` on their own line are ignored. Lyrics can be UTF-8 (with or without
a BOM), UTF-16 or Windows-1253 Greek.

On *Stoned* (Monitored) this pipeline put 24 of 24 sung lines within 0.04 s of the reference run from the
feasibility study. That study measured about 18–20 of 24 lines within about 0.3 s of the real singing, and none off by
more than 1 s. On the synthesized demo songs in `tests/fixtures`, every line was within 0.08 s (English) and 0.03 s
(Greek) of the known times.

## Using the app

1. **Add songs** (MP3, WAV, FLAC, M4A, AAC, OGG), or drag files onto the window.
   - If a `.txt` with the same name sits next to the audio, its lyrics load automatically.
   - Otherwise, paste the lyrics into the box with one sung line per line.
2. Press **Auto-sync** for the selected song, or **Sync all** to run the whole queue. Each song shows its progress
   and status. The title bar shows where the engine runs: **CUDA · NVIDIA GeForce RTX 3090**, or **CPU**.
3. Review the result:
   - Click **▶** to play from a line.
   - Select a line and nudge its start by **±0.1 s** or **±0.01 s**, or double-click a start time to type a new one.
   - `↻` marks a detected repeat. *too long* or *too short* flags an implausible line duration.
4. **Export**:
   - Choose an output folder; the app remembers it.
   - Tick **TTML / LRC / SRT / VTT**; all four are on by default.
   - Files are named `Artist - Title.ext` from the ID3 tags, or from the audio file name when there are no tags.
     Greek names are kept.
   - Optional: **UTF-8 BOM for SRT**, and **Export right after sync**.

Formats (identical to Lyricist 1.1.0, verified byte-for-byte against its `formats.js` in `tests/test_formats.py`):

- **TTML**: Apple style, with `itunes:timing="Line"`, `<div begin="00:00:00.000">`, `HH:MM:SS.mmm` times and
  `xml:lang` taken from the lyrics language (Greek → `el`).
  - Each line ends at its aligned end + 0.4 s, and never later than the start of the next line.
- **LRC**: `[ti:]`, `[ar:]` and `[al:]` headers, then `[mm:ss.xx]` lines.
- **SRT**: UTF-8, with an optional BOM.
- **VTT**: `WEBVTT`, never with a BOM.

### Command line

`LyricistSync.exe` also runs without the GUI:

```
LyricistSync.exe --setup [--variant auto|cuda|cpu]       first-run download without the GUI
LyricistSync.exe --sync song1.mp3 song2.flac [--out DIR] [--formats ttml,lrc,srt,vtt] [--bom] [--lang el]
LyricistSync.exe --selftest --report selftest.json      checks GUI, exporters and packaging (no models)
LyricistSync.exe --screens DIR                           renders screenshots
```

## Installing, first run and disk space

- The installer (`AxEasy-LyricistSync-Setup-1.0.0.exe`, about 50 MB) is per-user, so it needs no admin rights.
  It adds a Start-menu entry, an optional desktop shortcut and an uninstaller.
- On first run, the app downloads the sync engine into `%LOCALAPPDATA%\Ax-Easy\LyricistSync` and shows a progress
  window that you can pause and resume. Every file is SHA256-checked, and an interrupted download resumes where it
  stopped (HTTP Range).

| Build | What is downloaded | Size |
|---|---|---|
| **CUDA 12.4** (picked automatically when an NVIDIA GPU is found) | Python 3.11 (25 MB), PyTorch 2.5.1+cu124 (2.51 GB), 39 engine wheels (104 MB), models (1.83 GB) | **4.48 GB** |
| **CPU** | Same, with PyTorch 2.5.1+cpu (205 MB) | **2.17 GB** |

The three models are Demucs htdemucs (84 MB), Whisper small (484 MB) and MMS_FA (1.26 GB).

- **Time:** about 6–8 minutes at 100 Mbit/s for the CUDA build, plus 2–4 minutes to unpack and install.
- **Disk:** about 7 GB after setup with CUDA, or 3.5 GB with CPU. The downloaded wheels are deleted after
  installing. Uninstalling asks whether to remove this folder as well.

**Speed per song:**

| Machine | Time for a 2:09 song |
|---|---|
| 8-core CPU | about 70 s (measured on *Stoned*) |
| RTX 3090 | expected about 5–10 s |

**Why a small installer instead of an all-in-one build:**

- An all-in-one CUDA build would be a 3+ GB installer, and would need rebuilding for every app change.
- The bootstrap downloads the right PyTorch for the machine, either CUDA or CPU, so a CPU-only PC never downloads
  2.5 GB of CUDA libraries.
- Downloads are resumable and verified.
- App updates stay small because the engine and models are kept.

### Windows SmartScreen (unsigned installer)

The installer and the app are **not code-signed**, because Windows code signing is currently not available (the
Azure subscription is stopped). Windows SmartScreen will therefore warn: *"Windows protected your PC"*. Click
**More info → Run anyway**. Check the SHA256 published next to the installer before running it.

## Licences of the models

- Demucs and Whisper: MIT.
- **MMS_FA** (Meta, through torchaudio): **CC-BY-NC 4.0, which means non-commercial use only**. Keep this in mind if
  the tool or its output is used commercially. A commercial-safe aligner could replace it later.

## Building

GitHub Actions (`.github/workflows/build.yml`) does the build on a `windows-latest` runner:

1. Runs the unit tests.
2. Builds `LyricistSync.exe` with PyInstaller.
3. Runs `--selftest` on the frozen app: GUI, footer links, exporters, the native window frame and the QtMultimedia
   backend.
4. Renders screenshots.
5. Builds the Inno Setup installer.
6. Installs it silently, self-tests the installed copy, and uninstalls it.
7. Uploads the installer with its `.sha256`.

The `e2e` job then installs the artifact on a clean runner, runs the real first-run setup (CPU build), and syncs the
English and Greek demo songs, checking them against their known line times.

Layout:

```
app/lyricist_sync/   GUI (PySide6, frameless liquid-glass window), bootstrap/downloader, exporters, CLI
engine/              lyricist_engine.py: runs in the downloaded Python (Demucs → Whisper → MMS_FA)
installer/           Inno Setup script, icon, version info
tools/               manifest generator and the Windows lock file for the engine
tests/               exporter parity, repeat detection, downloader, demo fixtures with known times
```

© 2026 Ax-Easy. All rights reserved.
