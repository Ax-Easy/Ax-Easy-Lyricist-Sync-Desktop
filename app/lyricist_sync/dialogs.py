"""Frameless glass dialogs: About and the first-run engine setup."""
import importlib
import os
import threading
import time

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QTextBrowser, QVBoxLayout, QWidget

from . import bootstrap, chrome, paths, updater, winfx
from .theme import ACCENT
from .widgets import AMBER, GlassProgress, PillButton, STATE

meta = importlib.import_module(__package__)


class GlassDialog(QDialog, chrome.Frame):
    def __init__(self, parent, title, w=560, h=380):
        super().__init__(parent)
        self.theme = parent.theme
        self.init_frame()
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        m = self.margin()
        self.resize(w + 2 * m, h + 2 * m)
        self._drag = None
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(26 + m, 18 + m, 26 + m, 20 + m)
        self.lay.setSpacing(10)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName('h1')
        head.addWidget(t)
        head.addStretch(1)
        from .window import CaptionButton
        c = CaptionButton('close')
        c.clicked.connect(self.reject)
        head.addWidget(c)
        self.lay.addLayout(head)

    def showEvent(self, e):
        super().showEvent(e)
        if winfx.IS_WIN and not getattr(self, '_fx', False):
            self._fx = True
            hwnd = int(self.winId())
            if self._mode == 'win11' and winfx.set_mica(hwnd, self.theme.dark):
                winfx.enable_native_frame(hwnd, dwm_frame=True)
            elif self._mode == 'win11':   # no Mica after all: painted path
                self._mode = self._backdrop = 'painted'
                m = self.margin()
                self.lay.setContentsMargins(26 + m, 18 + m, 26 + m, 20 + m)
                self.resize(self.width() + 2 * m, self.height() + 2 * m)

    def paintEvent(self, _e):
        body = self.body_rect()

        def paint(q):
            if self.margin():
                chrome.paint_shadow(q, body, chrome.RADIUS, self.theme.dark)
            chrome.paint_glass(q, body, chrome.RADIUS, self.theme, self._backdrop)
        pm = chrome.cached_background(self, (self.theme.dark, self._backdrop, self.margin()), paint)
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawPixmap(0, 0, pm)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 56 + self.margin() and self.body_rect().contains(e.position()):
            if self.windowHandle() is None or not self.windowHandle().startSystemMove():
                self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


def link_label(html, name='footer'):
    l = QLabel(html)
    l.setObjectName(name)
    l.setTextFormat(Qt.RichText)
    l.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
    l.setOpenExternalLinks(True)
    l.setWordWrap(True)
    return l


class AboutDialog(GlassDialog):
    def __init__(self, parent):
        super().__init__(parent, 'About', 520, 360)
        app = parent.app
        info = app.engine_info or {}
        lines = [
            '<span style="font-size:17px;font-weight:600">%s</span>&nbsp;&nbsp;v%s' % (meta.APP_NAME, meta.VERSION),
            'Auto-syncs pasted lyrics to a song: Demucs vocal separation, Whisper repeat detection '
            'and MMS_FA forced alignment. Exports TTML, LRC, SRT and VTT in the Ax-Easy Lyricist format.',
        ]
        for h in lines:
            self.lay.addWidget(link_label(h, 'plain'))
        eng = ('Engine: %s · %s · PyTorch %s' % (info.get('device', '').upper(), info.get('device_name', ''), info.get('torch', ''))
               if info else 'Engine: not set up yet')
        self.lay.addWidget(link_label(eng, 'sub'))
        self.lay.addWidget(link_label('Data folder: ' + paths.home().replace('<', '&lt;'), 'sub'))
        self.lay.addWidget(link_label('Models: Demucs (MIT), Whisper (MIT), MMS_FA (CC-BY-NC 4.0, non-commercial).', 'sub'))
        self.lay.addStretch(1)
        self.lay.addWidget(link_label(meta.CREDIT_HTML))
        self.lay.addWidget(link_label(meta.INSPIRED_HTML))
        row = QHBoxLayout()
        row.addStretch(1)
        ok = PillButton('Close', 'primary')
        ok.setFixedWidth(110)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        self.lay.addLayout(row)


