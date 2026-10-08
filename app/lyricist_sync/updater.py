"""In-app updates from a static manifest on the publisher's own site (no GitHub API, no token).

update.json: {"version": "1.1.0", "date": "2026-10-09", "notes": "markdown or plain text",
              "url": "https://www.ax-easy.com/lyricist-sync/AxEasy-LyricistSync-Setup-1.1.0.exe",
              "sha256": "<64 hex>", "size": 41000000, "minimum_os": "10.0.17763"}
Only HTTPS is accepted (plain HTTP on 127.0.0.1/localhost only when LYRICIST_SYNC_UPDATE_TEST=1,
for the CI test server). Downloads resume and are SHA256-verified before anything runs.
No Qt here: the GUI and the CLI test share it."""
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import paths

DEFAULT_URL = 'https://www.ax-easy.com/lyricist-sync/update.json'
UA = 'AxEasy-LyricistSync-Updater'
INSTALL_ARGS = ['/SILENT', '/SUPPRESSMSGBOXES', '/CLOSEAPPLICATIONS', '/RESTARTAPPLICATIONS', '/NORESTART']


class UpdateError(Exception):
    """A problem worth showing to the user as is (friendly text)."""


class Cancelled(Exception):
    pass


def manifest_url(settings=None):
    return (os.environ.get('LYRICIST_SYNC_UPDATE_URL') or (settings or {}).get('update_url') or DEFAULT_URL).strip()


def parse_version(v):
    parts = re.findall(r'\d+', str(v or ''))[:4]
    return tuple(int(x) for x in parts) + (0,) * (4 - len(parts))


def is_newer(latest, current):
    return parse_version(latest) > parse_version(current)


def url_allowed(url):
    u = urllib.parse.urlparse(url)
    if u.scheme == 'https' and u.hostname:
        return True
    return (u.scheme == 'http' and u.hostname in ('127.0.0.1', 'localhost')
            and os.environ.get('LYRICIST_SYNC_UPDATE_TEST') == '1')


def os_build():
    if os.name != 'nt':
        return (0, 0, 0)
    v = sys.getwindowsversion()
    return (v.major, v.minor, v.build)


def _get(url, timeout):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(256 * 1024)


def check(current, url=None, timeout=10):
    """-> dict(status=available|current|notfound|offline|invalid|insecure, message, manifest).
    Never raises."""
    url = url or DEFAULT_URL
    res = {'status': 'invalid', 'message': '', 'manifest': None, 'url': url, 'current': current}
    if not url_allowed(url):
        res.update(status='insecure', message='The update address must use HTTPS.')
        return res
    try:
        data = _get(url, timeout)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            res.update(status='notfound', message="No update information has been published yet. Please try again later.")
        else:
            res.update(status='offline', message='The update server answered with an error (HTTP %d). Please try again later.' % e.code)
        return res
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        res.update(status='offline', message="Couldn't reach the update server. Check your internet connection and try again.")
        res['detail'] = str(e)
        return res
    try:
        m = json.loads(data.decode('utf-8-sig'))
        m = validate(m)
    except (ValueError, UpdateError) as e:
        res.update(status='invalid', message='The update information on the server is not valid (%s).' % e)
        return res
    res['manifest'] = m
    if m.get('minimum_os') and os.name == 'nt' and os_build() < parse_version(m['minimum_os'])[:3]:
        res.update(status='current', message='Version %s needs Windows %s or newer.' % (m['version'], m['minimum_os']))
        return res
    if is_newer(m['version'], current):
        res.update(status='available', message='Version %s is available.' % m['version'])
    else:
        res.update(status='current', message="You're up to date.")
    return res


def validate(m):
    if not isinstance(m, dict):
        raise UpdateError('not an object')
    for k in ('version', 'url', 'sha256', 'size'):
        if k not in m:
            raise UpdateError('missing "%s"' % k)
    if not re.fullmatch(r'[0-9a-fA-F]{64}', str(m['sha256'])):
        raise UpdateError('bad sha256')
    try:
        m['size'] = int(m['size'])
    except (TypeError, ValueError):
        raise UpdateError('bad size')
    if m['size'] <= 0 or m['size'] > 2 * 1024 ** 3:
        raise UpdateError('bad size')
    if not parse_version(m['version'])[0] and not any(parse_version(m['version'])):
        raise UpdateError('bad version')
    m['sha256'] = str(m['sha256']).lower()
    m['notes'] = str(m.get('notes') or '')
    m['date'] = str(m.get('date') or '')
    return m


