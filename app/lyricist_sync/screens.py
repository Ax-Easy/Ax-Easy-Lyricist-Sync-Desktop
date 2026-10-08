"""Screenshots for review (CI and local), labelled with the code path they show.

Windows 10 path: the window is rendered *with its alpha channel* (transparent shadow
margin included) and composited onto a desktop wallpaper and onto a checkerboard, so the
true rounded outline and the painted shadow are visible and nothing else is.
Windows 11 path: Mica comes from DWM, which an offscreen render cannot capture; it is
simulated with a blurred wallpaper and labelled as such."""
import glob
import json
import os
import platform
import tempfile

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QRadialGradient, QRegion
from PySide6.QtWidgets import QApplication, QWidget


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


def checker(w, h, s=16):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.fillRect(0, 0, w, h, QColor('#ffffff'))
    for y in range(0, h, s):
        for x in range(0, w, s):
            if (x // s + y // s) % 2:
                p.fillRect(x, y, s, s, QColor('#cfd3da'))
    p.end()
    return img


def blur(img, k=28):
    small = img.scaled(max(1, img.width() // k), max(1, img.height() // k), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(img.width(), img.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def render_alpha(widget):
    """The widget as an ARGB image; transparent where the window is transparent."""
    QApplication.processEvents()
    img = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    widget.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return img


def _banner(p, w, text, dark):
    f = QFont()
    f.setPointSizeF(10.5)
    f.setBold(True)
    p.setFont(f)
    r = QRectF(16, 12, w - 32, 30)
    path = QPainterPath()
    path.addRoundedRect(r, 10, 10)
    p.fillPath(path, QColor(0, 0, 0, 150) if dark else QColor(255, 255, 255, 200))
    p.setPen(QColor('#ffffff') if dark else QColor('#14171F'))
    p.drawText(r.adjusted(12, 0, -12, 0), Qt.AlignVCenter | Qt.AlignLeft, text)


def compose_labeled(widget, dark, label, backdrop='wallpaper', simulate_mica=False):
    win = render_alpha(widget)
    mw, mh = 90, 80
    w, h = win.width() + 2 * mw, win.height() + 2 * mh
    bg = checker(w, h) if backdrop == 'checker' else wallpaper(w, h, dark)
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawImage(0, 0, bg)
    if simulate_mica:  # DWM shadow + Mica can't be captured offscreen: approximate them
        r = QRectF(mw, mh, win.width(), win.height())
        p.setPen(Qt.NoPen)
        for i in range(24, 0, -2):
            p.setBrush(QColor(0, 0, 0, int(8 * (1 - i / 26))))
            p.drawRoundedRect(r.adjusted(-i * 0.6, -i * 0.3 + 10, i * 0.6, i * 0.9 + 10), 8 + i, 8 + i)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.setClipPath(path)
        p.drawImage(0, 0, blur(bg))
        p.setClipping(False)
    p.drawImage(mw, mh, win)
    _banner(p, w, label, dark if backdrop != 'checker' else False)
    p.end()
    return out


def _save(img, path):
    img.save(path)
    print('saved', path, flush=True)


def render(out_dir, fixture_dir=None):
    os.environ['LYRICIST_SYNC_HOME'] = tempfile.mkdtemp(prefix='lsync-screens-')
    os.makedirs(out_dir, exist_ok=True)
    from . import chrome
    from .app import App
    from .widgets import STATE
    qapp = QApplication.instance() or QApplication(['LyricistSync'])
    from . import theme as thememod
    qapp.setFont(thememod.ui_font())
    fixture_dir = fixture_dir or os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'fixtures')
    audios = sorted(glob.glob(os.path.join(fixture_dir, 'demo_*.mp3')))
    where = '%s offscreen render' % ('Windows' if os.name == 'nt' else platform.system())
    forced = chrome.FORCE_WIN10
    paths_out = []
    for style in ('win10', 'win11'):
        chrome.force_win10(style == 'win10')
        for dark in (True, False):
            name = '%s_%s' % (style, 'dark' if dark else 'light')
            app = App(qapp, screenshot=True, dark=dark)
            win = app.win
            if style == 'win11':
                win._mode, win._backdrop = 'win11', 'mica'
                win._apply_margins()
                label = 'Windows 11 path · DWM rounded corners + Mica (simulated here: DWM effects are not in offscreen renders) · %s' % where
            else:
                label = 'Windows 10 path%s · painted glass + painted shadow, true alpha outline · %s' % (
                    ' (forced with --force-win10-style)' if os.name == 'nt' else '', where)
            win.resize(1280 + 2 * win.margin(), 820 + 2 * win.margin())
            win.show()
            app.add_songs(audios)
            win.set_device({'text': 'Engine ready'})
            sim = style == 'win11'
            if style == 'win10' or dark:
                _save(compose_labeled(win, dark, label + ' · before sync', simulate_mica=sim),
                      os.path.join(out_dir, '%s_1_before_sync.png' % name))
            info = None
            for s in app.songs:
                rp = os.path.splitext(s.path)[0] + '.result.json'
                if os.path.exists(rp):
                    with open(rp, encoding='utf-8') as f:
                        s.result = json.load(f)
                    reps = len(s.result.get('repeats') or [])
                    low = sum(1 for l in s.result['lines'] if (l.get('conf') if l.get('conf') is not None else 1) < 0.6)
                    s.status = 'Synced' + (' · %d repeat%s' % (reps, 's' if reps > 1 else '') if reps else '') + \
                        (' · %d to check' % low if low else '')
                    info = {'device': s.result.get('device'), 'device_name': s.result.get('device_name', '')}
            en = next((k for k, s in enumerate(app.songs) if s.path.endswith('demo_en.mp3')), 0)
            if len(app.songs) > 1:
                other = 1 - en
                app.songs[other].status = 'Aligning lines 72%'
                app.songs[other].result = None
                app.songs[other].out_dir = os.path.join(os.path.dirname(app.songs[other].path), 'Album B')
            app.cur = en
            win.refresh_queue(app.songs, en)
            win.show_song(app.current())
            win.review.selectRow(3)
            win.set_busy(False, 'Ax-Easy Δοκιμή – Ήλιος · Aligning lines 72%', 0.94)
            if info:
                win.set_device(info)
            win.show_export_result([os.path.dirname(app.current().path)], 4)
            win.btn_update.set_badge(True)
            _save(compose_labeled(win, dark, label + ' · after sync', simulate_mica=sim),
                  os.path.join(out_dir, '%s_2_after_sync.png' % name))
            if style == 'win10' and dark:
                _save(compose_labeled(win, dark, label + ' · on a checkerboard: only the rounded window and its shadow',
                                      backdrop='checker'), os.path.join(out_dir, 'win10_checker_after_sync.png'))
            if style == 'win10':
                from .dialogs import AboutDialog, ConflictDialog, SetupDialog, UpdateDialog
                from . import bootstrap
                d = SetupDialog(win, 'cuda')
                st = d.state
                tot = sum(i['size'] for i in d.setup.step_items('dl_torch'))
                st.update('dl_torch', status='done', done=tot, total=tot, detail='45 files, %.2f GB, SHA256 checked while downloading' % (tot / 1e9))
                now = __import__('time').time()
                st.steps['dl_torch']['t0'], st.steps['dl_torch']['t1'] = now - 435, now - 83
                st.update('install', status='running', done=0, total=0, unit='files', indeterminate=True,
                          detail='Installing PyTorch · torch/lib/torch_cuda.dll')
                st.steps['install']['t0'] = now - 83
                d._t0 = now - 435
                d.variant.setEnabled(False)
                d.btn_start.hide()
                d.btn_pause.show()
                d.show()
                d._poll()
                _save(compose_labeled(d, dark, 'Setup (Windows 10 path) · static render, CUDA variant, step 2 running'),
                      os.path.join(out_dir, '%s_3_setup.png' % name))
                d.timer.stop()
                d.lat_timer.stop()
                d.hide()
                a = AboutDialog(win)
                a.show()
                _save(compose_labeled(a, dark, 'About (Windows 10 path)'), os.path.join(out_dir, '%s_4_about.png' % name))
                a.close()
                man = {'version': '1.2.0', 'date': '2026-11-02', 'size': 41500000, 'sha256': 'a' * 64,
                       'url': 'https://www.ax-easy.com/lyricist-sync/AxEasy-LyricistSync-Setup-1.2.0.exe',
                       'notes': '### What\'s new\n- Faster vocal separation on NVIDIA GPUs\n- Better timing for whispered lines\n'
                                '- Fixes for very long songs'}
                u = UpdateDialog(win, app, {'status': 'available', 'manifest': man, 'message': ''})
                u.show()
                _save(compose_labeled(u, dark, 'Update available (sample manifest)'), os.path.join(out_dir, '%s_7_update.png' % name))
                u.close()
                c = ConflictDialog(win, 'Ax-Easy Demo – Glass Towers',
                                   [os.path.join(os.path.dirname(app.current().path), 'Ax-Easy Demo - Glass Towers' + e)
                                    for e in ('.ttml', '.lrc', '.srt', '.vtt')])
                c.show()
                _save(compose_labeled(c, dark, 'Files already exist'), os.path.join(out_dir, '%s_8_conflict.png' % name))
                c.close()
            win.close()
    chrome.force_win10(forced)
    return 0
