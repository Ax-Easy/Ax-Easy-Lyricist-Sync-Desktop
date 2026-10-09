"""Write update.json for the in-app updater from a built installer.

  python tools/make_update_json.py dist-installer/AxEasy-LyricistSync-Desktop-Setup-1.3.1.exe \
      [--base https://www.ax-easy.com/lyricist-sync/] [--version 1.3.1] [--out dist-installer/update.json]
      [--mac AxEasy-LyricistSync-Desktop-1.3.1-mac-universal.dmg [--mac-base URL]]

The top level is the Windows installer (what 1.0-1.3.x clients read); "mac" is the entry the macOS app
overlays on it (url, sha256, size, minimum_os per architecture).

Publishing: upload the Setup exe and update.json to /lyricist-sync/ on ax-easy.com."""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))


def notes_for(version, changelog=os.path.join(ROOT, 'CHANGELOG.md')):
    """The CHANGELOG section for `version` (markdown, without the heading)."""
    try:
        text = open(changelog, encoding='utf-8').read()
    except OSError:
        return ''
    m = re.search(r'^## \[?%s\]?[^\n]*\n(.*?)(?=^## |\Z)' % re.escape(version), text, re.S | re.M)
    return m.group(1).strip() if m else ''


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    from lyricist_sync import VERSION
    ap = argparse.ArgumentParser()
    ap.add_argument('installer')
    ap.add_argument('--base', default='https://www.ax-easy.com/lyricist-sync/')
    ap.add_argument('--version', default=VERSION)
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--notes', default=None, help='default: the CHANGELOG.md section of the version')
    ap.add_argument('--minimum-os', default='10.0.17763')
    ap.add_argument('--mac', metavar='DMG', help='also write the "mac" entry for this DMG')
    ap.add_argument('--mac-base', default=None, help='download folder of the DMG (default: --base)')
    ap.add_argument('--mac-minimum-os', default='arm64=11.0,x86_64=12.0')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv)
    man = {'version': a.version, 'date': a.date,
           'notes': a.notes if a.notes is not None else notes_for(a.version),
           'url': a.base.rstrip('/') + '/' + os.path.basename(a.installer),
           'sha256': sha256_of(a.installer), 'size': os.path.getsize(a.installer), 'minimum_os': a.minimum_os}
    if a.mac:
        mo = dict(kv.split('=', 1) for kv in a.mac_minimum_os.split(',')) if '=' in a.mac_minimum_os else a.mac_minimum_os
        man['mac'] = {'url': (a.mac_base or a.base).rstrip('/') + '/' + os.path.basename(a.mac),
                      'sha256': sha256_of(a.mac), 'size': os.path.getsize(a.mac), 'minimum_os': mo}
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.installer)), 'update.json')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps(dict(man, notes=man['notes'][:80] + '…'), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
