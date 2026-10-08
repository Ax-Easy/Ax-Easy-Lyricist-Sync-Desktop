# Changelog

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
