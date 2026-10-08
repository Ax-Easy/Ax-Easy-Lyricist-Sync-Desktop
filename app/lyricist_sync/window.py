"""The main window: frameless rounded 'liquid glass' shell, custom title bar, the song
queue, lyrics, review list and footer."""
import os

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QDesktopServices, QFont, QIcon, QKeySequence, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QShortcut)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QTableWidget, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSizePolicy, QSpacerItem, QTableWidgetItem,
                               QVBoxLayout, QWidget)

import importlib
from . import paths, theme as thememod, winfx
from .formats import EXTS, build, build_base_name, encode_file, fmt_lrc_time, parse_time
from .lyrics import LANGS, resolve_lang, sidecar_lyrics, split_lines
from .theme import ACCENT, display_family
from .widgets import GlassCard, GlassProgress, GlassRowDelegate, PillButton, ReviewTable, STATE

meta = importlib.import_module(__package__)
RADIUS = 16
EDGE = 6  # resize grip width (px)


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
        else:
            r = QRectF(c.x() - 4, c.y() - 4, 8, 8)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 1.5, 1.5)


class GlassWindow(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.theme = thememod.Theme(app.settings['dark'])
        STATE['dark'] = self.theme.dark
        self._cards = []
        self._drag = None
        self._resize = None
        self.setWindowTitle(meta.APP_NAME)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        self.resize(1120, 760)
        self._build_ui()
        self._apply_theme()
        self._backdrop = 'gradient'
        if not app.screenshot:
            self._fx_timer = self.startTimer(1)  # applied once the native window exists

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
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
        foot.addWidget(self.status_lbl)
        root.addLayout(foot)

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)

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
            row.addWidget(self.btn_add)
            row.addWidget(self.btn_remove)
            row.addStretch(1)
            lay.addLayout(row)
            self.queue = QTableWidget(0, 3)
            self.queue.setHorizontalHeaderLabels(['Song', 'Lyrics', 'Status'])
            self.queue.verticalHeader().hide()
            self.queue.verticalHeader().setDefaultSectionSize(30)
            self.queue.setShowGrid(False)
            self.queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.queue.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.queue.setWordWrap(False)
            hh = self.queue.horizontalHeader()
            hh.setSectionResizeMode(0, hh.ResizeMode.Stretch)
            self.queue.setColumnWidth(1, 70)
            self.queue.setColumnWidth(2, 130)
            self.queue.setMouseTracking(True)
            self.queue.setItemDelegate(GlassRowDelegate(self.queue, progress_col=2))
            self.queue.itemSelectionChanged.connect(self._song_selected)
            lay.addWidget(self.queue, 1)
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
            self.lyrics = QPlainTextEdit()
            self.lyrics.setPlaceholderText('Paste the lyrics here, one line per sung line.\n'
                                           'Lines like [Chorus] or (x2) are ignored.\n'
                                           'A .txt with the same name next to the audio loads automatically.')
            self.lyrics.setMaximumHeight(150)
            self.lyrics.textChanged.connect(self._lyrics_edited)
            lay.addWidget(self.lyrics)

            tools = QHBoxLayout()
            self.btn_play = PillButton('▶  Play from line')
            self.btn_play.clicked.connect(lambda: self._play_row(self.review.currentRow()))
            for txt, d in (('−0.1', -0.1), ('−0.01', -0.01), ('+0.01', 0.01), ('+0.1', 0.1)):
                b = PillButton(txt)
                b.setFixedWidth(64)
                b.clicked.connect(lambda _=False, d=d: self._nudge(d))
                tools.addWidget(b)
            tools.addWidget(self.btn_play)
            tools.addStretch(1)
            lay.addLayout(tools)
            self.review = ReviewTable()
            self.review.setMouseTracking(True)
            self.review.setItemDelegate(GlassRowDelegate(self.review))
            self.review.play_line.connect(self._play_row)
            self.review.itemChanged.connect(self._time_edited)
            lay.addWidget(self.review, 1)

            exp = QHBoxLayout()
            self.out_dir = QLineEdit()
            self.out_dir.setPlaceholderText('Output folder')
            self.out_dir.setReadOnly(True)
            self.btn_browse = PillButton('Browse…')
            self.btn_browse.clicked.connect(self._browse_out)
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
            self.btn_export.clicked.connect(lambda: self.app.export_current())
            row.addWidget(self.btn_export)
            row.addStretch(1)
            self.btn_about = PillButton('About')
            self.btn_about.clicked.connect(self._about)
            self.btn_theme = PillButton('Light')
            self.btn_theme.clicked.connect(self._toggle_theme)
            row.addWidget(self.btn_theme)
            row.addWidget(self.btn_about)
            lay.addLayout(row)
        return self._card(build)

    # ---------------------------------------------------------------- painting
    def paintEvent(self, _e):
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        rad = 0 if self.isMaximized() else RADIUS
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(t.bg_top))
        g.setColorAt(1, QColor(t.bg_bottom))
        if self._backdrop == 'gradient':
            p.fillPath(path, QBrush(g))
        else:
            p.fillPath(path, t.qcolor(t.tint))
        for c, pos in ((t.glow1, (0.15, 0.0)), (t.glow2, (0.95, 0.25))):
            gg = QLinearGradient(self.width() * pos[0], self.height() * pos[1],
                                 self.width() * (pos[0] + 0.5), self.height() * (pos[1] + 0.6))
            col = QColor(*c)
            gg.setColorAt(0, col)
            col2 = QColor(col)
            col2.setAlpha(0)
            gg.setColorAt(1, col2)
            p.fillPath(path, QBrush(gg))
        # Soft card shadows (stacked translucent rounded rects = cheap blur).
        p.setPen(Qt.NoPen)
        for card in self._cards:
            if not card.isVisible():
                continue
            g0 = QRectF(card.geometry())
            for i in range(10, 0, -1):
                sh = QColor(*t.shadow)
                sh.setAlpha(int(t.shadow[3] * (1 - i / 11) ** 2 / 3))
                p.setBrush(sh)
                p.drawRoundedRect(g0.adjusted(-i, -i + 6, i, i + 6), card.radius + i, card.radius + i)
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 46 if t.dark else 200), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

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
        winfx.enable_native_frame(hwnd)
        build = winfx.build()
        if build >= 22000 and winfx.set_mica(hwnd, self.theme.dark):
            self._backdrop = 'mica'
        elif winfx.set_acrylic(hwnd, 0xB0141820 if self.theme.dark else 0xC8F4F6FA):
            self._backdrop = 'acrylic'
            winfx.set_round_region(hwnd, self.width(), self.height(), RADIUS)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._backdrop == 'acrylic' and not self.isMaximized():
            winfx.set_round_region(int(self.winId()), self.width(), self.height(), RADIUS)

    def changeEvent(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.WindowStateChange and self._backdrop == 'acrylic':
            winfx.set_round_region(int(self.winId()), self.width(), self.height(), 0 if self.isMaximized() else RADIUS)
        super().changeEvent(e)

    def _toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _hit(self, pos):
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        if self.isMaximized():
            return self._caption_hit(pos)
        l, r, t, b = x < EDGE, x > w - EDGE, y < EDGE, y > h - EDGE
        if t and l:
            return winfx.HTTOPLEFT
        if t and r:
            return winfx.HTTOPRIGHT
        if b and l:
            return winfx.HTBOTTOMLEFT
        if b and r:
            return winfx.HTBOTTOMRIGHT
        if l:
            return winfx.HTLEFT
        if r:
            return winfx.HTRIGHT
        if t:
            return winfx.HTTOP
        if b:
            return winfx.HTBOTTOM
        return self._caption_hit(pos)

    def _caption_hit(self, pos):
        """Empty title-bar area acts as the native caption (drag, Aero Snap, double-click)."""
        if pos.y() < 46:
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
            if self.isMaximized():
                winfx.fix_maximized_rect(msg, int(self.winId()))
            return True, 0
        elif msg.message == winfx.WM_NCACTIVATE:
            return True, 1
        return False, 0

    def mousePressEvent(self, e):
        # Windows uses the native hit-test above; this path serves other platforms.
        if e.button() == Qt.LeftButton and self._hit(e.position().toPoint()) == winfx.HTCAPTION:
            if self.windowHandle() is None or not self.windowHandle().startSystemMove():
                self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif e.button() == Qt.LeftButton and not winfx.IS_WIN:
            hit = self._hit(e.position().toPoint())
            if hit != winfx.HTCLIENT:
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
        if e.position().y() < 46:
            self._toggle_max()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.app.add_songs([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ---------------------------------------------------------------- queue / review
    def refresh_queue(self, songs, current):
        self.queue.setRowCount(len(songs))
        for i, s in enumerate(songs):
            self.queue.setItem(i, 0, QTableWidgetItem(s.label()))
            self.queue.setItem(i, 1, QTableWidgetItem('%d lines' % len(split_lines(s.lyrics)) if s.lyrics.strip() else '—'))
            st = QTableWidgetItem(s.status)
            st.setToolTip(s.status)
            self.queue.setItem(i, 2, st)
        if 0 <= current < len(songs):
            self.queue.selectRow(current)
        self._update_buttons()

    def show_song(self, song):
        self._loading = True
        self.song_title.setText(song.label() if song else 'No song selected')
        self.lyrics.setPlainText(song.lyrics if song else '')
        idx = self.lang.findData(song.lang if song else 'auto')
        self.lang.setCurrentIndex(max(0, idx))
        self.review.setRowCount(0)
        if song and song.result:
            self._fill_review(song)
        self._loading = False
        self._update_buttons()

    def _fill_review(self, song):
        lines = song.result['lines']
        self.review.blockSignals(True)
        self.review.setRowCount(len(lines))
        for i, l in enumerate(lines):
            play = QTableWidgetItem('▶')
            play.setTextAlignment(Qt.AlignCenter)
            play.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.review.setItem(i, 0, play)
            txt = QTableWidgetItem(('↻ ' if l.get('repeat') else '') + l['text'])
            txt.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.review.setItem(i, 1, txt)
            st = QTableWidgetItem(fmt_lrc_time(l['start']))
            st.setTextAlignment(Qt.AlignCenter)
            st.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            self.review.setItem(i, 2, st)
            en = QTableWidgetItem(fmt_lrc_time(l['end']))
            en.setTextAlignment(Qt.AlignCenter)
            en.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.review.setItem(i, 3, en)
            note = l.get('flag') or ('placed' if l.get('guessed') else '')
            nt = QTableWidgetItem(note)
            nt.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if note:
                nt.setForeground(QColor('#e0a106'))
            self.review.setItem(i, 4, nt)
        self.review.blockSignals(False)

    def _song_selected(self):
        rows = self.queue.selectionModel().selectedRows()
        if rows and not getattr(self, '_loading', False):
            self.app.select(rows[0].row())

    def _lyrics_edited(self):
        if not getattr(self, '_loading', False):
            self.app.lyrics_changed(self.lyrics.toPlainText(), self.lang.currentData())

    def _update_buttons(self):
        busy = self.app.busy
        has = self.app.current() is not None
        synced = bool(has and self.app.current().result)
        for b in (self.btn_add, self.btn_remove, self.btn_sync, self.btn_all):
            b.setEnabled(not busy)
        self.btn_sync.setEnabled(not busy and has and bool(split_lines(self.app.current().lyrics)))
        self.btn_all.setEnabled(not busy and any(split_lines(s.lyrics) for s in self.app.songs))
        self.btn_export.setEnabled(synced and not busy)
        self.btn_cancel.setVisible(busy)

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
    def _nudge(self, delta):
        song = self.app.current()
        row = self.review.currentRow()
        if not song or not song.result or row < 0:
            return
        l = song.result['lines'][row]
        l['start'] = round(max(0.0, l['start'] + delta), 3)
        if row + 1 < len(song.result['lines']):
            l['end'] = min(l['end'], song.result['lines'][row + 1]['start'])
        l['end'] = round(max(l['end'], l['start']), 3)
        song.dirty = True
        self.review.item(row, 2).setText(fmt_lrc_time(l['start']))
        self.review.item(row, 3).setText(fmt_lrc_time(l['end']))

    def _time_edited(self, item):
        if item.column() != 2 or getattr(self, '_loading', False):
            return
        song = self.app.current()
        if not song or not song.result:
            return
        t = parse_time(item.text())
        l = song.result['lines'][item.row()]
        if t is None:
            item.setText(fmt_lrc_time(l['start']))
            return
        l['start'] = t
        l['end'] = round(max(l['end'], t), 3)
        song.dirty = True
        item.setText(fmt_lrc_time(t))
        self.review.item(item.row(), 3).setText(fmt_lrc_time(l['end']))

    def _play_row(self, row):
        song = self.app.current()
        if not song or not song.result or row < 0:
            return
        self.player.setSource(QUrl.fromLocalFile(song.path))
        self.player.setPosition(int(song.result['lines'][row]['start'] * 1000))
        self.player.play()

    # ---------------------------------------------------------------- export UI
    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(self, 'Output folder', self.out_dir.text() or os.path.expanduser('~'))
        if d:
            self.out_dir.setText(d)
            self.app.settings['out_dir'] = d
            self.app.save_settings()

    def export_options(self):
        return {'dir': self.out_dir.text().strip(), 'formats': [f for f, c in self.fmt_checks.items() if c.isChecked()],
                'bom': self.bom.isChecked()}

    def load_settings(self, s):
        self.out_dir.setText(s.get('out_dir', ''))
        for f, c in self.fmt_checks.items():
            c.setChecked(f in s.get('formats', ['ttml', 'lrc', 'srt', 'vtt']))
        self.bom.setChecked(bool(s.get('bom', False)))
        self.auto_export.setChecked(bool(s.get('auto_export', False)))
        self.bom.toggled.connect(lambda v: self._set('bom', v))
        self.auto_export.toggled.connect(lambda v: self._set('auto_export', v))
        for c in self.fmt_checks.values():
            c.toggled.connect(lambda _v: self._set('formats', [f for f, cc in self.fmt_checks.items() if cc.isChecked()]))
        self.lang.currentIndexChanged.connect(lambda _i: self._lyrics_edited())

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
        rows = self.queue.selectionModel().selectedRows()
        if rows:
            self.app.remove_song(rows[0].row())

    # ---------------------------------------------------------------- theme / about
    def _toggle_theme(self):
        self.theme = thememod.Theme(not self.theme.dark)
        self.app.settings['dark'] = self.theme.dark
        self.app.save_settings()
        self._apply_theme()
        if self._backdrop == 'mica':
            winfx.set_mica(int(self.winId()), self.theme.dark)
        elif self._backdrop == 'acrylic':
            winfx.set_acrylic(int(self.winId()), 0xB0141820 if self.theme.dark else 0xC8F4F6FA)

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
        super().closeEvent(e)


def export_song(song, options, meta_extra=None):
    """Write the chosen formats for one synced song. Returns the list of files written."""
    out_dir = options['dir']
    os.makedirs(out_dir, exist_ok=True)
    info = {'filename': os.path.basename(song.path), 'title': song.tags.get('title', ''), 'artist': song.tags.get('artist', '')}
    base = build_base_name(info)
    lines = [{'text': l['text'], 'time': l['start'], 'end': l['end'] + 0.4} for l in song.result['lines']]
    m = {'ti': info['title'], 'ar': info['artist'], 'al': song.tags.get('album', ''), 'lang': song.iso}
    written = []
    for fmt in options['formats']:
        path = os.path.join(out_dir, base + EXTS[fmt])
        text = build(fmt, lines, m, song.result.get('duration'))
        with open(path, 'wb') as f:
            f.write(encode_file(text, bom=(fmt == 'srt' and options.get('bom'))))
        written.append(path)
    return written


def read_tags(path):
    tags = {}
    try:
        from mutagen import File
        f = File(path, easy=True)
        if f and f.tags:
            for k in ('title', 'artist', 'album'):
                v = f.tags.get(k)
                if v:
                    tags[k] = str(v[0])
    except Exception:
        pass
    return tags