def updates_dir():
    d = os.path.join(paths.home(), 'updates')
    os.makedirs(d, exist_ok=True)
    return d


def installer_name(m):
    name = os.path.basename(urllib.parse.urlparse(m['url']).path) or 'LyricistSync-Setup.exe'
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', name)
    if not name.lower().endswith('.exe'):
        name += '.exe'
    return name


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def download(m, on_progress=None, cancel=None, retries=5):
    """Download the installer to updates/ with resume; verify size + SHA256. -> path.
    Raises UpdateError (friendly) or Cancelled."""
    on_progress = on_progress or (lambda done, total, spd: None)
    cancel = cancel or threading.Event()
    url = m['url']
    if not url_allowed(url):
        raise UpdateError('Refusing to download the update: the address is not HTTPS.')
    dest = os.path.join(updates_dir(), installer_name(m))
    if os.path.exists(dest) and os.path.getsize(dest) == m['size'] and sha256_file(dest) == m['sha256']:
        on_progress(m['size'], m['size'], 0)
        return dest
    part = dest + '.part'
    last_err = None
    for attempt in range(retries):
        if cancel.is_set():
            raise Cancelled()
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if have > m['size']:
            os.remove(part)
            have = 0
        try:
            if have < m['size']:
                hdr = {'User-Agent': UA}
                if have:
                    hdr['Range'] = 'bytes=%d-' % have
                with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=30) as r:
                    if have and r.status != 206:
                        have = 0
                    with open(part, 'ab' if have else 'wb') as f:
                        t0, b0, last = time.time(), have, 0
                        while True:
                            if cancel.is_set():
                                raise Cancelled()
                            b = r.read(1 << 18)
                            if not b:
                                break
                            f.write(b)
                            have += len(b)
                            if have > m['size']:
                                break
                            now = time.time()
                            if now - last > 0.2:
                                last = now
                                on_progress(have, m['size'], (have - b0) / max(0.001, now - t0))
            if have != m['size']:
                if have > m['size']:
                    os.remove(part)
                    raise UpdateError('The downloaded file is larger than announced; it was deleted. Please try again later.')
                raise IOError('incomplete download (%d of %d bytes)' % (have, m['size']))
            got = sha256_file(part)
            if got != m['sha256']:
                os.remove(part)
                raise UpdateError("The downloaded installer failed the SHA256 check, so it was deleted and won't be run.")
            os.replace(part, dest)
            on_progress(m['size'], m['size'], 0)
            return dest
        except (Cancelled, UpdateError):
            raise
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise UpdateError('The installer file was not found on the server (HTTP %d).' % e.code)
            last_err = e
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            last_err = e
        for _ in range(int(min(20, 2 * 2 ** attempt) * 5)):
            if cancel.is_set():
                raise Cancelled()
            time.sleep(0.2)
    raise UpdateError("The download didn't finish (%s). Press Update now to resume." % (last_err or 'network error'))


def run_installer(path, relaunch=True, wait=False, extra=None):
    """Start the Inno Setup installer silently. The installer closes this app if needed,
    keeps everything in %LOCALAPPDATA%\\Ax-Easy\\LyricistSync (settings, engine, models)
    and, with relaunch, starts the new version when it's done."""
    if not os.path.exists(path):
        raise UpdateError('The installer file is missing.')
    args = [path] + INSTALL_ARGS + (['/RELAUNCH=1'] if relaunch else []) + list(extra or [])
    from .bootstrap import popen
    flags = 0
    if os.name == 'nt':
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    p = popen(args, creationflags=flags, close_fds=True)
    if wait:
        return p.wait()
    return p


def cleanup(keep=None):
    """Remove old downloaded installers (keeps `keep`)."""
    d = updates_dir()
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if keep and os.path.abspath(p) == os.path.abspath(keep):
            continue
        try:
            if time.time() - os.path.getmtime(p) > 3600:
                os.remove(p)
        except OSError:
            pass


def due(settings, now=None):
    """Quiet launch check: enabled and not done in the last 24 h."""
    if not settings.get('update_check', True):
        return False
    return (now or time.time()) - float(settings.get('update_last', 0) or 0) >= 24 * 3600
