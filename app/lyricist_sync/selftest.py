"""--selftest: checks the frozen app without models (GUI loads, footer, exporters, packaging,
Windows frame/backdrop). Writes a JSON report and exits non-zero on failure."""
import json
import os
import struct
import sys
import tempfile
import traceback
import wave
import xml.etree.ElementTree as ET

RESULT = {'lines': [
    {'idx': 0, 'text': 'Καλησπέρα κόσμε', 'start': 4.02, 'end': 5.6, 'repeat': False, 'flag': ''},
    {'idx': 1, 'text': 'Ο ήλιος ανατέλλει πάλι 🌅', 'start': 6.71, 'end': 8.9, 'repeat': False, 'flag': ''},
    {'idx': 2, 'text': 'Tom & Jerry <live> "x"', 'start': 10.0, 'end': 11.2, 'repeat': False, 'flag': ''},
    {'idx': 0, 'text': 'Καλησπέρα κόσμε', 'start': 12.5, 'end': 13.4, 'repeat': True, 'flag': ''}],
    'duration': 15.0, 'language': 'el', 'repeats': [], 'device': 'cpu', 'timings': {}}


def _wav(path, sec=2.0, sr=22050):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b''.join(struct.pack('<h', 0) for _ in range(int(sec * sr))))


def run(report_path=None):
    checks = []

    def check(name, fn):
        try:
            detail = fn()
            checks.append({'name': name, 'ok': True, 'detail': detail})
        except Exception as e:
            checks.append({'name': name, 'ok': False, 'detail': '%s: %s' % (e.__class__.__name__, e),
                           'trace': traceback.format_exc()[-1500:]})

    tmp = tempfile.mkdtemp(prefix='lsync-selftest-')
    os.environ['LYRICIST_SYNC_HOME'] = os.path.join(tmp, 'home')
    from . import VERSION, bootstrap, macfx, paths
    from .formats import build

    def manifest():
        m = bootstrap.manifest()
        assert len(m['wheels']) > 30 and len(m['models']) >= 3
        if macfx.IS_MAC:   # both Mac stacks present; this Mac gets its own
            arm, x86 = bootstrap.manifest('arm64'), bootstrap.manifest('x86_64')
            assert list(arm['torch']) == ['mps'] and list(x86['torch']) == ['cpu']
            assert any(w['name'].startswith('torch-2.5.1') and 'arm64' in w['name'] for w in arm['torch']['mps'])
            assert any(w['name'].startswith('torch-2.2.2') and 'x86_64' in w['name'] for w in x86['torch']['cpu'])
            assert 'aarch64-apple-darwin' in arm['python']['name'] and 'x86_64-apple-darwin' in x86['python']['name']
            v = bootstrap.variants()[0]
            return {'arch': macfx.machine_arch(), 'variant': v, 'gb': round(bootstrap.total_size(v) / 1e9, 2),
                    'python': m['python']['name']}
        return {'cuda_gb': round(bootstrap.total_size('cuda') / 1e9, 2), 'cpu_gb': round(bootstrap.total_size('cpu') / 1e9, 2)}
    check('manifest', manifest)

    def packaging():
        eng = paths.engine_script()
        assert os.path.isfile(eng), eng
        for f in ('timing.py', 'transcribe.py'):  # modules the engine imports from its own folder
            assert os.path.isfile(os.path.join(os.path.dirname(eng), f)), 'engine/%s not packaged' % f
        out = {'engine': eng}
        if getattr(sys, 'frozen', False):
            for w in bootstrap.manifest()['local_wheels']:
                p = os.path.join(paths.app_dir(), 'wheels', w)
                assert os.path.isfile(p), p
                out[w] = os.path.getsize(p)
        for r in ('icon.svg', 'check.svg', 'chevron_dark.svg'):
            assert os.path.isfile(paths.resource('res', r)), r
        return out
    check('packaging', packaging)

    def licenses():   # the app is all-rights-reserved: no GPL tag reader (mutagen) in the bundle; tinytag (MIT) reads tags
        import importlib.util
        out = {'mutagen': importlib.util.find_spec('mutagen') is not None, 'tinytag': importlib.util.find_spec('tinytag') is not None}
        if getattr(sys, 'frozen', False):
            assert not out['mutagen'], 'mutagen (GPL) is bundled'
            assert out['tinytag'], 'tinytag missing'
            for f in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
                assert os.path.isfile(os.path.join(getattr(sys, '_MEIPASS', paths.app_dir()), f)), f
        return out
    check('licenses', licenses)

    check('gpu_detect', lambda: {'gpu': bootstrap.detect_gpu(), 'variant': bootstrap.recommended_variant()})

    def exporters():
        lines = [{'text': l['text'], 'time': l['start'], 'end': l['end'] + 0.4} for l in RESULT['lines']]
        meta = {'ti': 'Ήλιος', 'ar': 'Μόνιτορ', 'al': 'Δοκιμή', 'lang': ''}
        ttml = build('ttml', lines, meta, 15.0)
        root = ET.fromstring(ttml.encode('utf-8'))
        ns = '{http://www.w3.org/ns/ttml}'
        assert root.tag == ns + 'tt'
        assert root.get('{http://www.w3.org/XML/1998/namespace}lang') == 'el'
        assert root.get('{http://music.apple.com/lyric-ttml-internal}timing') == 'Line'
        div = root.find(ns + 'body/' + ns + 'div')
        assert div.get('begin') == '00:00:00.000'
        ps = div.findall(ns + 'p')
        assert len(ps) == 4 and ps[0].get('begin') == '00:00:04.020' and ps[1].text.endswith('🌅')
        lrc = build('lrc', lines, meta)
        assert lrc.startswith('[ti:Ήλιος]\n[ar:Μόνιτορ]\n[al:Δοκιμή]\n[00:04.02]Καλησπέρα κόσμε')
        srt = build('srt', lines, None, 15.0)
        assert srt.startswith('1\n00:00:04,020 --> 00:00:06,000\n')
        vtt = build('vtt', lines, None, 15.0)
        assert vtt.startswith('WEBVTT\n\n') and '&lt;live&gt;' in vtt
        return {'ttml_bytes': len(ttml.encode('utf-8'))}
    check('exporters', exporters)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication([sys.argv[0]])
    ctx = {}

    modals = []

    seen = {}

    def _dismiss():   # never hang on a modal the test didn't expect: close it (after 2 s) and remember its title
        w = QApplication.activeModalWidget()
        if w is None or getattr(w, '_selftest_keep', False):
            return
        seen[id(w)] = seen.get(id(w), 0) + 1
        if seen[id(w)] >= 5:
            modals.append(w.windowTitle() or w.__class__.__name__)
            w.reject()
    from PySide6.QtCore import QTimer
    watchdog = QTimer()
    watchdog.timeout.connect(_dismiss)
    watchdog.start(400)

    def gui():
        from .app import App
        app = App(qapp, screenshot=False)
        ctx['app'] = app
        win = app.win
        win.show()
        qapp.processEvents()
        assert app.settings.get('save_mode') == 'beside', app.settings.get('save_mode')
        audio = os.path.join(tmp, 'Τραγούδι δοκιμής.wav')
        _wav(audio)
        with open(os.path.splitext(audio)[0] + '.txt', 'w', encoding='utf-8-sig') as f:
            f.write('[Ρεφρέν]\nΚαλησπέρα κόσμε\nΟ ήλιος ανατέλλει πάλι 🌅\n\nTom & Jerry <live> "x"\n')
        app.add_songs([audio])
        s = app.current()
        assert s and len(s.lyrics.splitlines()) >= 3, 'sidecar lyrics not loaded'
        s.result = json.loads(json.dumps(RESULT))
        s.iso = 'ell'
        win.show_song(s)
        assert win.review.rowCount() == 4
        win.review.selectRow(1)
        win._nudge(0.1)
        win._nudge(-0.01)
        assert abs(s.result['lines'][1]['start'] - 6.80) < 1e-6, s.result['lines'][1]['start']
        win.bom.setChecked(True)
        names4 = ['Τραγούδι δοκιμής.lrc', 'Τραγούδι δοκιμής.srt', 'Τραγούδι δοκιμής.ttml', 'Τραγούδι δοκιμής.vtt']
        files = app.export_current()  # default: next to the audio file
        names = sorted(os.path.basename(f) for f in files)
        assert names == names4 and all(os.path.dirname(f) == tmp for f in files), files
        with open(os.path.join(tmp, 'Τραγούδι δοκιμής.srt'), 'rb') as f:
            assert f.read(3) == b'\xef\xbb\xbf'
        with open(os.path.join(tmp, 'Τραγούδι δοκιμής.ttml'), 'rb') as f:
            data = f.read()
            assert data[:5] == b'<?xml' and b'xml:lang="el"' in data
        assert macfx.FOLDER_LABEL in win.status_lbl.text() and 'href=' in win.status_lbl.text(), win.status_lbl.text()
        return {'files': names, 'platform': qapp.platformName()}
    check('gui_export', gui)

    def conflicts():
        app, win = ctx['app'], ctx['app'].win
        asked = []
        real = win.ask_conflict

        def script(choice):
            def f(song, existing, state):
                asked.append(len(existing))
                return choice
            return f
        before = os.path.getmtime(os.path.join(tmp, 'Τραγούδι δοκιμής.srt'))
        win.ask_conflict = script('skip')
        assert app.export_current() == [] and asked == [4]
        assert os.path.getmtime(os.path.join(tmp, 'Τραγούδι δοκιμής.srt')) == before
        win.ask_conflict = script('keep')
        kept = sorted(os.path.basename(f) for f in app.export_current())
        assert kept == ['Τραγούδι δοκιμής (2).lrc', 'Τραγούδι δοκιμής (2).srt', 'Τραγούδι δοκιμής (2).ttml',
                        'Τραγούδι δοκιμής (2).vtt'], kept
        win.ask_conflict = script('overwrite')
        over = app.export_current()
        assert sorted(os.path.basename(f) for f in over)[0] == 'Τραγούδι δοκιμής.lrc', over
        win.ask_conflict = real
        assert real(app.current(), ['x'], {'all': 'skip'}) == 'skip'  # "apply to all" is honoured
        from .dialogs import ConflictDialog
        d = ConflictDialog(win, 'Song', [os.path.join(tmp, 'a.lrc')])
        d.show()
        qapp.processEvents()
        d._pick('keep')
        assert d.choice == 'keep'
        return {'asked': asked}
    check('export_conflicts', conflicts)

    def song_folder():
        app, win = ctx['app'], ctx['app'].win
        s = app.current()
        out = os.path.join(tmp, 'Άλμπουμ')
        os.makedirs(out, exist_ok=True)
        win.queue.selectRow(0)
        assert win.selected_songs() == [s]
        app.set_song_dirs([s], out)
        files = app.export_current()
        assert files and all(os.path.dirname(f) == out for f in files), files
        app.settings['save_mode'] = 'folder'
        app.settings['out_dir'] = os.path.join(tmp, 'chosen')
        app.save_settings()
        with open(app.settings_path, encoding='utf-8') as f:
            saved = json.load(f)
        assert saved['song_dirs'].get(os.path.normcase(os.path.abspath(s.path))) == out or out in saved['song_dirs'].values(), saved
        assert saved['save_mode'] == 'folder'
        app.set_song_dirs([s], None)
        files = app.export_current()
        assert files and all(os.path.dirname(f) == os.path.join(tmp, 'chosen') for f in files), files
        app.settings['save_mode'] = 'beside'
        app.save_settings()
        return {'per_song': out, 'remembered': True}
    check('per_song_folder', song_folder)

    def confidence_resync():
        app, win = ctx['app'], ctx['app'].win
        s = app.current()
        s.result['lines'][2]['conf'] = 0.31
        s.result['lines'][2]['why'] = ['backing vocals overlap']
        win.show_song(s)
        notes = [(win.review.item(2, c).text(), win.review.item(2, c).toolTip()) for c in range(win.review.columnCount())
                 if win.review.item(2, c)]
        assert any('check' in t and 'backing' in tip for t, tip in notes), notes
        jobs = []
        app.ensure_engine = lambda: True

        class FakeEngine:
            def submit(self, job):
                jobs.append(job)
        real_engine, app.engine = app.engine, FakeEngine()
        app.resync(s, 1)
        app.engine = real_engine
        assert jobs and jobs[0]['cmd'] == 'resync' and jobs[0]['from'] == 1 and jobs[0]['anchor'] == s.result['lines'][1]['start']
        old0 = dict(s.result['lines'][0])
        new = [dict(l, start=l['start'] + 0.5, end=l['end'] + 0.5) for l in s.result['lines'][1:]]
        new[0]['start'] = s.result['lines'][1]['start']
        app._result(s.id, {'from': 1, 'lines': new, 'cmd': 'resync'})
        L = s.result['lines']
        assert L[0] == old0 and L[1]['manual'] and L[1]['conf'] == 1.0 and len(L) == 4
        assert not app.busy
        return {'low_conf_marker': True, 'resync_job': {k: jobs[0][k] for k in ('cmd', 'from', 'anchor')}}
    check('confidence_and_resync', confidence_resync)

    def updates():
        import http.server
        import threading
        from . import updater
        srv_dir = os.path.join(tmp, 'www')
        os.makedirs(srv_dir, exist_ok=True)
        payload = os.urandom(300000)
        with open(os.path.join(srv_dir, 'Setup-9.9.9.exe'), 'wb') as f:
            f.write(payload)
        import hashlib

        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=srv_dir, **k)

            def log_message(self, *a):
                pass
        httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:%d/' % httpd.server_address[1]
        man = {'version': '9.9.9', 'date': '2026-10-09', 'notes': '- test', 'url': base + 'Setup-9.9.9.exe',
               'sha256': hashlib.sha256(payload).hexdigest(), 'size': len(payload)}
        man_win = dict(man)
        if updater.IS_MAC:   # the Mac app reads the "mac" entry on top of the Windows top level
            man['mac'] = {'url': base + 'Setup-9.9.9.exe', 'sha256': man['sha256'], 'size': man['size'],
                          'minimum_os': {'arm64': '11.0', 'x86_64': '12.0'}}
        for name, m in (('update.json', man), ('bad.json', dict(man, sha256='0' * 64)), ('old.json', dict(man, version=VERSION)),
                        ('nomac.json', man_win)):
            with open(os.path.join(srv_dir, name), 'w') as f:
                json.dump(m, f)
        old = os.environ.get('LYRICIST_SYNC_UPDATE_TEST')
        os.environ['LYRICIST_SYNC_UPDATE_TEST'] = '1'
        out = {}
        try:
            out['available'] = updater.check(VERSION, base + 'update.json')['status']
            out['current'] = updater.check(VERSION, base + 'old.json')['status']
            out['notfound'] = updater.check(VERSION, base + 'nope.json')['status']
            if updater.IS_MAC:   # a manifest with only the Windows installer: nothing for this Mac
                nm = updater.check(VERSION, base + 'nomac.json')['status']
                assert nm == 'notfound', 'manifest without a mac entry: %s' % nm
            out['offline'] = updater.check(VERSION, 'http://127.0.0.1:9/update.json', timeout=3)['status']
            path = updater.download(man)
            out['download'] = os.path.getsize(path) == len(payload)
            os.remove(path)
            try:
                updater.download(dict(man, sha256='0' * 64))
                out['mismatch'] = 'accepted'
            except updater.UpdateError:
                out['mismatch'] = 'rejected'
            os.environ['LYRICIST_SYNC_UPDATE_TEST'] = '0'
            out['insecure'] = updater.check(VERSION, base + 'update.json')['status']
            out['ftp'] = updater.url_allowed('ftp://x/y.exe')
        finally:
            httpd.shutdown()
            if old is None:
                os.environ.pop('LYRICIST_SYNC_UPDATE_TEST', None)
            else:
                os.environ['LYRICIST_SYNC_UPDATE_TEST'] = old
        assert out == {'available': 'available', 'current': 'current', 'notfound': 'notfound', 'offline': 'offline',
                       'download': True, 'mismatch': 'rejected', 'insecure': 'insecure', 'ftp': False}, out
        from .dialogs import UpdateDialog
        d = UpdateDialog(ctx['app'].win, ctx['app'], {'status': 'notfound', 'message': 'x', 'manifest': None})
        d.show()
        qapp.processEvents()
        assert 'No update information' in d.head.text(), d.head.text()
        d.hide()
        d = UpdateDialog(ctx['app'].win, ctx['app'], {'status': 'current', 'message': '', 'manifest': dict(man, version=VERSION)})
        assert "up to date" in d.head.text() and d.btn_check.isVisibleTo(d), d.head.text()
        d.hide()
        assert ctx['app'].win.btn_update.isVisible()
        return out
    check('updater', updates)

    def frame():
        from . import chrome, winfx
        win = ctx['app'].win
        m = win.margin()
        out = {'mode': win._mode, 'path': chrome.label(), 'margin': m, 'radius': win.radius()}
        if macfx.IS_MAC:
            assert win._mode == 'mac' and m == 0 and win.radius() == 0, out
            assert not win.btn_close.isVisible() and not win.btn_max.isVisible(), 'custom caption buttons on a Mac'
            assert not (win.windowFlags() & Qt.FramelessWindowHint), 'Mac window must keep the native title bar'
            out.update(titlebar=bool(getattr(win, '_mac_titlebar', False)), backdrop=win._backdrop,
                       vibrancy=bool(getattr(win, '_vibrancy', None)))
            if qapp.platformName() == 'cocoa':
                assert out['titlebar'], 'full-size content view / transparent title bar not applied'
            return out
        if win._mode == 'painted':
            assert m == chrome.MARGIN and win.radius() == chrome.RADIUS
            b = win.body_rect()
            cy = int(b.center().y())
            assert win.edge_hit(int(b.left()) + 1, cy) == winfx.HTLEFT
            assert win.edge_hit(int(b.left()) - 6, cy) == winfx.HTLEFT
            assert win.edge_hit(2, cy) == winfx.HTTRANSPARENT
            assert win.edge_hit(int(b.right()) - 1, int(b.bottom()) - 1) == winfx.HTBOTTOMRIGHT
            assert win.edge_hit(int(b.center().x()), cy) is None
            win.showMaximized()
            qapp.processEvents()
            out['maximized_margin'] = win.margin()
            assert win.margin() == 0
            win.showNormal()
            qapp.processEvents()
        return out
    check('window_frame', frame)


    def footer():
        win = ctx['app'].win
        t1, t2 = win.foot1.text(), win.foot2.text()
        assert 'href="https://www.ax-easy.com"' in t1 and 'href="https://grok.com"' in t1, t1
        assert 'href="https://www.monitored.gr"' in t2, t2
        from PySide6.QtGui import QTextDocument
        d = QTextDocument()
        d.setHtml(t1)
        p1 = d.toPlainText()
        d.setHtml(t2)
        p2 = d.toPlainText()
        assert p1 == 'Made by Ax-Easy with the help of Grok', p1
        assert p2 == 'Inspired by the music of Monitored', p2
        assert win.foot1.isVisible() and win.foot2.isVisible() and win.foot1.openExternalLinks()
        return [p1, p2]
    check('footer', footer)

    def multimedia():
        win = ctx['app'].win
        ok = win.player.isAvailable()
        if qapp.platformName() in ('windows', 'cocoa'):
            assert ok, 'QtMultimedia backend not available: play-from-line would not work'
        return {'player': bool(win.player), 'available': ok}
    check('multimedia', multimedia)

    def about():
        from .dialogs import AboutDialog, SetupDialog
        a = AboutDialog(ctx['app'].win)
        a.show()
        qapp.processEvents()
        txt = ' '.join(w.text() for w in a.findChildren(type(ctx['app'].win.foot1)))
        assert 'grok.com' in txt and 'monitored.gr' in txt and 'ax-easy.com' in txt
        a.close()
        d = SetupDialog(ctx['app'].win)
        d.show()
        qapp.processEvents()
        assert len(d.rows) == 7, list(d.rows)
        d.hide()
        return 'ok'
    check('about_setup_dialogs', about)

    def mac_native():
        """macOS: menu bar (app menu roles, ⌘ shortcuts), ⌫ deletes a line, Quit goes through the
        unsaved-lyrics check, Finder wording."""
        if not macfx.IS_MAC:
            return 'skipped (not macOS)'
        from PySide6.QtGui import QAction, QKeySequence
        app, win = ctx['app'], ctx['app'].win
        a = win.mac_actions
        roles = {k: a[k].menuRole() for k in ('about', 'updates', 'settings', 'quit')}
        assert roles['about'] == QAction.AboutRole and roles['quit'] == QAction.QuitRole and roles['settings'] == QAction.PreferencesRole
        sc = {k: a[k].shortcut().toString(QKeySequence.PortableText) for k in a}
        assert sc['quit'] == 'Ctrl+Q' and sc['settings'] == 'Ctrl+,' and sc['undo'] == 'Ctrl+Z', sc
        assert sc['redo'] in ('Ctrl+Shift+Z', 'Shift+Ctrl+Z'), sc['redo']
        assert sc['export'] == 'Ctrl+S' and sc['add'] == 'Ctrl+O', sc
        assert a['fullscreen'].shortcut() == QKeySequence(QKeySequence.FullScreen) and not a['fullscreen'].shortcut().isEmpty()
        assert macfx.FOLDER_LABEL == 'Reveal in Finder'
        s = app.current()
        had = (s.result, s.dirty)
        # ⌫ deletes the selected line (Delete on Windows), undoable
        s.result = json.loads(json.dumps(RESULT))
        win.show_song(s)
        n = win.review.rowCount()
        win.review.setFocus()
        win.review.selectRow(1)
        assert win.handle_key(Qt.Key_Backspace) and win.review.rowCount() == n - 1, (n, win.review.rowCount())
        win.undo()
        bs = win.review.rowCount() == n
        assert bs, 'undo after ⌫'
        # Quit (⌘Q) with unsaved lyrics: Cancel keeps the window open
        s.result = s.result or json.loads(json.dumps(RESULT))
        s.dirty = True
        asked = []
        real = win.ask_unsaved
        win.ask_unsaved = lambda songs, action='close': asked.append(len(songs)) or 'cancel'
        try:
            a['quit'].trigger()
            qapp.processEvents()
            assert asked and win.isVisible(), ('quit did not ask about unsaved lyrics', asked)
        finally:
            win.ask_unsaved = real
            s.result, s.dirty = had
        return {'roles': {k: str(v).split('.')[-1] for k, v in roles.items()}, 'shortcuts': {k: sc[k] for k in
                ('quit', 'settings', 'undo', 'redo', 'export', 'add', 'fullscreen')},
                'menus': [m.text() for m in win.menubar.actions()], 'backspace_deletes': bs}
    check('mac_native', mac_native)

    def native():
        from . import winfx
        win = ctx['app'].win
        if not winfx.IS_WIN or qapp.platformName() != 'windows':
            return 'skipped (%s)' % qapp.platformName()
        import ctypes
        hwnd = int(win.winId())
        style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, -16)
        out = {'backdrop': win._backdrop, 'mode': win._mode, 'build': winfx.build(), 'thickframe': bool(style & 0x00040000),
               'maximizebox': bool(style & 0x00010000), 'margin': win.margin()}
        if win._mode == 'painted':
            assert win._backdrop != 'acrylic' and win.margin() == 20
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QCursor
        g = win.geometry().adjusted(win.margin(), win.margin(), -win.margin(), -win.margin())  # visible edge
        tests = {'left_edge': (QPoint(g.left() + 2, g.top() + g.height() // 2), winfx.HTLEFT),
                 'bottom_right': (QPoint(g.right() - 2, g.bottom() - 2), winfx.HTBOTTOMRIGHT),
                 'caption': (QPoint(g.left() + g.width() // 2, g.top() + 22), winfx.HTCAPTION),
                 'client': (QPoint(g.left() + g.width() // 2, g.top() + g.height() // 2), winfx.HTCLIENT)}
        if win.margin():
            tests['shadow'] = (QPoint(g.left() - 15, g.top() + g.height() // 2), winfx.HTTRANSPARENT)
        for name, (pt, want) in tests.items():
            got = win._hit(win.mapFromGlobal(pt))
            out[name] = got
            assert got == want, (name, got, want)
        assert out['thickframe'] and out['maximizebox']
        return out
    check('native_frame', native)

    def pump(sec, until=None):
        import time as _t
        t = _t.time()
        while _t.time() - t < sec and not (until and until()):
            qapp.processEvents()
            _t.sleep(0.002)

    def music_lines():
        from . import instrumental
        from .formats import fmt_lrc_time
        app, win = ctx['app'], ctx['app'].win
        s = app.current()
        texts = ['Καλησπέρα κόσμε', 'Ο ήλιος ανατέλλει πάλι 🌅', 'Tom & Jerry <live> "x"', 'Καλησπέρα κόσμε']
        s.result = {'lines': [{'idx': i % 3, 'text': t, 'start': st, 'end': en, 'conf': 0.9}
                              for i, (t, st, en) in enumerate(zip(texts, (10.0, 13.0, 30.0, 33.0), (12.5, 15.0, 32.0, 35.0)))],
                    'duration': 50.0, 'vocals': [[9.9, 15.6], [29.9, 35.1]], 'language': 'el', 'repeats': []}
        instrumental.apply(s.result, app.settings)
        win.show_song(s)
        kinds = [l.get('kind') for l in s.result['lines'] if l.get('inst')]
        assert kinds == ['intro', 'break', 'outro'], kinds
        rows = [r for r in range(win.review.rowCount()) if win.review.item(r, 1).data(Qt.UserRole + 1) == 'inst']
        assert rows == [0, 3, 6], rows
        assert win.review.item(3, 4).text() == 'music' and win.review.item(3, 1).font().italic()
        assert fmt_lrc_time(s.result['lines'][2]['end']) == '00:15.60'   # previous line ends where the gap starts
        win.review.selectRow(3)
        assert not win.btn_resync.isEnabled()                       # ♪ lines are never aligned
        jobs = []

        class FakeEngine:
            def submit(self, job):
                jobs.append(job)
        app.ensure_engine = lambda: True
        real_engine, app.engine = app.engine, FakeEngine()
        app.resync(s, 4)                                            # row 4 = 3rd sung line
        app.engine = real_engine
        assert jobs and jobs[0]['from'] == 2 and '♪' not in jobs[0]['lines'] and len(jobs[0]['lines']) == 4, jobs
        app.busy = False
        app.queue = []
        win.review.selectRow(0)
        assert win.handle_key(Qt.Key_Delete)                        # delete the intro ♪
        assert win.review.rowCount() == 6 and s.result.get('inst_deleted') == ['intro']
        win.wave.pos = 20.0
        win._insert_inst()                                           # "Insert ♪ here" at the playhead
        ins = [l for l in s.result['lines'] if l.get('inst') and not l.get('auto')]
        assert len(ins) == 1 and ins[0]['start'] == 20.0 and abs(ins[0]['end'] - 29.7) < 1e-6, ins
        real_ask, win.ask_conflict = win.ask_conflict, lambda *a: 'overwrite'
        try:
            files = app.export_current()
        finally:
            win.ask_conflict = real_ask
        lrc = [f for f in files if f.endswith('.lrc')][0]
        with open(lrc, encoding='utf-8-sig') as f:
            text = f.read()
        # the manual ♪ replaces the automatic one of the same gap; the outro stays
        assert '[00:20.00]♪' in text and '[00:35.10]♪' in text and '[00:15.60]♪' not in text, text
        srt = [f for f in files if f.endswith('.srt')][0]
        with open(srt, encoding='utf-8-sig') as f:
            assert '00:00:20,000 --> 00:00:29,700\n♪' in f.read()
        return {'kinds': kinds, 'lrc': [l for l in text.splitlines() if '♪' in l]}
    check('music_lines', music_lines)

    def player():
        from . import player as P
        win = ctx['app'].win
        s = ctx['app'].current()
        win._load_audio(s)
        pump(15, lambda: win.wave.duration > 0)
        assert abs(win.wave.duration - 2.0) < 0.05, ('decode', win.wave.duration, win.wave.message)
        hit = win.audio.get(s.path)
        assert hit and os.path.exists(hit[0]) and abs(len(hit[1]) / 2 * P.HOP - 2.0) < 0.05, hit and len(hit[1])
        assert os.path.dirname(hit[0]) == P.cache_dir()
        out = {'decoded_s': round(win.wave.duration, 3), 'peaks': len(hit[1]) // 2, 'cache': hit[0]}
        win._seek(1.25)
        pump(3, lambda: win.player.mediaStatus() in (win.player.MediaStatus.LoadedMedia, win.player.MediaStatus.BufferedMedia))
        pump(0.3)
        out['source'] = os.path.basename(win._src)
        out['player_pos_ms'] = win.player.position()
        assert win._src == hit[0], win._src
        assert abs(win.position() - 1.25) < 1e-6
        if qapp.platformName() == 'windows' and win.player.isAvailable():
            assert abs(win.player.position() - 1250) <= 30, win.player.position()
        assert win.time_lbl.text().startswith('0:01.25'), win.time_lbl.text()
        win.review.selectRow(1)
        before = s.result['lines'][1]['start']
        assert win.handle_key(Qt.Key_Right) and abs(s.result['lines'][1]['start'] - before - 0.1) < 1e-6
        assert win.handle_key(Qt.Key_Left, Qt.ShiftModifier) and abs(s.result['lines'][1]['start'] - before - 0.09) < 1e-6
        assert win.handle_key(Qt.Key_Down) and win.review.currentRow() == 2
        assert win.handle_key(Qt.Key_S) and s.result['lines'][2]['start'] == 1.25 and win.review.currentRow() == 3
        win.lyrics.setFocus()
        qapp.processEvents()
        out['typing_guard'] = win._typing() if QApplication.focusWidget() is win.lyrics else 'focus n/a'
        win._set_active(1.3, True)
        assert win.review._active_row == 2, win.review._active_row
        win.wave.zoom(0.4, 1.0)
        assert 0 < win.wave.span < 2.0, win.wave.span
        win.toggle_play()
        pump(0.5)
        out['play_state'] = str(win.player.playbackState()).split('.')[-1]
        win.player.stop()
        return out
    check('player', player)

    def maximize():
        from . import winfx
        win = ctx['app'].win
        win.showNormal()
        pump(0.3)
        normal = win.geometry()
        sizes = lambda: {'review': (win.review.width(), win.review.height()), 'queue': (win.queue.width(), win.queue.height()),
                         'wave': (win.wave.width(), win.wave.height())}
        n_sizes = sizes()
        out = {'normal': normal.getRect(), 'avail': win.screen().availableGeometry().getRect(),
               'screen': win.screen().geometry().getRect(), 'platform': qapp.platformName()}

        mac = macfx.IS_MAC

        def check_fill(tag, want):
            g = win.frameGeometry() if mac else win.geometry()
            out[tag] = g.getRect()
            if winfx.IS_WIN:
                out[tag + '_native'] = winfx.native_rects(int(win.winId()))
            assert win.margin() == 0 and win.radius() == 0, (tag, win.margin(), win.radius())
            if mac:   # zoom / full-screen space are the system's: it fills (nearly) the whole area
                assert g.width() >= want.width() * 0.9 and g.height() >= want.height() * 0.85, (tag, g.getRect(), want.getRect())
            else:
                assert all(abs(a - b) <= 2 for a, b in zip(g.getRect(), want.getRect())), (tag, g.getRect(), want.getRect())
            sz = sizes()
            out[tag + '_sizes'] = sz
            if want.width() > normal.width() + 40 and want.height() > normal.height() + 40:
                for k in sz:   # everything stretched, nothing left at its old size
                    assert sz[k][0] > n_sizes[k][0] and sz[k][1] >= n_sizes[k][1], (tag, k, sz[k], n_sizes[k])

        T = 3.0 if mac else 1.0   # macOS animates zoom and full screen
        win._toggle_max()
        pump(T, lambda: win.isMaximized() and win.geometry() == win.screen().availableGeometry())
        pump(0.2 if not mac else 1.0)
        assert win.isMaximized()
        check_fill('maximized', win.screen().availableGeometry())
        win._toggle_max()
        pump(T, lambda: not win.isMaximized() and win.geometry() == normal)
        pump(0.0 if not mac else 0.8)
        out['restored'] = win.geometry().getRect()
        assert all(abs(a - b) <= (2 if not mac else 30) for a, b in zip(win.geometry().getRect(), normal.getRect())), (out['restored'], normal.getRect())
        if winfx.IS_WIN and qapp.platformName() == 'windows':
            winfx.show_window(int(win.winId()), 3)      # SW_MAXIMIZE: what Win+Up and snap-to-top do
            pump(1.0, lambda: win.isMaximized() and win.geometry() == win.screen().availableGeometry())
            pump(0.2)
            assert win.isMaximized()
            check_fill('native_maximized', win.screen().availableGeometry())
            winfx.show_window(int(win.winId()), 9)      # SW_RESTORE (Win+Down)
            pump(1.0, lambda: not win.isMaximized() and win.geometry() == normal)
            out['native_restored'] = win.geometry().getRect()
            assert all(abs(a - b) <= 2 for a, b in zip(win.geometry().getRect(), normal.getRect())), out['native_restored']
        win._toggle_full()
        pump(T if not mac else 12.0, lambda: win.isFullScreen() and win.geometry() == win.screen().geometry())
        pump(0.2 if not mac else 1.5)
        assert win.isFullScreen()
        check_fill('fullscreen', win.screen().geometry())
        win._toggle_full()
        pump(T, lambda: not win.isFullScreen() and win.geometry() == normal)
        if mac:   # leaving the full-screen space animates; slow on the Intel CI VMs
            pump(12.0, lambda: not win.isFullScreen() and not win.isMaximized())
            pump(1.5)
            if win.isFullScreen() or win.isMaximized():   # Intel CI VMs sometimes drop the exit animation; record and ask once more
                out['fullscreen_exit_retry'] = [win.isFullScreen(), win.isMaximized(), win.geometry().getRect()]
                win.showNormal()
                pump(12.0, lambda: not win.isFullScreen() and not win.isMaximized())
                pump(1.5)
        out['after_fullscreen'] = win.geometry().getRect()
        assert not win.isFullScreen() and not win.isMaximized()
        out['healed'] = getattr(win, '_healed', 0)
        return out
    check('maximize', maximize)

    def tiers():
        out = {}
        md = bootstrap.ModelDownload('medium')   # Engine settings download plan for this platform's PyTorch variant
        assert [i['kind'] for i in md.setup.items] == ['model'], md.setup.items
        out['model_download_variant'] = md.setup.variant
        for gb, want in ((None, 'small'), (4.0, 'small'), (8.0, 'medium'), (12.0, 'large-v3-turbo'), (16.0, 'large-v3-turbo'),
                         (23.7, 'large-v3'), (24.0, 'large-v3')):
            got = bootstrap.whisper_tier(gb, 'cuda')
            assert got == want, (gb, got)
            out[str(gb)] = got
        assert bootstrap.whisper_tier(24.0, 'cpu') == 'small'
        # Macs: Apple Silicon by unified memory, Intel by RAM
        mac = {gb: bootstrap.whisper_tier(gb, 'mps') for gb in (8.0, 16.0, 18.0, 24.0, 32.0, 36.0, 64.0)}
        assert list(mac.values()) == ['small', 'medium', 'medium', 'large-v3-turbo', 'large-v3', 'large-v3', 'large-v3'], mac
        assert bootstrap.whisper_tier(16.0, 'mac-cpu') == 'small' and bootstrap.whisper_tier(32.0, 'mac-cpu') == 'medium'
        out['mac'] = {str(k): v for k, v in mac.items()}
        assert bootstrap.parse_smi('NVIDIA GeForce RTX 3090, 591.44, 24576')['vram_gb'] == 24.0
        sizes = {n: m['size'] for n, m in bootstrap.whisper_models().items()}
        assert list(sizes) == ['small', 'medium', 'large-v3-turbo', 'large-v3'], sizes
        for t in sizes:
            wh = [i for i in bootstrap.plan(bootstrap.variants()[0], whisper=t) if i['kind'] == 'model' and bootstrap.model_group(i) == 'whisper']
            assert len(wh) == 1 and wh[0]['size'] == sizes[t]
        return out
    check('whisper_tiers', tiers)

    def transcribe_ui():
        from .widgets import WORDS_ROLE
        app, win = ctx['app'], ctx['app'].win
        s = app.current()
        s.lyrics, s.result = '', None
        win.show_song(s)
        assert win.btn_sync.isEnabled() and win.btn_tr.isEnabled() and win.btn_sync.text() == 'Transcribe + sync'
        jobs = []

        class FakeEngine:
            def submit(self, job):
                jobs.append(job)
        app.ensure_engine = lambda: True
        real_engine, app.engine = app.engine, FakeEngine()
        app.sync_current()                       # no lyrics: Auto-sync transcribes
        app.engine = real_engine
        assert jobs and jobs[0]['cmd'] == 'transcribe' and jobs[0]['whisper'], jobs
        res = {'mode': 'transcribe', 'language': 'el', 'whisper': 'small', 'duration': 15.0, 'vocals': [[3.9, 12.0]],
               'low_conf': 1, 'version': 3, 'device': 'cpu', 'timings': {}, 'dropped': [],
               'lines': [{'idx': 0, 'text': 'Καλησπέρα κόσμε', 'start': 4.0, 'end': 5.2, 'conf': 0.93, 'why': [],
                          'words': [['Καλησπέρα', 4.0, 4.6, 0.95], ['κόσμε', 4.6, 5.2, 0.91]]},
                         {'idx': 1, 'text': 'Ο ήλιος ανατέλει πάλη', 'start': 6.3, 'end': 8.0, 'conf': 0.52, 'why': ['unsure words: ανατέλει, πάλη'],
                          'words': [['Ο', 6.3, 6.4, 0.9], ['ήλιος', 6.4, 6.9, 0.88], ['ανατέλει', 6.9, 7.5, 0.31], ['πάλη', 7.5, 8.0, 0.22]]}]}
        res['text'] = '\n'.join(l['text'] for l in res['lines'])
        app._result(s.id, res)
        assert s.lyrics == res['text'] and s.status.startswith('Transcribed'), (s.lyrics, s.status)
        assert win.lyrics.toPlainText() == res['text']
        sung = [r for r in range(win.review.rowCount()) if win.review.item(r, 1).data(Qt.UserRole + 1) != 'inst']
        words = win.review.item(sung[1], 1).data(WORDS_ROLE)
        assert words and [w for w, low in words if low] == ['ανατέλει', 'πάλη'], words
        assert win.review.item(sung[0], 1).data(WORDS_ROLE) is None
        assert win.review.item(sung[1], 4).text() == '● check'
        amber = [sel.cursor.selectedText() for sel in win.lyrics.extraSelections()]
        assert amber == ['ανατέλει', 'πάλη'], amber
        win.review.viewport().repaint()          # the delegate paints the amber words
        assert win.btn_sync.text() == 'Auto-sync'
        jobs.clear()
        app.engine = FakeEngine()
        app.busy, app.queue = False, []
        app.sync_current()                       # fix the words, then Auto-sync aligns the text
        app.engine = real_engine
        assert jobs and jobs[0]['cmd'] == 'sync' and jobs[0]['lines'][1] == 'Ο ήλιος ανατέλει πάλη', jobs
        app.busy, app.queue = False, []
        return {'amber_words': amber, 'jobs': ['transcribe', 'sync']}
    check('transcribe_ui', transcribe_ui)

    def engine_dialog():
        from .dialogs import EngineDialog
        app = ctx['app']
        os.environ['LYRICIST_SYNC_FAKE_VRAM'] = '24'
        try:
            hw = app.hardware()
            assert hw['tier'] == 'large-v3' and hw['variant'] == 'cuda', hw
            dlg = EngineDialog(app.win, app)
            dlg.show()
            pump(0.2)
            items = [dlg.combo.itemData(i) for i in range(dlg.combo.count())]
            assert items == ['auto', 'small', 'medium', 'large-v3-turbo', 'large-v3'], items
            assert 'large-v3' in dlg.combo.itemText(0)
            assert 'GB' in dlg.combo.itemText(4) and 'accuracy' in dlg.combo.itemText(4)
            dlg.combo.setCurrentIndex(3)
            assert dlg.btn_dl.isVisible() and 'large-v3-turbo' in dlg.btn_dl.text()
            dlg.combo.setCurrentIndex(0)
            dlg.timer.stop()
            dlg.done(0)
        finally:
            os.environ.pop('LYRICIST_SYNC_FAKE_VRAM', None)
        return {'tier': hw['tier'], 'items': items}
    check('engine_dialog', engine_dialog)

    def _fresh(app, lyrics, lines, duration=20.0):
        from . import edits
        s = app.current()
        s.lyrics = lyrics
        s.result = {'lines': json.loads(json.dumps(lines)), 'duration': duration, 'vocals': [], 'language': 'el',
                    'repeats': [], 'device': 'cpu', 'timings': {}, 'mode': 'sync'}
        s.history, s.edited, s.dirty, s.status = edits.History(), False, True, 'Synced'
        app.busy, app.queue = False, []
        app.win.show_song(s)
        qapp.processEvents()
        return s

    EDIT_LINES = [
        {'idx': 0, 'text': 'Καλησπέρα κόσμε', 'start': 1.0, 'end': 3.0, 'repeat': False, 'flag': '', 'conf': 0.4,
         'why': ['weak acoustic match'], 'words': [['Καλησπέρα', 1.0, 2.0, 0.3], ['κόσμε', 2.0, 3.0, 0.9]]},
        {'idx': 1, 'text': 'Ο ήλιος ανατέλλει πάλι', 'start': 3.5, 'end': 6.5, 'repeat': False, 'flag': '', 'conf': 0.9, 'why': []},
        {'idx': 2, 'text': 'Glass towers in the rain', 'start': 7.0, 'end': 9.0, 'repeat': False, 'flag': '', 'conf': 0.9, 'why': []},
        {'idx': 0, 'text': 'Καλησπέρα κόσμε', 'start': 12.0, 'end': 13.5, 'repeat': True, 'flag': '', 'conf': 0.9, 'why': []}]
    EDIT_LYRICS = '[Ρεφρέν]\nΚαλησπέρα κόσμε\nΟ ήλιος ανατέλλει πάλι\n\nGlass towers in the rain\n'

    def review_edits():
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QAbstractItemView
        from .lyrics import split_lines
        app, win = ctx['app'], ctx['app'].win
        s = _fresh(app, EDIT_LYRICS, EDIT_LINES)
        L = lambda: s.result['lines']   # noqa: E731
        # context menu: the labels of the manual
        labels = [a.text() for a in win.review_menu(1).actions() if not a.isSeparator()]
        want = ['✎  Edit Line…', '▶  Play from line', '⟲  Re-sync from here', '◎  Re-align this line', 'Split line at cursor',
                'Merge with next', 'Insert line above', 'Insert line below', '♪  Insert ♪ here', 'Mark as ♪', '♪ settings…',
                'Undo', 'Redo', 'Delete line']
        assert labels == want, labels
        # inline: double-click / F2 opens the editor on the words; Enter commits through the delegate
        win.review.selectRow(0)
        win.review.setFocus()
        assert win.handle_key(Qt.Key_F2) and win.review.state() == QAbstractItemView.State.EditingState
        ed = win.review_delegate.editor
        assert ed is not None and ed.text() == 'Καλησπέρα κόσμε', ed and ed.text()
        ed.setText('Καλησπέρα κόσμε μου')
        QApplication.sendEvent(ed, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        qapp.processEvents()
        assert L()[0]['text'] == 'Καλησπέρα κόσμε μου' and (L()[0]['start'], L()[0]['end']) == (1.0, 3.0), L()[0]
        assert L()[3]['text'] == 'Καλησπέρα κόσμε μου', 'repeat not updated'
        assert win.review.item(0, 4).text() == '✎ edited' and win.review.item(0, 1).data(Qt.UserRole + 2) is None
        assert 'Καλησπέρα κόσμε μου' in win.lyrics.toPlainText().splitlines() and '[Ρεφρέν]' in win.lyrics.toPlainText()
        assert win.lyrics.extraSelections() == [] and s.edited and s.dirty
        # inline time edit (mm:ss.xxx), invalid input refused
        win.review_delegate.edited.emit(2, 2, '00:06.750')
        assert L()[2]['start'] == 6.75 and L()[1]['end'] == 6.5
        win.review_delegate.edited.emit(2, 3, 'abc')
        assert L()[2]['end'] == 9.0
        assert abs(win.wave.lines[2]['start'] - 6.75) < 1e-9      # the waveform marker moved too
        # Edit Line dialog: Greek words, times, Enter saves / Esc cancels
        def key_click(w, k):   # (QtTest is not in the frozen app)
            QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))
            QApplication.sendEvent(w, QKeyEvent(QEvent.KeyRelease, k, Qt.NoModifier))
            qapp.processEvents()
        d = win.edit_line_dialog(1, exec_=False)
        assert d is not None, (app.busy, len(L()), win.review.currentRow())
        d._selftest_keep = True
        assert d.fields['start'].text() == '00:03.500' and d.btn_save.isDefault()
        d.text.setText('Ο ήλιος βγαίνει ξανά')
        d.fields['end'].setText('00:06.400')
        d._nudge('start', 0.1)
        d._nudge('start', -0.01)
        assert d.fields['start'].text() == '00:03.590', d.fields['start'].text()
        d.fields['end'].setText('00:03.000')
        assert not d.btn_save.isEnabled()
        d.fields['end'].setText('00:06.400')
        assert d.realign.isChecked()          # half of the words changed: Re-align is ticked
        d.realign.setChecked(False)
        d.show()
        key_click(d.fields['end'], Qt.Key_Return)
        assert d.result() == 1
        win.apply_line_dialog(1, d)
        assert (L()[1]['text'], L()[1]['start'], L()[1]['end']) == ('Ο ήλιος βγαίνει ξανά', 3.59, 6.4), L()[1]
        d = win.edit_line_dialog(1, exec_=False)
        d._selftest_keep = True
        d.text.setText('nothing')
        d.show()
        key_click(d.text, Qt.Key_Escape)
        assert d.result() == 0 and L()[1]['text'] == 'Ο ήλιος βγαίνει ξανά'
        d.close()
        # big word change ticks "Re-align"
        d = win.edit_line_dialog(2, exec_=False)
        d.text.setText('Completely different words now')
        assert d.realign.isChecked()
        d.close()
        # split (middle word, time by characters), merge, insert, delete, ♪ mark/unmark
        n0 = len(L())
        r2 = win.split_line(2)
        assert len(L()) == n0 + 1 and L()[2]['text'] == 'Glass towers' and L()[r2]['text'] == 'in the rain', [l['text'] for l in L()]
        assert abs(L()[2]['end'] - (6.75 + 2.25 * 12 / 23)) < 0.002, L()[2]
        win.merge_line(2)
        assert len(L()) == n0 and L()[2]['text'] == 'Glass towers in the rain'
        r = win.insert_line(2, below=True, edit=False)
        assert L()[r]['text'] == 'New line' and 'New line' in split_lines(win.lyrics.toPlainText())
        win.set_line_text(r, 'Ένας νέος στίχος')
        assert 'Ένας νέος στίχος' in split_lines(s.lyrics)
        win.delete_line(r)
        assert 'Ένας νέος στίχος' not in s.lyrics and len(L()) == n0
        win.mark_inst(2)
        assert L()[2].get('inst') and 'Glass towers in the rain' not in split_lines(s.lyrics)
        win.unmark_inst(2)
        assert L()[2]['text'] == 'Glass towers in the rain' and 'Glass towers in the rain' in split_lines(s.lyrics)
        # undo / redo with Ctrl+Z / Ctrl+Y (history per song)
        steps = len(s.history.undo_stack)
        win.review.setFocus()
        assert win.handle_key(Qt.Key_Z, Qt.ControlModifier)      # unmark undone
        assert L()[2].get('inst')
        assert win.handle_key(Qt.Key_Y, Qt.ControlModifier)
        assert not L()[2].get('inst')
        for _ in range(steps):
            win.handle_key(Qt.Key_Z, Qt.ControlModifier)
        assert [l['text'] for l in L()] == [l['text'] for l in EDIT_LINES], [l['text'] for l in L()]
        assert s.lyrics == EDIT_LYRICS and not s.edited
        assert not win.btn_undo.isEnabled() and win.btn_redo.isEnabled()
        win.handle_key(Qt.Key_Y, Qt.ControlModifier)
        assert L()[0]['text'] == 'Καλησπέρα κόσμε μου'
        # Re-align this line: one engine job inside the neighbours' bounds, result applied, undoable
        jobs = []

        class FakeEngine:
            def submit(self, job):
                jobs.append(job)
        real_engine, app.engine = app.engine, FakeEngine()
        real_ensure, app.ensure_engine = app.ensure_engine, lambda: True
        try:
            win.realign_line(2)
            assert jobs and jobs[0]['cmd'] == 'realign' and jobs[0]['lo'] <= L()[2]['start'] and jobs[0]['hi'] >= L()[2]['end'], jobs
            assert app.busy
            app._result(s.id, {'realign': True, 'row': 2, 'text': L()[2]['text'], 'start': 7.2, 'end': 8.8, 'conf': 0.88, 'why': []})
            assert not app.busy and (L()[2]['start'], L()[2]['end']) == (7.2, 8.8)
            win.undo()
            assert L()[2]['start'] == 7.0
            win.redo()
            # unsaved-edits safety: Keep my edits / Replace
            jobs.clear()
            win.ask_keep_edits = lambda songs, action: 'keep'
            app.sync_current()
            assert not jobs and not app.busy and s.edited
            app.transcribe_current()
            assert not jobs
            win.ask_keep_edits = lambda songs, action: 'replace'
            app.sync_current()
            assert jobs and jobs[0]['cmd'] == 'sync' and 'Καλησπέρα κόσμε μου' in jobs[0]['lines'], jobs
            app.busy, app.queue = False, []
        finally:
            app.engine, app.ensure_engine = real_engine, real_ensure
            del win.ask_keep_edits
        from .dialogs import KeepEditsDialog
        k = KeepEditsDialog(win, [s], 'sync')
        assert (k.btn_keep.text(), k.btn_replace.text()) == ('Keep my edits', 'Replace')
        k.close()
        # the exports show the edits
        out = os.path.join(tmp, 'edit-out')
        s.out_dir = out
        files = app.export_songs([s])
        lrc = open([f for f in files if f.endswith('.lrc')][0], encoding='utf-8').read()
        assert '[00:01.00]Καλησπέρα κόσμε μου' in lrc and '[00:12.00]Καλησπέρα κόσμε μου' in lrc and '[00:07.20]' in lrc, lrc
        s.out_dir = None
        return {'menu': labels, 'undo_steps': steps, 'unexpected_modals': list(modals)}
    check('review_edits', review_edits)

    def export_confirm():
        from .dialogs import ExportDoneDialog, export_summary
        app, win = ctx['app'], ctx['app'].win
        s = _fresh(app, EDIT_LYRICS, EDIT_LINES)
        assert s.dirty and win.queue.item(app.cur, 0).text().startswith('●'), win.queue.item(app.cur, 0).text()
        out = os.path.join(tmp, 'exp-ok')
        s.out_dir = out
        app.export_songs([s], show=True)
        d = win.export_popup
        assert isinstance(d, ExportDoneDialog) and d.isVisible() and not d.isModal()
        assert export_summary(app.last_export) == '4 files saved for 1 song', export_summary(app.last_export)
        assert out in d.details.toPlainText() and '.lrc' in d.details.toPlainText()
        assert (d.btn_open.text(), d.btn_ok.text()) == (macfx.FOLDER_LABEL, 'OK') and d.btn_open.isEnabled()
        assert not s.dirty and not win.queue.item(app.cur, 0).text().startswith('●')
        d.btn_ok.click()
        assert not d.isVisible()
        # batch: one ok, one failing (the folder is a file), one never synced
        bad = os.path.join(tmp, 'not-a-folder')
        open(bad, 'w').close()
        a, b, c = s, type(s).__new__(type(s)), type(s).__new__(type(s))
        b.__dict__.update(dict(s.__dict__, id='b', path=s.path, out_dir=os.path.join(bad, 'x'), dirty=True))
        c.__dict__.update(dict(s.__dict__, id='c', result=None, status='Ready'))
        a.out_dir = os.path.join(tmp, 'exp-batch')
        app.export_songs([a, b, c], show=True)
        d = win.export_popup
        st = [e['status'] for e in app.last_export]
        assert sorted(st) == ['failed', 'ok', 'skipped'], st
        assert export_summary(app.last_export) == '4 files saved for 1 song · 1 skipped · 1 failed', export_summary(app.last_export)
        html = d.details.toHtml()
        assert 'Failed:' in d.details.toPlainText() and 'Skipped: not synced or transcribed yet' in d.details.toPlainText()
        assert d.windowTitle() == 'Export finished with problems', d.windowTitle()
        assert d.btn_toggle.isVisible() and d.details.isVisible()       # problems: the list is open
        d.btn_toggle.click()
        assert not d.details.isVisible() and d.btn_toggle.text() == 'Show files ▾'
        d.btn_ok.click()
        assert b.dirty
        s.out_dir = None
        return {'summary': export_summary(app.last_export), 'red': 'ff5d5d' in html}
    check('export_confirm', export_confirm)

    def unsaved_close():
        from .dialogs import unsaved_dialog
        from . import updater as upd
        app, win = ctx['app'], ctx['app'].win
        s = _fresh(app, EDIT_LYRICS, EDIT_LINES)
        d = unsaved_dialog(win, [s])
        labels = [b.text() for b in d.buttons.values()]
        assert labels == ['Cancel', 'Close without saving', 'Export all & close'], labels
        assert any('You have unsaved lyrics for 1 song' in l.text() for l in d.findChildren(type(win.status_lbl)))
        d.close()
        asked = []
        win.ask_unsaved = lambda songs, action='close': (asked.append((len(songs), action)) or answer[0])
        answer = ['cancel']
        try:
            assert not app.confirm_close() and s.dirty
            answer[0] = 'discard'
            assert app.confirm_close() and s.dirty
            answer[0] = 'export'
            s.out_dir = os.path.join(tmp, 'close-export')
            assert app.confirm_close() and not s.dirty
            assert app.confirm_close() and len(asked) == 3      # nothing dirty: no question
            s.dirty = True
            bad = os.path.join(tmp, 'not-a-folder2')
            open(bad, 'w').close()
            s.out_dir = os.path.join(bad, 'x')
            assert not app.confirm_close() and s.dirty          # export failed: stays open
            assert win.export_popup.isVisible()
            win.export_popup.close()
            # the window's close button goes through the same question
            answer[0] = 'cancel'
            win.close()
            qapp.processEvents()
            assert win.isVisible()
            # the updater asks before it starts the installer
            from .dialogs import UpdateDialog
            started = []

            class FakeUpd:
                pass
            u = FakeUpd()
            u.app, u.info, u.bar = app, type(win.status_lbl)(), type('B', (), {'set_value': lambda self, v: None})()
            u._set_buttons = lambda st: None
            u._failed = lambda msg: u.info.setText(msg)
            u.accept = lambda: None
            real_run, upd.run_installer = upd.run_installer, lambda *a, **k: started.append(a)
            real_quit, app.quit_for_update = app.quit_for_update, lambda: started.append('quit')
            try:
                UpdateDialog._downloaded(u, os.path.join(tmp, 'fake-setup.exe'))
                assert not started and 'not installed' in u.info.text(), u.info.text()
            finally:
                upd.run_installer, app.quit_for_update = real_run, real_quit
            # removing an unsaved song asks first (the watchdog answers Cancel)
            n = len(app.songs)
            win.queue.selectRow(app.cur)
            before = len(modals)
            win._remove_song()
            assert len(app.songs) == n and modals[before:] == ['Remove unsaved song?'], modals[before:]
        finally:
            del win.ask_unsaved
            s.out_dir = None
        return {'asked': asked}
    check('unsaved_close', unsaved_close)

    ok = all(c['ok'] for c in checks)
    rep = {'version': VERSION, 'ok': ok, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': checks}
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if report_path:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(text)
    try:
        print(text)
    except Exception:
        pass
    if 'app' in ctx:
        ctx['app']._closing_ok = True
        ctx['app'].win.close()
    return 0 if ok else 1
