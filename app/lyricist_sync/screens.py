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
import sys
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
    """Label strip at the top; wraps onto a second line when the text is long."""
    f = QFont()
    f.setPointSizeF(10.5)
    f.setBold(True)
    p.setFont(f)
    flags = Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap
    need = p.boundingRect(QRectF(0, 0, w - 56, 200), flags, text)
    r = QRectF(16, 10, w - 32, max(30, need.height() + 12))
    path = QPainterPath()
    path.addRoundedRect(r, 10, 10)
    p.fillPath(path, QColor(0, 0, 0, 150) if dark else QColor(255, 255, 255, 200))
    p.setPen(QColor('#ffffff') if dark else QColor('#14171F'))
    p.drawText(r.adjusted(12, 0, -12, 0), flags, text)


_CLEAN = {}   # the same composition without the caption banner (saved by _save into clean/)


def compose_labeled(widget, dark, label, backdrop='wallpaper', simulate_mica=False, overlay=None):
    """overlay: (image, QPoint in widget coordinates) drawn over the window, e.g. an open dropdown."""
    win = render_alpha(widget)
    if overlay is not None:
        q = QPainter(win)
        q.drawImage(overlay[1], overlay[0])
        q.end()
    mw, mh = 90, 80
    w, h = win.width() + 2 * mw, win.height() + 2 * mh
    bg = checker(w, h) if backdrop == 'checker' else wallpaper(w, h, dark)
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawImage(0, 0, bg)
    mac_win = getattr(widget, '_mode', None) == 'mac'
    if mac_win:   # the native macOS frame (shadow, rounded corners, traffic lights) isn't in a widget render
        from . import macfx
        r = QRectF(mw, mh, win.width(), win.height())
        p.setPen(Qt.NoPen)
        for i in range(30, 0, -2):
            p.setBrush(QColor(0, 0, 0, int(9 * (1 - i / 32))))
            p.drawRoundedRect(r.adjusted(-i * 0.7, -i * 0.4 + 14, i * 0.7, i * 1.0 + 14), 10 + i, 10 + i)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        p.drawImage(0, 0, blur(bg))
        p.drawImage(mw, mh, win)
        p.setClipping(False)
        p.setPen(QColor(255, 255, 255, 40) if dark else QColor(0, 0, 0, 40))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        cy = mh + macfx.TITLEBAR_H / 2.0
        for k, (fill, edge) in enumerate((('#FF5F57', '#E0443E'), ('#FEBC2E', '#DEA123'), ('#28C840', '#1AAB29'))):
            p.setPen(QColor(edge))
            p.setBrush(QColor(fill))
            p.drawEllipse(QPointF(mw + 20 + 20 * k, cy), 6, 6)
        win = None
    elif simulate_mica:  # DWM shadow + Mica can't be captured offscreen: approximate them
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
    if win is not None:
        p.drawImage(mw, mh, win)
    p.end()
    _CLEAN['img'] = out.copy()
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    _banner(p, w, label, dark if backdrop != 'checker' else False)
    p.end()
    _CLEAN['for'] = out.cacheKey()
    return out


def _save(img, path):
    """Saves the labelled image and, in clean/, the same picture without the caption banner (for the manual)."""
    img.save(path)
    print('saved', path, flush=True)
    if _CLEAN.get('for') == img.cacheKey():
        d = os.path.join(os.path.dirname(path), 'clean')
        os.makedirs(d, exist_ok=True)
        _CLEAN['img'].save(os.path.join(d, os.path.basename(path)))


def _pump(sec, until=None):
    import time
    qapp = QApplication.instance()
    t = time.time()
    while time.time() - t < sec and not (until and until()):
        qapp.processEvents()
        time.sleep(0.002)


def _wait_audio(win):
    """The waveform is decoded asynchronously; wait for it before a screenshot."""
    _pump(20, lambda: win.wave.duration > 0 or win.wave.message.startswith('Waveform not'))
    _pump(0.05)


def _load_result(app, s, rp):
    from . import instrumental
    with open(rp, encoding='utf-8') as f:
        s.result = json.load(f)
    instrumental.apply(s.result, app.settings)
    reps = len(s.result.get('repeats') or [])
    low = sum(1 for l in s.result['lines'] if (l.get('conf') if l.get('conf') is not None else 1) < 0.6)
    s.status = 'Synced' + (' · %d repeat%s' % (reps, 's' if reps > 1 else '') if reps else '') + \
        (' · %d to check' % low if low else '')


