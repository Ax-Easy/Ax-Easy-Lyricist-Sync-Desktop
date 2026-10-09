"""Glass cards, pill buttons, the rounded progress bar and the review table."""
from PySide6.QtCore import Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QAbstractItemView, QPushButton, QTableWidget, QWidget

from .theme import ACCENT, ACCENT_2

STATE = {'dark': True}  # current theme for custom-painted widgets
AMBER = '#E0A106'      # 'check this line' marker


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


from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem  # noqa: E402


class GlassRowDelegate(QStyledItemDelegate):
    """Rounded, readable row selection/hover spanning the whole row, and a mini rounded
    progress bar in the status column while a song is syncing ('Aligning lines 72%')."""

    def __init__(self, view, progress_col=None):
        super().__init__(view)
        self.view = view
        self.progress_col = progress_col

    def paint(self, p, opt, idx):
        view = self.view
        row_sel = view.selectionModel().isRowSelected(idx.row(), idx.parent()) if view.selectionModel() else False
        hover = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
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
        view.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, o, p, view)