def _fmt_dur(sec):
    sec = int(max(0, sec))
    return '%d:%02d' % (sec // 60, sec % 60) if sec < 3600 else '%d:%02d:%02d' % (sec // 3600, sec // 60 % 60, sec % 60)


class StepIcon(QWidget):
    """waiting (hollow) · running (spinning arc) · done (check) · failed (cross) · paused (bars)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.status = 'waiting'
        self.phase = 0

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(3, 3, 14, 14)
        dark = STATE['dark']
        if self.status == 'done':
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#2fbf71'))
            p.drawEllipse(r)
            p.setPen(QPen(QColor('#ffffff'), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline([QPointF(6.5, 10.2), QPointF(9, 12.6), QPointF(13.6, 7.6)])
        elif self.status == 'failed':
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#d63638'))
            p.drawEllipse(r)
            p.setPen(QPen(QColor('#ffffff'), 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(7.5, 7.5), QPointF(12.5, 12.5))
            p.drawLine(QPointF(12.5, 7.5), QPointF(7.5, 12.5))
        elif self.status == 'running':
            p.setPen(QPen(QColor(255, 255, 255, 40) if dark else QColor(20, 25, 40, 40), 2))
            p.drawEllipse(r)
            p.setPen(QPen(QColor(ACCENT), 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, int(-self.phase * 16), 100 * 16)
        elif self.status == 'paused':
            p.setPen(QPen(QColor(AMBER), 2))
            p.drawEllipse(r)
            p.drawLine(QPointF(8.5, 7.5), QPointF(8.5, 12.5))
            p.drawLine(QPointF(11.5, 7.5), QPointF(11.5, 12.5))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 70) if dark else QColor(20, 25, 40, 70), 1.6))
            p.drawEllipse(r)


class StepRow(QWidget):
    def __init__(self, label, parent=None):
        super().__init__(parent)
        g = QVBoxLayout(self)
        g.setContentsMargins(0, 2, 0, 2)
        g.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.icon = StepIcon()
        self.name = QLabel(label)
        self.right = QLabel('')
        self.right.setObjectName('sub')
        top.addWidget(self.icon)
        top.addWidget(self.name, 1)
        top.addWidget(self.right)
        g.addLayout(top)
        sub = QHBoxLayout()
        sub.setContentsMargins(28, 0, 0, 0)
        sub.setSpacing(8)
        self.bar = GlassProgress(thin=True)
        self.detail = QLabel('')
        self.detail.setObjectName('hint')
        self.detail.setMinimumWidth(10)
        sub.addWidget(self.bar, 2)
        sub.addWidget(self.detail, 5)
        g.addLayout(sub)

    def show_state(self, st, now, phase):
        self.icon.status = st['status']
        self.icon.phase = phase
        self.icon.update()
        status = st['status']
        frac = (st['done'] / st['total']) if st['total'] else (1.0 if status == 'done' else 0.0)
        self.bar.set_value(frac)
        self.bar.set_indeterminate(status == 'running' and st.get('indeterminate'))
        el = (st['t1'] or now) - st['t0'] if st['t0'] else 0
        if status == 'running':
            if st['unit'] == 'bytes' and st['total']:
                spd = st.get('speed') or 0
                eta = (st['total'] - st['done']) / spd if spd > 0 else None
                txt = '%.0f / %.0f MB' % (st['done'] / 1e6, st['total'] / 1e6)
                if spd:
                    txt += ' · %.1f MB/s' % (spd / 1e6)
                if eta is not None:
                    txt += ' · %s left' % _fmt_dur(eta)
                self.right.setText(txt)
            else:
                self.right.setText('%s elapsed' % _fmt_dur(el))
        elif status == 'done':
            self.right.setText('Done' + (' in %s' % _fmt_dur(el) if el >= 1 else ''))
        elif status == 'failed':
            self.right.setText('Failed')
        elif status == 'paused':
            self.right.setText('Paused')
        else:
            self.right.setText('Waiting' if not st['total'] or st['unit'] != 'bytes' else '%.0f MB' % (st['total'] / 1e6))
        d = st['error'] if status == 'failed' else st['detail']
        self.detail.setText(self.detail.fontMetrics().elidedText(d or '', Qt.ElideRight, max(60, self.detail.width() - 4)))
        self.detail.setToolTip(d or '')


class SetupDialog(GlassDialog):
    """First-run setup in 7 visible steps on a worker thread; the UI polls the shared state
    10x per second (never blocks), shows per-step bars, overall time, a heartbeat after 60 s
    without progress, a live log, Pause/Resume, Cancel (confirm) and Retry step."""
    ready = Signal(object)
    STALL = 60.0

    def __init__(self, parent, variant=None):
        super().__init__(parent, 'Set up the sync engine', 700, 690)
        self.gpu = bootstrap.detect_gpu()
        rec = variant or bootstrap.recommended_variant(self.gpu)
        intro = ('One-time setup. Python, PyTorch and the AI models go into <b>%s</b>. '
                 'Pause any time; it continues where it stopped, also after a restart.' % paths.home())
        self.lay.addWidget(link_label(intro, 'plain'))
        if self.gpu['nvidia']:
            g = 'NVIDIA GPU found: <b>%s</b>%s%s → CUDA build recommended.' % (
                self.gpu['name'] or 'NVIDIA', (' · %g GB VRAM' % self.gpu['vram_gb']) if self.gpu.get('vram_gb') else '',
                (' (driver %s)' % self.gpu['driver']) if self.gpu['driver'] else '')
        else:
            g = 'No NVIDIA GPU found → CPU build (slower: about 1–2 minutes per song).'
        g += ' Whisper model for this hardware: <b>%s</b> (change any time in Engine settings).' % self.tier(rec)
        self.lay.addWidget(link_label(g, 'sub'))
        self.variant = QComboBox()
        for v, label in (('cuda', 'CUDA 12.4 (NVIDIA GPU) + Whisper %s  ·  %.2f GB download'),
                         ('cpu', 'CPU only + Whisper %s  ·  %.2f GB download')):
            self.variant.addItem(label % (self.tier(v), bootstrap.total_size(v, whisper=self.tier(v)) / 1e9), v)
        self.variant.setCurrentIndex(0 if rec == 'cuda' else 1)
        self.variant.currentIndexChanged.connect(lambda _i: self._new_state())
        self.lay.addWidget(self.variant)
        self.bar = GlassProgress()
        self.lay.addWidget(self.bar)
        self.info = QLabel('Ready.')
        self.info.setObjectName('sub')
        self.lay.addWidget(self.info)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(2)
        self.lay.addLayout(self.rows_box)
        self.stall = link_label('', 'hint')
        self.stall.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.stall.linkActivated.connect(lambda _u: self._toggle_log(True))
        self.lay.addWidget(self.stall)
        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(400)
        self.logview.setFixedHeight(120)
        self.logview.hide()
        self.lay.addWidget(self.logview)
        self.lay.addStretch(1)
        row = QHBoxLayout()
        self.btn_log = PillButton('Show log ▾')
        self.btn_log.clicked.connect(lambda: self._toggle_log(not self.logview.isVisible()))
        self.btn_folder = PillButton('Open log folder')
        self.btn_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.home())))
        row.addWidget(self.btn_log)
        row.addWidget(self.btn_folder)
        row.addStretch(1)
        self.btn_retry = PillButton('Retry step', 'primary')
        self.btn_retry.clicked.connect(self.start)
        self.btn_retry.hide()
        self.btn_pause = PillButton('Pause')
        self.btn_pause.clicked.connect(self.pause)
        self.btn_pause.hide()
        self.btn_cancel = PillButton('Cancel')
        self.btn_cancel.clicked.connect(self.cancel_setup)
        self.btn_start = PillButton('Download and install', 'primary')
        self.btn_start.clicked.connect(self.start)
        for b in (self.btn_retry, self.btn_pause, self.btn_cancel, self.btn_start):
            row.addWidget(b)
        self.lay.addLayout(row)
        self.cancel_ev = None
        self.thread = None
        self.error = None
        self.done_state = None
        self._log_n = 0
        self._phase = 0
        self.latency = {}          # step -> max event-loop lateness (ms)
        self.lat_spikes = []       # every lateness > 100 ms, for the CI report
        self._lat_last = None
        self.rows = {}
        self._new_state()
        if self.setup.progress_file().get('done'):
            self.btn_start.setText('Resume setup')
            self.info.setText('An earlier setup was interrupted; it continues at the first unfinished step.')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(100)                 # UI refresh: 10x per second
        self.lat_timer = QTimer(self)
        self.lat_timer.setTimerType(Qt.PreciseTimer)
        self.lat_timer.timeout.connect(self._lat_tick)
        self.lat_timer.start(50)              # event-loop latency probe

    def tier(self, variant):
        """Whisper size this setup installs: by VRAM for CUDA, small on CPU (only that one is downloaded)."""
        forced = os.environ.get('LYRICIST_SYNC_WHISPER_TIER')
        return forced or bootstrap.whisper_tier(self.gpu.get('vram_gb'), variant)

    # -- state
    def _new_state(self):
        if self.thread and self.thread.is_alive():
            return
        v = self.variant.currentData()
        self.setup = bootstrap.Setup(v, whisper=self.tier(v))
        self.state = self.setup.state
        for r in self.rows.values():
            r.setParent(None)
        self.rows = {}
        for sid in self.state.order:
            r = StepRow(self.state.steps[sid]['label'])
            self.rows[sid] = r
            self.rows_box.addWidget(r)
        done = set(self.setup.progress_file().get('done', []))
        for sid in done:
            if sid in self.state.steps and sid != 'check':
                self.state.update(sid, status='done', detail='Done earlier', done=1, total=1)
        self._poll()

    def _lat_tick(self):
        now = time.perf_counter()
        if now < getattr(self, 'lat_mute_until', 0):  # test screenshots/theme switches block on purpose
            self._lat_last = now
            return
        if self._lat_last is not None and self.thread is not None:
            late = (now - self._lat_last) * 1000 - 50
            sid = self.state.current or 'idle'
            if late > 100 and len(self.lat_spikes) < 50:
                self.lat_spikes.append({'step': sid, 'at_s': round(time.time() - self._t0, 1), 'ms': round(late, 1)})
            if late > self.latency.get(sid, 0):
                self.latency[sid] = round(late, 1)
        self._lat_last = now

    def _weights(self):
        w = {}
        for sid, st in self.state.steps.items():
            if sid.startswith('dl_'):
                w[sid] = max(1.0, sum(i['size'] for i in self.setup.step_items(sid)))
        tb = sum(i['size'] for i in self.setup.items if i['kind'] == 'wheel')
        w['install'] = tb * 0.6
        w['verify'] = sum(i['size'] for i in self.setup.items if i['kind'] == 'model') * 0.1
        w['check'] = 1.5e8
        return w

    def _poll(self):
        steps, cur, logs, n = self.state.snapshot(self._log_n)
        self._log_n = n
        if logs and self.logview.isVisible():
            self.logview.appendPlainText('\n'.join(logs[-200:]))
        elif logs:
            self._pending_log = (getattr(self, '_pending_log', []) + logs)[-400:]
        now = time.time()
        self._phase = (self._phase + 36) % 360
        w = self._weights()
        tot = sum(w.values())
        got = 0.0
        for sid, st in steps.items():
            frac = 1.0 if st['status'] == 'done' else ((st['done'] / st['total']) if st['total'] else 0.0)
            if st['status'] == 'running' and st.get('indeterminate') and sid == 'check':
                frac = min(0.9, (now - (st['t0'] or now)) / 40)
            got += w[sid] * min(1.0, frac)
            self.rows[sid].show_state(st, now, self._phase)
        frac = got / tot if tot else 0
        self.bar.set_value(frac)
        running = self.thread is not None and self.thread.is_alive()
        if running:
            el = now - self._t0
            spd = max([st.get('speed') or 0 for st in steps.values()] + [0])
            rem_dl = sum(w[s] * (1 - ((steps[s]['done'] / steps[s]['total']) if steps[s]['total'] else 0))
                         for s in steps if s.startswith('dl_') and steps[s]['status'] != 'done')
            rem = (rem_dl / spd if spd > 0 else None)
            if rem is not None:
                rem += sum({'install': 150 if self.setup.variant == 'cuda' else 60, 'verify': 20, 'check': 30}[s]
                           for s in ('install', 'verify', 'check') if steps[s]['status'] != 'done')
            self.info.setText('Overall %d%% · %s elapsed%s' % (round(frac * 100), _fmt_dur(el),
                                                                (' · about %s left' % _fmt_dur(rem)) if rem else ''))
            st = steps.get(cur) if cur else None
            quiet = now - st['last'] if st else 0
            if st and st['status'] == 'running' and quiet >= self.STALL:
                self.stall.setText('Still working… no new progress for %s (this step: %s elapsed). This can be normal while '
                                   'PyTorch installs. <a href="#log">Show log</a>' % (_fmt_dur(quiet), _fmt_dur(now - (st['t0'] or now))))
            else:
                self.stall.setText('')
        elif self.done_state is None and self.error is None and frac > 0 and frac < 1:
            self.info.setText('Overall %d%% · paused' % round(frac * 100) if self.cancel_ev else self.info.text())

    def _toggle_log(self, on):
        self.logview.setVisible(on)
        self.btn_log.setText('Hide log ▴' if on else 'Show log ▾')
        if on:
            pend = getattr(self, '_pending_log', [])
            if pend:
                self.logview.appendPlainText('\n'.join(pend))
                self._pending_log = []
            self.logview.verticalScrollBar().setValue(self.logview.verticalScrollBar().maximum())

    # -- control
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        if self.error is not None or self.cancel_ev is not None:
            prev = self.state
            v = self.variant.currentData()
            self.setup = bootstrap.Setup(v, state=prev, whisper=self.tier(v))
        self.error = None
        self.cancel_ev = threading.Event()
        self.setup.cancel = self.cancel_ev
        self._t0 = getattr(self, '_t0', None) or time.time()
        self.variant.setEnabled(False)
        for b in (self.btn_start, self.btn_retry):
            b.hide()
        self.btn_pause.setText('Pause')
        self.btn_pause.show()
        self.info.setText('Starting…')
        for sid, st in self.state.steps.items():
            if st['status'] in ('failed', 'paused'):
                self.state.update(sid, status='waiting', error='')

        def work():
            try:
                self._result = ('ok', self.setup.run())
            except bootstrap.Cancelled:
                self._result = ('paused', None)
            except Exception as e:  # shown in the step row, details in setup.log
                self._result = ('failed', str(e))
            self.state.finished = True

        self._result = None
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._check_thread)
        self._watch.start(150)

    def _check_thread(self):
        if self.thread and not self.thread.is_alive():
            self._watch.stop()
            kind, val = self._result or ('failed', 'stopped')
            if kind == 'ok':
                self._done(val)
            elif kind == 'paused':
                self.info.setText('Paused. Press Resume to continue where it stopped.')
                self.btn_pause.setText('Resume')
                self.btn_pause.show()
                self.variant.setEnabled(False)
            else:
                self.error = val
                self.info.setText('A step failed: %s' % (val.splitlines()[0][:160] if val else 'error'))
                self.btn_pause.hide()
                self.btn_retry.show()
                self.variant.setEnabled(True)
            self._poll()

    def pause(self):
        if self.thread and self.thread.is_alive():
            self.cancel_ev.set()
            self.info.setText('Pausing…')
        else:
            self.start()

    def cancel_setup(self):
        if self.done_state is not None:
            self.accept()
            return
        busy = self.thread and self.thread.is_alive()
        if busy or any(st['status'] == 'done' for st in self.state.steps.values()):
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self, 'Cancel setup', 'Stop the setup? Finished steps and downloaded data are kept, '
                                    'so it continues where it stopped next time.') != QMessageBox.Yes:
                return
        if self.cancel_ev:
            self.cancel_ev.set()
        super().reject()

    def _done(self, st):
        self.done_state = st
        self.bar.set_value(1)
        eng = (st or {}).get('engine', {})
        self.info.setText('Done in %s. Engine ready on %s%s.' % (_fmt_dur(time.time() - self._t0), eng.get('device', '?').upper(),
                                                                (' · ' + eng['device_name']) if eng.get('device_name') else ''))
        self.btn_pause.hide()
        self.btn_cancel.hide()
        self.btn_start.setText('Close')
        self.btn_start.show()
        self.btn_start.clicked.disconnect()
        self.btn_start.clicked.connect(self.accept)
        self.ready.emit(st)

    def reject(self):
        self.cancel_setup()


class ConflictDialog(GlassDialog):
    """Files exist: Overwrite / Keep both / Skip (+ apply to all). choice in self.choice."""

    def __init__(self, parent, song_label, existing):
        super().__init__(parent, 'Files already exist', 560, 300)
        self.choice = 'skip'
        names = '<br>'.join('• ' + os.path.basename(p).replace('<', '&lt;') for p in existing[:6])
        more = '<br>…and %d more' % (len(existing) - 6) if len(existing) > 6 else ''
        self.lay.addWidget(link_label('<b>%s</b><br>These files are already in <b>%s</b>:<br>%s%s' % (
            song_label.replace('<', '&lt;'), os.path.dirname(existing[0]).replace('<', '&lt;'), names, more), 'plain'))
        self.lay.addStretch(1)
        self.apply_all = QCheckBox('Do the same for the other songs in this export')
        self.lay.addWidget(self.apply_all)
        row = QHBoxLayout()
        row.addStretch(1)
        for label, key, kind in (('Skip', 'skip', 'ghost'), ('Keep both', 'keep', 'ghost'), ('Overwrite', 'overwrite', 'primary')):
            b = PillButton(label, kind)
            b.setMinimumWidth(104)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            row.addWidget(b)
            setattr(self, 'btn_' + key, b)
        self.lay.addLayout(row)

    def _pick(self, k):
        self.choice = k
        self.accept()

    def reject(self):
        self.choice = 'skip'
        super().reject()


class MusicDialog(GlassDialog):
    """♪ lines in instrumental parts: on/off, shortest gap, symbol, intro/outro."""

    def __init__(self, parent, settings):
        from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel
        from . import instrumental as I
        super().__init__(parent, '♪ in instrumental parts', 520, 330)
        st = I.settings_of(settings)
        self.lay.addWidget(link_label('When nothing is sung for a while (intro, solo, break, outro), a ♪ line is shown '
                                      'instead of the last sung line. It is in every exported format.', 'plain'))
        self.on = QCheckBox('Add ♪ lines automatically')
        self.on.setChecked(bool(st['inst_on']))
        self.lay.addWidget(self.on)
        row = QHBoxLayout()
        row.addWidget(QLabel('Shortest instrumental part'))
        self.gap = QDoubleSpinBox()
        self.gap.setRange(I.GAP_MIN, I.GAP_MAX)
        self.gap.setSingleStep(0.5)
        self.gap.setDecimals(1)
        self.gap.setSuffix(' s')
        self.gap.setValue(float(st['inst_gap']))
        row.addWidget(self.gap)
        row.addStretch(1)
        self.lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Symbol'))
        self.symbol = QComboBox()
        for sym in I.SYMBOLS:
            self.symbol.addItem(sym, sym)
        self.symbol.setCurrentIndex(max(0, self.symbol.findData(st['inst_symbol'])))
        row.addWidget(self.symbol)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.edges = QCheckBox('Also before the first line (intro) and after the last one (outro)')
        self.edges.setChecked(bool(st['inst_edges']))
        self.lay.addWidget(self.edges)
        self.lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = PillButton('Cancel')
        cancel.clicked.connect(self.reject)
        ok = PillButton('Apply', 'primary')
        ok.clicked.connect(self.accept)
        for b in (cancel, ok):
            b.setMinimumWidth(96)
            row.addWidget(b)
        self.lay.addLayout(row)

    def values(self):
        return {'inst_on': self.on.isChecked(), 'inst_gap': round(self.gap.value(), 1),
                'inst_symbol': self.symbol.currentData(), 'inst_edges': self.edges.isChecked()}


class _UpdBridge(QObject):
    checked = Signal(object)
    progress = Signal(float, float, float)
    downloaded = Signal(str)
    failed = Signal(str)


class UpdateDialog(GlassDialog):
    """Current/latest version, notes, Update now / Later / Skip this version;
    'You're up to date' + Check again; friendly offline/404 messages."""

    def __init__(self, parent, app, result=None):
        super().__init__(parent, 'Updates', 600, 440)
        self.app = app
        self.br = _UpdBridge()
        self.br.checked.connect(self.show_result)
        self.br.progress.connect(self._progress)
        self.br.downloaded.connect(self._downloaded)
        self.br.failed.connect(self._failed)
        self.cancel_ev = threading.Event()
        self.thread = None
        self.result = None
        self.installer = None
        self.head = link_label('', 'plain')
        self.lay.addWidget(self.head)
        self.versions = link_label('', 'sub')
        self.lay.addWidget(self.versions)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(150)
        self.lay.addWidget(self.notes, 1)
        self.bar = GlassProgress()
        self.bar.hide()
        self.lay.addWidget(self.bar)
        self.info = QLabel('')
        self.info.setObjectName('hint')
        self.info.setWordWrap(True)
        self.lay.addWidget(self.info)
        self.auto = QCheckBox('Check for updates automatically (once a day)')
        self.auto.setChecked(bool(app.settings.get('update_check', True)))
        self.auto.toggled.connect(lambda v: (app.settings.__setitem__('update_check', bool(v)), app.save_settings()))
        self.lay.addWidget(self.auto)
        row = QHBoxLayout()
        self.btn_skip = PillButton('Skip this version')
        self.btn_skip.clicked.connect(self.skip)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        self.btn_later = PillButton('Later')
        self.btn_later.clicked.connect(self.reject)
        self.btn_check = PillButton('Check again')
        self.btn_check.clicked.connect(self.check)
        self.btn_now = PillButton('Update now', 'primary')
        self.btn_now.clicked.connect(self.update_now)
        for b in (self.btn_later, self.btn_check, self.btn_now):
            row.addWidget(b)
        self.lay.addLayout(row)
        if result is not None:
            self.show_result(result)
        else:
            self.check()

    def _set_buttons(self, state):
        self.btn_now.setVisible(state in ('available', 'failed_dl'))
        self.btn_skip.setVisible(state == 'available')
        self.btn_later.setVisible(state in ('available', 'failed_dl', 'downloading'))
        self.btn_check.setVisible(state in ('current', 'error', 'checking'))
        self.btn_check.setEnabled(state != 'checking')
        self.btn_later.setText('Cancel' if state == 'downloading' else 'Later')

    def check(self, sync=False):
        self.head.setText('<span style="font-size:15px;font-weight:600">Checking for updates…</span>')
        self.versions.setText('Installed: v%s' % meta.VERSION)
        self.notes.hide()
        self.info.setText('')
        self._set_buttons('checking')
        url = updater.manifest_url(self.app.settings)

        def work():
            self.br.checked.emit(updater.check(meta.VERSION, url))
        if sync:
            work()
            return
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def show_result(self, r):
        self.result = r
        self.app.update_result(r)
        self.bar.hide()
        st = r['status']
        m = r.get('manifest') or {}
        if st == 'available':
            self.head.setText('<span style="font-size:15px;font-weight:600">Version %s is available</span>' % m['version'])
            self.versions.setText('Installed: v%s &nbsp;·&nbsp; Latest: v%s%s &nbsp;·&nbsp; %.1f MB' % (
                meta.VERSION, m['version'], (' (%s)' % m['date']) if m.get('date') else '', m['size'] / 1e6))
            self.notes.setMarkdown(m.get('notes') or 'No release notes.')
            self.notes.show()
            self.info.setText('The installer is checked against its SHA256 before it runs. Your settings, the engine and '
                              'the AI models stay in place, so nothing is downloaded again.')
            self._set_buttons('available')
        elif st == 'current':
            self.head.setText("<span style='font-size:15px;font-weight:600'>You're up to date</span>")
            self.versions.setText('Installed: v%s%s' % (meta.VERSION, (' &nbsp;·&nbsp; Latest: v%s' % m['version']) if m else ''))
            self.notes.hide()
            self.info.setText(r.get('message', '') if r.get('message') and "up to date" not in r['message'] else '')
            self._set_buttons('current')
        else:
            self.head.setText('<span style="font-size:15px;font-weight:600">%s</span>' % {
                'offline': "Couldn't check for updates", 'notfound': 'No update information yet',
                'insecure': 'Update address not allowed', 'invalid': 'Update information not readable'}.get(st, 'Update check failed'))
            self.versions.setText('Installed: v%s' % meta.VERSION)
            self.notes.hide()
            self.info.setText(r.get('message', ''))
            self._set_buttons('error')

    def skip(self):
        m = (self.result or {}).get('manifest') or {}
        if m:
            self.app.settings['update_skip'] = m['version']
            self.app.save_settings()
            self.app.update_result({'status': 'current', 'manifest': m})
        self.reject()

    def update_now(self):
        m = (self.result or {}).get('manifest')
        if not m or (self.thread and self.thread.is_alive()):
            return
        self.cancel_ev = threading.Event()
        self.bar.set_value(0)
        self.bar.show()
        self.info.setText('Downloading v%s…' % m['version'])
        self._set_buttons('downloading')

        def work():
            try:
                self.br.downloaded.emit(updater.download(m, lambda d, t, s: self.br.progress.emit(d, t, s), self.cancel_ev))
            except updater.Cancelled:
                self.br.failed.emit('Download paused. Press Update now to resume where it stopped.')
            except updater.UpdateError as e:
                self.br.failed.emit(str(e))
            except Exception as e:  # never crash the app over an update
                self.br.failed.emit('The update failed: %s' % e)
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def _progress(self, done, total, spd):
        self.bar.set_value(done / total if total else 0)
        self.info.setText('%.1f of %.1f MB%s' % (done / 1e6, total / 1e6, (' · %.1f MB/s' % (spd / 1e6)) if spd else ''))

    def _failed(self, msg):
        self.info.setText(msg)
        self._set_buttons('failed_dl')

    def _downloaded(self, path):
        self.installer = path
        self.bar.set_value(1)
        self.info.setText('SHA256 verified. Installing; the app closes and starts again by itself…')
        if getattr(self.app, 'update_no_install', False):
            self.accept()
            return
        if not self.app.confirm_close('update'):
            self.info.setText('The installer is ready. The update was not installed because some lyrics are not saved. Press Update now to try again.')
            self._set_buttons('failed_dl')
            return
        try:
            updater.run_installer(path, relaunch=True)
        except Exception as e:
            self._failed('Could not start the installer: %s' % e)
            return
        self.app.quit_for_update()

    def reject(self):
        if self.thread and self.thread.is_alive():
            self.cancel_ev.set()
        super().reject()


class EngineDialog(GlassDialog):
    """Engine settings: detected hardware, the Whisper model (Auto = by VRAM, or a fixed size) with
    size/speed/accuracy hints, on-demand download of another size (same per-step progress, resume
    and SHA256 check as the setup) and deleting sizes that are not used."""
    HINT = {'small': 'fastest, fine on CPU', 'medium': 'more accurate, needs ~5 GB VRAM for speed',
            'large-v3-turbo': 'near large-v3 accuracy, much faster', 'large-v3': 'most accurate, needs ~10 GB VRAM'}

    def __init__(self, parent, app, download=None):
        super().__init__(parent, 'Engine settings', 660, 560)
        self.app = app
        self.hw = app.hardware()
        self.models = bootstrap.whisper_models()
        self.dl = None
        self.thread = None
        self._result = None
        hw = self.hw
        if hw['variant'] == 'cuda':
            h = 'GPU: <b>%s</b>%s · CUDA build · Whisper runs in fp16' % (
                hw['gpu'] or 'NVIDIA GPU', (' · %g GB VRAM' % hw['vram_gb']) if hw['vram_gb'] else '')
        else:
            h = 'CPU: <b>%s</b> · CPU build · Whisper runs in fp32' % (hw['cpu'] or 'this PC')
        self.lay.addWidget(link_label('<b>Detected hardware</b><br>' + h, 'plain'))
        self.lay.addWidget(link_label('Recommended for this hardware: <b>Whisper %s</b>  (CPU or under 6 GB → small · 6–11 GB → medium · '
                                      '12–23 GB → large-v3-turbo · 24 GB and up → large-v3). Demucs and the MMS aligner are the same '
                                      'on every tier.' % hw['tier'], 'sub'))
        self.current = link_label('', 'plain')
        self.lay.addWidget(self.current)
        self.lay.addWidget(link_label('<b>Whisper model</b> (Transcribe and repeat detection)', 'plain'))
        self.combo = QComboBox()
        self.lay.addWidget(self.combo)
        self.hint = link_label('', 'sub')
        self.lay.addWidget(self.hint)
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(4)
        self.lay.addLayout(self.list_box)
        self.bar = GlassProgress()
        self.bar.hide()
        self.lay.addWidget(self.bar)
        self.rows = {}
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(2)
        self.lay.addLayout(self.rows_box)
        self.info = link_label('', 'sub')
        self.lay.addWidget(self.info)
        self.lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_pause = PillButton('Pause')
        self.btn_pause.clicked.connect(self.pause)
        self.btn_pause.hide()
        self.btn_dl = PillButton('Download', 'primary')
        self.btn_dl.clicked.connect(lambda: self.download(self._wanted()))
        self.btn_close = PillButton('Close')
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_pause, self.btn_dl, self.btn_close):
            row.addWidget(b)
        self.lay.addLayout(row)
        self._fill()
        self.combo.currentIndexChanged.connect(self._picked)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(100)
        if download:
            i = self.combo.findData(download)
            if i >= 0:
                self.combo.setCurrentIndex(i)
            QTimer.singleShot(0, lambda: self.download(download))

    # -- view
    def _fill(self):
        inst = bootstrap.whisper_installed()
        choice = self.app.settings.get('whisper_model') or 'auto'
        self.combo.blockSignals(True)
        self.combo.clear()
        tier = self.hw['tier']
        self.combo.addItem('Auto (by hardware) → %s%s' % (tier, '' if tier in inst else ' · not downloaded yet'), 'auto')
        for n, m in self.models.items():
            self.combo.addItem('%s  ·  %.2f GB  ·  speed: %s  ·  accuracy: %s%s' % (
                n, m['size'] / 1e9, m['speed'], m['accuracy'], '  ·  ✓ installed' if n in inst else ''), n)
        self.combo.setCurrentIndex(max(0, self.combo.findData(choice)))
        self.combo.blockSignals(False)
        eff = self.app.whisper_effective()
        prec = 'fp16 on CUDA' if self.hw['variant'] == 'cuda' else 'fp32 on CPU'
        note = ''
        want = tier if choice == 'auto' else choice
        if want != eff:
            note = ' <span style="color:%s">(Whisper %s is not downloaded; using the best installed one)</span>' % (AMBER, want)
        self.current.setText('In use: <b>Whisper %s</b> · %s%s' % (eff, prec, note))
        for i in reversed(range(self.list_box.count())):
            w = self.list_box.itemAt(i).widget()
            if w:
                w.setParent(None)
        for n in inst:
            r = QWidget()
            h = QHBoxLayout(r)
            h.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel('Installed: Whisper %s · %.2f GB%s' % (n, self.models[n]['size'] / 1e9, '  · in use' if n == eff else ''))
            lbl.setObjectName('sub')
            h.addWidget(lbl, 1)
            b = PillButton('Delete')
            b.setEnabled(n != eff and len(inst) > 1)
            b.setToolTip('In use' if n == eff else 'Free %.2f GB' % (self.models[n]['size'] / 1e9))
            b.clicked.connect(lambda _c=False, n=n: self.delete(n))
            h.addWidget(b)
            self.list_box.addWidget(r)
        self._picked()

    def _wanted(self):
        c = self.combo.currentData()
        return self.hw['tier'] if c == 'auto' else c

    def _picked(self, *_a):
        want = self._wanted()
        m = self.models.get(want)
        inst = bootstrap.whisper_installed()
        busy = self.thread is not None and self.thread.is_alive()
        if m:
            self.hint.setText('Whisper %s: %s. %.2f GB download, %s.' % (
                want, self.HINT.get(want, ''), m['size'] / 1e9, 'installed' if want in inst else 'not downloaded yet'))
        self.btn_dl.setVisible(want not in inst and not busy)
        self.btn_dl.setText('Download Whisper %s (%.2f GB)' % (want, m['size'] / 1e9) if m else 'Download')
        if not busy and (want in inst or self.combo.currentData() == 'auto'):
            self._apply()

    def _apply(self):
        c = self.combo.currentData()
        if self.app.settings.get('whisper_model') != c:
            self.app.settings['whisper_model'] = c
            self.app.save_settings()
        eff = self.app.whisper_effective()
        self.info.setText('Saved. The next Transcribe / Auto-sync uses Whisper %s.' % eff if c else '')

    # -- actions
    def delete(self, name):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, 'Delete model', 'Delete Whisper %s (%.2f GB)? You can download it again any time.' % (
                name, self.models[name]['size'] / 1e9)) != QMessageBox.Yes:
            return
        try:
            freed = bootstrap.delete_whisper(name, self.app.whisper_effective())
            self.info.setText('Deleted Whisper %s (%.2f GB freed).' % (name, freed / 1e9))
        except Exception as e:
            self.info.setText(str(e))
        self._fill()

    def download(self, name):
        if self.thread and self.thread.is_alive() or name not in self.models:
            return
        prev = self.dl.state if (self.dl and self.dl.name == name) else None
        self.dl = bootstrap.ModelDownload(name, state=prev)
        st = self.dl.state
        for sid, st_ in st.steps.items():
            if st_['status'] in ('failed', 'paused'):
                st.update(sid, status='waiting', error='')
        if not self.rows or prev is None:
            for r in self.rows.values():
                r.setParent(None)
            self.rows = {}
            for sid in st.order:
                self.rows[sid] = StepRow(st.steps[sid]['label'])
                self.rows_box.addWidget(self.rows[sid])
        self.bar.show()
        self.btn_dl.hide()
        self.btn_pause.setText('Pause')
        self.btn_pause.show()
        self.combo.setEnabled(False)
        self._t0 = time.time()

        def work():
            try:
                self._result = ('ok', self.dl.run())
            except bootstrap.Cancelled:
                self._result = ('paused', None)
            except Exception as e:
                self._result = ('failed', str(e))

        self._result = None
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def pause(self):
        if self.thread and self.thread.is_alive():
            self.dl.cancel.set()
            self.info.setText('Pausing…')
        elif self.dl:
            self.download(self.dl.name)

    def _poll(self):
        if not self.dl:
            return
        steps, _cur, _l, _n = self.dl.state.snapshot(10 ** 9)
        now = time.time()
        tot = got = 0.0
        for sid, st in steps.items():
            w = 1.0 if sid == 'dl_whisper' else 0.08
            frac = 1.0 if st['status'] == 'done' else ((st['done'] / st['total']) if st['total'] else 0.0)
            tot += w
            got += w * min(1.0, frac)
            self.rows[sid].show_state(st, now, int(now * 360) % 360)
        self.bar.set_value(got / tot if tot else 0)
        if self.thread is not None and not self.thread.is_alive() and self._result is not None:
            kind, val = self._result
            self._result = None
            self.combo.setEnabled(True)
            if kind == 'ok':
                self.btn_pause.hide()
                self.info.setText('Whisper %s downloaded and verified.' % val)
                self._fill()
                self._apply()
            elif kind == 'paused':
                self.btn_pause.setText('Resume')
                self.info.setText('Paused. Resume continues where it stopped (also after closing the app).')
            else:
                self.btn_pause.setText('Retry')
                self.info.setText('Download failed: %s' % (val or '')[:200])

    def reject(self):
        if self.thread and self.thread.is_alive():
            self.dl.cancel.set()
            self.thread.join(3)
        super().reject()


