"""Write update.json for the in-app updater from a built installer.

  python tools/make_update_json.py dist-installer/AxEasy-LyricistSync-Setup-1.1.0.exe \
      [--base https://www.ax-easy.com/lyricist-sync/] [--version 1.1.0] [--out dist-installer/update.json]

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


def main(argv=None):
    from lyricist_sync import VERSION
    ap = argparse.ArgumentParser()
    ap.add_argument('installer')
    ap.add_argument('--base', default='https://www.ax-easy.com/lyricist-sync/')
    ap.add_argument('--version', default=VERSION)
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--notes', default=None, help='default: the CHANGELOG.md section of the version')
    ap.add_argument('--minimum-os', default='10.0.17763')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv)
    h = hashlib.sha256()
    with open(a.installer, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    man = {'version': a.version, 'date': a.date,
           'notes': a.notes if a.notes is not None else notes_for(a.version),
           'url': a.base.rstrip('/') + '/' + os.path.basename(a.installer),
           'sha256': h.hexdigest(), 'size': os.path.getsize(a.installer), 'minimum_os': a.minimum_os}
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.installer)), 'update.json')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps(dict(man, notes=man['notes'][:80] + '…'), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
