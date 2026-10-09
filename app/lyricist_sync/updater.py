"""In-app updates from the GitHub Releases of the public repository (no token, no ax-easy.com).

The app asks https://api.github.com/repos/Ax-Easy/Ax-Easy-Lyricist-Sync-Desktop/releases/latest
(unauthenticated, with a User-Agent and an ETag cache, so repeated checks cost no rate limit).
GitHub never returns drafts or prereleases there, and they are ignored anyway. The version comes
from tag_name (vX.Y.Z) and the release notes from the release body (markdown).
The download is the asset whose name matches this platform:
  Windows: AxEasy-LyricistSync-Desktop-Setup-*.exe     Mac: *-mac-universal.dmg
Its SHA256 comes from the SHA256SUMS asset of the same release; an update without a matching
line is refused. On a Mac the update is a notarized DMG: after the SHA256 check the app mounts it,
checks the new app's signature (same Developer ID team) and Gatekeeper assessment, and either
replaces itself in place (when its folder is writable) or opens the DMG for a drag to Applications.

Optional fallback (off by default): a static update.json manifest, used only when an address is
configured (settings "update_url" or LYRICIST_SYNC_UPDATE_URL) and GitHub can't be reached.
update.json: {"version", "date", "notes", "url", "sha256", "size", "minimum_os", "mac": {...}}.

Only HTTPS is accepted (plain HTTP on 127.0.0.1/localhost only when LYRICIST_SYNC_UPDATE_TEST=1,
for the CI test servers). Downloads resume and are SHA256-verified before anything runs.
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

REPO = 'Ax-Easy/Ax-Easy-Lyricist-Sync-Desktop'
GITHUB_API = 'https://api.github.com/repos/%s/releases/latest' % REPO
RELEASES_PAGE = 'https://github.com/%s/releases' % REPO
DEFAULT_URL = ''                 # optional update.json fallback: none unless configured
ASSET_WIN = re.compile(r'^AxEasy-LyricistSync-Desktop-Setup-[0-9][0-9A-Za-z.\-]*\.exe$')
ASSET_MAC = re.compile(r'^.+-mac-universal\.dmg$')
SUMS_NAME = 'SHA256SUMS'
IS_MAC = sys.platform == 'darwin'
TEAM_ID = '7BMSHL4YZ6'           # Developer ID team that signs the Mac app
UA = 'AxEasy-LyricistSync-Updater'
INSTALL_ARGS = ['/SILENT', '/SUPPRESSMSGBOXES', '/CLOSEAPPLICATIONS', '/RESTARTAPPLICATIONS', '/NORESTART']


class UpdateError(Exception):
    """A problem worth showing to the user as is (friendly text)."""


class Cancelled(Exception):
    pass


def manifest_url(settings=None):
    """The optional update.json fallback ('' = none, the default)."""
    return (os.environ.get('LYRICIST_SYNC_UPDATE_URL') or (settings or {}).get('update_url') or DEFAULT_URL).strip()


def api_url(settings=None):
    """The GitHub "latest release" endpoint (a local mock in the CI tests)."""
    return (os.environ.get('LYRICIST_SYNC_UPDATE_API') or (settings or {}).get('update_api') or GITHUB_API).strip()


def is_release_api(url):
    return '/releases/' in urllib.parse.urlparse(url or '').path


def check_for(current, settings=None, timeout=10):
    """What the app calls: GitHub Releases, then the configured update.json (if any) when GitHub fails."""
    return check(current, api_url(settings), timeout, fallback=manifest_url(settings))


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


def check(current, url=None, timeout=10, fallback=None):
    """-> dict(status=available|current|notfound|offline|invalid|insecure, message, manifest, source).
    `url`: a GitHub "releases/latest" endpoint (default) or, for an explicit manifest, an update.json.
    `fallback`: an update.json tried when GitHub can't be reached or has nothing usable. Never raises."""
    url = (url or GITHUB_API).strip()
    if not is_release_api(url):
        return check_manifest(current, url, timeout)
    res = check_github(current, url, timeout)
    if fallback and res['status'] in ('offline', 'notfound', 'invalid'):
        fb = check_manifest(current, fallback, timeout)
        if fb['status'] in ('available', 'current'):
            fb['github'] = {k: res[k] for k in ('status', 'message')}
            return fb
    return res


def _cache_path():
    return os.path.join(updates_dir(), 'github-release.json')


def _load_cache(url):
    try:
        with open(_cache_path(), encoding='utf-8') as f:
            c = json.load(f)
        return c if c.get('url') == url and c.get('etag') and isinstance(c.get('release'), dict) else None
    except (OSError, ValueError):
        return None


