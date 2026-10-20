"""Glass cards, pill buttons, the rounded progress bar and the review table."""
from PySide6.QtCore import Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QAbstractItemView, QPushButton, QTableWidget, QWidget

from .theme import ACCENT, ACCENT_2

STATE = {'dark': True}  # current theme for custom-painted widgets
AMBER = '#E0A106'      # 'check this line' marker
WORDS_ROLE = Qt.UserRole + 2   # review text cell: [(word, unsure)] from Transcribe


class GlassCard(QWidget):
    """Rounded frosted card: top highlight, 1 px light border, soft shadow."""

    def __init__(self, theme, radius=13, shadow=True, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.radius = radius
        self.shadow = shadow  # drawn by GlassWindow behind the card (cheaper than QGraphicsEffect)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, _e):
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, t.qcolor(t.card_top))
        g.setColorAt(1, t.qcolor(t.card))
        p.fillPath(path, QBrush(g))
        p.setPen(QPen(t.qcolor(t.card_border), 1))
        p.drawPath(path)


class PillButton(QPushButton):
    """Rounded pill. kind: 'primary' (accent gradient), 'ghost' (glass), 'danger'."""

    def __init__(self, text, kind='ghost', parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self._hover = 0.0
        self._press = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(34)
        self.anim = QPropertyAnimation(self, b'hoverValue', self)
        self.anim.setDuration(140)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

    def _get_hover(self):
        return self._hover

    def _set_hover(self, v):
        self._hover = v
        self.update()

    hoverValue = Property(float, _get_hover, _set_hover)

    def enterEvent(self, e):
        self.anim.stop()
        self.anim.setEndValue(1.0)
        self.anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.anim.stop()
        self.anim.setEndValue(0.0)
        self.anim.start()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._press = True
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = False
        self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        on = self.isEnabled()
        if self.kind == 'primary':
            g = QLinearGradient(0, 0, 0, self.height())
            top = QColor(ACCENT_2).lighter(100 + int(12 * self._hover))
            g.setColorAt(0, top)
            g.setColorAt(1, QColor(ACCENT))
            p.fillPath(path, QBrush(g))
            p.setPen(QPen(QColor(255, 255, 255, 70), 1))
            color = QColor('#ffffff')
        elif self.kind == 'danger':
            p.fillPath(path, QColor(214, 54, 56, 40 + int(40 * self._hover)))
            p.setPen(QPen(QColor(214, 54, 56, 160), 1))
            color = QColor('#ff8a8c')
        else:
            if STATE['dark']:
                p.fillPath(path, QColor(255, 255, 255, int(20 + 18 * self._hover)))
                p.setPen(QPen(QColor(255, 255, 255, 46), 1))
            else:
                p.fillPath(path, QColor(255, 255, 255, int(170 + 60 * self._hover)))
                p.setPen(QPen(QColor(20, 25, 40, 40), 1))
            color = QColor(self.palette().color(QPalette.ColorRole.ButtonText))
        if not on:
            p.fillPath(path, QColor(128, 128, 128, 60))
            color = QColor(color)
            color.setAlpha(110)
        p.setPen(color)
        f = QFont(self.font())
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        dy = 1 if self._press else 0
        p.drawText(self.rect().adjusted(0, dy, 0, dy), Qt.AlignCenter, self.text())


class IconPillButton(PillButton):
    """Pill with a painted icon ('update': circular arrows) and an optional badge dot."""

    def __init__(self, text, icon='update', kind='ghost', parent=None):
        super().__init__('      ' + text, kind, parent)
        self.icon = icon
        self._badge = False
        self.setMinimumWidth(104)

    def set_badge(self, on):
        self._badge = bool(on)
        self.update()

    def badge(self):
        return self._badge

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(self.palette().color(QPalette.ColorRole.ButtonText))
        if not self.isEnabled():
            col.setAlpha(110)
        fm = self.fontMetrics()
        tw = fm.horizontalAdvance(self.text().strip())
        cx = self.width() / 2 - tw / 2 - 6
        cy = self.height() / 2 + (1 if self._press else 0)
        r = 5.5
        pen = QPen(col, 1.6, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        # two arcs with arrow heads = circular arrows
        p.drawArc(box, 30 * 16, 150 * 16)
        p.drawArc(box, 210 * 16, 150 * 16)
        import math
        for ang in (30, 210):
            a = math.radians(ang)
            x, y = cx + r * math.cos(a), cy - r * math.sin(a)
            # arrow head pointing along the clockwise tangent
            tx, ty = math.sin(a), math.cos(a)
            nx, ny = math.cos(a), -math.sin(a)
            p.drawLine(QPointF(x, y), QPointF(x - 3.2 * tx + 2.4 * nx, y - 3.2 * ty + 2.4 * ny))
            p.drawLine(QPointF(x, y), QPointF(x - 3.2 * tx - 2.4 * nx, y - 3.2 * ty - 2.4 * ny))
        if self._badge:
            p.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(QPointF(self.width() - 13, 9), 4.5, 4.5)


class GlassProgress(QWidget):
    """Rounded progress bar with an accent gradient chunk and a percent label; thin=True
    for step rows (no label); indeterminate mode animates a glass sweep."""

    def __init__(self, parent=None, thin=False):
        super().__init__(parent)
        self._pct = 0.0
        self.thin = thin
        self._ind = False
        self._pos = 0.0
        h = 8 if thin else 16
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        self._anim = None

    def set_value(self, pct):
        pct = max(0.0, min(1.0, pct))
        if abs(pct - self._pct) > 1e-4:
            self._pct = pct
            self.update()

    def set_indeterminate(self, on):
        on = bool(on)
        if on == self._ind:
            return
        self._ind = on
        from PySide6.QtCore import QTimer
        if on:
            self._anim = QTimer(self)
            self._anim.timeout.connect(self._tick)
            # 10 fps: on a translucent (layered) window every frame re-uploads the whole window
            # to the compositor, so a smooth 30 fps bar costs real CPU while setup is busy
            self._anim.start(100)
        elif self._anim:
            self._anim.stop()
            self._anim = None
        self.update()

    def _tick(self):
        self._pos = (self._pos + 0.054) % 1.4
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = r.height() / 2
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.fillPath(path, QColor(255, 255, 255, 18) if STATE['dark'] else QColor(20, 25, 40, 22))
        if self._ind:
            p.setClipPath(path)
            w = r.width() * 0.3
            x = r.x() + (self._pos - 0.3) * r.width()
            g = QLinearGradient(x, 0, x + w, 0)
            c0 = QColor(ACCENT)
            c0.setAlpha(0)
            g.setColorAt(0, c0)
            g.setColorAt(0.5, QColor(ACCENT_2))
            g.setColorAt(1, c0)
            c = QPainterPath()
            c.addRoundedRect(QRectF(x, r.y(), w, r.height()), rad, rad)
            p.fillPath(c, QBrush(g))
            return
        if self.thin:
            if self._pct > 0:
                c = QPainterPath()
                c.addRoundedRect(QRectF(r.x(), r.y(), max(r.height(), r.width() * self._pct), r.height()), rad, rad)
                g = QLinearGradient(0, 0, r.width(), 0)
                g.setColorAt(0, QColor(ACCENT_2))
                g.setColorAt(1, QColor(ACCENT))
                p.setClipPath(path)
                p.fillPath(c, QBrush(g))
            return
        if self._pct > 0:
            w = max(16, r.width() * self._pct)
            c = QPainterPath()
            c.addRoundedRect(QRectF(r.x(), r.y(), w, r.height()), 8, 8)
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0, QColor(ACCENT_2))
            g.setColorAt(1, QColor(ACCENT))
            p.setClipPath(path)
            p.fillPath(c, QBrush(g))
        p.setPen(QColor('#ffffff') if (STATE['dark'] or self._pct > 0.55) else QColor('#14171F'))
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, '%d%%' % round(self._pct * 100))


