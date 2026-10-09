"""Application controller: songs, settings, sync queue and export."""
import importlib
import json
import os
import sys
import threading
import time
import uuid

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from . import bootstrap, edits, instrumental, paths, theme as thememod, updater
from .engine_client import EngineClient
from .export import export_song, read_tags, target_dir
from .lyrics import LANGS, resolve_lang, sidecar_lyrics, split_lines
from .window import GlassWindow

meta = importlib.import_module(__package__)

AUDIO_EXT = ('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma')
STAGES = {'decode': 'Reading audio', 'separate': 'Separating vocals', 'transcribe': 'Listening for repeats',
          'align': 'Aligning lines'}
ISO_FROM_WHISPER = {v[0]: v[1] for v in LANGS.values() if v[0]}


def _t(t):
    from .formats import fmt_lrc_time
    return fmt_lrc_time(t)


class _UpdSignal(QObject):
    checked = Signal(object)


class Song:
    def __init__(self, path, out_dir=None):
        self.id = uuid.uuid4().hex[:8]
        self.path = path
        self.out_dir = out_dir if out_dir and os.path.isdir(out_dir) else None
        self.tags = read_tags(path)
        text, src = sidecar_lyrics(path)
        self.lyrics = text or ''
        self.lyrics_src = src
        self.lang = 'auto'
        self.iso = ''
        self.status = 'Ready' if self.lyrics.strip() else 'Needs lyrics'
        self.result = None
        self.dirty = False
        self.job = 'sync'            # what the queued run does: 'sync' or 'transcribe'
        self.edited = False          # lines edited by hand in the review list (asked before replacing them)
        self.history = edits.History()

    def label(self):
        t = self.tags.get('title') or os.path.splitext(os.path.basename(self.path))[0]
        a = self.tags.get('artist')
        return '%s – %s' % (a, t) if a else t


