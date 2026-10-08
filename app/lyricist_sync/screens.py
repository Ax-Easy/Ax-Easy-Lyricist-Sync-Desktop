"""Render marketing/QA screenshots of the window (before and after a sync) composited on a
blurred wallpaper so the glass effect is visible even where no OS backdrop exists."""
import glob
import json
import os
import tempfile

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QRadialGradient, QLinearGradient
from PySide6.QtWidgets import QApplication


def wallpaper(w, h, dark):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor('#0d1424' if dark else '#dfe7f5'))
    g.setColorAt(1, QColor('#1a0f24' if dark else '#f6e9e0'))
    p.fillRect(0, 0, w, h, g)
    blobs = [((0.18, 0.22), 0.42, '#ff6a01'), ((0.85, 0.30), 0.38, '#2f6bff'), ((0.55, 0.92), 0.45, '#9b4dff'),
             ((0.95, 0.95), 0.30, '#00c2a8'), ((0.05, 0.85), 0.28, '#ff3d7f')]
    for (cx, cy), r, col in blobs:
        rg = QRadialGradient(QPointF(cx * w, cy * h), r * max(w, h))
        c = QColor(col)
        c.setAlpha(200 if dark else 150)
        rg.setColorAt(0, c)
        c2 = QColor(col)
        c2.setAlpha(0)
        rg.setColorAt(1, c2)
        p.fillRect(0, 0, w, h, rg)
    p.end()
    return img


def blur(img, k=28):
    small = img.scaled(max(1, img.width() // k), max(1, img.height() // k), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(img.width(), img.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def compose(win_img, dark, radius=16):
    mw, mh = 110, 90
    w, h = win_img.width() + 2 * mw, win_img.height() + 2 * mh
    bg = wallpaper(w, h, dark)
    bl = blur(bg)
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawImage(0, 0, bg)
    r = QRectF(mw, mh, win_img.width(), win_img.height())
    p.setPen(Qt.NoPen)
    for i in range(36, 0, -2):
        p.setBrush(QColor(0, 0, 0, int(9 * (1 - i / 38))))
        p.drawRoundedRect(r.adjusted(-i * 0.6, -i * 0.3 + 14, i * 0.6, i * 0.9 + 14), radius + i, radius + i)
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    p.setClipPath(path)
    p.drawImage(0, 0, bl)
    p.setClipping(False)
    p.drawImage(int(r.x()), int(r.y()), win_img)
    p.end()
    return out


def _grab(widget, dark, path):
    QApplication.processEvents()
    img = widget.grab().toImage()
    compose(img, dark).save(path)
    print('saved', path, flush=True)


def render(out_dir, fixture_dir=None):
    os.environ['LYRICIST_SYNC_HOME'] = tempfile.mkdtemp(prefix='lsync-screens-')
    os.makedirs(out_dir, exist_ok=True)
    from .app import App
    from .lyrics import split_lines
    qapp = QApplication.instance() or QApplication(['LyricistSync'])
    from . import theme as thememod
    qapp.setFont(thememod.ui_font())
    fixture_dir = fixture_dir or os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'fixtures')
    audios = sorted(glob.glob(os.path.join(fixture_dir, 'demo_*.mp3')))
    for dark in (True, False):
        name = 'dark' if dark else 'light'
        app = App(qapp, screenshot=True, dark=dark)
        win = app.win
        win._backdrop = 'acrylic'   # paint the translucent tint; compose() supplies the blur
        win.resize(1280, 820)
        win.show()
        app.add_songs(audios)
        win.set_device({'text': 'Engine ready'})
        _grab(win, dark, os.path.join(out_dir, '%s_1_before_sync.png' % name))
        info = None
        for s in app.songs:
            rp = os.path.splitext(s.path)[0] + '.result.json'
            if os.path.exists(rp):
                with open(rp, encoding='utf-8') as f:
                    s.result = json.load(f)
                reps = len(s.result.get('repeats') or [])
                s.status = 'Synced' + (' · %d repeat%s' % (reps, 's' if reps > 1 else '') if reps else '')
                info = {'device': s.result.get('device'), 'device_name': s.result.get('device_name', '')}
        en = next((k for k, s in enumerate(app.songs) if s.path.endswith('demo_en.mp3')), 0)
        if len(app.songs) > 1:
            other = 1 - en
            app.songs[other].status = 'Aligning lines 72%'
            app.songs[other].result = None
        app.cur = en
        win.refresh_queue(app.songs, en)
        win.show_song(app.current())
        win.review.selectRow(3)
        win.set_busy(False, 'Ax-Easy Δοκιμή – Ήλιος · Aligning lines 72%', 0.94)
        if info:
            win.set_device(info)
        win.status_lbl.setText('Exported 4 files to %s' % win.out_dir.text())
        _grab(win, dark, os.path.join(out_dir, '%s_2_after_sync.png' % name))
        from .dialogs import AboutDialog, SetupDialog
        d = SetupDialog(win)
        d._backdrop = 'acrylic'
        from . import bootstrap
        v = d.variant.currentData()
        tot = bootstrap.total_size(v) / 1e9
        d.bar.set_value(0.42)
        d.info.setText('%.2f of %.2f GB · 23.5 MB/s · about %d min left' % (tot * 0.42, tot, max(1, round(tot * 0.58 * 1000 / 23.5 / 60))))
        d.file_lbl.setText('torch (%s)' % v.upper())
        d.btn_start.hide()
        d.btn_pause.show()
        d.show()
        _grab(d, dark, os.path.join(out_dir, '%s_3_setup.png' % name))
        d.close()
        a = AboutDialog(win)
        a._backdrop = 'acrylic'
        a.show()
        _grab(a, dark, os.path.join(out_dir, '%s_4_about.png' % name))
        a.close()
        win.close()
    return 0
