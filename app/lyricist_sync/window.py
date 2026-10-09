"""The main window: frameless rounded 'liquid glass' shell, custom title bar, the song
queue, lyrics, review list and footer."""
import os

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QDesktopServices, QFont, QIcon, QKeySequence, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QShortcut)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QTableWidget, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSizePolicy, QSpacerItem, QTableWidgetItem,
                               QAbstractSpinBox, QTextEdit, QVBoxLayout, QWidget)

import importlib
from . import chrome, instrumental, paths, theme as thememod, winfx
from .player import INST, AudioCache, Waveform, fmt_clock
from .chrome import MARGIN, RADIUS
from .export import SAVE_MODES, export_song, read_tags, target_dir  # noqa: F401  (re-exported for the CLI)
from .formats import fmt_lrc_time, parse_time
from .lyrics import LANGS, resolve_lang, sidecar_lyrics, split_lines
from .theme import ACCENT, display_family
LOW_CONF = 0.6
from .widgets import GlassCard, GlassProgress, GlassRowDelegate, IconPillButton, PillButton, ReviewTable, STATE, AMBER

meta = importlib.import_module(__package__)


def _now():
    import time
    return time.monotonic()
SAVE_LABELS = {'beside': 'Next to the audio file', 'folder': 'A chosen folder', 'ask': 'Ask every time'}


class CaptionButton(QPushButton):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = STATE['dark']
        if self._hover:
            p.setBrush(QColor(214, 54, 56) if self.kind == 'close' else QColor(255, 255, 255, 28 if dark else 90))
            p.setPen(Qt.NoPen)
            p.drawEllipse(self.rect().adjusted(2, 2, -2, -2))
        col = QColor('#ffffff') if (self._hover and self.kind == 'close') or dark else QColor('#2a2e38')
        p.setPen(QPen(col, 1.5, Qt.SolidLine, Qt.RoundCap))
        c = self.rect().center()
        if self.kind == 'close':
            p.drawLine(c.x() - 4, c.y() - 4, c.x() + 4, c.y() + 4)
            p.drawLine(c.x() + 4, c.y() - 4, c.x() - 4, c.y() + 4)
        elif self.kind == 'min':
            p.drawLine(c.x() - 5, c.y(), c.x() + 5, c.y())
        elif self.window().isMaximized() or self.window().isFullScreen():
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(c.x() - 4, c.y() - 2, 7, 7), 1.5, 1.5)
            p.drawPolyline([QPoint(c.x() - 2, c.y() - 4), QPoint(c.x() + 5, c.y() - 4), QPoint(c.x() + 5, c.y() + 3)])
        else:
            r = QRectF(c.x() - 4, c.y() - 4, 8, 8)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 1.5, 1.5)


