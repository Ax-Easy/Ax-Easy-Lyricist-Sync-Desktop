# Changelog

## 1.3.0 (2026-10-09)

### Transcribe: no lyrics needed
- New **Transcribe** button, and **Transcribe all** for every song that has no lyrics yet. **Auto-sync** on a song
  without lyrics transcribes it too.
- Whisper listens to the separated vocals (Demucs) with word timestamps. The language is detected on the 30 s
  with the most singing (not the instrumental intro); the Language box overrides it. Greek works.
- Lines follow the singing: Whisper's phrases, pauses longer than 0.6 s, punctuation, and at most about 42
  characters per line. If Whisper ends a phrase with the first word of the next line (*"…the sound You"*), that
  word moves to the next line.
- Line starts come from the MMS_FA aligner run on Whisper's own text, with the same checks as Auto-sync,
  because Whisper's word times run early. The ♪ gap logic runs as usual.
- **Unsure words are amber** in the line list and underlined in the lyrics box (Whisper word probability below
  45 %). Lines with low confidence get the amber **● check** marker with the reason.
- Recommended workflow: **Transcribe → fix the amber words → Auto-sync**. Auto-sync then reuses the cached vocals,
  emissions and transcript, so it only runs the aligner.
- Against hallucinations:
  - Whisper only hears the parts where the vocals stem is active;
  - condition_on_previous_text is off;
  - temperature fallback is on, with compression-ratio, log-prob and no-speech thresholds;
  - segments are dropped when there are no vocals under them, when Whisper loops on one line, when they are
    gibberish, humming or a known filler ("Thank you for watching", "Subtitles by…", "Υπότιτλοι…").
- Command line: `LyricistSync.exe --transcribe song.mp3 [--lang el] [--whisper large-v3]` writes the timed files
  and `song.transcript.txt`.

### Whisper model by hardware
- Setup picks the Whisper size from the GPU memory (nvidia-smi):

  | Hardware | Whisper |
  |---|---|
  | CPU, or a GPU under 6 GB | small (0.48 GB) |
  | 6–11 GB | medium (1.53 GB) |
  | 12–23 GB | large-v3-turbo (1.62 GB) |
  | 24 GB and more (e.g. RTX 3090) | large-v3 (3.09 GB) |

  Only that one model is downloaded.
- **Engine** settings (button next to Light/Dark) show:
  - the detected hardware and the model in use;
  - a dropdown with Auto, small, medium, large-v3-turbo and large-v3, with size, speed and accuracy hints.
- Picking a model that is not downloaded yet fetches it on the spot, with the same per-step progress, resume
  and SHA256 check as the setup. Models that are not in use can be deleted.
- Whisper runs in fp16 on CUDA and in fp32 on the CPU.
- Demucs and the MMS aligner are the same on every tier.
- **Updating from 1.2.0** keeps PyTorch and every model. If the GPU's tier is bigger than the installed small
  model, the app asks once whether to download it. Until then (or after a No) small keeps working.

### Measured (CPU, 8 cores)
*Stoned* (Monitored, 2:09, English), with no lyrics given, compared with the real lyrics as sung (24 lines,
160 words, repeats included). The 8-core CPU box ran every size; separation and analysis (about 60 s) come on top,
once per song.

| Whisper | WER | WER without the outro "Stay! Stay!"¹ | Whisper time on CPU | Line starts (aligned) | Whisper's own starts |
|---|---|---|---|---|---|
| small | 9.4 % | 8.1 % | 62 s | 23/23 within 0.04 s | 17/23 within 0.3 s, median 0.20 s |
| medium | 6.2 % | 5.0 % | 171 s | 23/23 within 0.04 s | 17/23 within 0.3 s, median 0.18 s |
| large-v3-turbo | 6.9 % | 5.6 % | 110 s | 22/22 within 0.04 s | 11/22 within 0.3 s, median 0.30 s |
| large-v3 | 6.2 % | 5.0 % | 371 s | 23/23 within 0.04 s | 17/23 within 0.3 s, median 0.21 s |

¹ The outro's "Stay! Stay!" is sung but not in the lyrics file, so every size gets two insertions there. Most of
the remaining errors are word splits (*back end* / *backend*, *fire walls* / *firewalls*) and near-homophones
(*wire* / *wired*, *met* / *mapped*).

Line starts are measured against the Auto-sync of the real lyrics, for every line whose first word Whisper heard
correctly. "Aligned" is what Transcribe shows. "Whisper's own" is the plain Whisper word time, which runs about
0.25 s early on average and up to 1.2 s off; that is why Transcribe re-times the lines with the aligner.

Demo songs (synthesized voices, known times):
- **English**: WER 4.2 % (small) and 2.1 % (large-v3-turbo). Every line starts within 0.08 s of the truth.
- **Greek**, with the Language box set to Greek: WER 5.6 % (medium), 33 % (large-v3), and 78 % (small and
  large-v3-turbo). The matched lines start within 0.02 s.
