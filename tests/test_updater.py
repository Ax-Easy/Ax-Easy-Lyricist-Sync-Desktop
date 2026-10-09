"""In-app updater against mocked GitHub API answers: newer / same / older release, draft and
prerelease, missing asset, missing or wrong SHA256SUMS, 403 rate limit, offline, ETag 304 cache,
and the optional update.json fallback. No network: urllib.request.urlopen is replaced."""
import email.message
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
os.environ['LYRICIST_SYNC_HOME'] = tempfile.mkdtemp(prefix='lsync-upd-test-')
from lyricist_sync import updater as U  # noqa: E402

API = U.GITHUB_API
DL = 'https://github.com/%s/releases/download/v{v}/{n}' % U.REPO
PAYLOAD = b'installer bytes ' * 4000
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def asset_name(mac, v='9.9.9'):
    return 'AxEasy-LyricistSync-Desktop-%s-mac-universal.dmg' % v if mac else 'AxEasy-LyricistSync-Desktop-Setup-%s.exe' % v


def release(v='9.9.9', mac=False, draft=False, pre=False, asset=True, sums=True, body='## %s\n- **New** things'):
    assets = []
    if asset:   # both platforms' files, as on the real release
        for m in (False, True):
            n = asset_name(m, v)
            assets.append({'name': n, 'size': len(PAYLOAD), 'browser_download_url': DL.format(v=v, n=n)})
    assets.append({'name': 'AxEasy-LyricistSync-Desktop-Manual-EN.pdf', 'size': 10, 'browser_download_url': DL.format(v=v, n='m.pdf')})
    if sums:
        assets.append({'name': 'SHA256SUMS', 'size': 200, 'browser_download_url': DL.format(v=v, n='SHA256SUMS')})
    return {'tag_name': 'v' + v, 'draft': draft, 'prerelease': pre, 'body': body % v if '%s' in body else body,
            'published_at': '2026-10-09T17:00:00Z', 'html_url': 'https://github.com/x/releases/tag/v' + v, 'assets': assets}


