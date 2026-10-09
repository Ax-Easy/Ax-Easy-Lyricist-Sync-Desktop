"""CI helpers: run the setup window on its own and measure event-loop latency per step
(--setup-gui --auto), and exercise the updater end to end (--update-test URL)."""
import json
import os
import sys
import platform
import time

WHERE = 'Windows' if os.name == 'nt' else platform.system()


def _qapp():
    from PySide6.QtWidgets import QApplication
    from . import theme as thememod
    qapp = QApplication.instance() or QApplication([sys.argv[0]])
    thememod.apply_platform_style(qapp)
    qapp.setFont(thememod.ui_font())
    return qapp


class _Host:
    """Minimal parent for the glass dialogs (theme + app)."""

    def __init__(self, qapp, dark=True):
        from PySide6.QtWidgets import QWidget
        from . import theme as thememod
        from .widgets import STATE
        self.w = QWidget()
        self.w.theme = thememod.Theme(dark)
        STATE['dark'] = dark
        qapp.setStyleSheet(self.w.theme.qss())
        qapp.setPalette(self.w.theme.palette())


def set_theme(qapp, dlg, dark):
    from . import theme as thememod
    from .widgets import STATE
    dlg.theme = thememod.Theme(dark)
    STATE['dark'] = dark
    qapp.setStyleSheet(dlg.theme.qss())
    qapp.setPalette(dlg.theme.palette())
    dlg.update()
    for w in dlg.findChildren(object):
        if hasattr(w, 'update'):
            try:
                w.update()
            except TypeError:
                pass


def shot(widget, path, dark, label):
    from .screens import compose_labeled
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    compose_labeled(widget, dark, label).save(path)
    print('saved', path, flush=True)


def run_setup_gui(variant, auto, report, shots):
    from PySide6.QtCore import QEventLoop, QTimer
    from . import bootstrap, chrome
    from .dialogs import SetupDialog
    qapp = _qapp()
    host = _Host(qapp, True)
    v = None if variant == 'auto' else variant
    dlg = SetupDialog(host.w, v)
    if not auto:
        return dlg.exec()
    dlg.STALL = float(os.environ.get('LYRICIST_SYNC_STALL', '60'))
    dlg.show()
    t_show = time.time()
    while time.time() - t_show < 1.5:  # first paint/layout happens before anyone could click Start
        qapp.processEvents()
        time.sleep(0.01)
    dlg.start()
    info = {'shots': [], 'heartbeat_seen': [], 'variant': dlg.setup.variant, 'path': chrome.label()}
    t0 = time.time()
    taken = {'mid': False, 'install': False}

    def tick():
        steps, cur, _l, _n = dlg.state.snapshot(10 ** 9)
        if dlg.stall.text() and cur not in info['heartbeat_seen']:
            info['heartbeat_seen'].append(cur)
        if shots and not taken['mid'] and cur == 'dl_torch':
            st = steps['dl_torch']
            if st['total'] and st['done'] / st['total'] > 0.4:
                taken['mid'] = True
                dlg.lat_mute_until = time.perf_counter() + 60
                os.makedirs(shots, exist_ok=True)
                for dark in (True, False):
                    set_theme(qapp, dlg, dark)
                    p = os.path.join(shots, '%s_5_setup_midway.png' % ('dark' if dark else 'light'))
                    shot(dlg, p, dark, 'Setup during step 1 · live run on %s, %s variant, local throttled mirror · %s' % (WHERE, dlg.setup.variant.upper(), chrome.label()))
                    info['shots'].append(p)
                set_theme(qapp, dlg, True)
                dlg.lat_mute_until = time.perf_counter() + 1.5  # screenshots + theme switch block the loop on purpose
        if shots and not taken['install'] and cur == 'install' and steps['install']['t0'] and time.time() - steps['install']['t0'] > 5:
            taken['install'] = True
            dlg.lat_mute_until = time.perf_counter() + 60
            for dark in (True, False):
                set_theme(qapp, dlg, dark)
                p = os.path.join(shots, '%s_6_setup_installing.png' % ('dark' if dark else 'light'))
                shot(dlg, p, dark, 'Setup during step 2 (installing PyTorch) · live run on %s · %s' % (WHERE, chrome.label()))
                info['shots'].append(p)
            set_theme(qapp, dlg, True)
            dlg.lat_mute_until = time.perf_counter() + 1.5
        if dlg.thread and not dlg.thread.is_alive() and (dlg.done_state is not None or dlg.error is not None or
                                                         (dlg._result and dlg._result[0] != 'ok')):
            loop.quit()
        if time.time() - t0 > 3600:
            loop.quit()

    loop = QEventLoop()
    tm = QTimer()
    tm.timeout.connect(tick)
    tm.start(200)
    loop.exec()
    tm.stop()
    steps, _c, _l, _n = dlg.state.snapshot(10 ** 9)
    ok = dlg.done_state is not None
    worst = max(dlg.latency.values()) if dlg.latency else 0
    # Shared CI runners stall now and then for ~200 ms regardless of the app (main build 37947068051:
    # 3 stalls of 117-209 ms in 205 s). Responsive = no stall of 400 ms or more and at most 3 over 200 ms.
    over = [x for x in (dlg.lat_spikes or []) if x.get('ms', 0) >= 200]
    lat_ok = worst < 400 and len(over) <= 3
    rep = dict(info, ok=ok, error=dlg.error, seconds=round(time.time() - t0, 1), latency_ms=dlg.latency,
               max_latency_ms=worst, latency_ok=lat_ok, latency_spikes=dlg.lat_spikes,
               steps={k: {'status': v['status'], 'seconds': round((v['t1'] or time.time()) - v['t0'], 1) if v['t0'] else 0,
                          'detail': v['detail']} for k, v in steps.items()})
    if report:
        with open(report, 'w', encoding='utf-8') as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1), flush=True)
    return 0 if ok and lat_ok else 1