def _show_at(win, row, t):
    """Select `row`, playhead at t (paused), the line playing at t highlighted."""
    win.review.selectRow(row)
    win._show_position(t, playing=True)
    win.wave.set_selected(row)


def _music(app, win, dark, fixture_dir, label, out_dir, name):
    """♪ lines (intro_long fixture: a long instrumental intro, real 1.1.0 engine result + vocal
    regions) and the player panel."""
    hard = os.path.join(fixture_dir, '..', 'hard')
    audio, rp = os.path.join(hard, 'intro_long.mp3'), os.path.join(hard, 'intro_long.result.json')
    if not (os.path.exists(audio) and os.path.exists(rp)):
        return
    app.add_songs([audio])
    s = app.songs[-1]
    _load_result(app, s, rp)
    app.cur = len(app.songs) - 1
    win.refresh_queue(app.songs, app.cur)
    win.show_song(s)
    _wait_audio(win)
    win.set_busy(False, '', 1.0)
    win.status_lbl.setText('')
    _show_at(win, 0, 18.4)
    _save(compose_labeled(win, dark, label + ' · ♪ line in the instrumental intro (intro_long fixture, gap ≥ 8 s, '
                                           'violet in the list and on the waveform)'),
          os.path.join(out_dir, '%s_10_music_lines.png' % name))
    win.wave.t0, win.wave.span = 28.0, 18.0
    win.wave._cache = None
    _show_at(win, 2, 36.2)
    win.btn_pp.setText('❚❚')
    win.speed.setCurrentIndex(1)
    _save(compose_labeled(win, dark, label + ' · player: waveform zoomed (wheel), line markers, playhead, '
                                           'the line playing now highlighted, speed 0.75×'),
          os.path.join(out_dir, '%s_11_player.png' % name))
    win.btn_pp.setText('▶')
    win.speed.setCurrentIndex(2)


def render_maximized(out_dir, fixture_dir=None):
    """Maximized window, dark and light, on offscreen screens of 1280×720, 1920×1080 and
    2560×1440 (one process: three virtual screens side by side). Offscreen screens have no
    taskbar, so the work area is the whole screen here."""
    sizes = ((1280, 720), (1920, 1080), (2560, 1440))
    os.makedirs(out_dir, exist_ok=True)
    # next to the screenshots, passed as a relative path: the platform string is split at ':' so
    # a Windows drive letter ('C:/...') would cut it in two
    cfg = os.path.join(out_dir, 'screens.json')
    x = 0
    scr = []
    for w, h in sizes:
        scr.append({'name': '%dx%d' % (w, h), 'x': x, 'y': 0, 'width': w, 'height': h, 'logicalDpi': 96, 'logicalBaseDpi': 96, 'dpr': 1})
        x += w
    with open(cfg, 'w') as f:
        json.dump({'screens': scr}, f)
    if QApplication.instance() is None:
        try:
            rel = os.path.relpath(cfg)
        except ValueError:   # another drive
            rel = cfg
        os.environ['QT_QPA_PLATFORM'] = 'offscreen:configfile=' + rel.replace('\\', '/')
        if os.name == 'nt':   # the offscreen platform on Windows only finds fonts through QT_QPA_FONTDIR
            os.environ.setdefault('QT_QPA_FONTDIR', os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts'))
    os.environ['LYRICIST_SYNC_HOME'] = tempfile.mkdtemp(prefix='lsync-screens-')
    os.makedirs(out_dir, exist_ok=True)
    from PySide6.QtCore import QPoint as _P
    from .app import App
    from . import theme as thememod
    qapp = QApplication.instance() or QApplication(['LyricistSync'])
    thememod.apply_platform_style(qapp)
    qapp.setFont(thememod.ui_font())
    fixture_dir = fixture_dir or os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'fixtures')
    hard = os.path.join(fixture_dir, '..', 'hard')
    report = []
    for dark in (True, False):
        app = App(qapp, screenshot=True, dark=dark)
        win = app.win
        win.resize(1160 + 2 * win.margin(), 780 + 2 * win.margin())
        win.show()
        audios = sorted(glob.glob(os.path.join(fixture_dir, 'demo_*.mp3'))) + \
            [os.path.join(hard, n + '.mp3') for n in ('intro_long', 'choir') if os.path.exists(os.path.join(hard, n + '.mp3'))]
        app.add_songs(audios)
        for s in app.songs:
            for rp in (os.path.splitext(s.path)[0] + '.result.json',):
                if os.path.exists(rp):
                    _load_result(app, s, rp)
        win.set_device({'text': 'Engine ready'})
        cur = next((k for k, s in enumerate(app.songs) if s.path.endswith('intro_long.mp3')), 0)
        app.cur = cur
        win.refresh_queue(app.songs, cur)
        win.show_song(app.current())
        _wait_audio(win)
        for screen in sorted(qapp.screens(), key=lambda s: s.geometry().width()):
            win.showNormal()
            _pump(0.1)
            win.setScreen(screen)
            win.move(screen.geometry().topLeft() + _P(40, 40))
            _pump(0.1)
            win._toggle_max()
            _pump(1.0, lambda: win.isMaximized() and win.geometry() == screen.availableGeometry())
            _pump(0.1)
            _show_at(win, 1, 33.0)
            g, a = win.geometry(), screen.availableGeometry()
            ok = win.isMaximized() and g == a and win.margin() == 0 and win.radius() == 0
            report.append({'theme': 'dark' if dark else 'light', 'screen': screen.name(), 'window': g.getRect(),
                           'work_area': a.getRect(), 'review': [win.review.width(), win.review.height()],
                           'queue': [win.queue.width(), win.queue.height()], 'waveform': [win.wave.width(), win.wave.height()],
                           'ok': ok})
            _save(compose_labeled(win, dark, 'Maximized on a %s screen · offscreen render (no taskbar offscreen: work area = '
                                             'screen) · window %dx%d, no shadow margin or rounded corners'
                                  % (screen.name().replace('x', '×'), g.width(), g.height())),
                  os.path.join(out_dir, 'maximized_%s_%s.png' % ('dark' if dark else 'light', screen.name())))
            win._toggle_max()
            _pump(0.3)
        win.close()
    with open(os.path.join(out_dir, 'maximized.json'), 'w') as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    return 0 if all(r['ok'] for r in report) else 1


