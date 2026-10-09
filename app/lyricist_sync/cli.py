"""Command line: LyricistSync.exe [--selftest | --screens DIR | --setup | --sync AUDIO ...] (GUI without arguments)."""
import argparse
import json
import os
import subprocess
import sys
import threading
import time


def _console():
    """A windowed exe has no stdout; attach to the parent console when started from cmd/PowerShell."""
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):
                sys.stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace')
                sys.stderr = sys.stdout
        except Exception:
            pass
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = sys.stdout


def main(argv=None):
    argv = sys.argv if argv is None else argv
    ap = argparse.ArgumentParser(prog='LyricistSync')
    ap.add_argument('files', nargs='*', help='audio files to open in the GUI')
    ap.add_argument('--version', action='store_true')
    ap.add_argument('--selftest', action='store_true', help='check GUI, exporters and packaging without models')
    ap.add_argument('--screens', metavar='DIR', help='render screenshots of the main window')
    ap.add_argument('--screens-maximized', metavar='DIR', help='render the maximized window on 1280×720, 1920×1080 and '
                    '2560×1440 offscreen screens')
    ap.add_argument('--fixture', metavar='DIR', help='folder with demo_*.mp3/.txt/.result.json for --screens')
    ap.add_argument('--setup', action='store_true', help='download and install the engine without the GUI')
    ap.add_argument('--variant', choices=['auto', 'cuda', 'cpu'], default='auto')
    ap.add_argument('--sync', metavar='AUDIO', nargs='+', help='sync audio files without the GUI')
    ap.add_argument('--transcribe', metavar='AUDIO', nargs='+', help='no lyrics needed: Whisper writes the lines '
                    '(saves AUDIO.transcript.txt and the timed files)')
    ap.add_argument('--whisper', default='auto', help='Whisper size: auto (by hardware), small, medium, large-v3-turbo, large-v3')
    ap.add_argument('--lyrics', metavar='TXT', help='lyrics file (default: same name .txt next to the audio)')
    ap.add_argument('--lang', default='auto')
    ap.add_argument('--no-music-lines', action='store_true', help='don\'t add ♪ lines in instrumental parts')
    ap.add_argument('--music-gap', type=float, default=8.0, help='shortest instrumental gap that gets a ♪ line (3-30 s)')
    ap.add_argument('--out', metavar='DIR', help='output folder (default: next to the audio)')
    ap.add_argument('--formats', default='ttml,lrc,srt,vtt')
    ap.add_argument('--bom', action='store_true', help='UTF-8 BOM in .srt')
    ap.add_argument('--report', metavar='JSON', help='write a JSON report (selftest/sync/setup-gui/update-test)')
    ap.add_argument('--force-win10-style', action='store_true',
                    help='use the Windows 10 window path (painted glass + painted shadow) on any Windows')
    ap.add_argument('--setup-gui', action='store_true', help='run the setup window by itself (with --auto: start it, '
                    'measure event-loop latency, close when done)')
    ap.add_argument('--auto', action='store_true')
    ap.add_argument('--shots', metavar='DIR', help='with --setup-gui: screenshots of the setup window midway (dark+light)')
    ap.add_argument('--update-test', metavar='URL', help='check/download/verify an update from URL (CI test); '
                    'with --install also run the installer silently')
    ap.add_argument('--install', action='store_true')
    a = ap.parse_args(argv[1:])
    if a.force_win10_style:
        os.environ['LYRICIST_SYNC_FORCE_WIN10'] = '1'
        from . import chrome
        chrome.force_win10(True)
    if a.setup_gui:
        _console()
        from .setup_test import run_setup_gui
        return _hard_exit(run_setup_gui(a.variant, a.auto, a.report, a.shots))
    if a.update_test:
        _console()
        from .setup_test import run_update_test
        return _hard_exit(run_update_test(a.update_test, a.install, a.report))
    headless = a.version or a.selftest or a.screens or a.setup or a.sync or a.screens_maximized or a.transcribe
    if not headless:
        from .app import run_gui
        return run_gui([argv[0]] + a.files)
    _console()
    if a.version:
        from . import VERSION
        print(VERSION)
        return 0
    if a.selftest:
        from .selftest import run
        return _hard_exit(run(a.report))
    if a.screens:
        from .screens import render
        return _hard_exit(render(a.screens, a.fixture))
    if a.screens_maximized:
        from .screens import render_maximized
        return _hard_exit(render_maximized(a.screens_maximized, a.fixture))
    if a.setup:
        return cli_setup(a.variant)
    if a.sync or a.transcribe:
        return cli_sync(a)
    return 0


