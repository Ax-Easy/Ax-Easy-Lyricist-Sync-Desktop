"""A local stand-in for GitHub's "latest release" API, for the CI updater tests.

  python tools/make_mock_release.py DIR --version 9.9.9 --base http://127.0.0.1:8766/ FILE [FILE ...]

Writes DIR/latest (the JSON that https://api.github.com/repos/OWNER/REPO/releases/latest returns:
tag_name, body, draft/prerelease, assets with name, size and browser_download_url) and
DIR/SHA256SUMS for the files, which must already be in DIR. Serve DIR with tools/serve_throttled.py
(it serves by file name and answers If-None-Match with 304, like the API) and point the app at
BASE + repos/Ax-Easy/Ax-Easy-Lyricist-Sync-Desktop/releases/latest."""
import argparse
import hashlib
import json
import os


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('dir')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--version', default='9.9.9')
    ap.add_argument('--base', default='http://127.0.0.1:8766/')
    ap.add_argument('--notes', default='## %s\n\n- CI test release (local mock of the GitHub API)')
    a = ap.parse_args(argv)
    base = a.base.rstrip('/') + '/'
    names = [os.path.basename(f) for f in a.files]
    with open(os.path.join(a.dir, 'SHA256SUMS'), 'w', newline='\n') as f:
        for n in names:
            f.write('%s  %s\n' % (sha256(os.path.join(a.dir, n)), n))
    assets = [{'id': i + 1, 'name': n, 'size': os.path.getsize(os.path.join(a.dir, n)), 'state': 'uploaded',
               'content_type': 'application/octet-stream', 'browser_download_url': base + n}
              for i, n in enumerate(names + ['SHA256SUMS'])]
    rel = {'tag_name': 'v' + a.version, 'name': 'Ax-Easy Lyricist Sync Desktop ' + a.version, 'draft': False, 'prerelease': False,
           'published_at': '2026-10-09T12:00:00Z', 'html_url': base + 'releases/tag/v' + a.version,
           'body': a.notes % a.version if '%s' in a.notes else a.notes, 'assets': assets}
    with open(os.path.join(a.dir, 'latest'), 'w', encoding='utf-8') as f:
        json.dump(rel, f, indent=1)
    print(json.dumps(rel, indent=1))


if __name__ == '__main__':
    main()