def _choir(app, win, dark, fixture_dir, label, out_dir, name):
    """Review list of the choir fixture with its real 1.1.0 engine result (amber 'check' markers)."""
    hard = os.path.join(fixture_dir, '..', 'hard')
    audio, rp = os.path.join(hard, 'choir.mp3'), os.path.join(hard, 'choir.result.json')
    if not (os.path.exists(audio) and os.path.exists(rp)):
        return
    app.add_songs([audio])
    s = app.songs[-1]
    _load_result(app, s, rp)
    app.cur = len(app.songs) - 1
    win.refresh_queue(app.songs, app.cur)
    win.show_song(s)
    _wait_audio(win)
    k = next((i for i, l in enumerate(s.result['lines']) if (l.get('conf') or 1) < 0.6), 0)
    win.review.selectRow(k)
    win.set_busy(False, '', 1.0)
    _save(compose_labeled(win, dark, label + ' · choir fixture, real 1.1.0 engine result: amber "check" on the choir line'),
          os.path.join(out_dir, '%s_9_choir_review.png' % name))


def _fake_small(home):
    """Screenshots: pretend 1.2.0 installed Whisper small (sparse file of the right size)."""
    from . import bootstrap
    p = bootstrap.whisper_path('small', home)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.exists(p):
        with open(p, 'wb') as f:
            f.truncate(bootstrap.whisper_models()['small']['size'])
        open(p + '.ok', 'w').close()


