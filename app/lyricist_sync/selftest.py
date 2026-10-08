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
        assert len(m['wheels']) > 30 and len(m['models']) == 3
        return {'cuda_gb': round(bootstrap.total_size('cuda') / 1e9, 2), 'cpu_gb': round(bootstrap.total_size('cpu') / 1e9, 2)}
    check('manifest', manifest)

    def packaging():
        eng = paths.engine_script()
        assert os.path.isfile(eng), eng
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
        out = os.path.join(tmp, 'out')
        win.out_dir.setText(out)
        win.bom.setChecked(True)
        files = app.export_current()
        names = sorted(os.path.basename(f) for f in files)
        assert names == ['Τραγούδι δοκιμής.lrc', 'Τραγούδι δοκιμής.srt', 'Τραγούδι δοκιμής.ttml', 'Τραγούδι δοκιμής.vtt'], names
        with open(os.path.join(out, 'Τραγούδι δοκιμής.srt'), 'rb') as f:
            assert f.read(3) == b'\xef\xbb\xbf'
        with open(os.path.join(out, 'Τραγούδι δοκιμής.ttml'), 'rb') as f:
            data = f.read()
            assert data[:5] == b'<?xml' and b'xml:lang="el"' in data
        return {'files': names, 'platform': qapp.platformName()}
    check('gui_export', gui)

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
        d.close()
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
        out = {'backdrop': win._backdrop, 'build': winfx.build(), 'thickframe': bool(style & 0x00040000),
               'maximizebox': bool(style & 0x00010000)}
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QCursor
        g = win.geometry()
        tests = {'left_edge': (QPoint(g.left() + 2, g.top() + g.height() // 2), winfx.HTLEFT),
                 'bottom_right': (QPoint(g.right() - 2, g.bottom() - 2), winfx.HTBOTTOMRIGHT),
                 'caption': (QPoint(g.left() + g.width() // 2, g.top() + 22), winfx.HTCAPTION),
                 'client': (QPoint(g.left() + g.width() // 2, g.top() + g.height() // 2), winfx.HTCLIENT)}
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