def fmt_edit_time(t):
    """mm:ss.xxx for the time fields of the Edit Line dialog and the inline editor."""
    ms = int(round(max(0.0, t) * 1000))
    return '%02d:%02d.%03d' % (ms // 60000, (ms % 60000) // 1000, ms % 1000)


def words_changed(a, b):
    """Share of words that differ between two versions of a line (0..1)."""
    import difflib
    wa, wb = a.lower().split(), b.lower().split()
    if not wa and not wb:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, wa, wb).ratio()


class EditLineDialog(GlassDialog):
    """Edit Line…: the words, Start and End (mm:ss.xxx with ±0.1 / ±0.01), Play line, Re-align.
    Enter saves, Esc cancels. After exec(): values() -> (text, start, end, realign), or
    self.split_cursor (int) when "Split at cursor" was pressed."""
    REALIGN_AT = 0.4    # this share of the words changed: Re-align is ticked for you

    def __init__(self, parent, line, number, play=None, can_realign=True):
        from PySide6.QtWidgets import QGridLayout, QLineEdit
        from .formats import parse_time
        super().__init__(parent, 'Edit line %d' % number, 600, 330)
        self._parse = parse_time
        self.line = line
        self.play = play
        self.split_cursor = None
        self._auto_realign = True
        self.lay.addWidget(link_label('The words and times of this line. Saving updates the lyrics box, the waveform '
                                      'and the exported files. <b>Enter</b> saves, <b>Esc</b> cancels.', 'plain'))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(10)
        lab = QLabel('Line')
        lab.setObjectName('sub')
        grid.addWidget(lab, 0, 0)
        self.text = QLineEdit(line['text'])
        self.text.setObjectName('editText')
        self.text.setPlaceholderText('The words of this line')
        self.text.textChanged.connect(self._text_changed)
        grid.addWidget(self.text, 0, 1, 1, 6)
        self.fields = {}
        for r, (key, label) in enumerate((('start', 'Start'), ('end', 'End')), start=1):
            lab = QLabel(label)
            lab.setObjectName('sub')
            grid.addWidget(lab, r, 0)
            f = QLineEdit(fmt_edit_time(line[key]))
            f.setFixedWidth(108)
            f.setAlignment(Qt.AlignCenter)
            f.setToolTip('mm:ss.xxx (also ss.xx or m:ss)')
            f.textChanged.connect(self._validate)
            self.fields[key] = f
            grid.addWidget(f, r, 1)
            for c, (txt, d) in enumerate((('−0.1', -0.1), ('−0.01', -0.01), ('+0.01', 0.01), ('+0.1', 0.1)), start=2):
                b = PillButton(txt)
                b.setFixedWidth(58)
                b.setAutoDefault(False)
                b.setToolTip('%s %+g s' % (label, d))
                b.clicked.connect(lambda _=False, k=key, d=d: self._nudge(k, d))
                grid.addWidget(b, r, c)
        grid.setColumnStretch(6, 1)
        self.lay.addLayout(grid)
        row = QHBoxLayout()
        self.btn_play = PillButton('▶  Play line')
        self.btn_play.setAutoDefault(False)
        self.btn_play.setToolTip('Play this line from Start to End')
        self.btn_play.clicked.connect(self._play)
        self.btn_play.setEnabled(play is not None)
        self.btn_split = PillButton('Split at cursor')
        self.btn_split.setAutoDefault(False)
        self.btn_split.setToolTip('Split the line where the text cursor is (the time is divided by the characters)')
        self.btn_split.clicked.connect(self._split)
        row.addWidget(self.btn_play)
        row.addWidget(self.btn_split)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.realign = QCheckBox('Re-align this line after saving (fixes the timing after big word changes)')
        self.realign.setEnabled(can_realign)
        self.realign.toggled.connect(lambda _v: setattr(self, '_auto_realign', False))
        self.lay.addWidget(self.realign)
        self.err = QLabel('')
        self.err.setObjectName('hint')
        self.err.setStyleSheet('color: %s;' % AMBER)
        self.lay.addWidget(self.err)
        self.lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = PillButton('Cancel')
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = PillButton('Save', 'primary')
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._save)
        for b in (self.btn_cancel, self.btn_save):
            b.setMinimumWidth(96)
            row.addWidget(b)
        self.lay.addLayout(row)
        self.text.setFocus()
        self.text.selectAll()

    def _time(self, key):
        return self._parse(self.fields[key].text())

    def _validate(self, *_a):
        s, e = self._time('start'), self._time('end')
        msg = ''
        if not self.text.text().strip():
            msg = 'The line needs at least one word.'
        elif s is None or e is None:
            msg = 'Times are mm:ss.xxx, for example 01:02.345.'
        elif e <= s:
            msg = 'End must be after Start.'
        self.err.setText(msg)
        self.btn_save.setEnabled(not msg)
        return not msg

    def _text_changed(self, t):
        if self._auto_realign and self.realign.isEnabled():
            self.realign.blockSignals(True)
            self.realign.setChecked(words_changed(self.line['text'], t) >= self.REALIGN_AT)
            self.realign.blockSignals(False)
        self._validate()

    def _nudge(self, key, d):
        t = self._time(key)
        if t is not None:
            self.fields[key].setText(fmt_edit_time(t + d))

    def _play(self):
        s, e = self._time('start'), self._time('end')
        if self.play and s is not None and e is not None:
            self.play(s, max(e, s + 0.1))

    def _split(self):
        if self._validate():
            self.split_cursor = self.text.cursorPosition()
            self.accept()

    def _save(self):
        if self._validate():
            self.accept()

    def values(self):
        return (self.text.text().strip(), self._time('start'), self._time('end'),
                self.realign.isChecked() and self.realign.isEnabled())