def _transcribe(app, win, dark, fixture_dir, label, out_dir, name):
    """Transcribe result: lines and times written by Whisper, unsure words amber (list + lyrics box).
    Uses <song>.transcribe.json next to the audio (a real engine result)."""
    from . import instrumental
    for rp in sorted(glob.glob(os.path.join(fixture_dir, '*.transcribe.json'))):
        audio = rp[:-len('.transcribe.json')] + '.mp3'
        if not os.path.exists(audio):
            continue
        app.add_songs([audio])
        s = next(x for x in app.songs if x.path == audio)
        with open(rp, encoding='utf-8') as f:
            s.result = json.load(f)
        s.result.pop('whisper_segments', None)
        instrumental.apply(s.result, app.settings)
        s.lyrics = s.result['text']
        s.lyrics_src = 'transcribe'
        low = s.result.get('low_conf') or 0
        s.status = 'Transcribed' + (' · %d to check' % low if low else '')
        app.cur = app.songs.index(s)
        win.refresh_queue(app.songs, app.cur)
        win.show_song(s)
        _wait_audio(win)
        lines = s.result['lines']
        k = next((i for i, l in enumerate(lines) if not l.get('inst') and any(w[3] < 0.45 for w in l.get('words', []))), 1)
        sel = min(len(lines) - 1, k + 1)        # the amber words show best on an unselected row
        win.review.selectRow(sel)
        win.review.scrollTo(win.review.model().index(max(0, k - 3), 1), win.review.ScrollHint.PositionAtTop)
        from PySide6.QtGui import QTextCursor
        blk = win.lyrics.document().findBlockByNumber(min(win.lyrics.document().blockCount() - 1, k + 1))
        win.lyrics.setTextCursor(QTextCursor(blk))
        win.lyrics.centerCursor()
        win.set_busy(False, '', 1.0)
        res = s.result
        win.status_lbl.setText('Transcribed with Whisper %s (%s): %d lines. Fix the amber words, then press Auto-sync for '
                               'exact timing.' % (res.get('whisper'), res.get('language'), len([l for l in lines if not l.get('inst')])))
        base = os.path.splitext(os.path.basename(audio))[0]
        _save(compose_labeled(win, dark, label + ' · Transcribe (%s, Whisper %s, no lyrics given): lines and times from '
                                               'Whisper, unsure words in amber' % (base, res.get('whisper'))),
              os.path.join(out_dir, '%s_12_transcribe_%s.png' % (name, base)))


def _engine(app, win, dark, label, out_dir, name):
    """Engine settings with the detected hardware and the open Whisper model dropdown, then a model
    download in progress (static render of the real dialog)."""
    from PySide6.QtCore import QPoint as _P
    from . import bootstrap
    from .dialogs import EngineDialog
    os.environ['LYRICIST_SYNC_FAKE_VRAM'] = '24'
    os.environ['LYRICIST_SYNC_FAKE_GPU'] = 'NVIDIA GeForce RTX 3090'
    os.environ['LYRICIST_SYNC_FAKE_MEM'] = '32'   # macOS: sample unified memory
    hw = 'sample memory: 32 GB' if sys.platform == 'darwin' else 'sample hardware: RTX 3090, 24 GB'
    try:
        _fake_small(os.environ['LYRICIST_SYNC_HOME'])
        app.settings['whisper_model'] = 'auto'
        d = EngineDialog(win, app)
        d.show()
        _pump(0.2)
        d.combo.showPopup()
        _pump(0.3)
        pop = d.combo.view().window()
        img = render_alpha(pop)
        pos = d.combo.mapTo(d, _P(0, d.combo.height() + 2))
        _save(compose_labeled(d, dark, 'Engine settings (%s) · Whisper model by hardware, ' % hw +
                                       'dropdown with size / speed / accuracy', overlay=(img, pos)),
              os.path.join(out_dir, '%s_13_engine_settings.png' % name))
        d.combo.hidePopup()
        _pump(0.1)
        _save(compose_labeled(d, dark, 'Engine settings (%s) · after the update from 1.2.0: ' % hw +
                                       'small installed, large-v3 recommended'),
              os.path.join(out_dir, '%s_14_engine_panel.png' % name))
        d.combo.setCurrentIndex(d.combo.findData('large-v3'))
        d.dl = bootstrap.ModelDownload('large-v3')
        st = d.dl.state
        for sid in st.order:
            from .dialogs import StepRow
            d.rows[sid] = StepRow(st.steps[sid]['label'])
            d.rows_box.addWidget(d.rows[sid])
        tot = bootstrap.whisper_models()['large-v3']['size']
        import time as _t
        now = _t.time()
        st.update('dl_whisper', status='running', done=int(tot * 0.42), total=tot, unit='bytes', speed=11.6e6,
                  detail='Whisper large-v3 · %.0f of %.0f MB' % (tot * 0.42 / 1e6, tot / 1e6))
        st.steps['dl_whisper']['t0'] = now - 112
        st.update('verify', status='waiting', total=tot, unit='bytes')
        d.bar.show()
        d.btn_dl.hide()
        d.btn_pause.setText('Pause')
        d.btn_pause.show()
        d.combo.setEnabled(False)
        d.info.setText('Downloading Whisper large-v3: resumable (also after closing the app), SHA256 checked.')
        d._poll()
        _pump(0.1)
        _save(compose_labeled(d, dark, 'Engine settings · switching to Whisper large-v3: download with per-step progress '
                                       '(static render)'),
              os.path.join(out_dir, '%s_15_model_download.png' % name))
        d.timer.stop()
        d.dl = None
        d.hide()
    finally:
        os.environ.pop('LYRICIST_SYNC_FAKE_VRAM', None)
        os.environ.pop('LYRICIST_SYNC_FAKE_MEM', None)
        os.environ.pop('LYRICIST_SYNC_FAKE_GPU', None)


