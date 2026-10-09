"""Render the (light, so the Finder's black icon labels stay readable) DMG window background (660x420 @1x and @2x): Ax-Easy glass, the app icon slot on
the left, an arrow, the Applications slot on the right, and the instruction.
  python mac/make_dmg_background.py OUTDIR   (needs PySide6; QT_QPA_PLATFORM=offscreen works)"""
import os
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

W, H = 660, 420
ICON_Y = 205          # icon centres (dmgbuild icon_locations use the same numbers)
LEFT_X, RIGHT_X = 170, 490


def render(scale, path):
    img = QImage(int(W * scale), int(H * scale), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor('#EEF1F7'))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(scale, scale)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor('#F4F6FA'))
    g.setColorAt(1, QColor('#DCE2EC'))
    p.fillRect(QRectF(0, 0, W, H), g)
    for col, (cx, cy, r) in ((QColor(255, 140, 60, 80), (0.1, 0.0, 420)), (QColor(90, 140, 255, 60), (1.0, 0.85, 380))):
        rg = QRadialGradient(W * cx, H * cy, r)
        rg.setColorAt(0, col)
        c2 = QColor(col)
        c2.setAlpha(0)
        rg.setColorAt(1, c2)
        p.fillRect(QRectF(0, 0, W, H), rg)
    # glass card behind the two icons
    card = QRectF(40, 92, W - 80, 226)
    shape = QPainterPath()
    shape.addRoundedRect(card, 24, 24)
    p.fillPath(shape, QColor(255, 255, 255, 150))
    p.setPen(QPen(QColor(255, 255, 255, 230), 1))
    p.drawPath(shape)
    # arrow
    p.setPen(QPen(QColor('#FF6A01'), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    a, b = QPointF(LEFT_X + 88, ICON_Y), QPointF(RIGHT_X - 88, ICON_Y)
    p.drawLine(a, b)
    p.drawLine(b, QPointF(b.x() - 16, b.y() - 14))
    p.drawLine(b, QPointF(b.x() - 16, b.y() + 14))
    f = QFont()
    f.setFamilies(['Helvetica Neue', 'Helvetica', 'Arial', 'DejaVu Sans'])
    f.setPixelSize(26)
    f.setWeight(QFont.DemiBold)
    p.setFont(f)
    p.setPen(QColor('#14171F'))
    p.drawText(QRectF(0, 26, W, 40), Qt.AlignHCenter | Qt.AlignVCenter, 'Ax-Easy Lyricist Sync')
    f.setPixelSize(15)
    f.setWeight(QFont.Normal)
    p.setFont(f)
    p.setPen(QColor('#4A5160'))
    p.drawText(QRectF(0, 336, W, 24), Qt.AlignHCenter | Qt.AlignVCenter, 'Drag Lyricist Sync onto Applications to install')
    f.setPixelSize(12)
    p.setFont(f)
    p.setPen(QColor('#79808E'))
    p.drawText(QRectF(0, 366, W, 20), Qt.AlignHCenter | Qt.AlignVCenter,
               'Made by Ax-Easy with the help of Grok  ·  Inspired by the music of Monitored')
    p.end()
    img.save(path)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else '.'
    os.makedirs(out, exist_ok=True)
    app = QGuiApplication(sys.argv[:1])
    render(1, os.path.join(out, 'dmg-background.png'))
    render(2, os.path.join(out, 'dmg-background@2x.png'))
