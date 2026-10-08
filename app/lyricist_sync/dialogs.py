"""Frameless glass dialogs: About and the first-run engine setup."""
import importlib
import os
import threading
import time

from PySide6.QtCore import QObject, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout

from . import bootstrap, paths, winfx
from .widgets import GlassProgress, PillButton, STATE

meta = importlib.import_module(__package__)


class GlassDialog(QDialog):
    def __init__(self, parent, title, w=560, h=380):
        super().__init__(parent)
        self.theme = parent.theme
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.resize(w, h)
        self._drag = None
        self._backdrop = 'gradient'
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(26, 18, 26, 20)
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
            if winfx.build() >= 22000 and winfx.set_mica(hwnd, self.theme.dark):
                self._backdrop = 'mica'
            elif winfx.set_acrylic(hwnd, 0xB0141820 if self.theme.dark else 0xC8F4F6FA):
                self._backdrop = 'acrylic'
                winfx.set_round_region(hwnd, self.width(), self.height(), 16)

    def paintEvent(self, _e):
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)
        if self._backdrop == 'gradient':
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0, QColor(t.bg_top))
            g.setColorAt(1, QColor(t.bg_bottom))
            p.fillPath(path, QBrush(g))
        else:
            p.fillPath(path, t.qcolor(t.tint))
        g2 = QLinearGradient(0, 0, self.width() * 0.6, self.height() * 0.7)
        c = QColor(*t.glow1)
        g2.setColorAt(0, c)
        c2 = QColor(c)
        c2.setAlpha(0)
        g2.setColorAt(1, c2)
        p.fillPath(path, QBrush(g2))
        p.setPen(QPen(QColor(255, 255, 255, 50 if t.dark else 210), 1))
        p.drawPath(path)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 56:
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


class _Bridge(QObject):
    progress = Signal(float, float, str, float)
    status = Signal(str)
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)


class SetupDialog(GlassDialog):
    """Downloads and installs the engine (resumable). Emits ready(state) when done."""
    ready = Signal(object)

    def __init__(self, parent):
        super().__init__(parent, 'Set up the sync engine', 640, 430)
        self.gpu = bootstrap.detect_gpu()
        rec = bootstrap.recommended_variant(self.gpu)
        intro = ('First run only. The app downloads Python, PyTorch and the AI models into<br><b>%s</b>.<br>'
                 'Downloads resume where they stopped if the connection drops or you pause.' % paths.home())
        self.lay.addWidget(link_label(intro, 'plain'))
        if self.gpu['nvidia']:
            g = 'NVIDIA GPU found: <b>%s</b>%s → CUDA build recommended.' % (
                self.gpu['name'] or 'NVIDIA', (' (driver %s)' % self.gpu['driver']) if self.gpu['driver'] else '')
        else:
            g = 'No NVIDIA GPU found → CPU build (slower: about 1–2 minutes per song).'
        self.lay.addWidget(link_label(g, 'plain'))
        self.variant = QComboBox()
        for v, label in (('cuda', 'CUDA 12.4 (NVIDIA GPU)  ·  %.2f GB download'), ('cpu', 'CPU only  ·  %.2f GB download')):
            self.variant.addItem(label % (bootstrap.total_size(v) / 1e9), v)
        self.variant.setCurrentIndex(0 if rec == 'cuda' else 1)
        self.lay.addWidget(self.variant)
        self.bar = GlassProgress()
        self.lay.addWidget(self.bar)
        self.info = QLabel('Ready to download.')
        self.info.setObjectName('sub')
        self.lay.addWidget(self.info)
        self.file_lbl = QLabel('')
        self.file_lbl.setObjectName('hint')
        self.lay.addWidget(self.file_lbl)
        self.lay.addStretch(1)
        row = QHBoxLayout()
        self.btn_log = PillButton('Open log')
        self.btn_log.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(paths.home(), 'setup.log'))))
        row.addWidget(self.btn_log)
        row.addStretch(1)
        self.btn_pause = PillButton('Pause')
        self.btn_pause.clicked.connect(self.pause)
        self.btn_pause.hide()
        self.btn_start = PillButton('Download and install', 'primary')
        self.btn_start.clicked.connect(self.start)
        row.addWidget(self.btn_pause)
        row.addWidget(self.btn_start)
        self.lay.addLayout(row)
        self.cancel_ev = None
        self.thread = None
        self.br = _Bridge()
        self.br.progress.connect(self._progress)
        self.br.status.connect(self.info.setText)
        self.br.log.connect(lambda s: self.file_lbl.setText(s[9:][:110]))
        self.br.done.connect(self._done)
        self.br.failed.connect(self._failed)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        v = self.variant.currentData()
        self.cancel_ev = threading.Event()
        self._t0 = time.time()
        self.variant.setEnabled(False)
        self.btn_start.hide()
        self.btn_pause.show()
        self.info.setText('Starting…')

        def work():
            try:
                st = bootstrap.Setup(v, on_progress=lambda d, t, it, spd: self.br.progress.emit(d, t, it.get('label', ''), spd),
                                     on_status=self.br.status.emit, on_log=self.br.log.emit, cancel=self.cancel_ev).run()
                self.br.done.emit(st)
            except bootstrap.Cancelled:
                self.br.failed.emit('Paused. Press Resume to continue where it stopped.')
            except Exception as e:  # shown to the user, details in setup.log
                self.br.failed.emit(str(e))

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def pause(self):
        if self.cancel_ev:
            self.cancel_ev.set()
            self.info.setText('Pausing…')

    def _progress(self, done, total, label, spd):
        self.bar.set_value(done / total if total else 0)
        eta = ''
        if spd > 0:
            sec = (total - done) / spd
            eta = ' · about %d min left' % max(1, round(sec / 60)) if sec > 60 else ' · less than a minute left'
        self.info.setText('%.2f of %.2f GB · %s%s' % (done / 1e9, total / 1e9, ('%.1f MB/s' % (spd / 1e6)) if spd else '', eta))
        self.file_lbl.setText(label)

    def _done(self, st):
        self.bar.set_value(1)
        eng = st.get('engine', {})
        self.info.setText('Done. Engine ready on %s%s.' % (eng.get('device', '?').upper(),
                                                          (' · ' + eng['device_name']) if eng.get('device_name') else ''))
        self.btn_pause.hide()
        self.btn_start.setText('Close')
        self.btn_start.show()
        self.btn_start.clicked.disconnect()
        self.btn_start.clicked.connect(self.accept)
        self.ready.emit(st)

    def _failed(self, msg):
        self.info.setText(msg)
        self.variant.setEnabled(True)
        self.btn_pause.hide()
        self.btn_start.setText('Resume')
        self.btn_start.show()

    def reject(self):
        self.pause()
        super().reject()