class Resp(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = email.message.Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def http_error(url, code, headers=None):
    h = email.message.Message()
    for k, v in (headers or {}).items():
        h[k] = v
    return urllib.error.HTTPError(url, code, 'err', h, io.BytesIO(b'{}'))


class Server:
    """Fake urlopen: routes by URL; records request headers."""
    def __init__(self, rel=None, sums=None, api_error=None, etag=True, offline=False):
        self.rel, self.sums, self.api_error, self.offline = rel, sums, api_error, offline
        # like GitHub: the ETag follows the content
        self.etag = '"%s"' % hashlib.sha1(json.dumps(rel, sort_keys=True).encode()).hexdigest()[:12] if etag else None
        self.requests = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else req
        hdrs = dict(req.header_items()) if hasattr(req, 'header_items') else {}
        self.requests.append((url, hdrs))
        if self.offline:
            raise urllib.error.URLError(OSError(101, 'Network is unreachable'))
        if url.endswith('/releases/latest'):
            if self.api_error:
                raise http_error(url, *self.api_error)
            if self.etag and hdrs.get('If-none-match') == self.etag:
                raise http_error(url, 304, {'ETag': self.etag})
            return Resp(json.dumps(self.rel).encode(), headers={'ETag': self.etag} if self.etag else {})
        if url.endswith('/SHA256SUMS'):
            if self.sums is None:
                raise http_error(url, 404)
            return Resp(self.sums.encode())
        if url.endswith(('.exe', '.dmg')):
            return Resp(PAYLOAD, headers={'Content-Length': str(len(PAYLOAD))})
        raise http_error(url, 404)


def sums_for(v='9.9.9', sha=SHA):
    return ''.join('%s  %s\n' % (sha, asset_name(m, v)) for m in (False, True))


class Base(unittest.TestCase):
    mac = False

    def setUp(self):
        for f in os.listdir(U.updates_dir()):
            os.remove(os.path.join(U.updates_dir(), f))
        self.p_mac = mock.patch.object(U, 'IS_MAC', self.mac)
        self.p_mac.start()
        os.environ.pop('LYRICIST_SYNC_UPDATE_API', None)
        os.environ.pop('LYRICIST_SYNC_UPDATE_URL', None)

    def tearDown(self):
        self.p_mac.stop()

    def run_check(self, srv, current='1.3.1', **kw):
        with mock.patch.object(U.urllib.request, 'urlopen', srv):
            return U.check_for(current, kw.pop('settings', {}), **kw)


class TestWindows(Base):
    def test_newer(self):
        srv = Server(release(), sums_for())
        r = self.run_check(srv)
        self.assertEqual(r['status'], 'available', r)
        m = r['manifest']
        self.assertEqual((m['version'], m['sha256'], m['size']), ('9.9.9', SHA, len(PAYLOAD)))
        self.assertTrue(m['url'].endswith('/AxEasy-LyricistSync-Desktop-Setup-9.9.9.exe'))
        self.assertTrue(m['notes'].startswith('## 9.9.9'))
        self.assertEqual(m['date'], '2026-10-09')
        api_req = srv.requests[0]
        self.assertEqual(api_req[0], API)
        self.assertIn('AxEasy', api_req[1].get('User-agent', ''))
        self.assertNotIn('Authorization', api_req[1])
        with mock.patch.object(U.urllib.request, 'urlopen', srv):
            path = U.download(m)
        self.assertEqual(U.sha256_file(path), SHA)
        self.assertEqual(os.path.basename(path), 'AxEasy-LyricistSync-Desktop-Setup-9.9.9.exe')

    def test_same_and_older(self):
        for v in ('1.3.1', '1.2.0'):
            r = self.run_check(Server(release(v), sums_for(v)))
            self.assertEqual(r['status'], 'current', (v, r))
        r = self.run_check(Server(release('1.3.10'), sums_for('1.3.10')), current='1.3.9')
        self.assertEqual(r['status'], 'available')   # numeric, not string, comparison

    def test_draft_and_prerelease_ignored(self):
        for kw in ({'draft': True}, {'pre': True}):
            srv = Server(release(**kw), sums_for())
            r = self.run_check(srv)
            self.assertEqual(r['status'], 'current', (kw, r))
            self.assertEqual(len(srv.requests), 1)    # no SHA256SUMS or installer fetched

    def test_missing_asset(self):
        r = self.run_check(Server(release(asset=False), sums_for()))
        self.assertEqual(r['status'], 'notfound')
        self.assertIn('no download', r['message'])

    def test_missing_or_incomplete_sums_refused(self):
        r = self.run_check(Server(release(sums=False)))
        self.assertEqual(r['status'], 'invalid')
        self.assertIn('SHA256SUMS', r['message'])
        r = self.run_check(Server(release(), '%s  other-file.exe\n' % SHA))
        self.assertEqual(r['status'], 'invalid')
        r = self.run_check(Server(release(), None))       # listed but 404
        self.assertEqual(r['status'], 'invalid')

    def test_bad_hash_refused(self):
        srv = Server(release(), sums_for(sha='0' * 64))
        r = self.run_check(srv)
        self.assertEqual(r['status'], 'available')
        with mock.patch.object(U.urllib.request, 'urlopen', srv):
            with self.assertRaises(U.UpdateError) as cm:
                U.download(r['manifest'])
        self.assertIn('SHA256', str(cm.exception))
        self.assertFalse([f for f in os.listdir(U.updates_dir()) if f.endswith(('.exe', '.dmg', '.part'))])

    def test_rate_limited(self):
        r = self.run_check(Server(api_error=(403, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1791565200'})))
        self.assertEqual(r['status'], 'offline')
        self.assertTrue(r.get('ratelimited'))
        self.assertIn('limit', r['message'])
        r = self.run_check(Server(api_error=(429, {'Retry-After': '120'})))
        self.assertTrue(r.get('ratelimited') and 'in 2 minutes' in r['message'], r)
        r = self.run_check(Server(api_error=(403, {})))     # a 403 that is not a rate limit
        self.assertEqual(r['status'], 'offline')
        self.assertIn('HTTP 403', r['message'])

    def test_offline_and_not_published(self):
        r = self.run_check(Server(offline=True))
        self.assertEqual(r['status'], 'offline')
        self.assertIn("Couldn't reach", r['message'])
        r = self.run_check(Server(api_error=(404, {})))
        self.assertEqual(r['status'], 'notfound')

    def test_etag_cache(self):
        srv = Server(release(), sums_for())
        self.assertFalse(self.run_check(srv).get('cached'))
        r = self.run_check(srv)
        self.assertEqual(r['status'], 'available')
        self.assertTrue(r.get('cached'))
        self.assertEqual(srv.requests[-2][1].get('If-none-match'), srv.etag)

    def test_bad_answers(self):
        for rel in ({'tag_name': 'nightly', 'assets': []}, ['not', 'a', 'release']):
            r = self.run_check(Server(rel, sums_for()))
            self.assertEqual(r['status'], 'invalid', (rel, r))

    def test_defaults_point_at_github_only(self):
        self.assertEqual(U.api_url({}), 'https://api.github.com/repos/Ax-Easy/Ax-Easy-Lyricist-Sync-Desktop/releases/latest')
        self.assertEqual(U.manifest_url({}), '')
        self.assertNotIn('ax-easy.com', U.api_url({}) + U.manifest_url({}))
        self.assertFalse(U.url_allowed('http://api.github.com/x'))

    def test_manifest_fallback_only_when_configured(self):
        man = {'version': '9.9.9', 'url': 'https://example.org/Setup.exe', 'sha256': SHA, 'size': len(PAYLOAD)}

        def srv(req, timeout=None):
            url = req.full_url
            if url.endswith('/releases/latest'):
                raise urllib.error.URLError('offline')
            if url == 'https://example.org/update.json':
                return Resp(json.dumps(man).encode())
            raise http_error(url, 404)
        r = self.run_check(srv)
        self.assertEqual(r['status'], 'offline')
        r = self.run_check(srv, settings={'update_url': 'https://example.org/update.json'})
        self.assertEqual((r['status'], r['source']), ('available', 'manifest'))


class TestMac(Base):
    mac = True

    def test_newer_picks_the_dmg(self):
        srv = Server(release(), sums_for())
        r = self.run_check(srv)
        self.assertEqual(r['status'], 'available', r)
        self.assertTrue(r['manifest']['url'].endswith('-mac-universal.dmg'))
        self.assertEqual(r['manifest']['sha256'], SHA)

    def test_missing_dmg(self):
        rel = release()
        rel['assets'] = [a for a in rel['assets'] if not a['name'].endswith('.dmg')]
        r = self.run_check(Server(rel, sums_for()))
        self.assertEqual(r['status'], 'notfound')
        self.assertIn('Mac', r['message'])


class TestHelpers(unittest.TestCase):
    def test_parse_sums(self):
        t = '%s  a.exe\n%s *dir/b.dmg\nbad line\n' % ('A' * 64, 'b' * 64)
        self.assertEqual(U.parse_sums(t, 'a.exe'), 'a' * 64)
        self.assertEqual(U.parse_sums(t, 'b.dmg'), 'b' * 64)
        self.assertIsNone(U.parse_sums(t, 'c.exe'))

    def test_asset_patterns(self):
        self.assertTrue(U.ASSET_WIN.match('AxEasy-LyricistSync-Desktop-Setup-1.3.1.exe'))
        self.assertFalse(U.ASSET_WIN.match('AxEasy-LyricistSync-Setup-1.3.1.exe'))
        self.assertFalse(U.ASSET_WIN.match('AxEasy-LyricistSync-Desktop-Setup-1.3.1.exe.sha256'))
        self.assertTrue(U.ASSET_MAC.match('AxEasy-LyricistSync-Desktop-1.3.1-mac-universal.dmg'))
        self.assertFalse(U.ASSET_MAC.match('AxEasy-LyricistSync-Desktop-1.3.1-mac-universal.dmg.zip'))


if __name__ == '__main__':
    unittest.main()