def _save_cache(url, etag, release):
    try:
        with open(_cache_path(), 'w', encoding='utf-8') as f:
            json.dump({'url': url, 'etag': etag, 'release': release, 'time': time.time()}, f)
    except OSError:
        pass


def _rate_limit_message(headers):
    reset = (headers or {}).get('X-RateLimit-Reset') or (headers or {}).get('x-ratelimit-reset')
    when = ''
    try:
        when = ' after %s' % time.strftime('%H:%M', time.localtime(int(reset)))
    except (TypeError, ValueError):
        retry = (headers or {}).get('Retry-After')
        if retry and str(retry).isdigit():
            when = ' in %d minutes' % max(1, int(retry) // 60)
    return ("GitHub's limit for update checks from this network was reached. Please try again%s." % (when or ' later'))


def fetch_release(url, timeout=10):
    """GET the release JSON with the ETag cache. -> (release dict, from_cache). Raises urllib errors."""
    hdr = {'User-Agent': UA, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    cached = _load_cache(url)
    if cached:
        hdr['If-None-Match'] = cached['etag']
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=timeout) as r:
            data = r.read(2 * 1024 * 1024)
            etag = r.headers.get('ETag')
    except urllib.error.HTTPError as e:
        if e.code == 304 and cached:
            return cached['release'], True
        raise
    rel = json.loads(data.decode('utf-8-sig'))
    if etag and isinstance(rel, dict):
        _save_cache(url, etag, rel)
    return rel, False


def release_entry(rel, mac=None):
    """A GitHub release -> manifest-like dict (version, date, notes, url, size, name, sums_url),
    None for a draft/prerelease. Raises UpdateError when it isn't a usable release."""
    mac = IS_MAC if mac is None else mac
    if not isinstance(rel, dict):
        raise UpdateError('not a release')
    if rel.get('draft') or rel.get('prerelease'):
        return None
    tag = str(rel.get('tag_name') or '').strip()
    mv = re.fullmatch(r'[vV]?(\d+(?:\.\d+){1,3})', tag)
    if not mv:
        raise UpdateError('the release tag "%s" is not a version' % tag[:40])
    pat = ASSET_MAC if mac else ASSET_WIN
    assets = [a for a in (rel.get('assets') or []) if isinstance(a, dict)]
    asset = next((a for a in assets if pat.match(str(a.get('name') or ''))), None)
    sums = next((a for a in assets if a.get('name') == SUMS_NAME), None)
    out = {'version': mv.group(1), 'date': str(rel.get('published_at') or '')[:10], 'notes': str(rel.get('body') or ''),
           'page': rel.get('html_url') or RELEASES_PAGE, 'url': None, 'size': 0, 'name': None,
           'sums_url': sums.get('browser_download_url') if sums else None}
    if asset:
        out.update(url=asset.get('browser_download_url'), size=asset.get('size') or 0, name=asset.get('name'))
    return out


def parse_sums(text, name):
    """The SHA256 of `name` in a SHA256SUMS file (sha256sum format), or None."""
    for line in (text or '').splitlines():
        m = re.match(r'^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$', line)
        if m and os.path.basename(m.group(2)) == name:
            return m.group(1).lower()
    return None


def check_github(current, url, timeout=10):
    res = {'status': 'invalid', 'message': '', 'manifest': None, 'url': url, 'current': current, 'source': 'github'}
    if not url_allowed(url):
        res.update(status='insecure', message='The update address must use HTTPS.')
        return res
    try:
        rel, cached = fetch_release(url, timeout)
        res['cached'] = cached
    except urllib.error.HTTPError as e:
        if e.code in (403, 429) and (e.headers.get('X-RateLimit-Remaining') == '0' or e.code == 429 or e.headers.get('Retry-After')):
            res.update(status='offline', message=_rate_limit_message(e.headers), ratelimited=True)
        elif e.code in (404, 410):
            res.update(status='notfound', message='No update information has been published yet. Please try again later.')
        else:
            res.update(status='offline', message='The update server answered with an error (HTTP %d). Please try again later.' % e.code)
        return res
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        res.update(status='offline', message="Couldn't reach the update server. Check your internet connection and try again.")
        res['detail'] = str(e)
        return res
    except ValueError as e:
        res.update(status='invalid', message='The update information on the server is not valid (%s).' % e)
        return res
    try:
        m = release_entry(rel)
    except UpdateError as e:
        res.update(status='invalid', message='The update information on the server is not valid (%s).' % e)
        return res
    if m is None:   # a draft or prerelease: never offered
        res.update(status='current', message="You're up to date.")
        return res
    if not is_newer(m['version'], current):
        res['manifest'] = m
        res.update(status='current', message="You're up to date.")
        return res
    if not m['url']:
        res.update(status='notfound', message='Version %s has no download for this %s yet. Please try again later.'
                   % (m['version'], 'Mac' if IS_MAC else 'computer'))
        return res
    if not m['sums_url'] or not url_allowed(m['sums_url']) or not url_allowed(m['url']):
        res.update(status='invalid', message="Version %s can't be verified (no SHA256SUMS in the release), so it won't be "
                   "installed." % m['version'])
        return res
    try:
        sums = _get(m['sums_url'], timeout).decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        res.update(status='invalid', message="Version %s can't be verified (SHA256SUMS: HTTP %d)." % (m['version'], e.code))
        return res
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        res.update(status='offline', message="Couldn't reach the update server. Check your internet connection and try again.")
        res['detail'] = str(e)
        return res
    h = parse_sums(sums, m['name'])
    if not h:
        res.update(status='invalid', message="Version %s can't be verified (%s is not in SHA256SUMS), so it won't be "
                   "installed." % (m['version'], m['name']))
        return res
    m['sha256'] = h
    try:
        m = validate(m)
    except UpdateError as e:
        res.update(status='invalid', message='The update information on the server is not valid (%s).' % e)
        return res
    res['manifest'] = m
    res.update(status='available', message='Version %s is available.' % m['version'])
    return res


def check_manifest(current, url=None, timeout=10):
    """The optional update.json fallback. -> same dict as check(). Never raises."""
    url = url or DEFAULT_URL
    res = {'status': 'invalid', 'message': '', 'manifest': None, 'url': url, 'current': current, 'source': 'manifest'}
    if not url or not url_allowed(url):
        res.update(status='insecure' if url else 'notfound',
                   message='The update address must use HTTPS.' if url else 'No update address is configured.')
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
        if IS_MAC and isinstance(m, dict) and not isinstance(m.get('mac'), dict):
            res.update(status='notfound', message='Version %s has no Mac download yet. Please try again later.' % m.get('version', '?'))
            return res
        m = validate(for_platform(m))
    except (ValueError, UpdateError) as e:
        res.update(status='invalid', message='The update information on the server is not valid (%s).' % e)
        return res
    res['manifest'] = m
    if m.get('minimum_os') and os.name == 'nt' and os_build() < parse_version(m['minimum_os'])[:3]:
        res.update(status='current', message='Version %s needs Windows %s or newer.' % (m['version'], m['minimum_os']))
        return res
    if m.get('minimum_os') and IS_MAC:
        from . import macfx
        mo = m['minimum_os']
        if isinstance(mo, dict):
            mo = mo.get(macfx.machine_arch()) or max(mo.values(), key=parse_version)
        if macfx.macos_version() < parse_version(mo)[:3]:
            res.update(status='current', message='Version %s needs macOS %s or newer on this Mac.' % (m['version'], mo))
            return res
    if is_newer(m['version'], current):
        res.update(status='available', message='Version %s is available.' % m['version'])
    else:
        res.update(status='current', message="You're up to date.")
    return res


def for_platform(m, mac=None):
    """The entry for this platform: the top level (Windows) or the top level overlaid with "mac"."""
    mac = IS_MAC if mac is None else mac
    if not isinstance(m, dict) or not mac:
        return m
    out = {k: v for k, v in m.items() if k not in ('mac', 'minimum_os')}
    out.update(m.get('mac') or {})
    return out


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
    ext = '.dmg' if IS_MAC else '.exe'
    name = os.path.basename(urllib.parse.urlparse(m['url']).path) or ('LyricistSync-Setup' + ext)
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', name)
    if not name.lower().endswith(ext):
        name += ext
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
    """Mac: install_mac() (DMG). Windows: start the Inno Setup installer silently. The installer closes this app if needed,
    keeps everything in %LOCALAPPDATA%\\Ax-Easy\\LyricistSync (settings, engine, models)
    and, with relaunch, starts the new version when it's done."""
    if IS_MAC:
        return install_mac(path, relaunch=relaunch)
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


# ---------------------------------------------------------------- macOS: DMG install
def current_bundle():
    """/Applications/Lyricist Sync Desktop.app when running from a bundle, else None."""
    exe = os.path.realpath(sys.executable)
    i = exe.find('.app/Contents/MacOS/')
    return exe[:i + 4] if i > 0 else None


def _run(args, timeout=120):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def mount_dmg(path):
    """hdiutil attach (read-only, not shown in Finder) -> mount point."""
    import plistlib
    r = subprocess.run(['/usr/bin/hdiutil', 'attach', '-nobrowse', '-readonly', '-noautoopen', '-plist', path],
                       capture_output=True, timeout=300)
    if r.returncode != 0:
        raise UpdateError('The downloaded disk image could not be opened (%s).' % r.stderr.decode('utf-8', 'replace').strip()[:200])
    for e in plistlib.loads(r.stdout).get('system-entities', []):
        if e.get('mount-point'):
            return e['mount-point']
    raise UpdateError('The downloaded disk image has no volume.')


def detach(mount):
    try:
        _run(['/usr/bin/hdiutil', 'detach', '-quiet', mount], 60)
    except Exception:
        pass


def verify_app(app):
    """The new app must be intact, signed by our Developer ID team and accepted by Gatekeeper
    (notarized). -> dict of what was checked. Raises UpdateError."""
    r = _run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], 300)
    if r.returncode != 0:
        raise UpdateError('The new version failed the code signature check, so it was not installed.')
    info = _run(['/usr/bin/codesign', '-dv', '--verbose=2', app]).stderr
    team = re.search(r'^TeamIdentifier=(\S+)', info, re.M)
    if not team or team.group(1) != TEAM_ID:
        raise UpdateError('The new version is not signed by Ax-Easy, so it was not installed.')
    gk = _run(['/usr/sbin/spctl', '--assess', '--type', 'execute', '-vv', app], 300)
    ok_gk = gk.returncode == 0
    if not ok_gk and os.environ.get('LYRICIST_SYNC_UPDATE_TEST') != '1':
        raise UpdateError('macOS Gatekeeper did not accept the new version (%s).' % gk.stderr.strip()[:200])
    return {'signature': True, 'team': team.group(1), 'gatekeeper': gk.stderr.strip()[:300], 'gatekeeper_ok': ok_gk}