class App:
    def __init__(self, qapp, screenshot=False, dark=None):
        self.qapp = qapp
        self.screenshot = screenshot
        self.songs = []
        self.cur = -1
        self.busy = False
        self.queue = []
        self.engine_info = None
        self.settings_path = os.path.join(paths.home(), 'settings.json')
        self.settings = {'dark': None, 'out_dir': os.path.join(os.path.expanduser('~'), 'Documents', 'Lyricist Sync'),
                         'save_mode': 'beside', 'song_dirs': {},
                         'formats': ['ttml', 'lrc', 'srt', 'vtt'], 'bom': False, 'auto_export': False,
                         'update_check': True, 'update_last': 0, 'update_skip': '',
                         'whisper_model': 'auto', 'whisper_asked': ''}
        self.settings.update(instrumental.DEFAULTS)
        self.update_state = None
        self._upd = _UpdSignal()
        self._upd.checked.connect(self._quiet_checked)
        self._ask_dir = None
        self._batch_conflict = None
        try:
            with open(self.settings_path, encoding='utf-8') as f:
                self.settings.update(json.load(f))
        except (OSError, ValueError):
            pass
        if dark is not None:
            self.settings['dark'] = dark
        if self.settings['dark'] is None:
            self.settings['dark'] = thememod.system_is_dark()
        thememod.apply_platform_style(qapp)
        qapp.setFont(thememod.ui_font())
        self.win = GlassWindow(self)
        self.win.load_settings(self.settings)
        self.engine = EngineClient()
        self.engine.hello.connect(self._hello)
        self.engine.progress.connect(self._progress)
        self.engine.result.connect(self._result)
        self.engine.error.connect(self._error)
        self.engine.exited.connect(self._exited)
        st = bootstrap.state()
        if st and st.get('engine'):
            self.engine_info = st['engine']
            self.win.set_device(st['engine'])
        elif not bootstrap.is_ready():
            self.win.set_device({'text': 'Engine not set up yet'})
        self.win.refresh_queue(self.songs, self.cur)

    def save_settings(self):
        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=1)
        except OSError:
            pass

    # ---------------------------------------------------------------- songs
    def current(self):
        return self.songs[self.cur] if 0 <= self.cur < len(self.songs) else None

    def add_songs(self, files):
        for p in files:
            if os.path.isfile(p) and os.path.splitext(p)[1].lower() in AUDIO_EXT and not any(s.path == p for s in self.songs):
                self.songs.append(Song(p, (self.settings.get('song_dirs') or {}).get(os.path.abspath(p))))
        if self.cur < 0 and self.songs:
            self.cur = 0
        self.win.refresh_queue(self.songs, self.cur)
        self.win.show_song(self.current())

    def apply_instrumental(self, songs=None):
        """Re-place the ♪ lines of synced songs after the ♪ settings changed."""
        for s in songs or self.songs:
            if s.result:
                edits.history(s).push(s, '♪ settings')
                instrumental.apply(s.result, self.settings)
                s.dirty = True
        if self.current() and self.current().result:
            self.win.show_song(self.current())

    def remove_song(self, i):
        if self.busy or not (0 <= i < len(self.songs)):
            return
        del self.songs[i]
        self.cur = min(self.cur, len(self.songs) - 1)
        self.win.refresh_queue(self.songs, self.cur)
        self.win.show_song(self.current())

    def select(self, i):
        if i != self.cur:
            self.cur = i
            self.win.show_song(self.current())

    def lyrics_changed(self, text, lang):
        s = self.current()
        if not s:
            return
        s.lyrics = text
        s.lang = lang or 'auto'
        if not self.busy and s.status in ('Ready', 'Needs lyrics'):
            s.status = 'Ready' if split_lines(text) else 'Needs lyrics'
        item = self.win.queue.item(self.cur, 1)
        if item:
            item.setText('%d lines' % len(split_lines(text)) if text.strip() else '—')
            self.win.queue.item(self.cur, 2).setText(s.status)
        self.win._update_buttons()

    # ---------------------------------------------------------------- sync
    def ensure_engine(self):
        if bootstrap.is_ready():
            return True
        from .dialogs import SetupDialog
        dlg = SetupDialog(self.win)
        dlg.ready.connect(lambda st: (setattr(self, 'engine_info', st.get('engine')), self.win.set_device(st.get('engine'))))
        dlg.exec()
        return bootstrap.is_ready()

    def keep_edits(self, songs, action):
        """Songs whose lines were edited by hand are only replaced after "Replace". Returns the songs to run."""
        edited = [s for s in songs if s.edited and s.result]
        if not edited or self.busy:
            return songs
        if self.win.ask_keep_edits(edited, action) == 'replace':
            return songs
        kept = [s for s in songs if s not in edited]
        self.win.status_lbl.setText('Kept your edits%s.' % ('' if not kept else ' (%d song%s skipped)' % (
            len(edited), '' if len(edited) == 1 else 's')))
        return kept

    def sync_current(self):
        s = self.current()
        if not s:
            return
        job = 'sync' if split_lines(s.lyrics) else 'transcribe'   # no lyrics yet: transcribe first
        if self.keep_edits([s], job):
            self._start([s], job)

    def sync_all(self):
        self._start(self.keep_edits([s for s in self.songs if split_lines(s.lyrics)], 'sync'))

    def transcribe_current(self):
        s = self.current()
        if s:
            if s.edited and s.result:
                if not self.keep_edits([s], 'transcribe'):
                    return
            elif split_lines(s.lyrics) and s.lyrics_src != 'transcribe' and not self.win.confirm(
                    'Transcribe', 'Replace the lyrics of this song with what Whisper hears?\n'
                    'Ctrl+Z in the line list brings the current lines and text back.'):
                return
            self._start([s], 'transcribe')

    def transcribe_all(self):
        self._start(self.keep_edits([s for s in self.songs if not split_lines(s.lyrics)], 'transcribe'), 'transcribe')

    def song_edited(self, s):
        """After an edit / undo: the queue row shows the lyric line count."""
        if s in self.songs:
            i = self.songs.index(s)
            item = self.win.queue.item(i, 1)
            if item:
                item.setText('%d lines' % len(split_lines(s.lyrics)) if s.lyrics.strip() else '—')

    def realign(self, s, row):
        """Re-run the aligner for one line (after its words changed), between its neighbours."""
        if self.busy or not s.result or not self.ensure_engine():
            return
        lines = s.result['lines']
        if not (0 <= row < len(lines)) or lines[row].get('inst'):
            return
        lo, hi = edits.realign_window(lines, row, s.result.get('duration'))
        lang, iso = resolve_lang(s.lang, split_lines(s.lyrics))
        if not iso and s.iso:
            iso = s.iso
        job = {'cmd': 'realign', 'id': s.id, 'audio': s.path, 'text': lines[row]['text'], 'lo': lo, 'hi': hi,
               'row': row, 'iso': iso, 'lang': lang, 'whisper': self.whisper_effective()}
        self.busy = True
        self.queue = [s]
        s.job = 'realign'
        self._realign_was = s.status
        s.status = 'Re-aligning line %d' % (row + 1)
        self._set_row(s)
        self.win.set_busy(True, '%s · re-aligning line %d' % (s.label(), row + 1), 0.0)
        try:
            self.engine.submit(job)
        except OSError as e:
            self._error(s.id, 'Engine could not start: %s' % e)

    # ---------------------------------------------------------------- Whisper model (Engine settings)
    def hardware(self):
        """{'variant', 'gpu' name, 'vram_gb', 'tier'} from the engine check (state.json) or nvidia-smi."""
        st = bootstrap.state() or {}
        eng = st.get('engine') or self.engine_info or {}
        variant = st.get('variant') or ('cuda' if eng.get('device') == 'cuda' else 'cpu')
        vram = eng.get('vram_gb') if eng.get('device') == 'cuda' else None
        name = eng.get('device_name') if eng.get('device') == 'cuda' else None
        if variant == 'cuda' and not vram:
            g = getattr(self, '_gpu', None) or bootstrap.detect_gpu()
            self._gpu = g
            vram, name = g.get('vram_gb'), name or g.get('name')
        if os.environ.get('LYRICIST_SYNC_FAKE_VRAM'):   # screenshots/tests
            variant, vram = 'cuda', float(os.environ['LYRICIST_SYNC_FAKE_VRAM'])
            name = os.environ.get('LYRICIST_SYNC_FAKE_GPU', 'NVIDIA GeForce RTX 3090')
        if bootstrap.IS_MAC and not os.environ.get('LYRICIST_SYNC_FAKE_VRAM'):
            # Mac: Apple Silicon (MPS, tiered by unified memory) or Intel (CPU, tiered by RAM)
            from . import macfx
            variant = st.get('variant') or bootstrap.recommended_variant()
            mem = float(os.environ.get('LYRICIST_SYNC_FAKE_MEM') or eng.get('memory_gb') or macfx.memory_gb() or 0)
            chip = eng.get('device_name') or macfx.chip_name()
            return {'variant': variant, 'gpu': chip if variant == 'mps' else None, 'vram_gb': mem, 'memory_gb': mem,
                    'device': eng.get('device') or '', 'cpu': chip, 'mac': True,
                    'tier': bootstrap.whisper_tier(mem, bootstrap.tier_variant(variant))}
        return {'variant': variant, 'gpu': name, 'vram_gb': vram, 'cpu': eng.get('device_name') if eng.get('device') == 'cpu' else '',
                'tier': bootstrap.whisper_tier(vram, variant)}

    def whisper_effective(self):
        hw = self.hardware()
        return bootstrap.effective_whisper(self.settings.get('whisper_model'), hw['tier'], bootstrap.whisper_installed())

    def open_engine(self, download=None):
        from .dialogs import EngineDialog
        dlg = EngineDialog(self.win, self, download=download)
        dlg.exec()

    def offer_tier_upgrade(self):
        """After an update from 1.2.0 (small only): offer the bigger Whisper this GPU can run. Asked
        once per tier; nothing is downloaded without a yes."""
        if not bootstrap.is_ready() or self.screenshot:
            return
        hw = self.hardware()
        tier = hw['tier']
        if self.settings.get('whisper_model', 'auto') != 'auto' or tier in bootstrap.whisper_installed() \
                or self.settings.get('whisper_asked') == tier:
            return
        self.settings['whisper_asked'] = tier
        self.save_settings()
        m = bootstrap.whisper_models()[tier]
        if self.win.confirm('Better transcription available',
                            'Your %s (%g GB) can run Whisper %s for more accurate Transcribe.\n\n'
                            'Download it now (%.1f GB)? PyTorch and the other models are already installed and are '
                            'not downloaded again. Until then Whisper %s is used.' % (
                                hw['gpu'] or 'GPU', hw['vram_gb'] or 0, tier, m['size'] / 1e9, self.whisper_effective())):
            self.open_engine(download=tier)

    def _start(self, songs, job='sync'):
        if job == 'sync':
            songs = [s for s in songs if split_lines(s.lyrics)]
        if not songs or self.busy or not self.ensure_engine():
            return
        for s in songs:
            s.status = 'Queued'
            s.job = job
        self.queue = list(songs)
        self.busy = True
        self.win.refresh_queue(self.songs, self.cur)
        self._next()

    def _next(self):
        if not self.queue:
            self.busy = False
            self.win.set_busy(False, 'Done.', 1.0)
            self.win.refresh_queue(self.songs, self.cur)
            return
        s = self.queue[0]
        lines = split_lines(s.lyrics)
        lang, iso = resolve_lang(s.lang, lines)
        s.status = 'Starting…'
        self._set_row(s)
        if s.job == 'transcribe':
            lang = None if s.lang in (None, '', 'auto') else lang   # the Language box overrides auto-detect
            job = {'cmd': 'transcribe', 'id': s.id, 'audio': s.path, 'lang': lang}
        else:
            s.iso = iso
            job = {'cmd': 'sync', 'id': s.id, 'audio': s.path, 'lines': lines, 'lang': lang, 'iso': iso}
        job['whisper'] = self.whisper_effective()
        try:
            self.engine.submit(job)
        except OSError as e:
            self._error(s.id, 'Engine could not start: %s' % e)

    def _find(self, sid):
        return next((s for s in self.songs if s.id == sid), None)

    def _set_row(self, s):
        if s in self.songs:
            it = self.win.queue.item(self.songs.index(s), 2)
            if it:
                it.setText(s.status)

    def _hello(self, info):
        self.engine_info = info
        self.win.set_device(info)

    def _progress(self, sid, stage, pct):
        s = self._find(sid)
        if not s:
            return
        label = 'Transcribing' if (stage == 'transcribe' and s.job == 'transcribe') else STAGES.get(stage, stage)
        s.status = '%s %d%%' % (label, round(pct * 100))
        self._set_row(s)
        done = len([x for x in self.songs if x.status.startswith('Synced')])
        self.win.set_busy(True, '%s · %s' % (s.label(), s.status), pct)

    def resync(self, s, row):
        """Keep line `row` at its current start and re-align only the sung lines after it
        (♪ lines are never aligned; they are recomputed afterwards)."""
        if self.busy or not s.result or not self.ensure_engine():
            return
        lines = s.result['lines']
        if not (0 <= row < len(lines)) or lines[row].get('inst'):
            return
        sung = instrumental.sung(lines)
        k = sung.index(lines[row])
        job = {'cmd': 'resync', 'id': s.id, 'audio': s.path, 'lines': [l['text'] for l in sung],
               'idx': [l.get('idx', i) for i, l in enumerate(sung)], 'from': k, 'anchor': sung[k]['start'],
               'starts': [l['start'] for l in sung], 'ends': [l.get('end0', l['end']) for l in sung], 'iso': s.iso,
               'lang': resolve_lang(s.lang, split_lines(s.lyrics))[0]}
        self.busy = True
        self.queue = [s]
        s.status = 'Re-syncing from line %d' % (row + 1)
        self._set_row(s)
        self.win.set_busy(True, '%s · re-syncing from line %d' % (s.label(), row + 1), 0.0)
        try:
            self.engine.submit(job)
        except OSError as e:
            self._error(s.id, 'Engine could not start: %s' % e)

    def _result(self, sid, res):
        s = self._find(sid)
        if s and res.get('realign') and s.result:
            row = res.get('row')
            L = s.result['lines']
            s.status = getattr(self, '_realign_was', '') or s.status
            s.job = 'sync'
            if row is not None and 0 <= row < len(L) and L[row]['text'] == res.get('text'):
                old = L[row]['start']
                edits.history(s).push(s, 'Re-align line %d' % (row + 1))
                edits.apply_realign(s, row, res['start'], res['end'], res.get('conf'), res.get('why'))
                if s is self.current():
                    self.win.after_edit(s, row)
                self.win.status_lbl.setText('Line %d re-aligned: %s → %s (%d%% sure) · Ctrl+Z to undo' % (
                    row + 1, _t(old), _t(res['start']), round(100 * (res.get('conf') or 0))))
            else:
                self.win.status_lbl.setText('The line changed while it was re-aligned; nothing applied.')
            self._set_row(s)
            self._pop(sid)
            return
        if s and s.result and (res.get('mode') in ('transcribe', 'sync') or 'from' in res):
            edits.history(s).push(s, {'transcribe': 'Transcribe'}.get(res.get('mode'), 'Re-sync' if 'from' in res else 'Auto-sync'))
        if s and 'from' not in res:
            s.edited = False
        if s and 'from' in res and s.result:
            k0 = res['from']
            sung = instrumental.sung(s.result['lines'])
            manual = [l for l in s.result['lines'] if l.get('inst') and not l.get('auto')]
            keep = sung[:k0]
            new = res['lines']
            if new:
                new[0]['manual'] = True
                new[0]['conf'], new[0]['why'] = 1.0, ['set by hand']
            s.result['lines'] = keep + new + manual
            if res.get('vocals') is not None:
                s.result['vocals'] = res['vocals']
            instrumental.apply(s.result, self.settings)
            s.dirty = True
            low = sum(1 for l in s.result['lines'] if (l.get('conf') if l.get('conf') is not None else 1) < 0.6)
            s.status = 'Synced' + (' · %d to check' % low if low else '')
            self._set_row(s)
            if s is self.current():
                self.win.show_song(s)
                sel = new[0] if new else (keep[-1] if keep else None)
                self.win.review.selectRow(next((i for i, l in enumerate(s.result['lines']) if l is sel), 0))
            self.win.status_lbl.setText('Re-synced %d lines after line %d.' % (max(0, len(new) - 1), k0 + 1))
            self._pop(sid)
            return
        if s and res.get('mode') == 'transcribe':
            s.result = res
            instrumental.apply(res, self.settings)
            s.lyrics = res.get('text') or ''
            s.lyrics_src = 'transcribe'
            if res.get('language') in ISO_FROM_WHISPER:
                s.iso = ISO_FROM_WHISPER[res['language']]
            low = res.get('low_conf') or 0
            s.status = 'Transcribed' + (' · %d to check' % low if low else '')
            s.dirty = True
            self._set_row(s)
            if s is self.current():
                self.win.show_song(s)
                self.win.status_lbl.setText('Transcribed with Whisper %s (%s): %d lines. Fix the amber words, then press '
                                            'Auto-sync for exact timing.' % (res.get('whisper'), res.get('language'), len(res['lines'])))
            self._pop(sid)
            return
        if s:
            s.result = res
            instrumental.apply(res, self.settings)
            reps = len(res.get('repeats') or [])
            low = res.get('low_conf') or 0
            s.status = 'Synced' + (' · %d repeat%s' % (reps, 's' if reps > 1 else '') if reps else '') + \
                (' · %d to check' % low if low else '')
            if not s.iso and res.get('language') in ISO_FROM_WHISPER:
                s.iso = ISO_FROM_WHISPER[res['language']]
            self._set_row(s)
            if s is self.current():
                self.win.show_song(s)
            if self.settings.get('auto_export'):
                self.export_songs([s], batch=bool(self.queue[1:]))
        self._pop(sid)

    def _error(self, sid, msg):
        s = self._find(sid)
        if s:
            s.status = (getattr(self, '_realign_was', '') or 'Error') if s.job == 'realign' else 'Error'
            if s.job == 'realign':
                s.job = 'sync'
            self._set_row(s)
            self.win.status_lbl.setText('%s: %s' % (s.label(), msg[:160]))
        self._pop(sid)

    def _pop(self, sid):
        self.queue = [q for q in self.queue if q.id != sid]
        if not self.queue:
            self._ask_dir = None
            self._batch_conflict = None
        self._next()

    def _exited(self, code):
        if self.busy and self.queue:
            s = self.queue[0]
            self._error(s.id, 'The engine stopped unexpectedly (exit %s). See engine.log in %s.' % (code, paths.home()))

    def cancel(self):
        self.queue = []
        self.engine.stop()
        for s in self.songs:
            if not s.status.startswith(('Synced', 'Transcribed')) and s.status != 'Error':
                s.status = 'Ready' if split_lines(s.lyrics) else 'Needs lyrics'
        self.busy = False
        self.win.set_busy(False, 'Cancelled.', 0)
        self.win.refresh_queue(self.songs, self.cur)

    # ---------------------------------------------------------------- export
    def set_song_dirs(self, songs, d):
        sd = dict(self.settings.get('song_dirs') or {})
        for s in songs:
            s.out_dir = d
            key = os.path.abspath(s.path)
            if d:
                sd[key] = d
            else:
                sd.pop(key, None)
        if len(sd) > 500:
            sd = dict(list(sd.items())[-500:])
        self.settings['song_dirs'] = sd
        self.save_settings()
        self.win.refresh_dirs()

    def export_songs(self, songs, batch=False, ask_dir=None, show=False):
        """Export each song to its own folder. Never overwrites silently. Returns files written.
        self.last_export: one entry per song {song, label, dir, files, status ok|skipped|failed, reason};
        show=True opens the export confirmation (Export button)."""
        report = []
        for s in songs:
            if not s.result:
                report.append({'song': s, 'label': s.label(), 'dir': target_dir(s, self.settings), 'files': [],
                               'status': 'skipped', 'reason': 'not synced or transcribed yet'})
        songs = [s for s in songs if s.result]
        self.last_export = report
        opts = self.win.export_options()
        if not songs:
            if show and report:
                self.win.show_export_report(report)
            return []
        if not opts['formats']:
            self.win.status_lbl.setText('Choose at least one format.')
            return []
        asked = ask_dir or (self._ask_dir if batch else None)
        if any(target_dir(s, self.settings) is None for s in songs) and not asked:
            asked = QFileDialog.getExistingDirectory(self.win, 'Save the lyric files to…',
                                                     self.settings.get('last_export_dir') or os.path.dirname(songs[0].path))
            if not asked:
                self.win.status_lbl.setText('Export cancelled.')
                return []
            self.settings['last_export_dir'] = asked
            self.save_settings()
            if batch:
                self._ask_dir = asked
        if batch:
            if self._batch_conflict is None:
                self._batch_conflict = {}
            state = self._batch_conflict
        else:
            state = {}
        files, folders, skipped = [], [], 0
        for s in songs:
            d = target_dir(s, self.settings, asked)
            entry = {'song': s, 'label': s.label(), 'dir': d, 'files': [], 'status': 'ok', 'reason': ''}
            report.append(entry)
            try:
                written = export_song(s, dict(opts, dir=d), on_conflict=lambda song, ex: self.win.ask_conflict(song, ex, state))
            except OSError as e:
                entry['status'], entry['reason'] = 'failed', (e.strerror or str(e)) + (
                    (' (%s)' % e.filename) if getattr(e, 'filename', None) else '')
                self.win.status_lbl.setText('Export failed for %s: %s' % (s.label(), e))
                continue
            entry['files'] = written
            if not written:
                skipped += 1
                entry['status'], entry['reason'] = 'skipped', 'the files already exist and you chose Skip'
                continue
            s.dirty = False
            files += written
            if d not in folders:
                folders.append(d)
        report.sort(key=lambda e: [x for x in self.songs].index(e['song']) if e['song'] in self.songs else 0)
        self.win.show_export_result(folders, len(files), skipped, failed=sum(1 for e in report if e['status'] == 'failed'))
        self.win.refresh_dirty()
        if show:
            self.win.show_export_report(report)
        return files

    def export_selected(self):
        sel = list(self.win.selected_songs())
        if not any(s.result for s in sel) and self.current() and self.current().result:
            sel = [self.current()]
        return self.export_songs(sel, show=True)

    def export_current(self):
        s = self.current()
        return self.export_songs([s], show=True) if s and s.result else []

    def export(self, s):
        return self.export_songs([s])

    # ---------------------------------------------------------------- unsaved work
    def dirty_songs(self):
        return [s for s in self.songs if s.result and s.dirty]

    def confirm_close(self, action='close'):
        """Before the window closes (or the updater restarts the app): unsaved lyrics?
        True when it may close. "Export all & close" exports each song to its save location and
        only says yes when every song was written."""
        dirty = self.dirty_songs()
        if not dirty or self.screenshot:
            return True
        choice = self.win.ask_unsaved(dirty, action)
        if choice == 'discard':
            return True
        if choice != 'export':
            return False
        self.export_songs(dirty)
        rep = getattr(self, 'last_export', []) or []
        ok = len(rep) == len(dirty) and all(e['status'] == 'ok' for e in rep)
        if not ok:
            self.win.show_export_report(rep, closing=True)
        return ok

    # ---------------------------------------------------------------- updates
    def quiet_update_check(self):
        if self.screenshot or not updater.due(self.settings):
            return
        url = updater.manifest_url(self.settings)
        threading.Thread(target=lambda: self._upd.checked.emit(updater.check(meta.VERSION, url)), daemon=True).start()

    def _quiet_checked(self, r):
        if r['status'] in ('available', 'current'):
            self.settings['update_last'] = time.time()
            self.save_settings()
        self.update_result(r)

    def update_result(self, r):
        self.update_state = r
        m = r.get('manifest') or {}
        badge = r.get('status') == 'available' and m.get('version') != self.settings.get('update_skip')
        self.win.btn_update.set_badge(badge)
        self.win.btn_update.setToolTip(('Version %s is available' % m['version']) if badge else 'Check for updates')

    def open_updates(self):
        from .dialogs import UpdateDialog
        r = self.update_state if (self.update_state or {}).get('status') == 'available' else None
        UpdateDialog(self.win, self, r).exec()

    def quit_for_update(self):
        self._closing_ok = True        # the unsaved-lyrics question was asked before the installer started
        self.engine.stop()
        self.win.player.stop()
        self.busy = False
        QTimer.singleShot(200, self.qapp.quit)