class ReviewTable(QTableWidget):
    """Line review list: ▶ | line | start | end | note. Start is editable (double-click)."""
    play_line = Signal(int)

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(['', 'Line', 'Start', 'End', 'Note'])
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(32)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setWordWrap(False)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(1, hh.ResizeMode.Stretch)
        for i, w in ((0, 34), (2, 84), (3, 84), (4, 92)):
            self.setColumnWidth(i, w)
        self.cellClicked.connect(lambda r, c: self.play_line.emit(r) if c == 0 else None)
        self._active_row = -1   # the line playing now (painted by GlassRowDelegate)


from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem  # noqa: E402


class GlassRowDelegate(QStyledItemDelegate):
    """Rounded, readable row selection/hover spanning the whole row, and a mini rounded
    progress bar in the status column while a song is syncing ('Aligning lines 72%').
    Review list: in-place editing of the line text (col 1) and the times (cols 2, 3, as
    mm:ss.xxx). The edit is not written to the item: `edited(row, col, text)` is emitted and the
    window applies it (undo history, lyrics box, waveform). `split(row, cursor, text)` comes from
    the editor's right-click "Split line at cursor"."""
    edited = Signal(int, int, str)
    split = Signal(int, int, str)
    TIME_ROLE = Qt.UserRole + 3     # seconds of the start / end cells

    def __init__(self, view, progress_col=None):
        super().__init__(view)
        self.view = view
        self.progress_col = progress_col
        self.editor = None

    def createEditor(self, parent, opt, idx):
        from PySide6.QtWidgets import QLineEdit
        e = QLineEdit(parent)
        e.setObjectName('inlineEdit')
        e.setFrame(False)
        if idx.column() in (2, 3):
            e.setAlignment(Qt.AlignCenter)
            e.setToolTip('mm:ss.xxx — Enter saves, Esc cancels')
        else:
            e.setToolTip('Enter saves, Esc cancels · right-click: Split line at cursor')
            e.setContextMenuPolicy(Qt.CustomContextMenu)
            e.customContextMenuRequested.connect(lambda pos, e=e, r=idx.row(): self._editor_menu(e, r, pos))
        self.editor = e
        e.destroyed.connect(lambda *_a: setattr(self, 'editor', None))
        return e

    def _editor_menu(self, e, row, pos):
        m = e.createStandardContextMenu()
        m.addSeparator()
        a = m.addAction('Split line at cursor')
        a.setEnabled(bool(e.text().strip()) and 0 < e.cursorPosition() < len(e.text()))
        a.triggered.connect(lambda: self._split_now(e, row))
        m.exec(e.mapToGlobal(pos))

    def _split_now(self, e, row):
        cur, text = e.cursorPosition(), e.text()
        self.closeEditor.emit(e, QStyledItemDelegate.EndEditHint.RevertModelCache)
        self.split.emit(row, cur, text)

    def setEditorData(self, e, idx):
        if idx.column() in (2, 3):
            t = idx.data(self.TIME_ROLE)
            if t is not None:
                ms = int(round(float(t) * 1000))
                e.setText('%02d:%02d.%03d' % (ms // 60000, (ms % 60000) // 1000, ms % 1000))
            else:
                e.setText(str(idx.data() or ''))
        else:
            t = str(idx.data() or '')
            e.setText(t[2:] if t.startswith('↻ ') else t)
        e.selectAll()

    def setModelData(self, e, model, idx):
        self.edited.emit(idx.row(), idx.column(), e.text())

    def updateEditorGeometry(self, e, opt, idx):
        e.setGeometry(opt.rect.adjusted(2, 3, -2, -3))

    def paint(self, p, opt, idx):
        view = self.view
        row_sel = view.selectionModel().isRowSelected(idx.row(), idx.parent()) if view.selectionModel() else False
        hover = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        active = getattr(view, '_active_row', -1) == idx.row()
        inst = idx.column() >= 0 and view.model().index(idx.row(), 1).data(Qt.UserRole + 1) == 'inst'
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if inst or active:
            first = view.visualRect(view.model().index(idx.row(), 0))
            last = view.visualRect(view.model().index(idx.row(), view.model().columnCount() - 1))
            full = QRectF(first.left() + 2, opt.rect.top() + 2, last.right() - first.left() - 4, opt.rect.height() - 4)
            path = QPainterPath()
            path.addRoundedRect(full, 9, 9)
            p.setClipRect(opt.rect)
            if inst:   # ♪ rows: a quiet violet band
                p.fillPath(path, QColor(143, 123, 255, 30 if STATE['dark'] else 24))
            if active:  # the line playing now: accent glow + a bar on the left
                g = QLinearGradient(full.left(), 0, full.right(), 0)
                g.setColorAt(0, QColor(255, 106, 1, 90 if STATE['dark'] else 70))
                g.setColorAt(1, QColor(255, 106, 1, 8))
                p.fillPath(path, QBrush(g))
                if idx.column() == 0:
                    p.fillRect(QRectF(full.left() + 1, full.top() + 5, 3, full.height() - 10), QColor(ACCENT))
            p.setClipping(False)
        if row_sel or hover:
            first = view.visualRect(view.model().index(idx.row(), 0))
            last = view.visualRect(view.model().index(idx.row(), view.model().columnCount() - 1))
            full = QRectF(first.left() + 2, opt.rect.top() + 2, last.right() - first.left() - 4, opt.rect.height() - 4)
            path = QPainterPath()
            path.addRoundedRect(full, 9, 9)
            p.setClipRect(opt.rect)
            if row_sel:
                p.fillPath(path, QColor(255, 106, 1, 62 if STATE['dark'] else 46))
                p.setPen(QPen(QColor(255, 140, 60, 120), 1))
                p.drawPath(path)
            else:
                p.fillPath(path, QColor(255, 255, 255, 14) if STATE['dark'] else QColor(20, 25, 40, 12))
        p.restore()
        text = str(idx.data() or '')
        if self.progress_col is not None and idx.column() == self.progress_col and text.endswith('%'):
            try:
                pct = float(text.rsplit(' ', 1)[1][:-1]) / 100
            except ValueError:
                pct = 0
            p.save()
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(opt.rect).adjusted(6, opt.rect.height() / 2 - 5, -8, -(opt.rect.height() / 2 - 5))
            track = QPainterPath()
            track.addRoundedRect(r, 5, 5)
            p.fillPath(track, QColor(255, 255, 255, 26) if STATE['dark'] else QColor(20, 25, 40, 26))
            if pct > 0:
                c = QPainterPath()
                c.addRoundedRect(QRectF(r.x(), r.y(), max(10, r.width() * pct), r.height()), 5, 5)
                g = QLinearGradient(r.x(), 0, r.right(), 0)
                g.setColorAt(0, QColor(ACCENT_2))
                g.setColorAt(1, QColor(ACCENT))
                p.fillPath(c, QBrush(g))
            p.restore()
            return
        o = QStyleOptionViewItem(opt)
        self.initStyleOption(o, idx)
        o.state &= ~QStyle.StateFlag.State_Selected
        o.state &= ~QStyle.StateFlag.State_HasFocus
        o.state &= ~QStyle.StateFlag.State_MouseOver
        words = idx.data(WORDS_ROLE)
        if words:
            o.text = ''
        view.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, o, p, view)
        if words:   # Transcribe: draw the words ourselves, the unsure ones in amber
            self._paint_words(p, o, words, view)

    def _paint_words(self, p, o, words, view):
        p.save()
        r = view.style().subElementRect(QStyle.SubElement.SE_ItemViewItemText, o, view).adjusted(3, 0, -3, 0)
        p.setClipRect(r)
        p.setFont(o.font)
        fm = p.fontMetrics()
        base = o.palette.color(QPalette.ColorRole.Text)
        x = r.left()
        y = r.top() + (r.height() + fm.ascent() - fm.descent()) / 2
        space = fm.horizontalAdvance(' ')
        for w, low in words:
            w = w.strip()
            wd = fm.horizontalAdvance(w)
            if x + wd > r.right():
                p.setPen(base)
                p.drawText(QPointF(x, y), '…')
                break
            p.setPen(QColor(AMBER) if low else base)
            p.drawText(QPointF(x, y), w)
            if low:
                p.drawLine(QPointF(x, y + 2.5), QPointF(x + wd, y + 2.5))
            x += wd + space
        p.restore()


class Knob(QWidget):
    """Round glass knob. Drag up/down (or left/right), wheel, arrow keys; double-click resets to the default.
    kind 'volume': arc from the minimum; kind 'pan': arc from the top centre. valueChanged(float) while turning,
    released(float) when a drag / wheel / key change ends (to save the setting)."""
    valueChanged = Signal(float)
    released = Signal(float)
    SWEEP = 270.0

    def __init__(self, kind='volume', minimum=0.0, maximum=1.0, default=1.0, label='', fmt=None, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        self.kind, self.lo, self.hi, self.default = kind, minimum, maximum, default
        self.label, self.fmt = label, fmt or (lambda v: '%d %%' % round(v * 100))
        self._v = default
        self._drag = None
        self._hover = False
        self.setFixedSize(34, 34)
        self.setCursor(Qt.SizeVerCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self._done = QTimer(self)
        self._done.setSingleShot(True)
        self._done.setInterval(400)
        self._done.timeout.connect(lambda: self.released.emit(self._v))
        self._tip()

    def value(self):
        return self._v

    def setValue(self, v, emit=False):
        v = max(self.lo, min(self.hi, float(v)))
        if self.kind == 'pan' and abs(v) < 0.025:
            v = 0.0  # a little detent at the centre
        if v == self._v:
            return
        self._v = v
        self._tip()
        self.update()
        if emit:
            self.valueChanged.emit(v)

    def text(self):
        return '%s: %s' % (self.label, self.fmt(self._v)) if self.label else self.fmt(self._v)

    def _tip(self):
        self.setToolTip('%s\nDrag, scroll or use the arrow keys · double-click resets' % self.text())
        self.setAccessibleName(self.text())

    def _show_tip(self):
        from PySide6.QtWidgets import QToolTip
        QToolTip.showText(self.mapToGlobal(QPoint(self.width() // 2, self.height() + 4)), self.text(), self)

    def _nudge(self, steps):
        span = self.hi - self.lo
        self.setValue(self._v + steps * span / 50.0, emit=True)
        self._show_tip()
        self._done.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position(), self._v)
            self.setFocus()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        p0, v0 = self._drag
        d = (p0.y() - e.position().y()) + (e.position().x() - p0.x())
        self.setValue(v0 + d / 150.0 * (self.hi - self.lo), emit=True)
        self._show_tip()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.released.emit(self._v)

    def mouseDoubleClickEvent(self, e):
        self._drag = None
        self.setValue(self.default, emit=True)
        self._show_tip()
        self.released.emit(self._v)

    def wheelEvent(self, e):
        dy = e.angleDelta().y() or e.angleDelta().x()
        if dy:
            self._nudge(1 if dy > 0 else -1)
        e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Up, Qt.Key_Right):
            self._nudge(1)
        elif k in (Qt.Key_Down, Qt.Key_Left):
            self._nudge(-1)
        elif k in (Qt.Key_PageUp, Qt.Key_PageDown):
            self._nudge(5 if k == Qt.Key_PageUp else -5)
        elif k in (Qt.Key_Home, Qt.Key_End, Qt.Key_0):
            self.setValue(self.default if k != Qt.Key_End else self.hi, emit=True)
            self._done.start()
        else:
            super().keyPressEvent(e)  # Space etc. still reach the window

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def _angle(self, v):
        """Degrees clockwise from 12 o'clock."""
        return -self.SWEEP / 2 + (v - self.lo) / (self.hi - self.lo) * self.SWEEP

    def paintEvent(self, _e):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = STATE['dark']
        side = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        r_ring = side / 2 - 2.5
        r_body = r_ring - 4
        on = self.isEnabled()
        # track
        ring = QRectF(c.x() - r_ring, c.y() - r_ring, 2 * r_ring, 2 * r_ring)
        pen = QPen(QColor(255, 255, 255, 38) if dark else QColor(20, 25, 40, 34), 3)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        start = 90 - self._angle(self.lo)  # Qt arcs: 0 = 3 o'clock, counter-clockwise, 1/16 degree
        p.drawArc(ring, int(start * 16), int(-self.SWEEP * 16))
        # value arc
        a0 = self._angle(0.0 if self.kind == 'pan' else self.lo)
        a1 = self._angle(self._v)
        if abs(a1 - a0) > 0.5:
            pen = QPen(QColor(ACCENT) if on else QColor(128, 128, 128), 3)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(ring, int((90 - a0) * 16), int(-(a1 - a0) * 16))
        # glass body
        body = QRectF(c.x() - r_body, c.y() - r_body, 2 * r_body, 2 * r_body)
        g = QLinearGradient(0, body.top(), 0, body.bottom())
        if dark:
            g.setColorAt(0, QColor(255, 255, 255, 52 + (14 if self._hover else 0)))
            g.setColorAt(1, QColor(255, 255, 255, 16))
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        else:
            g.setColorAt(0, QColor(255, 255, 255, 250))
            g.setColorAt(1, QColor(255, 255, 255, 170 + (40 if self._hover else 0)))
            p.setPen(QPen(QColor(20, 25, 40, 46), 1))
        p.setBrush(QBrush(g))
        p.drawEllipse(body)
        if self.hasFocus():
            p.setPen(QPen(QColor(ACCENT_2), 1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(body.adjusted(-1, -1, 1, 1))
        # pointer
        rad = math.radians(a1)
        dx, dy = math.sin(rad), -math.cos(rad)
        pen = QPen(QColor(ACCENT) if on else QColor(128, 128, 128), 2.2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(c.x() + dx * r_body * 0.25, c.y() + dy * r_body * 0.25),
                   QPointF(c.x() + dx * (r_body - 2.5), c.y() + dy * (r_body - 2.5)))
        # tiny glyph in the middle: L|R for pan, a dot for volume
        col = QColor('#F2F4F8') if dark else QColor('#4A5160')
        col.setAlpha(150)
        p.setPen(col)
        f = QFont(self.font())
        f.setPixelSize(7)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        if self.kind == 'pan':
            p.drawText(QRectF(c.x() - r_ring, c.y() + r_ring - 9, 9, 9), Qt.AlignCenter, 'L')
            p.drawText(QRectF(c.x() + r_ring - 9, c.y() + r_ring - 9, 9, 9), Qt.AlignCenter, 'R')
        else:
            p.drawText(QRectF(c.x() - r_ring, c.y() + r_ring - 9, 9, 9), Qt.AlignCenter, '−')
            p.drawText(QRectF(c.x() + r_ring - 9, c.y() + r_ring - 9, 9, 9), Qt.AlignCenter, '+')
