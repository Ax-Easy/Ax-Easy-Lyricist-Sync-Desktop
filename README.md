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
   Non-Latin lyrics such as **Greek** are romanized with **uroman** first. A wildcard token absorbs whatever is
   sung that is not in the lyrics: hums, "ohhh" or ad-libs.
4. **Timing checks** (1.1.0):
   - A vocal-activity detector on the vocal stem makes sure no line starts where nobody sings. Each start snaps
     to the vocal onset of its first word.
   - Whisper's word times are a cross-check: if the aligner starts a line far ahead of the first matching
     Whisper word, the later time wins.
   - Starts are always in order, and lines never overlap.
   - Every line gets a **confidence** score from the acoustic match, Whisper agreement and vocal overlap.
     Lines below 0.6 are marked amber, with the reason, for a quick check.

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
   - An amber **● check** marks a line the engine is unsure about; hover over it to see why. This is typical of
     choirs and backing vocals.
   - **⟲ Re-sync from here**: fix one line by hand, then re-align only the lines after it. Earlier lines are kept.
     It takes a few seconds, because the song analysis is cached.
   - **Player** (below the song list and above the line list):
     - The **waveform** of the selected song shows a marker at every line start, violet **♪** regions, amber
       markers on lines to check, and the playhead. Click to seek, use the wheel to zoom (Shift+wheel scrolls),
       double-click to see the whole song, and drag a line marker to move that line.
     - Transport: **▶ / ❚❚**, **−2 s / +2 s**, speed **0.5×–1.5×**, the time, and **▶ Play from line**. The line
       playing now is highlighted and the list follows it.
     - The song is decoded once to PCM for exact seeking and cached (the last 8 songs) in
       `%LOCALAPPDATA%\Ax-Easy\LyricistSync\cache\audio`.
   - **Keyboard** (not while you type in a text box):

     | Key | Action |
     |---|---|
     | Space | play / pause |
     | ↑ / ↓ | select the previous / next line (in the song list they move between songs) |
     | ← / → | nudge the selected line by 0.1 s; with Shift by 0.01 s |
     | S | stamp: the selected line starts at the playhead, and the next line is selected |
     | Delete | remove the selected ♪ line |
     | F11 | full screen (Esc leaves it) |
   - **♪ in instrumental parts**: when nothing is sung for longer than a threshold, a **♪** line is added, so a
     lyric display shows ♪ instead of the last sung line during intros, solos, breaks and the outro.
     - A gap is measured from where the previous line's singing really stops (the end of its vocal activity on
       the vocal stem, a held note at most 3 s) to the next line. The previous line ends there, and the ♪ line
       ends 0.3 s before the next line.
     - Hums, ad-libs and backing "ohh"s in the gap don't stop the ♪: it marks the part with no lyric line.
     - **♪ …** sets it up: on/off, the shortest gap (default **8 s**, 3–30 s), the symbol (**♪**, **♪♪**,
       **♫** or **♪ instrumental ♪**) and whether the intro and outro get one.
     - **+ ♪** (or right-click → *Insert ♪ here*) adds one at the playhead. **Delete** or right-click removes
       one, and it stays removed.
     - ♪ lines are in every format (LRC `[mm:ss.xx]♪`; SRT, VTT and TTML as normal cues) and are never sent to the
       aligner.
4. **Export**:
   - **Save to**: *Next to the audio file* (the default), *A chosen folder* or *Ask every time*.
   - **Per song**: the queue has an **Output folder** column, and **Change…** sets a folder for one song. To set
     one folder for several songs, select them and use **Set folder for selected…**. All of this is remembered.
   - Existing files are never overwritten silently. You choose **Overwrite / Keep both / Skip**, with "do the
     same for the other songs".
   - When the export finishes, **Open folder** links appear.
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

### Updates

The **Update** button next to About checks `https://www.ax-easy.com/lyricist-sync/update.json`.
- The quiet check on start runs at most once a day, and can be switched off in the update window.
- The badge dot means a new version is out.
- **Update now** downloads the installer to `%LOCALAPPDATA%\Ax-Easy\LyricistSync\updates`. The download
  resumes if interrupted.
- The installer's SHA256 is checked before it runs, and the app refuses a mismatch or any non-HTTPS URL.
- The installer runs silently, then the app starts again. The settings, the engine and the models stay where
  they are.
- No GitHub API and no tokens are involved.

To publish an update, upload Setup-x.y.z.exe and update.json to /lyricist-sync/ on ax-easy.com

CI writes `update.json` next to the installer, with the real SHA256 and size (`tools/make_update_json.py`). Its
fields are:

```json
{"version": "1.2.0", "date": "2026-10-09", "notes": "…", "url": "https://www.ax-easy.com/lyricist-sync/AxEasy-LyricistSync-Setup-1.2.0.exe",
 "sha256": "…", "size": 52000000, "minimum_os": "10.0.17763"}
```

### Window style

- **Windows 11** (build 22000 or newer): DWM rounded corners and Mica.
- **Windows 10**: a frameless translucent window. The app paints its own rounded glass (16 px radius, gradient,
  grain and a top highlight) and a soft shadow in a 20 px transparent margin. There is no window-wide acrylic,
  which Windows 10 renders slowly.
- Maximized windows drop the margin.
- Snap, drag and resize work as usual; resizing grabs the visible edge.
- `--force-win10-style` shows the Windows 10 look on Windows 11. CI uses it for screenshots.

### Command line

`LyricistSync.exe` also runs without the GUI:

```
LyricistSync.exe --setup [--variant auto|cuda|cpu]       first-run download without the GUI
LyricistSync.exe --sync song1.mp3 song2.flac [--out DIR] [--formats ttml,lrc,srt,vtt] [--bom] [--lang el]
LyricistSync.exe --selftest --report selftest.json      checks GUI, exporters and packaging (no models)
LyricistSync.exe --screens DIR                           renders screenshots (both window paths, labelled)
LyricistSync.exe --setup-gui [--auto --report r.json --shots DIR]   setup window on its own (CI latency test)
LyricistSync.exe --update-test URL [--install]           updater end-to-end test against a local manifest
LyricistSync.exe --force-win10-style                     use the Windows 10 window style on any Windows
```

## Installing, first run and disk space

- The installer (`AxEasy-LyricistSync-Setup-1.2.0.exe`, about 50 MB) is per-user, so it needs no admin rights.
  It adds a Start-menu entry, an optional desktop shortcut and an uninstaller.
- On first run, the app downloads the sync engine into `%LOCALAPPDATA%\Ax-Easy\LyricistSync`. Every file is
  SHA256-checked, and an interrupted download resumes where it stopped (HTTP Range). The setup window shows 7 steps:
  1. Download PyTorch and the packages
  2. Install
  3. Demucs model
  4. Whisper model
  5. MMS model
  6. Verify (SHA256)
  7. GPU check / warm-up

  Each step has its own progress bar with MB, speed and time left. The window also has:
  - an overall bar with elapsed and remaining time;
  - a live log and "Open log folder";
  - **Pause/Resume**, **Cancel** (asks first) and **Retry step**.

  If a step is quiet for 60 s, a "still working…" notice appears with the elapsed time. The next start resumes at
  the first unfinished step.

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

1. Runs the unit tests: exporters, repeats, downloader and timing.
2. Builds `LyricistSync.exe` with PyInstaller on Python 3.12.
3. Runs `--selftest` on the frozen app. It runs twice, once normally and once with `--force-win10-style`, and covers:
   - the GUI, footer links and exporters;
   - save modes, overwrite prompts and per-song folders;
   - confidence markers and re-sync;
   - the updater, against a local HTTP server;
   - the painted frame and native hit-tests;
   - QtMultimedia.
4. Renders labelled screenshots of both window paths.
5. Builds the Inno Setup installer and `update.json`.
6. Installs the build silently, self-tests the installed copy, and uninstalls it.
7. Runs the updater end to end. A local server offers a fake newer version that points at the freshly built
   installer. The test checks that:
   - the popup finds it;
   - the download and SHA256 check pass;
   - the silent install runs and keeps the user data;
   - a wrong hash is refused;
   - a 404 shows the friendly message.
8. Uploads the installer with its `.sha256` and `update.json`.

The `e2e` job then runs on a clean runner:
1. Installs the artifact.
2. Runs the first-run setup in its GUI window (CPU build). The files come from a throttled local mirror, and the
   job checks that the event loop stays responsive: under 200 ms per step. It also takes mid-way screenshots in
   both themes.
3. Syncs the English and Greek demos plus the hard fixtures: a long intro, an intro with a hummed "ohhh", vocal
   bleed and a choir. Each is checked against its known line times.

Layout:

```
app/lyricist_sync/   GUI (PySide6, frameless liquid-glass window), bootstrap/downloader, exporters, CLI
engine/              lyricist_engine.py: runs in the downloaded Python (Demucs → Whisper → MMS_FA)
installer/           Inno Setup script, icon, version info
tools/               manifest generator and the Windows lock file for the engine
tests/               exporter parity, repeat detection, downloader, timing, demo + hard fixtures with known times
CHANGELOG.md         release notes (also used for update.json)
```

© 2026 Ax-Easy. All rights reserved.
