# Ax-Easy Lyricist Sync

**Paste the lyrics, drop in the song, get perfectly timed lyric files.**
Lyricist Sync is a desktop app for **Windows and macOS** that auto-syncs lyrics to a recording, line by line, and
exports **TTML, LRC, SRT and VTT**. It runs entirely on your computer: vocals are separated with Demucs, listened to
with Whisper and aligned with Meta's MMS forced aligner, on an NVIDIA GPU, an Apple Silicon GPU or the CPU.
No account, no upload, no cloud.

![Lyricist Sync after an Auto-sync: song queue, waveform with line markers, timed line list](docs/screenshots/hero-dark.webp)

Made by [Ax-Easy](https://www.ax-easy.com) with the help of [Grok](https://grok.com)
Inspired by the music of [Monitored](https://www.monitored.gr)

## Download

| | File | |
|---|---|---|
| **Windows 10 / 11** (64-bit) | [AxEasy-LyricistSync-Setup-1.3.1.exe](https://github.com/Ax-Easy/lyricist-sync/releases/download/v1.3.1/AxEasy-LyricistSync-Setup-1.3.1.exe) | per-user installer, about 41 MB |
| **macOS 11+** (Apple Silicon) / **12+** (Intel) | [AxEasy-LyricistSync-1.3.1-mac-universal.dmg](https://github.com/Ax-Easy/lyricist-sync/releases/download/v1.3.1/AxEasy-LyricistSync-1.3.1-mac-universal.dmg) | universal, signed and notarized by Apple, about 94 MB |
| **Manual** (English) | [AxEasy-LyricistSync-Manual-EN.pdf](https://github.com/Ax-Easy/lyricist-sync/releases/download/v1.3.1/AxEasy-LyricistSync-Manual-EN.pdf) | |
| **Εγχειρίδιο** (Ελληνικά) | [AxEasy-LyricistSync-Manual-GR.pdf](https://github.com/Ax-Easy/lyricist-sync/releases/download/v1.3.1/AxEasy-LyricistSync-Manual-GR.pdf) | |

Every release lists the SHA-256 of each file in `SHA256SUMS`. All releases: [Releases](https://github.com/Ax-Easy/lyricist-sync/releases).

## Features

- **Auto-sync** pasted lyrics to MP3, WAV, FLAC, M4A, AAC or OGG – Greek and other non-Latin scripts included.
- **Repeats found by ear**: a chorus written once but sung twice is detected and timed twice.
- **Transcribe** songs without lyrics: Whisper writes the lines and their times; unsure words are marked amber.
- **Confidence per line**, with the reason, so you only check the lines that need it.
- **Review and edit**: a waveform with draggable line markers, a player with 0.5×–1.5× speed, nudge buttons,
  in-place editing, split / merge / insert, *Re-sync from here*, *Re-align this line*, full undo / redo.
- **♪ lines** for intros, solos and outros, so a lyric display never shows a stale line.
- **Exports** byte-identical to the Ax-Easy Lyricist WordPress plugin formats: Apple-style TTML, LRC, SRT, VTT.
- **Runs locally** on CUDA (NVIDIA), Metal (Apple Silicon) or the CPU; the Whisper size follows your hardware.
- **Built-in updater** that checks SHA-256 (and, on macOS, the Apple signature) before installing.
- Native look on each system: Mica on Windows 11, glass on Windows 10, vibrancy and the menu bar on macOS;
  dark and light themes.

## Gallery

| Dark | Light |
|---|---|
| ![Main window after a sync (dark)](docs/screenshots/main-dark.webp) | ![Main window after a sync (light)](docs/screenshots/main-light.webp) |
| ![Transcribe without lyrics](docs/screenshots/transcribe-dark.webp) | ![Transcribe without lyrics](docs/screenshots/transcribe-light.webp) |
| ![Edit Line dialog](docs/screenshots/edit-line-dark.webp) | ![Edit Line dialog](docs/screenshots/edit-line-light.webp) |
| ![Player with the waveform](docs/screenshots/player-dark.webp) | ![Player with the waveform](docs/screenshots/player-light.webp) |
| ![♪ lines in instrumental parts](docs/screenshots/music-lines-dark.webp) | ![♪ lines in instrumental parts](docs/screenshots/music-lines-light.webp) |
| ![Engine settings](docs/screenshots/engine-dark.webp) | ![Engine settings](docs/screenshots/engine-light.webp) |
| ![Export confirmation](docs/screenshots/export-done-dark.webp) | ![Export confirmation](docs/screenshots/export-done-light.webp) |

**macOS**

| Dark | Light |
|---|---|
| ![Lyricist Sync on macOS (dark)](docs/screenshots/mac-main-dark.webp) | ![Lyricist Sync on macOS (light)](docs/screenshots/mac-main-light.webp) |

## System requirements

| | Windows | macOS |
|---|---|---|
| OS | Windows 10 1809 (build 17763) or later, 64-bit | macOS 11 Big Sur or later on Apple Silicon; macOS 12 Monterey or later on Intel |
| Engine | NVIDIA GPU with CUDA 12.4 drivers (fastest), or any x86-64 CPU | Apple Silicon: PyTorch with Metal (MPS) and CPU fallback. Intel: PyTorch 2.2.2 on the CPU |
| Memory | 8 GB RAM; GPU memory decides the Whisper size | 8 GB; unified memory decides the Whisper size (8 GB small, 16 GB medium, 24 GB large-v3-turbo, 32 GB+ large-v3) |
| Disk | 3.5 GB (CPU) to 7–9 GB (CUDA, large Whisper) after the first-run setup | about 3 GB (Whisper small) to 6.5 GB (large-v3) after the first-run setup |
| Internet | only for the one-time engine download (2.2–7 GB) and update checks | same (2.0–4.6 GB download) |

## Quick start

1. **Install.**
   - *Windows*: run the installer (no admin rights needed). It isn't code-signed yet, so SmartScreen may say
     *"Windows protected your PC"* → **More info → Run anyway**.
   - *macOS*: open the DMG and drag **Lyricist Sync** onto **Applications**. The app is signed with a Developer ID
     and notarized by Apple, so it opens without warnings.
2. **First run**: the setup window downloads the sync engine (Python, PyTorch for your hardware, the Demucs,
   Whisper and MMS models) into your user folder – 7 steps, each SHA-256 checked, pausable and resumable.
3. **Add songs** (or drag them onto the window). A `.txt` with the same name next to the audio is loaded as the
   lyrics; otherwise paste them, one sung line per line.
4. Press **Auto-sync** (or **Transcribe** when you have no lyrics). Check the amber lines, nudge or edit if needed.
5. **Export** – TTML, LRC, SRT and VTT next to the audio or in a folder you choose.

The full guide is in the manual ([English](https://github.com/Ax-Easy/lyricist-sync/releases/download/v1.3.1/AxEasy-LyricistSync-Manual-EN.pdf) ·
[Ελληνικά](https://github.com/Ax-Easy/lyricist-sync/releases/download/v1.3.1/AxEasy-LyricistSync-Manual-GR.pdf)) and below.

## On macOS

- One **universal** app for Apple Silicon and Intel; the first-run setup downloads the PyTorch build for your Mac
  into `~/Library/Application Support/Ax-Easy/LyricistSync` (Apple Silicon: current PyTorch with **Metal / MPS** and an
  automatic CPU fallback for anything Metal can't run; Intel: PyTorch 2.2.2, the last release for Intel Macs, on the CPU).
- Mac conventions: the menu bar (**Lyricist Sync ▸ About, Check for Updates…, Settings… ⌘,, Quit ⌘Q** – Quit asks about
  unsaved lyrics first), **⌘** shortcuts (⌘O add songs, ⌘S export, ⌘R auto-sync, ⇧⌘T transcribe, ⌘Z / ⇧⌘Z undo / redo,
  ⇧⌘L light / dark), the native traffic-light title bar, full screen with the green button or **⌃⌘F**, **⌫** deletes
  the selected line, and **Reveal in Finder**.
- **Updates**: *Check for Updates…* downloads the new DMG, checks its SHA-256, the Apple code signature, the
  Ax-Easy Team ID (7BMSHL4YZ6) and Gatekeeper, then replaces the app in place and restarts it. If the app can't be
  replaced where it is (for example a read-only folder), the DMG opens so you can drag the new version to Applications.
- **Not on the Mac App Store**: App Store apps may not download and run code after installation, and Lyricist Sync's
  first-run setup downloads its engine (Python and PyTorch) at runtime, sized for each Mac. It is distributed as a
  notarized DMG instead.

## How it works

For each song:

1. **Demucs (htdemucs)** separates the vocals from the music.
2. **Whisper** listens to the vocals and finds lines that are **sung more often than they are written**
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

The Whisper size depends on the hardware (1.3.0): **small** on the CPU or a GPU under 6 GB, **medium** on 6–11 GB,
**large-v3-turbo** on 12–23 GB and **large-v3** on 24 GB and more (for example an RTX 3090). See *Engine settings*.

## Using the app

On macOS read **⌘** for Ctrl, **⌫** for Delete, **⌃⌘F** for F11 and **Reveal in Finder** for Open folder.

1. **Add songs** (MP3, WAV, FLAC, M4A, AAC, OGG), or drag files onto the window.
   - If a `.txt` with the same name sits next to the audio, its lyrics load automatically.
   - Otherwise, paste the lyrics into the box with one sung line per line.
2. Press **Auto-sync** for the selected song, or **Sync all** to run the whole queue. Each song shows its progress
   and status. The title bar shows where the engine runs: **CUDA · NVIDIA GeForce RTX 3090**, or **CPU**.
3. Review the result:
   - Click **▶** to play from a line.
   - Select a line and nudge its start by **±0.1 s** or **±0.01 s**, or double-click a start or end time to type a
     new one (`mm:ss.xxx`).
   - **Edit the lines in the list** (see *Editing lines* below): double-click the words or press **F2** to edit them in
     place, or right-click → **Edit Line…**.
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
       `%LOCALAPPDATA%\Ax-Easy\LyricistSync\cache\audio` (macOS: `~/Library/Application Support/Ax-Easy/LyricistSync/cache/audio`).
   - **Keyboard** (not while you type in a text box):

     | Key | Action |
     |---|---|
     | Space | play / pause |
     | ↑ / ↓ | select the previous / next line (in the song list they move between songs) |
     | ← / → | nudge the selected line by 0.1 s; with Shift by 0.01 s |
     | S | stamp: the selected line starts at the playhead, and the next line is selected |
     | Delete | delete the selected line (Ctrl+Z brings it back) |
     | F2 | edit the words of the selected line in place (Enter saves, Esc cancels) |
     | Enter | open **Edit Line…** for the selected line |
     | Ctrl+Z / Ctrl+Y | undo / redo the last change in the line list (Ctrl+Shift+Z also redoes) |
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
   - **Transcribe (no lyrics needed)**: press **Transcribe** (or **Auto-sync** on a song without lyrics, or
     **Transcribe all** for every song without lyrics). Whisper writes the lines with their times into the lyrics
     box and the line list.
     - The language is detected automatically; set the **Language** box to override it (for example Greek).
     - Lines follow the singing: phrases, pauses over 0.6 s, at most about 42 characters.
     - Starts come from the MMS aligner on Whisper's text, so they are as exact as an Auto-sync of that text.
     - **Amber words** (underlined in the lyrics box) are the ones Whisper is unsure about. Lines with low
       confidence get **● check**.
     - Recommended: **Transcribe → fix the amber words in the lyrics box → Auto-sync**. The second step only runs
       the aligner, because the song analysis is cached.
     - Against made-up text: Whisper only hears where the vocals stem is active, and segments with no vocals
       under them, loops, gibberish, humming and filler like "Thank you for watching" are dropped.
   - **Editing lines** (1.3.1). Every change updates the lyrics box, the waveform markers and the exported files.
     - **In place**: double-click the words (or **F2**) to edit them; double-click a start or end time to type it
       as `mm:ss.xxx`. **Enter** saves, **Esc** cancels. Right-click inside the text editor → **Split line at
       cursor**.
     - **Edit Line…** (right-click, or **Enter** on a line): a small dialog with the **Line** text (any language,
       Greek included), **Start** and **End** (`mm:ss.xxx`, with **−0.1 / −0.01 / +0.01 / +0.1**), **▶ Play line**
       (plays from Start to End), **Split at cursor**, the option **Re-align this line after saving (fixes the
       timing after big word changes)**, and **Cancel / Save**. Enter saves, Esc cancels. The Re-align option is
       ticked for you when 40 % or more of the words changed.
     - **Right-click menu**: **Edit Line…**, **Play from line**, **Re-sync from here**, **Re-align this line**,
       **Split line at cursor**, **Merge with next**, **Insert line above**, **Insert line below**, **Insert ♪
       here**, **Mark as ♪** / **Unmark ♪ (make it a sung line)**, **♪ settings…**, **Undo**, **Redo**, **Delete line**.
     - Editing the words keeps the times. The line's amber **● check** and amber words go away and the note says
       **✎ edited**. When a chorus line repeats (`↻`), changing its words changes every repeat of it.
     - **Split line at cursor** splits at the text cursor (in place or in Edit Line…), otherwise at the playhead when
       it is inside the line, otherwise at the word nearest the middle; the time is divided in proportion to the
       characters. **Merge with next** joins a line with the next (start of the first, end of the second).
     - **Insert line above / below** puts a *New line* in the gap there (or in half of the line when there is no
       gap) and opens it for typing.
     - **Re-align this line** runs the aligner again for that line only, between the end of the line before and the
       start of the line after. It takes well under a second when the song analysis is cached.
     - **Undo / Redo** (**Ctrl+Z / Ctrl+Y**, or the **↶ ↷** buttons next to Re-sync) for every change in the line
       list, separately for each song. Nudging one line with the arrow keys counts as one step.
     - **Transcribe** or **Auto-sync** on a song you edited asks first: **Keep my edits** or **Replace** (Replace
       can be undone with Ctrl+Z too).
   - **Engine settings** (the **Engine** button): the detected hardware, the Whisper model in use and a dropdown
     (**Auto**, small, medium, large-v3-turbo, large-v3, with size, speed and accuracy). Picking a model that
     isn't downloaded yet downloads it right there, with per-step progress, resume and SHA256 check. Models not
     in use can be deleted.
4. **Export**:
   - **Save to**: *Next to the audio file* (the default), *A chosen folder* or *Ask every time*.
   - **Per song**: the queue has an **Output folder** column, and **Change…** sets a folder for one song. To set
     one folder for several songs, select them and use **Set folder for selected…**. All of this is remembered.
   - Existing files are never overwritten silently. You choose **Overwrite / Keep both / Skip**, with "do the
     same for the other songs".
   - When the export finishes, a confirmation opens and stays until you close it: the summary (*12 files saved for
     3 songs*), and per song the full folder path and the files written. Skipped songs show in amber and failed
     ones in red, each with the reason. With several songs the list folds away behind **Show files ▾**. Buttons:
     **Open folder** and **OK**.
   - **Unsaved lyrics**: a song is marked with **●** in the song list after Auto-sync, Transcribe or any edit, until
     it is exported. Closing the window (✕, Alt+F4, or the restart of an update) with marked songs asks **You have
     unsaved lyrics for N songs**, lists them, and offers **Export all & close** (each song goes to its own save
     location; the window closes only if every song was saved), **Close without saving** and **Cancel**. Removing
     a marked song from the list asks too (**Remove** / **Cancel**).
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

The **Update** button next to About (macOS: *Lyricist Sync ▸ Check for Updates…*) checks
`https://www.ax-easy.com/lyricist-sync/update.json`.
- The quiet check on start runs at most once a day, and can be switched off in the update window.
- The badge dot means a new version is out.
- **Update now** downloads the installer to `%LOCALAPPDATA%\Ax-Easy\LyricistSync\updates`. The download
  resumes if interrupted.
- The installer's SHA256 is checked before it runs, and the app refuses a mismatch or any non-HTTPS URL.
- The installer runs silently, then the app starts again. The settings, the engine and the models stay where
  they are.
- No GitHub API and no tokens are involved.

To publish an update, attach the Setup exe and the DMG to the GitHub release, then upload update.json to
/lyricist-sync/ on ax-easy.com (its download URLs point at the GitHub release).

CI writes `update.json` next to the installer, with the real SHA256 and size (`tools/make_update_json.py`). Its
fields are:

```json
{"version": "1.3.1", "date": "2026-10-09", "notes": "…",
 "url": "https://github.com/Ax-Easy/lyricist-sync/releases/download/v1.3.1/AxEasy-LyricistSync-Setup-1.3.1.exe",
 "sha256": "…", "size": 41396276, "minimum_os": "10.0.17763",
 "mac": {"url": "https://github.com/Ax-Easy/lyricist-sync/releases/download/v1.3.1/AxEasy-LyricistSync-1.3.1-mac-universal.dmg",
         "sha256": "…", "size": 0, "minimum_os": {"arm64": "11.0", "x86_64": "12.0"}}}
```

The top level is the Windows entry (what every Windows version reads); the macOS app reads `mac` on top of it.

### Window style

- **macOS**: the native title bar with the traffic lights, an NSVisualEffectView vibrancy backdrop under the glass, and
  the system menu bar.
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
LyricistSync.exe --transcribe song.mp3 [--lang el] [--whisper auto|small|medium|large-v3-turbo|large-v3] [--out DIR]
                                                         no lyrics: timed files + song.transcript.txt
LyricistSync.exe --selftest --report selftest.json      checks GUI, exporters and packaging (no models)
LyricistSync.exe --screens DIR                           renders screenshots (both window paths, labelled)
LyricistSync.exe --setup-gui [--auto --report r.json --shots DIR]   setup window on its own (CI latency test)
LyricistSync.exe --update-test URL [--install]           updater end-to-end test against a local manifest
LyricistSync.exe --force-win10-style                     use the Windows 10 window style on any Windows
```

## Installing, first run and disk space

- The installer (`AxEasy-LyricistSync-Setup-1.3.0.exe`, about 50 MB) is per-user, so it needs no admin rights.
  It adds a Start-menu entry, an optional desktop shortcut and an uninstaller.
- macOS: the DMG (about 94 MB) holds the universal app; drag it to Applications.
- On first run, the app downloads the sync engine into `%LOCALAPPDATA%\Ax-Easy\LyricistSync`
  (macOS: `~/Library/Application Support/Ax-Easy/LyricistSync`). Every file is
  SHA256-checked, and an interrupted download resumes where it stopped (HTTP Range). The setup window shows 7 steps:
  1. Download PyTorch and the packages
  2. Install
  3. Demucs model
  4. Whisper model (only the size for this hardware)
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
| **CUDA 12.4** (picked automatically when an NVIDIA GPU is found) | Python 3.11 (25 MB), PyTorch 2.5.1+cu124 (2.51 GB), 39 engine wheels (104 MB), models | **4.48 GB** with Whisper small · 5.52 GB medium · 5.61 GB large-v3-turbo · **7.08 GB large-v3** (24 GB GPUs) |
| **CPU** | Same, with PyTorch 2.5.1+cpu (205 MB), Whisper small | **2.17 GB** |
| **macOS, Apple Silicon** | Python 3.11 (27 MB), PyTorch 2.5.1 with Metal (66 MB), 36 engine wheels (96 MB), models | **2.02 GB** with Whisper small (8 GB Macs) · 3.07 GB medium (16 GB) · 3.16 GB large-v3-turbo (24 GB) · **4.62 GB large-v3** (32 GB+) |
| **macOS, Intel** | Python 3.11 (27 MB), PyTorch 2.2.2 CPU (154 MB), 35 engine wheels (108 MB), models | **2.11 GB** with Whisper small · 3.16 GB medium (32 GB+) |

The models are Demucs htdemucs (84 MB), MMS_FA (1.26 GB) and one Whisper size: small (484 MB), medium (1.53 GB),
large-v3-turbo (1.62 GB) or large-v3 (3.09 GB).

**Updating from 1.2.0** downloads nothing but the app. If the GPU can run a bigger Whisper than the installed small,
the app asks once whether to download it (Engine settings); PyTorch and the other models are kept.

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

## License

**Copyright © 2026 Ax-Easy (Evangelos Makrydakis). All rights reserved.** The source code is published for viewing
only; you may run the official binaries for personal use. See [LICENSE](LICENSE).

Third-party components keep their own licenses – Whisper (MIT), Demucs (MIT), PyTorch (BSD), PySide6 / Qt
(LGPL-3.0, dynamically linked and replaceable), uroman (MIT-style, with attribution), and the **MMS_FA alignment
model (CC BY-NC 4.0, non-commercial)**. Details, versions and your LGPL rights: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Building

**macOS** (`.github/workflows/mac.yml`): a universal2 build (python.org Python 3.12, PySide6 6.7.3) on an Apple
Silicon runner, every Mach-O signed inside-out with the Developer ID (hardened runtime), notarized and stapled, packed
into the DMG, then installed from the DMG and tested on **Apple Silicon and Intel** runners: Gatekeeper, self-test,
the in-app updater, the first-run engine setup and a real sync / transcribe. Signing secrets are only available to
pushes to this repository and manual runs, never to pull requests from forks.

**Windows**: GitHub Actions (`.github/workflows/build.yml`) does the build on a `windows-latest` runner:

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
app/lyricist_sync/   GUI (PySide6; liquid-glass window on Windows, native window on macOS), bootstrap/downloader, exporters, CLI
engine/              lyricist_engine.py: runs in the downloaded Python (Demucs → Whisper → MMS_FA)
installer/           Inno Setup script, icon, version info (Windows)
mac/                 macOS icon, entitlements, signing / notarization scripts, DMG layout
LyricistSync-mac.spec  PyInstaller spec of the universal2 app
tools/               manifest generators and the engine lock files (Windows, macOS arm64, macOS Intel)
tests/               exporter parity, repeat detection, downloader, timing, demo + hard fixtures with known times
CHANGELOG.md         release notes (also used for update.json)
```