class KeepEditsDialog(GlassDialog):
    """Transcribe / Auto-sync would replace lines edited by hand: Keep my edits / Replace."""

    def __init__(self, parent, songs, action):
        super().__init__(parent, 'Replace your edits?', 560, 270)
        self.choice = 'keep'
        names = ', '.join('“%s”' % s.label() for s in songs[:3]) + (' and %d more' % (len(songs) - 3) if len(songs) > 3 else '')
        what = ('Transcribe replaces the lines, words and times with what Whisper hears.' if action == 'transcribe' else
                'Auto-sync re-aligns every line with the words in the lyrics box (your edited words are kept there), '
                'but the times you set by hand are replaced.')
        self.lay.addWidget(link_label('You edited the lines of %s in the review list.<br><br>%s<br><br>'
                                      'Either way you can undo it with <b>Ctrl+Z</b>.' % (names.replace('<', '&lt;'), what), 'plain'))
        self.lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_keep = PillButton('Keep my edits')
        self.btn_keep.clicked.connect(self.reject)
        self.btn_replace = PillButton('Replace', 'primary')
        self.btn_replace.clicked.connect(self._replace)
        for b in (self.btn_keep, self.btn_replace):
            b.setMinimumWidth(120)
            row.addWidget(b)
        self.btn_keep.setDefault(True)
        self.lay.addLayout(row)

    def _replace(self):
        self.choice = 'replace'
        self.accept()

    def reject(self):
        self.choice = 'keep'
        super().reject()


