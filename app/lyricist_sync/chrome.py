"""Window chrome for the frameless glass windows and dialogs.

Three code paths, chosen once per process:
  'mac'     macOS main window: the real title bar with the traffic lights over a full-size
            content view, behind-window vibrancy (NSVisualEffectView) under a translucent tint;
            the system rounds the corners and draws the shadow. Dialogs use 'painted'.
  'win11'   Windows 11 (build >= 22000): DWM rounded corners + Mica + the DWM shadow.
  'painted' Windows 10 and everything else (and --force-win10-style): no window-wide
            acrylic (it blurs the whole rectangle and shows square edges); the window is
            transparent, the glass is painted as a rounded rect inside a transparent
            margin that carries a painted soft drop shadow. Nothing is drawn outside the
            rounded shape except that shadow. The margin goes away when maximized."""
import os
import random

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPixmap, QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from . import macfx, winfx

RADIUS = 16
MARGIN = 20          # transparent shadow margin (px) on the painted path
FORCE_WIN10 = os.environ.get('LYRICIST_SYNC_FORCE_WIN10') == '1'


def mode():
    if macfx.IS_MAC:
        return 'mac'
    if not FORCE_WIN10 and winfx.IS_WIN and winfx.build() >= 22000:
        return 'win11'
    return 'painted'


def force_win10(on=True):
    global FORCE_WIN10
    FORCE_WIN10 = on


def label():
    """Honest description of the active code path (for screenshots/About)."""
    if mode() == 'mac':
        return 'macOS path: native title bar (traffic lights) + vibrancy (NSVisualEffectView)'
    if mode() == 'win11':
        return 'Windows 11 path: DWM rounded corners + Mica + DWM shadow'
    if FORCE_WIN10 and winfx.IS_WIN and winfx.build() >= 22000:
        return 'Windows 10 path (forced with --force-win10-style): painted glass + painted shadow'
    return 'Windows 10 path: painted glass + painted shadow'


_NOISE = None


def noise():
    """128x128 tile of faint grain that makes flat paint read as frosted glass."""
    global _NOISE
    if _NOISE is None:
        rnd = random.Random(7)
        buf = bytearray(128 * 128 * 4)
        for i in range(0, len(buf), 4):
            v, a = rnd.randint(0, 255), rnd.randint(0, 9)
            pv = v * a // 255  # premultiplied BGRA
            buf[i:i + 4] = bytes((pv, pv, pv, a))
        _NOISE = QImage(bytes(buf), 128, 128, 128 * 4, QImage.Format_ARGB32_Premultiplied).copy()
    return _NOISE


def paint_shadow(p, body, radius, dark, strength=1.0):
    """Soft drop shadow around `body` (QRectF), layered translucent rounded rects."""
    p.save()
    p.setPen(Qt.NoPen)
    n = MARGIN - 2
    base = (0, 0, 0, 90 if dark else 46)
    for i in range(n, 0, -1):
        f = (1 - i / (n + 1)) ** 2.2
        c = QColor(*base[:3], int(base[3] * f * strength / 5.5))
        p.setBrush(c)
        r = body.adjusted(-i, -i + 4, i, i + 6)
        p.drawRoundedRect(r, radius + i * 0.9, radius + i * 0.9)
    # contact shadow right under the edge
    p.setBrush(QColor(0, 0, 0, 40 if dark else 22))
    p.drawRoundedRect(body.adjusted(-1, 0, 1, 2), radius + 1, radius + 1)
    p.restore()


