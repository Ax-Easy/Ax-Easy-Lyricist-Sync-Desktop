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
    from . import VERSION, bootstrap, paths
    from .formats import build

    def manifest():
        m = bootstrap.manifest()
        assert len(m['wheels']) > 30 and len(m['models']) >= 3
        return {'cuda_gb': round(bootstrap.total_size('cuda') / 1e9, 2), 'cpu_gb': round(bootstrap.total_size('cpu') / 1e9, 2)}
    check('manifest', manifest)

    def packaging():
        eng = paths.engine_script()
        assert os.path.isfile(eng), eng
        for f in ('timing.py',):  # modules the engine imports from its own folder
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

    from PySide6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication([sys.argv[0]])
    ctx = {}

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
        assert 'Open folder' in win.status_lbl.text() and 'href=' in win.status_lbl.text(), win.status_lbl.text()
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
        for name, m in (('update.json', man), ('bad.json', dict(man, sha256='0' * 64)), ('old.json', dict(man, version=VERSION))):
            with open(os.path.join(srv_dir, name), 'w') as f:
                json.dump(m, f)
        old = os.environ.get('LYRICIST_SYNC_UPDATE_TEST')
        os.environ['LYRICIST_SYNC_UPDATE_TEST'] = '1'
        out = {}
        try:
            out['available'] = updater.check(VERSION, base + 'update.json')['status']
            out['current'] = updater.check(VERSION, base + 'old.json')['status']
            out['notfound'] = updater.check(VERSION, base + 'nope.json')['status']
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
        if qapp.platformName() == 'windows':
            assert ok, 'QtMultimedia backend (FFmpeg) not available: play-from-line would not work'
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
        ctx['app'].win.close()
    return 0 if ok else 1