RED = '#ff5d5d'


def _esc(t):
    return str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def export_summary(report):
    """'12 files saved for 3 songs' (+ skipped / failed counts) from App.last_export."""
    ok = [e for e in report if e['status'] == 'ok']
    n = sum(len(e['files']) for e in ok)
    txt = '%d file%s saved for %d song%s' % (n, '' if n == 1 else 's', len(ok), '' if len(ok) == 1 else 's')
    sk = sum(1 for e in report if e['status'] == 'skipped')
    fa = sum(1 for e in report if e['status'] == 'failed')
    if sk:
        txt += ' · %d skipped' % sk
    if fa:
        txt += ' · %d failed' % fa
    return txt


def export_details_html(report):
    rows = []
    for e in report:
        head = '<b>%s</b>' % _esc(e['label'])
        if e['status'] == 'ok':
            files = ''.join('<div style="margin-left:14px">• %s</div>' % _esc(os.path.basename(f)) for f in e['files'])
            rows.append('%s — %d file%s<br><span style="opacity:.75">%s</span>%s' % (
                head, len(e['files']), '' if len(e['files']) == 1 else 's', _esc(e['dir']), files))
        elif e['status'] == 'skipped':
            rows.append('%s<br><span style="color:%s">⚠ Skipped: %s</span>%s' % (
                head, AMBER, _esc(e['reason']), ('<br><span style="opacity:.75">%s</span>' % _esc(e['dir'])) if e.get('dir') else ''))
        else:
            rows.append('%s<br><span style="color:%s">✕ Failed: %s</span>%s' % (
                head, RED, _esc(e['reason']), ('<br><span style="opacity:.75">%s</span>' % _esc(e['dir'])) if e.get('dir') else ''))
    return '<div style="line-height:135%">' + '<div style="height:8px"></div>'.join(rows) + '</div>'


