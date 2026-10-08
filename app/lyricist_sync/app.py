"""Application controller: songs, settings, sync queue and export."""
import json
import os
import sys
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from . import bootstrap, paths, theme as thememod
from .engine_client import EngineClient
from .lyrics import LANGS, resolve_lang, sidecar_lyrics, split_lines
from .window import GlassWindow, export_song, read_tags

AUDIO_EXT = ('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma')
STAGES = {'decode': 'Reading audio', 'separate': 'Separating vocals', 'transcribe': 'Listening for repeats',
          'align': 'Aligning lines'}
ISO_FROM_WHISPER = {v[0]: v[1] for v in LANGS.values() if v[0]}


class Song:
    def __init__(self, path):
        self.id = uuid.uuid4().hex[:8]
        self.path = path
        self.tags = read_tags(path)
        text, src = sidecar_lyrics(path)
        self.lyrics = text or ''
        self.lyrics_src = src
        self.lang = 'auto'
        self.iso = ''
        self.status = 'Ready' if self.lyrics.strip() else 'Needs lyrics'
        self.result = None
        self.dirty = False

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
                         'formats': ['ttml', 'lrc', 'srt', 'vtt'], 'bom': False, 'auto_export': False}
        try:
            with open(self.settings_path, encoding='utf-8') as f:
                self.settings.update(json.load(f))
        except (OSError, ValueError):
            pass
        if dark is not None:
            self.settings['dark'] = dark
        if self.settings['dark'] is None:
            self.settings['dark'] = thememod.system_is_dark()
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
                self.songs.append(Song(p))
        if self.cur < 0 and self.songs:
            self.cur = 0
        self.win.refresh_queue(self.songs, self.cur)
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

    def sync_current(self):
        s = self.current()
        if s:
            self._start([s])

    def sync_all(self):
        self._start([s for s in self.songs if split_lines(s.lyrics)])

    def _start(self, songs):
        songs = [s for s in songs if split_lines(s.lyrics)]
        if not songs or self.busy or not self.ensure_engine():
            return
        for s in songs:
            s.status = 'Queued'
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
        s.iso = iso
        s.status = 'Starting…'
        self._set_row(s)
        try:
            self.engine.submit({'cmd': 'sync', 'id': s.id, 'audio': s.path, 'lines': lines, 'lang': lang, 'iso': iso})
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
        s.status = '%s %d%%' % (STAGES.get(stage, stage), round(pct * 100))
        self._set_row(s)
        done = len([x for x in self.songs if x.status.startswith('Synced')])
        self.win.set_busy(True, '%s · %s' % (s.label(), s.status), pct)

    def _result(self, sid, res):
        s = self._find(sid)
        if s:
            s.result = res
            reps = len(res.get('repeats') or [])
            s.status = 'Synced' + (' · %d repeat%s' % (reps, 's' if reps > 1 else '') if reps else '')
            if not s.iso and res.get('language') in ISO_FROM_WHISPER:
                s.iso = ISO_FROM_WHISPER[res['language']]
            self._set_row(s)
            if s is self.current():
                self.win.show_song(s)
            if self.settings.get('auto_export'):
                self.export(s)
        self._pop(sid)

    def _error(self, sid, msg):
        s = self._find(sid)
        if s:
            s.status = 'Error'
            self._set_row(s)
            self.win.status_lbl.setText('%s: %s' % (s.label(), msg[:160]))
        self._pop(sid)

    def _pop(self, sid):
        self.queue = [q for q in self.queue if q.id != sid]
        self._next()

    def _exited(self, code):
        if self.busy and self.queue:
            s = self.queue[0]
            self._error(s.id, 'The engine stopped unexpectedly (exit %s). See engine.log in %s.' % (code, paths.home()))

    def cancel(self):
        self.queue = []
        self.engine.stop()
        for s in self.songs:
            if not s.status.startswith('Synced') and s.status != 'Error':
                s.status = 'Ready' if split_lines(s.lyrics) else 'Needs lyrics'
        self.busy = False
        self.win.set_busy(False, 'Cancelled.', 0)
        self.win.refresh_queue(self.songs, self.cur)

    # ---------------------------------------------------------------- export
    def export(self, s):
        opts = self.win.export_options()
        if not opts['formats']:
            self.win.status_lbl.setText('Choose at least one format.')
            return []
        if not opts['dir']:
            opts['dir'] = self.settings['out_dir']
        try:
            files = export_song(s, opts)
        except OSError as e:
            self.win.status_lbl.setText('Export failed: %s' % e)
            return []
        self.win.status_lbl.setText('Exported %d files to %s' % (len(files), opts['dir']))
        return files

    def export_current(self):
        s = self.current()
        if s and s.result:
            return self.export(s)
        return []


def run_gui(argv):
    qapp = QApplication.instance() or QApplication(argv)
    qapp.setApplicationName('Ax-Easy Lyricist Sync')
    qapp.setOrganizationName('Ax-Easy')
    from PySide6.QtGui import QIcon
    qapp.setWindowIcon(QIcon(paths.resource('res', 'icon.svg')))
    app = App(qapp)
    app.win.show()
    files = [a for a in argv[1:] if os.path.isfile(a)]
    if files:
        app.add_songs(files)
    if not bootstrap.is_ready():
        QTimer.singleShot(400, app.ensure_engine)
    return qapp.exec()