def run_update_test(url, install, report):
    """1) the popup finds the newer version at URL, 2) download + SHA256, 3) optional silent
    install (detached; this process exits right away so the installer can replace it),
    4) a manifest with a wrong hash is refused, 5) a missing manifest shows the friendly message."""
    from PySide6.QtCore import QEventLoop, QTimer
    from . import VERSION, updater
    from .app import App
    from .dialogs import UpdateDialog
    qapp = _qapp()
    rep = {'url': url, 'checks': []}

    def check(name, ok, detail=''):
        rep['checks'].append({'name': name, 'ok': bool(ok), 'detail': detail})
        print(('PASS ' if ok else 'FAIL ') + name + (' · ' + str(detail) if detail else ''), flush=True)

    def wait(pred, sec=120):
        loop = QEventLoop()
        t0 = time.time()
        tm = QTimer()
        tm.timeout.connect(lambda: loop.quit() if pred() or time.time() - t0 > sec else None)
        tm.start(50)
        loop.exec()
        tm.stop()
        return pred()

    app = App(qapp, screenshot=True)
    if updater.is_release_api(url):   # a (mock) GitHub "releases/latest" endpoint
        app.settings['update_api'] = url
        app.settings['update_url'] = ''
    else:                             # the optional update.json fallback on its own
        app.settings['update_api'] = 'http://127.0.0.1:9/repos/none/none/releases/latest'
        app.settings['update_url'] = url
    app.update_no_install = True
    dlg = UpdateDialog(app.win, app)
    dlg.show()
    wait(lambda: dlg.result is not None, 60)
    r = dlg.result or {}
    m = r.get('manifest') or {}
    check('popup detects the newer version', r.get('status') == 'available' and dlg.btn_now.isVisible() and
          m.get('version', '') in dlg.head.text(), '%s → %s · %s %s %s' % (VERSION, m.get('version'), r.get('status'),
                                                                            r.get('message'), r.get('detail', '')))
    if updater.is_release_api(url):
        check('release notes from the release body', bool(m.get('notes')) and dlg.notes.isVisible(), (m.get('notes') or '')[:60])
        check('SHA256 taken from SHA256SUMS', len(m.get('sha256') or '') == 64, m.get('sha256'))
        r5 = updater.check_for(VERSION, app.settings)
        check('second check answered from the ETag cache (304)', r5.get('status') == 'available' and r5.get('cached'),
              '%s cached=%s' % (r5.get('status'), r5.get('cached')))
    if r.get('status') != 'available':   # nothing to download: report and stop here
        rep['ok'] = False
        if report:
            with open(report, 'w', encoding='utf-8') as f:
                json.dump(rep, f, ensure_ascii=False, indent=1)
        return 1
    check('badge shown on the Update button', app.win.btn_update.badge())
    dlg.update_now()
    wait(lambda: dlg.installer is not None or (dlg.thread and not dlg.thread.is_alive() and dlg.info.text()), 600)
    wait(lambda: dlg.installer is not None, 5)
    ok = dlg.installer and os.path.exists(dlg.installer) and updater.sha256_file(dlg.installer) == m.get('sha256')
    check('download + SHA256 verified', ok, dlg.installer or dlg.info.text())
    # wrong hash
    bad = dict(m, sha256='0' * 64)
    try:
        if dlg.installer:
            os.remove(dlg.installer)
        updater.download(bad)
        check('hash mismatch rejected', False, 'downloaded without error')
    except updater.UpdateError as e:
        leftover = [f for f in os.listdir(updater.updates_dir()) if f.endswith(('.exe', '.dmg', '.part'))]
        check('hash mismatch rejected', 'SHA256' in str(e) and not leftover, str(e))
    # non-HTTPS refused outside the test mode
    os.environ['LYRICIST_SYNC_UPDATE_TEST'] = '0'
    r2 = updater.check(VERSION, url)
    check('plain HTTP refused', r2['status'] == 'insecure', r2['message'])
    os.environ['LYRICIST_SYNC_UPDATE_TEST'] = '1'
    # 404 + offline: friendly, no crash
    r3 = updater.check(VERSION, url.rsplit('/', 1)[0] + ('/not-published' if updater.is_release_api(url) else '/not-published.json'))
    d3 = UpdateDialog(app.win, app, r3)
    check('404 shows the friendly message', r3['status'] == 'notfound' and 'No update information' in d3.head.text(), r3['message'])
    r4 = updater.check(VERSION, 'http://127.0.0.1:9/repos/a/b/releases/latest' if updater.is_release_api(url)
                       else 'http://127.0.0.1:9/update.json', timeout=3)
    check('offline shows the friendly message', r4['status'] == 'offline', r4['message'])
    if install and updater.IS_MAC:
        path = updater.download(m)
        try:   # mount, codesign/Team ID/Gatekeeper checks, stage next to this app, swap after this process exits
            how, info = updater.install_mac(path, relaunch=False)
            check('DMG verified and the swap staged', how == 'replaced', json.dumps(info)[:400])
        except updater.UpdateError as e:
            check('DMG verified and the swap staged', False, str(e))
    elif install:
        path = updater.download(m)
        log = os.path.join(os.getcwd(), 'update-install.log')
        updater.run_installer(path, relaunch=False, wait=False, extra=['/LOG=%s' % log])
        check('silent installer started', True, ' '.join(updater.INSTALL_ARGS))
    rep['ok'] = all(c['ok'] for c in rep['checks'])
    if report:
        with open(report, 'w', encoding='utf-8') as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    return 0 if rep['ok'] else 1