class ExportDoneDialog(GlassDialog):
    """After Export: what was written where (full folder paths), skipped / failed songs in amber /
    red with the reason; Open folder and OK. Stays until dismissed (not modal)."""

    def __init__(self, parent, report, closing=False):
        problems = any(e['status'] != 'ok' for e in report)
        title = ('Not closed: some lyrics were not saved' if closing else
                 'Export finished with problems' if problems else 'Export finished')
        super().__init__(parent, title, 620, 420)
        self.setModal(False)
        self.report = report
        self.folders = []
        for e in report:
            if e['status'] == 'ok' and e['dir'] and e['dir'] not in self.folders:
                self.folders.append(e['dir'])
        self.summary = QLabel(('<span style="color:%s">●</span> ' % ('#3ecf8e' if not problems else AMBER)) + export_summary(report))
        self.summary.setObjectName('h2')
        self.summary.setTextFormat(Qt.RichText)
        self.lay.addWidget(self.summary)
        if closing:
            self.lay.addWidget(link_label('The window stays open so nothing is lost. Fix the problem below (or use '
                                          '<b>Close without saving</b>) and close again.', 'plain'))
        self.details = QTextBrowser()
        self.details.setObjectName('exportList')
        self.details.setOpenLinks(False)
        self.details.setHtml(export_details_html(report))
        multi = len(report) > 1
        self.btn_toggle = PillButton('Hide files ▴' if not multi or problems else 'Show files ▾')
        self.btn_toggle.setAutoDefault(False)
        self.btn_toggle.clicked.connect(self._toggle)
        self.btn_toggle.setVisible(multi)
        self.lay.addWidget(self.btn_toggle, 0, Qt.AlignLeft)
        self.lay.addWidget(self.details, 1)
        self.details.setVisible(not multi or problems)
        self.spacer = QWidget()
        self.lay.addWidget(self.spacer, 1)
        self.spacer.setVisible(not self.details.isVisible())
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_open = PillButton('Open folder')
        self.btn_open.setAutoDefault(False)
        self.btn_open.setEnabled(bool(self.folders))
        self.btn_open.setToolTip('\n'.join(self.folders))
        self.btn_open.clicked.connect(self._open)
        self.btn_ok = PillButton('OK', 'primary')
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        for b in (self.btn_open, self.btn_ok):
            b.setMinimumWidth(110)
            row.addWidget(b)
        self.lay.addLayout(row)

    def _toggle(self):
        v = not self.details.isVisible()
        self.details.setVisible(v)
        self.spacer.setVisible(not v)
        self.btn_toggle.setText('Hide files ▴' if v else 'Show files ▾')

    def _open(self):
        if len(self.folders) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.folders[0]))
            return
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        for d in self.folders:
            m.addAction(d, lambda d=d: QDesktopServices.openUrl(QUrl.fromLocalFile(d)))
        m.exec(self.btn_open.mapToGlobal(self.btn_open.rect().bottomLeft()))