def _edit(app, win, dark, fixture_dir, label, out_dir, name):
    """1.3.1: the right-click menu on a line, the Edit Line dialog with Greek text, in-place editing,
    the export confirmation and the unsaved-lyrics question on close."""
    from PySide6.QtCore import QPoint as _P
    from .dialogs import ExportDoneDialog, unsaved_dialog
    from .lyrics import sidecar_lyrics
    audio = os.path.join(fixture_dir, 'demo_el.mp3')
    rp = os.path.join(fixture_dir, 'demo_el.result.json')
    if not (os.path.exists(audio) and os.path.exists(rp)):
        return
    app.add_songs([audio])
    s = next(x for x in app.songs if x.path == audio)
    _load_result(app, s, rp)
    s.lyrics = sidecar_lyrics(audio)[0] or s.lyrics
    s.dirty = True
    app.cur = app.songs.index(s)
    win.refresh_queue(app.songs, app.cur)
    win.show_song(s)
    _wait_audio(win)
    win.set_busy(False, '', 1.0)
    L = s.result['lines']
    row = next(i for i, l in enumerate(L) if l['text'].startswith('Τα λόγια'))
    # 16: right-click menu (a taller window, so the whole menu fits in the picture)
    size0 = win.size()
    win.resize(size0.width(), size0.height() + 180)
    _pump(0.2)
    _show_at(win, row, L[row]['start'] + 0.4)
    win.status_lbl.setText('Right-click a line for Edit Line…, split, merge, insert, ♪ and undo')
    m = win.review_menu(row)
    rect = win.review.visualRect(win.review.model().index(row, 1))
    at = win.review.viewport().mapTo(win, rect.center() + _P(-120, 6))
    m.popup(win.mapToGlobal(at))
    _pump(0.3)
    img = render_alpha(m)
    _save(compose_labeled(win, dark, label + ' · right-click a line: Edit Line…, Play, Re-sync, Re-align, Split, Merge, '
                                             'Insert, ♪, Undo / Redo, Delete', overlay=(img, at)),
          os.path.join(out_dir, '%s_16_line_menu.png' % name))
    m.hide()
    m.deleteLater()
    win.resize(size0)
    _pump(0.2)
    # 17: Edit Line… with Greek text
    d = win.edit_line_dialog(row, exec_=False)
    d.text.setText('Τα λόγια βρίσκουν πάντα τον ρυθμό τους')
    d.text.setCursorPosition(len('Τα λόγια βρίσκουν'))
    d.text.deselect()
    d.fields['start'].setText('00:08.814')
    d.show()
    _pump(0.2)
    d.text.deselect()
    d.text.setCursorPosition(len('Τα λόγια βρίσκουν'))
    _pump(0.05)
    _save(compose_labeled(d, dark, 'Edit Line… (Greek text): words, Start / End in mm:ss.xxx with ±0.1 / ±0.01, '
                                   'Play line, Split at cursor, Re-align, Save (Enter) / Cancel (Esc)'),
          os.path.join(out_dir, '%s_17_edit_line.png' % name))
    d.close()
    # 18: editing in place (double-click / F2)
    win.review.selectRow(row)
    win.edit_line(row)
    _pump(0.2)
    ed = win.review_delegate.editor
    if ed is not None:
        ed.setText('Τα λόγια βρίσκουν τον ρυθμό τους ξανά')
        ed.setCursorPosition(len(ed.text()))
        ed.deselect()
    win.status_lbl.setText('Editing line %d in place · Enter saves, Esc cancels · right-click in the text: Split line at cursor'
                           % (row + 1))
    _pump(0.1)
    _save(compose_labeled(win, dark, label + ' · editing a line in place (double-click the words or F2)'),
          os.path.join(out_dir, '%s_18_inline_edit.png' % name))
    if ed is not None:
        win.review.closePersistentEditor(win.review.item(row, 1))
        win.review_delegate.closeEditor.emit(ed, win.review_delegate.EndEditHint.RevertModelCache)
    _pump(0.1)
    # 19: export confirmation (static render with sample paths: 3 songs, one skipped, one failed)
    base = (r'C:\Users\You\Music\Demos' if os.name == 'nt' else
            '/Users/you/Music/Demos' if sys.platform == 'darwin' else '/home/you/Music/Demos')
    sep = '\\' if os.name == 'nt' else '/'
    rep = []
    for lab, sub, status, reason in (('Ax-Easy Tests – Long Intro', 'Long Intro', 'ok', ''),
                                     ('Ax-Easy Δοκιμή – Ήλιος', 'Ήλιος', 'ok', ''),
                                     ('Ax-Easy Demo – Glass Towers', 'Glass Towers', 'skipped', 'the files already exist and you chose Skip'),
                                     ('Ax-Easy Tests – Choir Test', 'Choir Test', 'failed',
                                      'Access is denied (%s%sChoir Test%sAx-Easy Tests - Choir Test.lrc)' % (base, sep, sep))):
        d0 = base + sep + sub
        files = [d0 + sep + lab.replace(' – ', ' - ') + e for e in ('.ttml', '.lrc', '.srt', '.vtt')] if status == 'ok' else []
        rep.append({'song': None, 'label': lab, 'dir': d0, 'files': files, 'status': status, 'reason': reason})
    e = ExportDoneDialog(win, rep)
    e.show()
    _pump(0.2)
    _save(compose_labeled(e, dark, 'Export confirmation (static render, sample paths): summary, files per song with the '
                                   'full folder, skipped in amber, failed in red'),
          os.path.join(out_dir, '%s_19_export_done.png' % name))
    e.close()

    class _S:
        def __init__(self, t):
            self.t = t

        def label(self):
            return self.t
    u = unsaved_dialog(win, [_S('Ax-Easy Tests – Long Intro'), _S('Ax-Easy Δοκιμή – Ήλιος'), _S('Ax-Easy Demo – Glass Towers')])
    u.show()
    _pump(0.2)
    _save(compose_labeled(u, dark, 'Closing with unsaved lyrics: Export all & close / Close without saving / Cancel'),
          os.path.join(out_dir, '%s_20_unsaved_close.png' % name))
    u.close()
    s.dirty = False