def install_mac(dmg, relaunch=True, target=None):
    """Mount the verified DMG, verify the app inside, then replace this app in place when its
    folder is writable (a helper waits for this process to quit, swaps the bundles, relaunches).
    Otherwise (read-only location, App Translocation, another user's /Applications) the DMG is
    opened in Finder to drag the app to Applications. -> ('replaced'|'manual', details)"""
    if not os.path.exists(dmg):
        raise UpdateError('The disk image is missing.')
    mount = mount_dmg(dmg)
    try:
        apps = [os.path.join(mount, f) for f in os.listdir(mount) if f.endswith('.app')]
        if not apps:
            raise UpdateError('The disk image has no app in it.')
        new = apps[0]
        checks = verify_app(new)
        target = target or current_bundle()
        if not target or '/AppTranslocation/' in target or not os.access(os.path.dirname(target), os.W_OK) \
                or (os.path.exists(target) and not os.access(target, os.W_OK)):
            detach(mount)
            subprocess.Popen(['/usr/bin/open', dmg])
            return 'manual', dict(checks, target=target)
        staged = os.path.join(os.path.dirname(target), '.%s.update' % os.path.basename(target))
        subprocess.run(['/bin/rm', '-rf', staged])
        r = _run(['/usr/bin/ditto', new, staged], 900)
        if r.returncode != 0:
            raise UpdateError('Could not copy the new version (%s).' % r.stderr.strip()[:200])
        verify_app(staged)
    finally:
        detach(mount)
    old = os.path.join(updates_dir(), 'previous.app')
    script = os.path.join(updates_dir(), 'swap.sh')
    with open(script, 'w') as f:
        f.write('#!/bin/sh\n'
                '# Lyricist Sync Desktop update: wait for the app to quit, swap the bundles, start the new one.\n'
                'pid=%d\n'
                'for i in $(seq 1 600); do kill -0 $pid 2>/dev/null || break; sleep 0.2; done\n'
                'rm -rf %s\n'
                'if mv %s %s && mv %s %s; then rm -rf %s; echo "update swapped"; else\n'
                '  [ -e %s ] || mv %s %s; echo "update swap failed"; fi\n'
                '%s\n' % (os.getpid(), _q(old), _q(target), _q(old), _q(staged), _q(target), _q(old),
                           _q(target), _q(old), _q(target), ('/usr/bin/open %s' % _q(target)) if relaunch else ''))
    os.chmod(script, 0o755)
    log = open(os.path.join(updates_dir(), 'swap.log'), 'a')
    subprocess.Popen(['/bin/sh', script], stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return 'replaced', dict(checks, target=target)


def _q(p):
    import shlex
    return shlex.quote(p)


def cleanup(keep=None):
    """Remove old downloaded installers (keeps `keep`, the release cache and the swap log)."""
    d = updates_dir()
    for f in os.listdir(d):
        if not f.lower().endswith(('.exe', '.dmg', '.part')):
            continue
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