class AskDialog(GlassDialog):
    """A glass question with custom buttons [(label, key, kind)]; Esc / ✕ = `cancel_key`."""

    def __init__(self, parent, title, html, buttons, cancel_key='cancel', w=560, h=300, items=None):
        super().__init__(parent, title, w, h)
        self.choice = cancel_key
        self.cancel_key = cancel_key
        self.lay.addWidget(link_label(html, 'plain'))
        if items:
            lst = QTextBrowser()
            lst.setObjectName('askList')
            lst.setHtml('<div style="line-height:140%">' + '<br>'.join(
                '<span style="color:%s">●</span> %s' % (ACCENT, _esc(i)) for i in items) + '</div>')
            lst.setMaximumHeight(min(160, 34 + 24 * len(items)))
            self.lay.addWidget(lst)
        self.lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons = {}
        for label, key, kind in buttons:
            b = PillButton(label, kind)
            b.setMinimumWidth(120)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            row.addWidget(b)
            self.buttons[key] = b
            if kind == 'primary':
                b.setDefault(True)
        self.lay.addLayout(row)

    def _pick(self, k):
        self.choice = k
        self.accept()

    def reject(self):
        self.choice = self.cancel_key
        super().reject()


def unsaved_dialog(parent, songs, action='close'):
    n = len(songs)
    when = 'before the update restarts the app' if action == 'update' else 'before you close'
    return AskDialog(parent, 'Unsaved lyrics',
                     '<span style="font-size:15px;font-weight:600">You have unsaved lyrics for %d song%s</span><br>'
                     'These songs were synced, transcribed or edited but not exported yet. Export them %s, or they are lost.'
                     % (n, '' if n == 1 else 's', when),
                     [('Cancel', 'cancel', 'ghost'), ('Close without saving', 'discard', 'danger'),
                      ('Export all & close', 'export', 'primary')], w=600, h=330 + min(5, n) * 10,
                     items=[s.label() for s in songs])


def remove_dialog(parent, songs):
    n = len(songs)
    return AskDialog(parent, 'Remove unsaved song%s?' % ('' if n == 1 else 's'),
                     '%s not exported yet. Removing %s from the library loses the synced lines.' % (
                         ('<b>%s</b> is' % _esc(songs[0].label())) if n == 1 else '<b>%d songs</b> are' % n,
                         'it' if n == 1 else 'them'),
                     [('Cancel', 'cancel', 'ghost'), ('Remove', 'remove', 'danger')], w=540, h=250,
                     items=[s.label() for s in songs] if n > 1 else None)
