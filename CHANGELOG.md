# Changelog

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