- **Greek on auto**: only large-v3 recognised the robotic synthesized Greek voice as Greek. small, medium and turbo
  guessed Latin, Finnish or Spanish. For Greek songs, set the Language box to Greek. Auto-detection never picks
  Latin and a few other languages that are never sung; it takes the next guess instead.

## 1.2.0 (2026-10-09)

### ♪ in instrumental parts
- When nothing is sung for longer than a threshold, a **♪** line is added: in the intro before the first line,
  in solos and breaks, and (optionally) in the outro. A lyric display then shows ♪ instead of the last sung line.
- The gap is found from the vocal activity on the separated vocals plus the line timings. The line before the gap
  ends where its singing really stops, and the ♪ ends 0.3 s before the next line.
- Settings (**♪ …**): on/off, shortest gap (default 8 s, 3–30 s), symbol (♪, ♪♪, ♫ or "♪ instrumental ♪"),
  intro and outro.
- In the line list ♪ lines are violet and italic. Delete one with the Delete key or the right-click menu, or
  add one at the playhead with **+ ♪** (*Insert ♪ here*).
- ♪ lines are in every format (LRC `[mm:ss.xx]♪`; SRT, VTT and TTML as normal cues). They are never sent to the
  aligner, and Re-sync from here skips them.

### Built-in player
- A waveform under the song list: line start markers, ♪ regions, amber markers on lines to check, and the
  playhead. Click to seek, wheel to zoom, drag a marker to move a line.
- Transport above the line list: play/pause, ±2 s, speed 0.5×–1.5×, time, Play from line. The line playing now
  is highlighted and the list follows it.
- Keyboard: Space play/pause, ↑/↓ select a line, ←/→ nudge 0.1 s (Shift: 0.01 s), S stamps the selected line
  at the playhead.
- Each song is decoded once to PCM, so seeking is exact, and cached together with its waveform.

### Window
- Maximize fills the screen's work area (the taskbar stays visible), with no shadow margin or rounded
  corners, and restores the previous size. All panels stretch with the window.
- Double-click the title bar to maximize or restore. **F11** toggles full screen. Win+↑/↓ and snap keep working.
- The lyrics box adapts to the window height, so the line list gets more room on 720p screens.

## 1.1.0 (2026-10-09)

### Timing
- The first line no longer starts too early. Each line starts on the first word that is actually sung:
  - a vocal-activity check on the separated vocals: no line starts where nobody sings;
  - starts snap to the nearest vocal onset;
  - a stretched first word (a hum or an instrument bleeding into it) is detected and re-aligned;
  - Whisper's word times are used as a cross-check, and the later start wins when the aligner is far ahead.
- Choirs and backing vocals:
  - every line gets a confidence score, built from the acoustic match, Whisper's agreement and the vocal overlap;
  - unsure lines get an amber "check" marker with the reason in a tooltip;
  - line starts are always in order and lines never overlap.
- **Re-sync from here**: fix one line by hand and re-align only the lines after it. This takes a few seconds,
  because the analysis of the song is cached.

### Saving
- **Save to**: *Next to the audio file* (the default), *A chosen folder* or *Ask every time*.
- **Per-song output folder**: use **Change…**, or select several songs and use **Set folder for selected…**.
  The app remembers the folders.
- Existing files are never overwritten without asking. You choose *Overwrite*, *Keep both* or *Skip*, and can
  apply the choice to all songs.
- After an export, **Open folder** links take you straight to the files.

### Window
- Windows 10 now gets a rounded glass window with a soft shadow, painted by the app itself. The heavy
  window-wide blur that Windows 10 handles badly is gone.
- Windows 11 keeps its native rounded corners and Mica.
- Snap, drag and resize work on the visible edge.

### Updates
- **Update** button next to About. The app quietly checks once a day; this can be switched off.
- Shows what's new, then downloads the update (it resumes if interrupted) and checks its SHA256 before
  installing. Your settings, the engine and the AI models are kept.

### First-run setup
- Fixed: setup could stop responding about halfway. The app now builds with Python 3.12: on Python 3.11 the
  Qt binding miscounted references during the constant progress repaints until the app aborted. The heavy
  work stays off the UI thread, and the UI refreshes at most 10 times per second.
- A new setup window with 7 steps. Each step has its own progress, speed and time left, plus:
  - a live log;
  - Pause/Resume, Cancel and **Retry step**;
  - a "still working…" notice when a step is quiet for a minute;
  - resume from the first unfinished step on the next start.

## 1.0.0 (2026-10-08)
- First release: auto-sync with Demucs, Whisper and MMS_FA, repeat detection, and TTML/LRC/SRT/VTT export
  in the Lyricist 1.1.0 formats.