def _hard_exit(rc):
    """Skip Qt/Python teardown for headless runs (avoids exit-time crashes in offscreen Qt)."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(rc)


def cli_setup(variant):
    from . import bootstrap
    gpu = bootstrap.detect_gpu()
    v = bootstrap.recommended_variant(gpu) if variant == 'auto' else variant
    print('GPU: %s → %s build, %.2f GB to download' % (gpu.get('name') or 'none', v, bootstrap.total_size(v) / 1e9), flush=True)
    last = [0]

    def prog(done, total, it, spd):
        if time.time() - last[0] > 5:
            last[0] = time.time()
            print('  %5.1f%%  %.2f/%.2f GB  %.1f MB/s  %s' % (100 * done / total, done / 1e9, total / 1e9, spd / 1e6, it.get('label')), flush=True)

    t0 = time.time()
    st = bootstrap.Setup(v, on_progress=prog, on_status=lambda s: print(s, flush=True), on_log=lambda s: print(s, flush=True)).run()
    st = st or bootstrap.state() or {}
    print('Setup finished in %.0f s: %s' % (time.time() - t0, json.dumps(st.get('engine'))), flush=True)
    return 0


def cli_sync(a):
    from . import bootstrap, paths
    from .formats import decode_text
    from .lyrics import resolve_lang, sidecar_lyrics, split_lines
    from .export import export_song, read_tags
    if not bootstrap.is_ready():
        print('The engine is not set up. Run LyricistSync --setup first (or start the app once).')
        return 2
    st = bootstrap.state() or {}
    eng = st.get('engine') or {}
    tier = bootstrap.whisper_tier(eng.get('vram_gb') if eng.get('device') == 'cuda' else None, st.get('variant', 'cpu'))
    whisper = bootstrap.effective_whisper(a.whisper, tier, bootstrap.whisper_installed())
    mode = 'transcribe' if a.transcribe else 'sync'
    print('Whisper: %s (hardware tier %s)' % (whisper, tier), flush=True)
    py = paths.runtime_python()
    proc = bootstrap.popen([py, '-u', paths.engine_script(), '--models', paths.models_dir(), 'serve'], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=open(os.path.join(paths.home(), 'engine.log'), 'a'),
                           env=bootstrap.engine_env(), creationflags=bootstrap.NO_WINDOW)
    report = []
    rc = 0

    class S:  # minimal song object for export_song
        pass

    for n, audio in enumerate(a.transcribe or a.sync):
        if mode == 'transcribe':
            lang = None if a.lang in ('', 'auto') else resolve_lang(a.lang, [])[0]
            job = {'cmd': 'transcribe', 'id': str(n), 'audio': os.path.abspath(audio), 'lang': lang, 'whisper': whisper}
            iso = ''
            lines = []
        elif a.lyrics:
            with open(a.lyrics, 'rb') as f:
                text = decode_text(f.read())[0]
        else:
            text = sidecar_lyrics(audio)[0] or ''
        if mode == 'sync':
            lines = split_lines(text)
            if not lines:
                print('%s: no lyrics found' % audio)
                rc = 1
                continue
            lang, iso = resolve_lang(a.lang, lines)
            job = {'cmd': 'sync', 'id': str(n), 'audio': os.path.abspath(audio), 'lines': lines, 'lang': lang, 'iso': iso,
                   'whisper': whisper}
        proc.stdin.write((json.dumps(job, ensure_ascii=False) + '\n').encode('utf-8'))
        proc.stdin.flush()
        res = None
        for raw in proc.stdout:
            ev = json.loads(raw.decode('utf-8'))
            if ev.get('event') == 'hello':
                print('Engine: %s %s (torch %s)' % (ev.get('device'), ev.get('device_name'), ev.get('torch')), flush=True)
            elif ev.get('event') == 'progress':
                pass
            elif ev.get('event') == 'result':
                res = ev['result']
                break
            elif ev.get('event') == 'error':
                print('%s: ERROR %s' % (audio, ev.get('error')), flush=True)
                break
        if not res:
            rc = 1
            continue
        s = S()
        if not a.no_music_lines:
            from . import instrumental
            instrumental.apply(res, {'inst_gap': a.music_gap})
        s.path, s.tags, s.result, s.iso = audio, read_tags(audio), res, iso
        if not iso and res.get('language'):
            s.iso = {'en': 'eng', 'el': 'ell'}.get(res['language'], '')
        out = a.out or os.path.dirname(os.path.abspath(audio))
        files = export_song(s, {'dir': out, 'formats': a.formats.split(','), 'bom': a.bom})
        if mode == 'transcribe':
            tp = os.path.join(out, os.path.splitext(os.path.basename(audio))[0] + '.transcript.txt')
            with open(tp, 'w', encoding='utf-8') as f:
                f.write(res.get('text', '') + '\n')
            files.append(tp)
            low = sum(1 for l in res['lines'] if (l.get('conf') if l.get('conf') is not None else 1) < 0.6 and not l.get('inst'))
            print('%s: transcribed %d lines (%s, Whisper %s, %d to check, %d segments dropped), %.1f s on %s → %s' % (
                os.path.basename(audio), sum(1 for l in res['lines'] if not l.get('inst')), res.get('language'),
                res.get('whisper'), low, len(res.get('dropped') or []), res['timings']['total'], res['device'],
                ', '.join(files)), flush=True)
            report.append({'audio': audio, 'files': files, 'result': res})
            continue
        print('%s: %d lines (+%d music), %d repeats, %.1f s on %s → %s' % (
            os.path.basename(audio), sum(1 for l in res['lines'] if not l.get('inst')), sum(1 for l in res['lines'] if l.get('inst')), len(res['repeats']),
                                                               res['timings']['total'], res['device'], ', '.join(files)), flush=True)
        report.append({'audio': audio, 'files': files, 'result': res})
    try:
        proc.stdin.close()
        proc.wait(timeout=30)
    except Exception:
        proc.kill()
    if a.report:
        with open(a.report, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    return rc