def _install_file_open_handler(qapp, app):
    """macOS: files dropped on the Dock icon or opened with "Open With" arrive as QFileOpenEvent (not argv)."""
    from PySide6.QtCore import QEvent, QObject

    class _Opener(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.FileOpen:
                f = ev.file()
                if f and os.path.isfile(f):
                    QTimer.singleShot(0, lambda: app.add_songs([f]))
                return True
            return False

    qapp._file_opener = _Opener(qapp)
    qapp.installEventFilter(qapp._file_opener)


def run_gui(argv):
    qapp = QApplication.instance() or QApplication(argv)
    qapp.setApplicationName(meta.APP_NAME)
    qapp.setOrganizationName('Ax-Easy')
    from PySide6.QtGui import QIcon
    qapp.setWindowIcon(QIcon(paths.resource('res', 'icon.svg')))
    app = App(qapp)
    if sys.platform == 'darwin':
        _install_file_open_handler(qapp, app)
    app.win.show()
    files = [a for a in argv[1:] if os.path.isfile(a)]
    if files:
        app.add_songs(files)
    if not bootstrap.is_ready():
        QTimer.singleShot(400, app.ensure_engine)
    else:
        QTimer.singleShot(2500, app.offer_tier_upgrade)
    QTimer.singleShot(3000, app.quiet_update_check)
    return qapp.exec()