def paint_glass(p, body, radius, theme, backdrop, glows=True):
    """The glass body. backdrop: 'painted' (semi-opaque gradient + grain + sheen) or
    'mica' (light tint over the OS backdrop)."""
    t = theme
    path = QPainterPath()
    path.addRoundedRect(body, radius, radius)
    p.save()
    p.setClipPath(path)
    if backdrop in ('mica', 'vibrancy'):
        p.fillPath(path, t.qcolor(t.tint))
    else:
        g = QLinearGradient(body.topLeft(), body.bottomRight())
        top, bot = QColor(t.bg_top), QColor(t.bg_bottom)
        top.setAlpha(242 if t.dark else 238)
        bot.setAlpha(248 if t.dark else 244)
        g.setColorAt(0, top)
        g.setColorAt(1, bot)
        p.fillPath(path, QBrush(g))
    if glows:
        for c, (cx, cy, rr) in ((t.glow1, (0.12, 0.0, 0.75)), (t.glow2, (0.98, 0.3, 0.7))):
            rg = QRadialGradient(body.x() + body.width() * cx, body.y() + body.height() * cy, max(body.width(), body.height()) * rr)
            col = QColor(*c)
            rg.setColorAt(0, col)
            col2 = QColor(col)
            col2.setAlpha(0)
            rg.setColorAt(1, col2)
            p.fillPath(path, QBrush(rg))
    if backdrop not in ('mica', 'vibrancy'):
        p.fillPath(path, QBrush(noise()))
        sheen = QLinearGradient(body.x(), body.y(), body.x(), body.y() + min(140.0, body.height() * 0.3))
        sheen.setColorAt(0, QColor(255, 255, 255, 22 if t.dark else 70))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(sheen))
    p.restore()
    # 1 px light rim, brighter at the top
    rim = QLinearGradient(body.x(), body.y(), body.x(), body.bottom())
    rim.setColorAt(0, QColor(255, 255, 255, 70 if t.dark else 235))
    rim.setColorAt(1, QColor(255, 255, 255, 22 if t.dark else 150))
    p.setPen(QPen(QBrush(rim), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


class Frame:
    """Mixin state for GlassWindow/GlassDialog: margin, body rect, hit-testing."""

    EDGE = 4       # resize band inside the visible edge (px)
    EDGE_OUT = 8   # ...and outside it, like the invisible borders of native Windows 10 windows

    def init_frame(self, native=False):
        """native: the main window (macOS: real title bar + vibrancy). Dialogs stay painted on a Mac."""
        self._mode = mode()
        if self._mode == 'mac' and not native:
            self._mode = 'painted'
        self._backdrop = 'mica' if self._mode == 'win11' else 'painted'

    def margin(self):
        if self._mode != 'painted' or self.isMaximized() or self.isFullScreen():
            return 0
        return MARGIN

    def radius(self):
        if self._mode == 'mac':   # the system clips the window to its own rounded corners
            return 0
        return 0 if (self.isMaximized() or self.isFullScreen()) else RADIUS

    def body_rect(self):
        m = self.margin()
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def edge_hit(self, x, y):
        """Resize hit on the visible edge (+-EDGE), transparent in the rest of the shadow
        margin, None inside the body."""
        if self.isMaximized():
            return None
        b = self.body_rect()
        E, O = self.EDGE, (self.EDGE_OUT if self.margin() else 0)
        inside_x = b.left() - O <= x <= b.right() + O
        inside_y = b.top() - O <= y <= b.bottom() + O
        if not (inside_x and inside_y):
            return winfx.HTTRANSPARENT
        l, r = x < b.left() + E, x > b.right() - E
        t, bt = y < b.top() + E, y > b.bottom() - E
        # rounded corners: use a slightly larger diagonal zone
        C = RADIUS * 0.6
        if (t or y < b.top() + C) and (l or x < b.left() + C) and (t or l):
            return winfx.HTTOPLEFT
        if (t or y < b.top() + C) and (r or x > b.right() - C) and (t or r):
            return winfx.HTTOPRIGHT
        if (bt or y > b.bottom() - C) and (l or x < b.left() + C) and (bt or l):
            return winfx.HTBOTTOMLEFT
        if (bt or y > b.bottom() - C) and (r or x > b.right() - C) and (bt or r):
            return winfx.HTBOTTOMRIGHT
        if l:
            return winfx.HTLEFT
        if r:
            return winfx.HTRIGHT
        if t:
            return winfx.HTTOP
        if bt:
            return winfx.HTBOTTOM
        return None


def cached_background(widget, key, paint):
    """The window background (shadow + glass) is the expensive part of every repaint; paint it
    once per size/theme into a pixmap and blit it. Progress updates then only redraw small
    regions, which keeps the UI thread free even on a busy CPU."""
    dpr = widget.devicePixelRatioF()
    full = (widget.width(), widget.height(), dpr) + tuple(key)
    c = getattr(widget, '_bg_cache', None)
    if c is None or c[0] != full:
        pm = QPixmap(max(1, int(widget.width() * dpr)), max(1, int(widget.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.Antialiasing)
        paint(q)
        q.end()
        c = (full, pm)
        widget._bg_cache = c
    return c[1]