class GlassWindow(QWidget, chrome.Frame):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.theme = thememod.Theme(app.settings['dark'])
        STATE['dark'] = self.theme.dark
        self._cards = []
        self._drag = None
        self._resize = None
        self.init_frame()
        self.setWindowTitle(meta.APP_NAME)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_margins()
        self.resize(1160 + 2 * self.margin(), 780 + 2 * self.margin())
        self._apply_theme()

    # ---------------------------------------------------------------- UI
    def _apply_margins(self):
        m = self.margin()
        self._root.setContentsMargins(14 + m, 10 + m, 14 + m, 10 + m)
        self.setMinimumSize(1000 + 2 * m, 660 + 2 * m)

    def _build_ui(self):
        root = QVBoxLayout(self)
        self._root = root
        root.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        ico = QLabel()
        ico.setPixmap(self._icon_pixmap(22))
        self.title_lbl = QLabel(meta.APP_NAME)
        self.title_lbl.setObjectName('title')
        self.ver_lbl = QLabel('v' + meta.VERSION)
        self.ver_lbl.setObjectName('sub')
        self.device_lbl = QLabel('')
        self.device_lbl.setObjectName('sub')
        bar.addWidget(ico)
        bar.addWidget(self.title_lbl)
        bar.addWidget(self.ver_lbl)
        bar.addSpacing(14)
        bar.addWidget(self.device_lbl)
        bar.addStretch(1)
        self.btn_min = CaptionButton('min')
        self.btn_max = CaptionButton('max')
        self.btn_close = CaptionButton('close')
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(self.close)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            bar.addWidget(b)
        root.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._left_card(), 2)
        body.addWidget(self._right_card(), 3)
        root.addLayout(body, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(8, 0, 8, 2)
        self.foot1 = self._link_label(meta.CREDIT_HTML)
        self.foot2 = self._link_label(meta.INSPIRED_HTML)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.foot1)
        col.addWidget(self.foot2)
        foot.addLayout(col)
        foot.addStretch(1)
        self.status_lbl = QLabel('')
        self.status_lbl.setObjectName('sub')
        self.status_lbl.setTextFormat(Qt.RichText)
        self.status_lbl.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.status_lbl.linkActivated.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))
        foot.addWidget(self.status_lbl)
        root.addLayout(foot)

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.playbackStateChanged.connect(self._playback_changed)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.positionChanged.connect(self._position_changed)
        self.player.errorOccurred.connect(lambda _e, msg: self.status_lbl.setText('Playback: %s' % msg) if msg else None)
        self._src = ''               # what the player has loaded
        self._pending_seek = None
        self._pos_anchor = (0.0, 0.0)  # (position s, monotonic time) for a smooth playhead
        self._active = -1
        self._normal_geo = None
        self.audio = AudioCache(self)
        self.audio.ready.connect(self._audio_ready)
        self.audio.failed.connect(self._audio_failed)
        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._update_playhead)
        QShortcut(QKeySequence(Qt.Key_F11), self, self._toggle_full)
        QApplication.instance().installEventFilter(self)

    def _link_label(self, html):
        l = QLabel(html)
        l.setObjectName('footer')
        l.setTextFormat(Qt.RichText)
        l.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        l.setOpenExternalLinks(True)
        l.linkActivated.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))
        return l

    def _icon_pixmap(self, size):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        QSvgRenderer(paths.resource('res', 'icon.svg')).render(QPainter(pm))
        return pm

    def _card(self, build, stretch=0):
        card = GlassCard(self.theme)
        self._cards.append(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        build(lay)
        return card

    def _left_card(self):
        def build(lay):
            row = QHBoxLayout()
            self.btn_add = PillButton('Add songs', 'primary')
            self.btn_add.clicked.connect(self._add_songs)
            self.btn_remove = PillButton('Remove')
            self.btn_remove.clicked.connect(self._remove_song)
            self.btn_setdir = PillButton('Set folder for selected…')
            self.btn_setdir.setToolTip('Choose where the lyric files of the selected songs are saved')
            self.btn_setdir.clicked.connect(self._set_folder_selected)
            row.addWidget(self.btn_add)
            row.addWidget(self.btn_remove)
            row.addStretch(1)
            row.addWidget(self.btn_setdir)
            lay.addLayout(row)
            self.queue = QTableWidget(0, 4)
            self.queue.setHorizontalHeaderLabels(['Song', 'Lyrics', 'Status', 'Output folder'])
            self.queue.verticalHeader().hide()
            self.queue.verticalHeader().setDefaultSectionSize(30)
            self.queue.setShowGrid(False)
            self.queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.queue.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
            self.queue.customContextMenuRequested.connect(self._queue_menu)
            self.queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.queue.setWordWrap(False)
            hh = self.queue.horizontalHeader()
            hh.setSectionResizeMode(0, hh.ResizeMode.Stretch)
            self.queue.setColumnWidth(1, 64)
            self.queue.setColumnWidth(2, 124)
            self.queue.setColumnWidth(3, 120)
            self.queue.setMouseTracking(True)
            self.queue.setItemDelegate(GlassRowDelegate(self.queue, progress_col=2))
            self.queue.itemSelectionChanged.connect(self._song_selected)
            lay.addWidget(self.queue, 3)
            self.btn_sync = PillButton('Auto-sync', 'primary')
            self.btn_sync.clicked.connect(lambda: self.app.sync_current())
            self.btn_all = PillButton('Sync all')
            self.btn_all.clicked.connect(self.app.sync_all)
            self.btn_cancel = PillButton('Cancel', 'danger')
            self.btn_cancel.clicked.connect(self.app.cancel)
            self.btn_cancel.hide()
            row2 = QHBoxLayout()
            for b in (self.btn_sync, self.btn_all, self.btn_cancel):
                row2.addWidget(b)
            lay.addLayout(row2)
            self.progress = GlassProgress()
            self.stage_lbl = QLabel('')
            self.stage_lbl.setObjectName('hint')
            lay.addWidget(self.progress)
            lay.addWidget(self.stage_lbl)
            wh = QHBoxLayout()
            wl = QLabel('Waveform')
            wl.setObjectName('sub')
            self.wave_hint = QLabel('click to seek · wheel to zoom · drag a marker to move a line')
            self.wave_hint.setObjectName('hint')
            wh.addWidget(wl)
            wh.addStretch(1)
            wh.addWidget(self.wave_hint)
            lay.addLayout(wh)
            self.wave = Waveform()
            self.wave.seek.connect(self._seek)
            self.wave.select.connect(lambda r: self.review.selectRow(r))
            self.wave.retime.connect(self._retime)
            lay.addWidget(self.wave, 2)
        return self._card(build)

    def _right_card(self):
        def build(lay):
            top = QHBoxLayout()
            self.song_title = QLabel('No song selected')
            self.song_title.setObjectName('h1')
            top.addWidget(self.song_title, 1)
            self.lang = QComboBox()
            for code, label in (('auto', 'Language: auto'), ('en', 'English'), ('el', 'Ελληνικά'), ('de', 'Deutsch'),
                                ('fr', 'Français'), ('es', 'Español'), ('it', 'Italiano'), ('pt', 'Português'),
                                ('nl', 'Nederlands'), ('tr', 'Türkçe'), ('ru', 'Русский'), ('bg', 'Български'),
                                ('ro', 'Română'), ('sq', 'Shqip')):
                self.lang.addItem(label, code)
            self.lang.setToolTip('Language of the lyrics. Auto detects Greek, and lets Whisper decide otherwise.')
            top.addWidget(self.lang)
            lay.addLayout(top)
            frow = QHBoxLayout()
            self.song_dir_lbl = QLabel('')
            self.song_dir_lbl.setObjectName('hint')
            self.song_dir_lbl.setTextFormat(Qt.RichText)
            self.song_dir_lbl.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
            self.song_dir_lbl.linkActivated.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))
            self.btn_song_dir = PillButton('Change…')
            self.btn_song_dir.setFixedWidth(96)
            self.btn_song_dir.setToolTip('Output folder for this song only')
            self.btn_song_dir.clicked.connect(self._change_song_dir)
            self.btn_song_dir_reset = PillButton('Default')
            self.btn_song_dir_reset.setFixedWidth(84)
            self.btn_song_dir_reset.setToolTip('Use the "Save to" setting again for this song')
            self.btn_song_dir_reset.clicked.connect(lambda: self._reset_song_dirs([self.app.current()]))
            frow.addWidget(self.song_dir_lbl, 1)
            frow.addWidget(self.btn_song_dir)
            frow.addWidget(self.btn_song_dir_reset)
            lay.addLayout(frow)
            self.lyrics = QPlainTextEdit()
            self.lyrics.setPlaceholderText('Paste the lyrics here, one line per sung line.\n'
                                           'Lines like [Chorus] or (x2) are ignored.\n'
                                           'A .txt with the same name next to the audio loads automatically.')
            self.lyrics.setMaximumHeight(150)
            self.lyrics.textChanged.connect(self._lyrics_edited)
            lay.addWidget(self.lyrics)

            self.btn_play = PillButton('▶  Play from line')
            self.btn_play.setToolTip('Play from the selected line')
            self.btn_play.clicked.connect(lambda: self._play_row(self.review.currentRow()))
            self.transport = QWidget()
            tr = QHBoxLayout(self.transport)
            tr.setContentsMargins(0, 0, 0, 0)
            tr.setSpacing(6)
            self.btn_back = PillButton('−2 s')
            self.btn_back.setToolTip('Back 2 seconds')
            self.btn_back.clicked.connect(lambda: self._skip(-2.0))
            self.btn_pp = PillButton('▶', 'primary')
            self.btn_pp.setToolTip('Play / pause (Space)')
            self.btn_pp.clicked.connect(self.toggle_play)
            self.btn_fwd = PillButton('+2 s')
            self.btn_fwd.setToolTip('Forward 2 seconds')
            self.btn_fwd.clicked.connect(lambda: self._skip(2.0))
            for b, w in ((self.btn_back, 58), (self.btn_pp, 54), (self.btn_fwd, 58)):
                b.setFixedWidth(w)
                tr.addWidget(b)
            self.time_lbl = QLabel('0:00.00 / 0:00.00')
            self.time_lbl.setObjectName('sub')
            self.time_lbl.setMinimumWidth(128)
            self.time_lbl.setAlignment(Qt.AlignCenter)
            tr.addWidget(self.time_lbl)
            self.speed = QComboBox()
            for r in (0.5, 0.75, 1.0, 1.25, 1.5):
                self.speed.addItem('%g×' % r, r)
            self.speed.setCurrentIndex(2)
            self.speed.setToolTip('Playback speed')
            self.speed.currentIndexChanged.connect(lambda _i: self.player.setPlaybackRate(self.speed.currentData()))
            tr.addWidget(self.speed)
            tr.addWidget(self.btn_play)
            tr.addStretch(1)
            self.low_lbl = QLabel('')
            self.low_lbl.setObjectName('hint')
            tr.addWidget(self.low_lbl)
            self.btn_inst_add = PillButton('+ ♪')
            self.btn_inst_add.setFixedWidth(54)
            self.btn_inst_add.setToolTip('Add a ♪ line at the playhead (an instrumental part the automatic detection missed)')
            self.btn_inst_add.clicked.connect(self._insert_inst)
            self.btn_inst_cfg = PillButton('♪ …')
            self.btn_inst_cfg.setFixedWidth(54)
            self.btn_inst_cfg.setToolTip('♪ lines in instrumental parts: on/off, gap, symbol')
            self.btn_inst_cfg.clicked.connect(self._inst_settings)
            lay.addWidget(self.transport)
            self.transport.hide()

            tools = QHBoxLayout()
            for txt, d in (('−0.1', -0.1), ('−0.01', -0.01), ('+0.01', 0.01), ('+0.1', 0.1)):
                b = PillButton(txt)
                b.setFixedWidth(54)
                b.setToolTip('Move the selected line (← → keys: 0.1 s, with Shift: 0.01 s)')
                b.clicked.connect(lambda _=False, d=d: self._nudge(d))
                tools.addWidget(b)
            self.btn_resync = PillButton('⟲  Re-sync from here')
            self.btn_resync.setToolTip('Keep this line where it is now (after you fixed it) and re-align only the lines after it')
            self.btn_resync.clicked.connect(lambda: self._resync_row(self.review.currentRow()))
            tools.addWidget(self.btn_resync)
            tools.addStretch(1)
            tools.addWidget(self.btn_inst_add)
            tools.addWidget(self.btn_inst_cfg)
            lay.addLayout(tools)
            self.review = ReviewTable()
            self.review.setMouseTracking(True)
            self.review.setItemDelegate(GlassRowDelegate(self.review))
            self.review.play_line.connect(self._play_row)
            self.review.itemChanged.connect(self._time_edited)
            self.review.setContextMenuPolicy(Qt.CustomContextMenu)
            self.review.customContextMenuRequested.connect(self._review_menu)
            self.review.itemSelectionChanged.connect(lambda: self.wave.set_selected(self.review.currentRow()))
            self.review.verticalScrollBar().sliderPressed.connect(self._user_scrolled)
            lay.addWidget(self.review, 1)

            exp = QHBoxLayout()
            save_lbl = QLabel('Save to')
            save_lbl.setObjectName('sub')
            self.save_mode = QComboBox()
            for k in SAVE_MODES:
                self.save_mode.addItem(SAVE_LABELS[k], k)
            self.save_mode.setToolTip('Where the lyric files go. A per-song folder (Change… / Set folder for selected…) always wins.')
            self.out_dir = QLineEdit()
            self.out_dir.setPlaceholderText('Output folder')
            self.out_dir.setReadOnly(True)
            self.btn_browse = PillButton('Browse…')
            self.btn_browse.clicked.connect(self._browse_out)
            exp.addWidget(save_lbl)
            exp.addWidget(self.save_mode)
            exp.addWidget(self.out_dir, 1)
            exp.addWidget(self.btn_browse)
            lay.addLayout(exp)
            checks = QHBoxLayout()
            self.fmt_checks = {}
            for fmt in ('ttml', 'lrc', 'srt', 'vtt'):
                c = QCheckBox(fmt.upper())
                c.setChecked(True)
                self.fmt_checks[fmt] = c
                checks.addWidget(c)
            self.bom = QCheckBox('UTF-8 BOM for SRT')
            self.bom.setToolTip('Some players need a byte-order mark at the start of .srt files. Never written to .vtt or .ttml.')
            self.auto_export = QCheckBox('Export right after sync')
            checks.addWidget(self.bom)
            checks.addWidget(self.auto_export)
            checks.addStretch(1)
            lay.addLayout(checks)
            row = QHBoxLayout()
            self.btn_export = PillButton('Export', 'primary')
            self.btn_export.setToolTip('Export the selected synced songs (each to its own folder)')
            self.btn_export.clicked.connect(lambda: self.app.export_selected())
            row.addWidget(self.btn_export)
            row.addStretch(1)
            self.btn_about = PillButton('About')
            self.btn_about.clicked.connect(self._about)
            self.btn_update = IconPillButton('Update', 'update')
            self.btn_update.setToolTip('Check for updates')
            self.btn_update.clicked.connect(lambda: self.app.open_updates())
            self.btn_theme = PillButton('Light')
            self.btn_theme.clicked.connect(self._toggle_theme)
            row.addWidget(self.btn_theme)
            row.addWidget(self.btn_update)
            row.addWidget(self.btn_about)
            lay.addLayout(row)
        return self._card(build)

    # ---------------------------------------------------------------- painting
    def paintEvent(self, _e):
        t = self.theme
        body = self.body_rect()
        rad = self.radius()
        cards = tuple((card.geometry().getRect(), card.radius) for card in self._cards if card.isVisible())

        def paint(q):
            if self.margin():
                chrome.paint_shadow(q, body, rad, t.dark)
            chrome.paint_glass(q, body, rad, t, self._backdrop)
            # Soft card shadows (stacked translucent rounded rects = cheap blur), clipped to the body.
            path = QPainterPath()
            path.addRoundedRect(body, rad, rad)
            q.setClipPath(path)
            q.setPen(Qt.NoPen)
            for (x, y, w, h), cr in cards:
                g0 = QRectF(x, y, w, h)
                for i in range(10, 0, -1):
                    sh = QColor(*t.shadow)
                    sh.setAlpha(int(t.shadow[3] * (1 - i / 11) ** 2 / 3))
                    q.setBrush(sh)
                    q.drawRoundedRect(g0.adjusted(-i, -i + 6, i, i + 6), cr + i, cr + i)
            q.setClipping(False)
        pm = chrome.cached_background(self, (t.dark, self._backdrop, self.margin(), rad, cards), paint)
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawPixmap(0, 0, pm)

    def _apply_theme(self):
        t = self.theme
        STATE['dark'] = t.dark
        self.app.qapp.setStyleSheet(t.qss())
        self.app.qapp.setPalette(t.palette())
        self.btn_theme.setText('Light' if t.dark else 'Dark')
        for c in self._cards:
            c.set_theme(t)
        self.update()

    # ---------------------------------------------------------------- window chrome
    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, '_fx_done', False) or self.app.screenshot:
            return
        self._fx_done = True
        hwnd = int(self.winId())
        if self._mode == 'win11':
            winfx.enable_native_frame(hwnd, dwm_frame=True)
            if not winfx.set_mica(hwnd, self.theme.dark):
                self._mode, self._backdrop = 'painted', 'painted'   # no Mica: painted glass + painted shadow
                winfx.enable_native_frame(hwnd, dwm_frame=False)
                self._apply_margins()
        else:
            winfx.enable_native_frame(hwnd, dwm_frame=False)
        self.update()

    def resizeEvent(self, e):
        # lyrics box: compact on short screens (1280×720), roomier on tall ones; the line list gets the rest
        self.lyrics.setMaximumHeight(max(84, min(200, int(self.height() * 0.13))))
        super().resizeEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            self._apply_margins()   # no shadow margin / rounded corners while maximized or full screen
            self.btn_max.update()
            self.update()
            if self.isMaximized() or self.isFullScreen():
                QTimer.singleShot(0, self._heal_geometry)
                QTimer.singleShot(250, self._heal_geometry)
        super().changeEvent(e)

    def target_geometry(self):
        """Where a maximized (work area: the screen minus the taskbar) or full-screen window belongs."""
        scr = self.screen() or QApplication.primaryScreen()
        return scr.geometry() if self.isFullScreen() else scr.availableGeometry()

    def _heal_geometry(self):
        """Maximized/full screen but not covering the target area (a frameless window can end up
        moved to the corner at its old size): put it there. Logged for the selftest."""
        if not (self.isMaximized() or self.isFullScreen()):
            return
        want = self.target_geometry()
        got = self.geometry()
        if abs(got.x() - want.x()) > 2 or abs(got.y() - want.y()) > 2 or abs(got.width() - want.width()) > 2 \
                or abs(got.height() - want.height()) > 2:
            self._healed = getattr(self, '_healed', 0) + 1
            self.setGeometry(want)

    def _toggle_max(self):
        if self.isFullScreen():
            self._toggle_full()
            return
        if self.isMaximized():
            self.showNormal()
            if self._normal_geo is not None and not winfx.IS_WIN:
                self.setGeometry(self._normal_geo)
        else:
            self._normal_geo = self.geometry()
            self.showMaximized()

    def _toggle_full(self):
        """F11: full screen and back to how it was (maximized or the previous size)."""
        if self.isFullScreen():
            if getattr(self, '_was_max', False):
                self.showMaximized()
            else:
                self.showNormal()
                if self._normal_geo is not None and not winfx.IS_WIN:
                    self.setGeometry(self._normal_geo)
        else:
            self._was_max = self.isMaximized()
            if not self._was_max:
                self._normal_geo = self.geometry()
            self.showFullScreen()

    def _hit(self, pos):
        edge = self.edge_hit(pos.x(), pos.y())
        if edge is not None:
            return edge
        return self._caption_hit(pos)

    def _caption_hit(self, pos):
        """Empty title-bar area acts as the native caption (drag, Aero Snap, double-click)."""
        if pos.y() < self.margin() + 46:
            child = self.childAt(pos)
            if not isinstance(child, (QPushButton, QComboBox, QLineEdit)) and not (
                    isinstance(child, QLabel) and child.objectName() == 'footer'):
                return winfx.HTCAPTION
        return winfx.HTCLIENT

    def nativeEvent(self, event_type, message):
        if not winfx.IS_WIN or event_type != b'windows_generic_MSG':
            return False, 0
        msg = winfx.read_msg(message)
        if msg.message == winfx.WM_NCHITTEST:
            hit = self._hit(self.mapFromGlobal(QCursor.pos()))
            if hit != winfx.HTCLIENT:
                return True, hit
        elif msg.message == winfx.WM_NCCALCSIZE and msg.wParam:
            # IsZoomed, not isMaximized(): Qt only learns about the new state on WM_SIZE, after this
            if winfx.is_zoomed(int(self.winId())) and not self.isFullScreen():
                winfx.fix_maximized_rect(msg, int(self.winId()))
            return True, 0
        elif msg.message == winfx.WM_NCACTIVATE:
            return True, 1
        return False, 0

    def mousePressEvent(self, e):
        # Windows uses the native hit-test above; this path serves other platforms.
        if e.button() == Qt.LeftButton and self._hit(e.position().toPoint()) == winfx.HTTRANSPARENT:
            return
        if e.button() == Qt.LeftButton and self._hit(e.position().toPoint()) == winfx.HTCAPTION:
            if self.windowHandle() is None or not self.windowHandle().startSystemMove():
                self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif e.button() == Qt.LeftButton and not winfx.IS_WIN:
            hit = self._hit(e.position().toPoint())
            if hit not in (winfx.HTCLIENT, winfx.HTTRANSPARENT):
                self._resize = (hit, e.globalPosition().toPoint(), self.geometry())

    def mouseMoveEvent(self, e):
        if not winfx.IS_WIN:
            cursors = {winfx.HTLEFT: Qt.SizeHorCursor, winfx.HTRIGHT: Qt.SizeHorCursor, winfx.HTTOP: Qt.SizeVerCursor,
                       winfx.HTBOTTOM: Qt.SizeVerCursor, winfx.HTTOPLEFT: Qt.SizeFDiagCursor, winfx.HTBOTTOMRIGHT: Qt.SizeFDiagCursor,
                       winfx.HTTOPRIGHT: Qt.SizeBDiagCursor, winfx.HTBOTTOMLEFT: Qt.SizeBDiagCursor}
            self.setCursor(cursors.get(self._hit(e.position().toPoint()), Qt.ArrowCursor))
        if self._drag and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
        elif self._resize and e.buttons() & Qt.LeftButton:
            hit, start, geo = self._resize
            d = e.globalPosition().toPoint() - start
            r = QRect(geo)
            if hit in (winfx.HTLEFT, winfx.HTTOPLEFT, winfx.HTBOTTOMLEFT):
                r.setLeft(geo.left() + d.x())
            if hit in (winfx.HTRIGHT, winfx.HTTOPRIGHT, winfx.HTBOTTOMRIGHT):
                r.setRight(geo.right() + d.x())
            if hit in (winfx.HTTOP, winfx.HTTOPLEFT, winfx.HTTOPRIGHT):
                r.setTop(geo.top() + d.y())
            if hit in (winfx.HTBOTTOM, winfx.HTBOTTOMLEFT, winfx.HTBOTTOMRIGHT):
                r.setBottom(geo.bottom() + d.y())
            if r.width() >= self.minimumWidth() and r.height() >= self.minimumHeight():
                self.setGeometry(r)

    def mouseReleaseEvent(self, e):
        self._drag = self._resize = None

    def mouseDoubleClickEvent(self, e):
        if self._hit(e.position().toPoint()) == winfx.HTCAPTION:
            self._toggle_max()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.app.add_songs([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ---------------------------------------------------------------- queue / review
    def _dir_display(self, song):
        d = target_dir(song, self.app.settings)
        if d is None:
            return 'Ask on export', ''
        if getattr(song, 'out_dir', None):
            return '★ ' + (os.path.basename(d.rstrip('\\/')) or d), d + '  (set for this song)'
        if self.app.settings.get('save_mode', 'beside') == 'beside':
            return 'Next to audio', d
        return os.path.basename(d.rstrip('\\/')) or d, d

    def refresh_queue(self, songs, current):
        self._loading = True
        self.queue.setRowCount(len(songs))
        for i, s in enumerate(songs):
            self.queue.setItem(i, 0, QTableWidgetItem(s.label()))
            self.queue.setItem(i, 1, QTableWidgetItem('%d lines' % len(split_lines(s.lyrics)) if s.lyrics.strip() else '—'))
            st = QTableWidgetItem(s.status)
            st.setToolTip(s.status)
            self.queue.setItem(i, 2, st)
            txt, tip = self._dir_display(s)
            di = QTableWidgetItem(txt)
            di.setToolTip(tip)
            self.queue.setItem(i, 3, di)
        if 0 <= current < len(songs):
            sel = set(self.selected_rows())
            if current not in sel:
                self.queue.selectRow(current)
        self._loading = False
        self._update_buttons()

    def refresh_dirs(self):
        for i, s in enumerate(self.app.songs):
            it = self.queue.item(i, 3)
            if it:
                txt, tip = self._dir_display(s)
                it.setText(txt)
                it.setToolTip(tip)
        self._show_song_dir(self.app.current())

    def selected_rows(self):
        sm = self.queue.selectionModel()
        return sorted(r.row() for r in sm.selectedRows()) if sm else []

    def selected_songs(self):
        return [self.app.songs[r] for r in self.selected_rows() if r < len(self.app.songs)]

    def _show_song_dir(self, song):
        if not song:
            self.song_dir_lbl.setText('')
            self.btn_song_dir.setEnabled(False)
            self.btn_song_dir_reset.setVisible(False)
            return
        d = target_dir(song, self.app.settings)
        self.btn_song_dir.setEnabled(True)
        self.btn_song_dir_reset.setVisible(bool(getattr(song, 'out_dir', None)))
        if d is None:
            self.song_dir_lbl.setText('Output folder: asked when you export')
            return
        el = self.song_dir_lbl.fontMetrics().elidedText(d, Qt.ElideMiddle, 420)
        url = QUrl.fromLocalFile(d).toString()
        self.song_dir_lbl.setText('Output folder: <a href="%s">%s</a>%s' % (url, el.replace('<', '&lt;'),
                                  ' &nbsp;(this song)' if getattr(song, 'out_dir', None) else ''))
        self.song_dir_lbl.setToolTip(d)

    def show_song(self, song):
        self._loading = True
        self.song_title.setText(song.label() if song else 'No song selected')
        self.lyrics.setPlainText(song.lyrics if song else '')
        idx = self.lang.findData(song.lang if song else 'auto')
        self.lang.setCurrentIndex(max(0, idx))
        self.review.setRowCount(0)
        self.low_lbl.setText('')
        self._active = -1
        self.review._active_row = -1
        if song and song.result:
            self._fill_review(song)
        else:
            self.wave.set_lines([])
        self.transport.setVisible(bool(song and song.result))
        self._load_audio(song)
        self._show_song_dir(song)
        self._loading = False
        self._update_buttons()

    def _fill_review(self, song):
        lines = song.result['lines']
        self.review.blockSignals(True)
        self.review.setRowCount(len(lines))
        low = 0
        for i, l in enumerate(lines):
            conf = l.get('conf')
            is_low = conf is not None and conf < LOW_CONF
            low += is_low
            why = l.get('why') or []
            tip = ('Confidence %d%%' % round(conf * 100) if conf is not None else 'Confidence: n/a') + \
                  ((' — ' + '; '.join(why)) if why else '')
            if is_low:
                tip += '\nCheck this line: play it, nudge or type the start, then “Re-sync from here” for the lines after it.'
            play = QTableWidgetItem('▶')
            play.setTextAlignment(Qt.AlignCenter)
            play.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            play.setToolTip('Play from this line')
            self.review.setItem(i, 0, play)
            inst = bool(l.get('inst'))
            if inst:
                tip = {'intro': 'Instrumental intro', 'outro': 'Instrumental outro', 'break': 'Instrumental part (solo / break)'}.get(
                    l.get('kind'), 'Instrumental part (added by hand)') + ' — shown as %s in the lyric files. ' % l['text'] + \
                    'Delete it with the Delete key or the right-click menu.'
            txt = QTableWidgetItem(('↻ ' if l.get('repeat') else '') + l['text'])
            txt.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            txt.setToolTip(tip)
            txt.setData(Qt.UserRole + 1, 'inst' if inst else '')
            if inst:
                f = QFont(self.review.font())
                f.setItalic(True)
                txt.setFont(f)
                txt.setForeground(QColor(INST).lighter(125) if self.theme.dark else QColor(INST).darker(135))
            self.review.setItem(i, 1, txt)
            st = QTableWidgetItem(fmt_lrc_time(l['start']))
            st.setTextAlignment(Qt.AlignCenter)
            st.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            st.setToolTip(tip)
            self.review.setItem(i, 2, st)
            en = QTableWidgetItem(fmt_lrc_time(l['end']))
            en.setTextAlignment(Qt.AlignCenter)
            en.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.review.setItem(i, 3, en)
            if inst:
                note = 'music' if l.get('auto') else 'music ✎'
            elif is_low:
                note = '● check'
            elif l.get('manual'):
                note = '✎ fixed'
            else:
                note = l.get('flag') or ('placed' if l.get('guessed') else '')
            nt = QTableWidgetItem(note)
            nt.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            nt.setToolTip(tip)
            nt.setData(Qt.UserRole, 'low' if is_low else '')
            if inst:
                nt.setForeground(QColor(INST))
            elif note and note != '✎ fixed':
                nt.setForeground(QColor(AMBER))
            self.review.setItem(i, 4, nt)
        self.review.blockSignals(False)
        self.wave.set_lines(lines, self.review.currentRow())
        self.low_lbl.setText(('<span style="color:%s">●</span> %d to check' % (AMBER, low)) if low else '')

    def _song_selected(self):
        if getattr(self, '_loading', False):
            return
        r = self.queue.currentRow()
        rows = self.selected_rows()
        if r not in rows and rows:
            r = rows[0]
        if r >= 0:
            self.app.select(r)
        self._update_buttons()

    def _lyrics_edited(self):
        if not getattr(self, '_loading', False):
            self.app.lyrics_changed(self.lyrics.toPlainText(), self.lang.currentData())

    def _update_buttons(self):
        busy = self.app.busy
        cur = self.app.current()
        has = cur is not None
        synced = bool(has and cur.result)
        for b in (self.btn_add, self.btn_remove, self.btn_sync, self.btn_all):
            b.setEnabled(not busy)
        self.btn_sync.setEnabled(not busy and has and bool(split_lines(cur.lyrics)))
        self.btn_all.setEnabled(not busy and any(split_lines(s.lyrics) for s in self.app.songs))
        sel = self.selected_songs() if hasattr(self, 'queue') else []
        self.btn_export.setEnabled(not busy and (synced or any(s.result for s in sel)))
        self.btn_setdir.setEnabled(bool(sel))
        row = self.review.currentRow()
        L = cur.result['lines'] if synced else []
        self.btn_resync.setEnabled(synced and not busy and 0 <= row < len(L) and not L[row].get('inst'))
        self.btn_cancel.setVisible(busy)
        self.btn_browse.setEnabled(self.save_mode.currentData() == 'folder')
        self.out_dir.setEnabled(self.save_mode.currentData() == 'folder')

    def _queue_menu(self, pos):
        songs = self.selected_songs()
        if not songs:
            return
        m = QMenu(self)
        m.addAction('Set output folder for %s…' % ('this song' if len(songs) == 1 else '%d songs' % len(songs)),
                    self._set_folder_selected)
        if any(getattr(s, 'out_dir', None) for s in songs):
            m.addAction('Use the "Save to" setting again', lambda: self._reset_song_dirs(songs))
        d = target_dir(songs[0], self.app.settings)
        if d and os.path.isdir(d):
            m.addAction('Open output folder', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(d)))
        m.addSeparator()
        m.addAction('Remove', self._remove_song)
        m.exec(self.queue.viewport().mapToGlobal(pos))

    def _pick_dir(self, title, start):
        return QFileDialog.getExistingDirectory(self, title, start or os.path.expanduser('~'))

    def _set_folder_selected(self):
        songs = self.selected_songs()
        if not songs:
            return
        start = target_dir(songs[0], self.app.settings) or self.app.settings.get('out_dir', '')
        d = self._pick_dir('Output folder for %d song%s' % (len(songs), '' if len(songs) == 1 else 's'), start)
        if d:
            self.app.set_song_dirs(songs, d)

    def _change_song_dir(self):
        s = self.app.current()
        if not s:
            return
        d = self._pick_dir('Output folder for “%s”' % s.label(), target_dir(s, self.app.settings) or '')
        if d:
            self.app.set_song_dirs([s], d)

    def _reset_song_dirs(self, songs):
        self.app.set_song_dirs([s for s in songs if s], None)

    def _review_menu(self, pos):
        row = self.review.rowAt(pos.y())
        if row < 0:
            return
        self.review.selectRow(row)
        m = QMenu(self)
        inst = bool(self._lines()[row].get('inst')) if row < len(self._lines()) else False
        m.addAction('▶  Play from this line', lambda: self._play_row(row))
        if not inst:
            a = m.addAction('⟲  Re-sync from this line', lambda: self._resync_row(row))
            a.setEnabled(not self.app.busy)
        m.addSeparator()
        m.addAction('♪  Insert ♪ here (at the playhead)', self._insert_inst)
        if inst:
            m.addAction('Delete this ♪ line', lambda: self._delete_inst(row))
        m.addAction('♪ settings…', self._inst_settings)
        m.exec(self.review.viewport().mapToGlobal(pos))

    def _resync_row(self, row):
        song = self.app.current()
        if not song or not song.result or row < 0 or self.app.busy:
            return
        self.app.resync(song, row)

    def show_export_result(self, folders, nfiles, skipped=0):
        links = ' · '.join('<a href="%s">%s</a>' % (QUrl.fromLocalFile(d).toString(),
                                                     (os.path.basename(d.rstrip('\\/')) or d).replace('<', '&lt;'))
                           for d in folders[:4])
        more = ' +%d' % (len(folders) - 4) if len(folders) > 4 else ''
        txt = 'Exported %d file%s' % (nfiles, '' if nfiles == 1 else 's')
        if skipped:
            txt += ', skipped %d song%s' % (skipped, '' if skipped == 1 else 's')
        self.status_lbl.setText(txt + ((' · Open folder: ' + links + more) if links else ''))

    def ask_conflict(self, song, existing, state):
        """Overwrite / Keep both / Skip, with 'apply to all' (remembered in state for this export)."""
        if state.get('all'):
            return state['all']
        from .dialogs import ConflictDialog
        d = ConflictDialog(self, song.label(), existing)
        d.exec()
        if d.apply_all.isChecked():
            state['all'] = d.choice
        return d.choice

    def set_busy(self, busy, stage='', pct=0.0):
        self.progress.set_value(pct)
        self.stage_lbl.setText(stage)
        self._update_buttons()

    def set_device(self, info):
        if not info:
            self.device_lbl.setText('')
            return
        if info.get('device') == 'cuda':
            self.device_lbl.setText('●  CUDA · %s' % info.get('device_name', 'NVIDIA GPU'))
            self.device_lbl.setStyleSheet('color: #3ecf8e;')
        elif info.get('device') == 'cpu':
            self.device_lbl.setText('●  CPU%s' % ('' if not info.get('note') else ' · ' + info['note']))
            self.device_lbl.setStyleSheet('color: #e0a106;')
        else:
            self.device_lbl.setText('●  ' + info.get('text', ''))
            self.device_lbl.setStyleSheet('')

    # ---------------------------------------------------------------- review editing
    def _lines(self):
        song = self.app.current()
        return song.result['lines'] if song and song.result else []

    def _refresh_row(self, row):
        L = self._lines()
        if 0 <= row < len(L) and self.review.item(row, 2):
            self.review.blockSignals(True)
            self.review.item(row, 2).setText(fmt_lrc_time(L[row]['start']))
            self.review.item(row, 3).setText(fmt_lrc_time(L[row]['end']))
            self.review.blockSignals(False)
        self.wave.set_lines(L, self.review.currentRow())

    def _set_start(self, row, t):
        """Move line `row` to start at t (nudge, typed time, stamp, waveform drag)."""
        song = self.app.current()
        L = self._lines()
        if not (0 <= row < len(L)):
            return
        l = L[row]
        l['start'] = round(max(0.0, t), 3)
        if l.get('inst'):
            l['auto'] = False      # edited by hand: kept when the ♪ lines are recomputed
        if row + 1 < len(L):
            l['end'] = min(l['end'], L[row + 1]['start'])
        l['end'] = round(max(l['end'], l['start']), 3)
        if row > 0 and L[row - 1]['end'] > l['start']:
            L[row - 1]['end'] = round(max(L[row - 1]['start'], l['start']), 3)
            self._refresh_row(row - 1)
        song.dirty = True
        self._refresh_row(row)

    def _nudge(self, delta):
        row = self.review.currentRow()
        L = self._lines()
        if 0 <= row < len(L):
            self._set_start(row, L[row]['start'] + delta)

    def _time_edited(self, item):
        if item.column() != 2 or getattr(self, '_loading', False):
            return
        L = self._lines()
        if not (0 <= item.row() < len(L)):
            return
        t = parse_time(item.text())
        if t is None:
            self._refresh_row(item.row())
            return
        self._set_start(item.row(), t)

    def _retime(self, row, t):
        self.review.selectRow(row)
        self._set_start(row, t)
        self.status_lbl.setText('Line %d now starts at %s' % (row + 1, fmt_lrc_time(t)))

    def stamp(self):
        """S: the selected line starts at the playhead; select the next line (tap along)."""
        row = self.review.currentRow()
        L = self._lines()
        if not (0 <= row < len(L)):
            return
        self._set_start(row, self.position())
        if row + 1 < len(L):
            self.review.selectRow(row + 1)

    def _insert_inst(self):
        song = self.app.current()
        if not song or not song.result:
            return
        t = self.position()
        if t <= 0.0 and self.review.currentRow() >= 0:
            t = self._lines()[self.review.currentRow()]['end']
        row = instrumental.insert(song.result, t, self.app.settings)
        song.dirty = True
        self._fill_review(song)
        self.review.selectRow(row)
        self.status_lbl.setText('Added a ♪ line at %s' % fmt_lrc_time(t))

    def _delete_inst(self, row=None):
        song = self.app.current()
        row = self.review.currentRow() if row is None else row
        if not song or not song.result or not (0 <= row < len(song.result['lines'])):
            return False
        if not instrumental.delete(song.result, row):
            return False
        song.dirty = True
        self._fill_review(song)
        self.review.selectRow(min(row, self.review.rowCount() - 1))
        self.status_lbl.setText('♪ line removed')
        return True

    def _inst_settings(self):
        from .dialogs import MusicDialog
        d = MusicDialog(self, self.app.settings)
        if d.exec():
            self.app.settings.update(d.values())
            self.app.save_settings()
            self.app.apply_instrumental()

    # ---------------------------------------------------------------- playback
    def _load_audio(self, song):
        path = song.path if song else ''
        if self._src and not self._src_is(path):
            self.player.stop()
            self.player.setSource(QUrl())
            self._src = ''
        if not song:
            self.wave.clear('Select a song to see its waveform')
            self._update_time()
            return
        hit = self.audio.get(path)
        if hit and os.path.exists(hit[0]):
            self.wave.set_audio(hit[1], hit[2])
        else:
            self.wave.clear('Reading the audio…')
            self.audio.load(path)
        self._update_time()

    def _src_is(self, path):
        hit = self.audio.get(path)
        return self._src in (path, hit[0] if hit else None)

    def _audio_ready(self, path, wav, peaks, dur):
        song = self.app.current()
        if song and song.path == path:
            if self.wave.peaks is not peaks:
                self.wave.set_audio(peaks, dur)
                self.wave.set_lines(self._lines(), self.review.currentRow())
            if self._src == path and self.player.playbackState() != QMediaPlayer.PlayingState:
                self._src = ''   # switch to the decoded copy on the next play / seek
            self._update_time()

    def _audio_failed(self, path, msg):
        song = self.app.current()
        if song and song.path == path:
            self.wave.clear('Waveform not available (%s). Playback uses the original file.' % msg[:80])

    def _ensure_source(self):
        """Prefer the decoded WAV (sample-accurate seeks); the original file until it's ready."""
        song = self.app.current()
        if not song:
            return False
        hit = self.audio.get(song.path)
        want = hit[0] if hit and os.path.exists(hit[0]) else song.path
        if self._src != want:
            pos = self.position() if self._src_is(song.path) else None
            self._src = want
            self.player.setSource(QUrl.fromLocalFile(want))
            self.player.setPlaybackRate(self.speed.currentData() or 1.0)
            if pos:
                self._pending_seek = pos
        return True

    def duration(self):
        return self.wave.duration or (self.player.duration() / 1000.0)

    def position(self):
        return self.wave.pos

    def _seek(self, t):
        if not self._ensure_source():
            return
        t = max(0.0, min(t, self.duration() or t))
        st = self.player.mediaStatus()
        if st in (QMediaPlayer.MediaStatus.LoadingMedia, QMediaPlayer.MediaStatus.NoMedia):
            self._pending_seek = t
        else:
            self.player.setPosition(int(round(t * 1000)))
        self._pos_anchor = (t, _now())
        self._show_position(t)

    def _media_status(self, st):
        if self._pending_seek is not None and st in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
                                                     QMediaPlayer.MediaStatus.BufferingMedia):
            t, self._pending_seek = self._pending_seek, None
            self.player.setPosition(int(round(t * 1000)))

    def _skip(self, dt):
        self._seek(self.position() + dt)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            return
        if not self._ensure_source():
            return
        if self._pending_seek is None and self.player.mediaStatus() == QMediaPlayer.MediaStatus.LoadingMedia:
            self._pending_seek = self.position()
        elif self._pending_seek is None and abs(self.player.position() / 1000.0 - self.position()) > 0.05:
            self.player.setPosition(int(round(self.position() * 1000)))
        self.player.play()

    def _play_row(self, row):
        L = self._lines()
        if not (0 <= row < len(L)):
            return
        self.review.selectRow(row)
        self._seek(L[row]['start'])
        if self.player.playbackState() != QMediaPlayer.PlayingState:
            self.player.play()

    def _playback_changed(self, state):
        playing = state == QMediaPlayer.PlayingState
        self.btn_pp.setText('❚❚' if playing else '▶')
        if playing:
            self._pos_anchor = (self.player.position() / 1000.0, _now())
            self._tick.start()
        else:
            self._tick.stop()
            if state == QMediaPlayer.StoppedState and self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self._show_position(self.duration())
            else:
                self._show_position(self.player.position() / 1000.0)

    def _position_changed(self, ms):
        self._pos_anchor = (ms / 1000.0, _now())
        if self.player.playbackState() != QMediaPlayer.PlayingState and self._pending_seek is None:
            self._show_position(ms / 1000.0)

    def _update_playhead(self):
        """33 ms while playing: interpolate between the player's position reports."""
        p0, t0 = self._pos_anchor
        rate = self.speed.currentData() or 1.0
        t = p0 + min(0.25, (_now() - t0)) * rate
        self._show_position(t, playing=True)

    def _show_position(self, t, playing=False):
        self.wave.set_position(t, playing)
        self._update_time(t)
        self._set_active(t, playing)

    def _update_time(self, t=None):
        t = self.position() if t is None else t
        self.time_lbl.setText('%s / %s' % (fmt_clock(t), fmt_clock(self.duration())))

    def _set_active(self, t, follow):
        L = self._lines()
        row = -1
        for i, l in enumerate(L):
            if l['start'] <= t + 0.005:
                if row < 0 or l['start'] >= L[row]['start']:
                    row = i
        if row >= 0 and t > L[row].get('end', t) + 1.0 and not L[row].get('inst'):
            row = -1 if not any(l['start'] > t for l in L) else row
        if row == self._active:
            return
        old, self._active = self._active, row
        self.review._active_row = row
        vp = self.review.viewport()
        for r in (old, row):
            if r >= 0:
                rect = self.review.visualRect(self.review.model().index(r, 0))
                vp.update(0, rect.top(), vp.width(), rect.height())
        if follow and row >= 0 and _now() - getattr(self, '_scrolled_at', 0) > 3.0 \
                and self.review.state() != QAbstractItemView.State.EditingState:
            self.review.scrollTo(self.review.model().index(row, 1), QAbstractItemView.ScrollHint.PositionAtCenter)

    def _user_scrolled(self):
        self._scrolled_at = _now()

    # ---------------------------------------------------------------- keyboard
    def _typing(self):
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
            return True
        return self.review.state() == QAbstractItemView.State.EditingState

    def eventFilter(self, obj, e):
        if e.type() != QEvent.KeyPress or QApplication.activeWindow() is not self or QApplication.activeModalWidget() \
                or QApplication.activePopupWidget() or self._typing() or e.isAutoRepeat() and e.key() == Qt.Key_Space:
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self:
            return False
        return self.handle_key(e.key(), e.modifiers())

    def handle_key(self, k, mods=Qt.NoModifier):
        """Player/review shortcuts (not while typing). True when the key was used."""
        if mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        in_queue = QApplication.focusWidget() is self.queue
        has = bool(self._lines())
        if k == Qt.Key_Space and self.app.current():
            self.toggle_play()
            return True
        if k in (Qt.Key_Up, Qt.Key_Down) and has and not in_queue:
            r = self.review.currentRow()
            n = self.review.rowCount()
            r = (0 if r < 0 else max(0, r - 1)) if k == Qt.Key_Up else (0 if r < 0 else min(n - 1, r + 1))
            self.review.selectRow(r)
            self.review.scrollTo(self.review.model().index(r, 1))
            return True
        if k in (Qt.Key_Left, Qt.Key_Right) and has and self.review.currentRow() >= 0:
            step = 0.01 if mods & Qt.ShiftModifier else 0.1
            self._nudge(step if k == Qt.Key_Right else -step)
            return True
        if k == Qt.Key_S and has and self.review.currentRow() >= 0:
            self.stamp()
            return True
        if k == Qt.Key_Delete and has and not in_queue:
            return self._delete_inst()
        if k == Qt.Key_Escape and self.isFullScreen():
            self._toggle_full()
            return True
        return False

    # ---------------------------------------------------------------- export UI
    def _browse_out(self):
        d = self._pick_dir('Output folder', self.out_dir.text())
        if d:
            self.out_dir.setText(d)
            self.app.settings['out_dir'] = d
            self.app.save_settings()
            self.refresh_dirs()

    def _save_mode_changed(self, _i):
        if getattr(self, '_loading_settings', False):
            return
        mode = self.save_mode.currentData()
        if mode == 'folder' and not self.app.settings.get('out_dir'):
            self._browse_out()
        self._set('save_mode', mode)
        self._update_buttons()
        self.refresh_dirs()

    def export_options(self):
        return {'formats': [f for f, c in self.fmt_checks.items() if c.isChecked()], 'bom': self.bom.isChecked()}

    def load_settings(self, s):
        self._loading_settings = True
        self.out_dir.setText(s.get('out_dir', ''))
        self.save_mode.setCurrentIndex(max(0, self.save_mode.findData(s.get('save_mode', 'beside'))))
        for f, c in self.fmt_checks.items():
            c.setChecked(f in s.get('formats', ['ttml', 'lrc', 'srt', 'vtt']))
        self.bom.setChecked(bool(s.get('bom', False)))
        self.auto_export.setChecked(bool(s.get('auto_export', False)))
        self._loading_settings = False
        self.save_mode.currentIndexChanged.connect(self._save_mode_changed)
        self.bom.toggled.connect(lambda v: self._set('bom', v))
        self.auto_export.toggled.connect(lambda v: self._set('auto_export', v))
        for c in self.fmt_checks.values():
            c.toggled.connect(lambda _v: self._set('formats', [f for f, cc in self.fmt_checks.items() if cc.isChecked()]))
        self.lang.currentIndexChanged.connect(lambda _i: self._lyrics_edited())
        self.review.itemSelectionChanged.connect(self._update_buttons)
        self._update_buttons()

    def _set(self, key, value):
        self.app.settings[key] = value
        self.app.save_settings()

    def _add_songs(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Add songs', self.app.settings.get('last_dir', ''),
                                                'Audio (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.wma);;All files (*)')
        if files:
            self.app.settings['last_dir'] = os.path.dirname(files[0])
            self.app.save_settings()
            self.app.add_songs(files)

    def _remove_song(self):
        rows = self.selected_rows()
        for r in sorted(rows, reverse=True):
            self.app.remove_song(r)

    # ---------------------------------------------------------------- theme / about
    def _toggle_theme(self):
        self.theme = thememod.Theme(not self.theme.dark)
        self.app.settings['dark'] = self.theme.dark
        self.app.save_settings()
        self._apply_theme()
        if self._backdrop == 'mica':
            winfx.set_mica(int(self.winId()), self.theme.dark)

    def _about(self):
        from .dialogs import AboutDialog
        AboutDialog(self).exec()

    def closeEvent(self, e):
        if self.app.busy:
            if QMessageBox.question(self, meta.APP_NAME, 'A sync is running. Quit anyway?') != QMessageBox.Yes:
                e.ignore()
                return
            self.app.cancel()
        self.player.stop()
        self.audio.cancel()
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(e)