def render(out_dir, fixture_dir=None):
    os.environ['LYRICIST_SYNC_HOME'] = tempfile.mkdtemp(prefix='lsync-screens-')
    os.makedirs(out_dir, exist_ok=True)
    from . import chrome
    from .app import App
    from .widgets import STATE
    qapp = QApplication.instance() or QApplication(['LyricistSync'])
    from . import theme as thememod
    thememod.apply_platform_style(qapp)
    qapp.setFont(thememod.ui_font())
    fixture_dir = fixture_dir or os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'fixtures')
    audios = sorted(glob.glob(os.path.join(fixture_dir, 'demo_*.mp3')))
    where = 'macOS widget render' if sys.platform == 'darwin' else '%s offscreen render' % ('Windows' if os.name == 'nt' else platform.system())
    forced = chrome.FORCE_WIN10
    paths_out = []
    # LYRICIST_SYNC_SCREENS=transcribe,engine: only those shots (Windows 10 path), e.g. for the manual
    only = [x for x in os.environ.get('LYRICIST_SYNC_SCREENS', '').split(',') if x]
    IS_MAC = sys.platform == 'darwin'
    styles = ('mac',) if IS_MAC else ('win10',) if only else ('win10', 'win11')
    for style in styles:
        if not IS_MAC:
            chrome.force_win10(style == 'win10')
        for dark in (True, False):
            name = '%s_%s' % (style, 'dark' if dark else 'light')
            app = App(qapp, screenshot=True, dark=dark)
            win = app.win
            if style == 'mac':
                label = 'macOS · native title bar + vibrancy (frame and traffic lights drawn in: not part of a widget render) · %s' % where
            elif style == 'win11':
                win._mode, win._backdrop = 'win11', 'mica'
                win._apply_margins()
                label = 'Windows 11 path · DWM rounded corners + Mica (simulated here: DWM effects are not in offscreen renders) · %s' % where
            else:
                label = 'Windows 10 path%s · painted glass + painted shadow, true alpha outline · %s' % (
                    ' (forced with --force-win10-style)' if os.name == 'nt' else '', where)
            win.resize(1280 + 2 * win.margin(), 820 + 2 * win.margin())
            win.show()
            if only and not IS_MAC:
                win.set_device({'device': 'cuda', 'device_name': 'NVIDIA GeForce RTX 3090'})
                if 'transcribe' in only:
                    _transcribe(app, win, dark, fixture_dir, label, out_dir, name)
                if 'engine' in only:
                    _engine(app, win, dark, label, out_dir, name)
                if 'edit' in only:
                    _edit(app, win, dark, fixture_dir, label, out_dir, name)
                win.close()
                continue
            app.add_songs(audios)
            win.set_device({'text': 'Engine ready'})
            sim = style == 'win11'
            if style in ('win10', 'mac') or dark:
                _save(compose_labeled(win, dark, label + ' · before sync', simulate_mica=sim),
                      os.path.join(out_dir, '%s_1_before_sync.png' % name))
            info = None
            for s in app.songs:
                rp = os.path.splitext(s.path)[0] + '.result.json'
                if os.path.exists(rp):
                    _load_result(app, s, rp)
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
            _wait_audio(win)
            _show_at(win, 3, app.current().result['lines'][4]['start'] + 0.6)
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
            if style in ('win10', 'mac'):
                from .dialogs import AboutDialog, ConflictDialog, SetupDialog, UpdateDialog
                from . import bootstrap
                d = SetupDialog(win, 'mps' if IS_MAC else 'cuda')
                st = d.state
                tot = sum(i['size'] for i in d.setup.step_items('dl_torch'))
                st.update('dl_torch', status='done', done=tot, total=tot, detail='45 files, %.2f GB, SHA256 checked while downloading' % (tot / 1e9))
                now = __import__('time').time()
                st.steps['dl_torch']['t0'], st.steps['dl_torch']['t1'] = now - 435, now - 83
                st.update('install', status='running', done=0, total=0, unit='files', indeterminate=True,
                          detail='Installing PyTorch · torch/lib/libtorch_cpu.dylib' if IS_MAC else
                          'Installing PyTorch · torch/lib/torch_cuda.dll')
                st.steps['install']['t0'] = now - 83
                d._t0 = now - 435
                d.variant.setEnabled(False)
                d.btn_start.hide()
                d.btn_pause.show()
                d.show()
                d._poll()
                _save(compose_labeled(d, dark, 'Setup · static render, %s variant, step 2 running' % ('Apple Silicon' if IS_MAC else 'CUDA')),
                      os.path.join(out_dir, '%s_3_setup.png' % name))
                d.timer.stop()
                d.lat_timer.stop()
                d.hide()
                a = AboutDialog(win)
                a.show()
                _save(compose_labeled(a, dark, 'About (Windows 10 path)'), os.path.join(out_dir, '%s_4_about.png' % name))
                a.close()
                man = {'version': '1.2.0', 'date': '2026-11-02', 'size': 41500000, 'sha256': 'a' * 64,
                       'url': 'https://github.com/Ax-Easy/Ax-Easy-Lyricist-Sync-Desktop/releases/download/v1.2.0/AxEasy-LyricistSync-Desktop-Setup-1.2.0.exe',
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
            if style in ('win10', 'mac'):
                _choir(app, win, dark, fixture_dir, label, out_dir, name)
                _music(app, win, dark, fixture_dir, label, out_dir, name)
                _transcribe(app, win, dark, fixture_dir, label, out_dir, name)
                _engine(app, win, dark, label, out_dir, name)
                _edit(app, win, dark, fixture_dir, label, out_dir, name)
            win.close()
    if not IS_MAC:
        chrome.force_win10(forced)
    return 0
