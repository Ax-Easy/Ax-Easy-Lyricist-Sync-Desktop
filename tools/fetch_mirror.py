"""CI: download every file of a setup variant (cpu/cuda) into DIR by file name, SHA256-checked,
so tools/serve_throttled.py can serve them as LYRICIST_SYNC_MIRROR for the GUI setup test.

  python tools/fetch_mirror.py cpu DIR"""
import hashlib
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))


def main():
    from lyricist_sync import bootstrap
    variant, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    items = bootstrap.plan(variant)
    total = 0
    for it in items:
        dest = os.path.join(out, os.path.basename(it['dest']))
        if os.path.exists(dest) and os.path.getsize(dest) == it['size']:
            total += it['size']
            continue
        h = hashlib.sha256()
        req = urllib.request.Request(it['url'], headers={'User-Agent': 'LyricistSync-CI'})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest + '.part', 'wb') as f:
            for b in iter(lambda: r.read(1 << 20), b''):
                h.update(b)
                f.write(b)
        if h.hexdigest() != it['sha256']:
            raise SystemExit('SHA256 mismatch: %s' % it['url'])
        os.replace(dest + '.part', dest)
        total += it['size']
        print('%-70s %8.1f MB' % (os.path.basename(dest)[:70], it['size'] / 1e6), flush=True)
    print('%d files, %.2f GB in %s' % (len(items), total / 1e9, out))


if __name__ == '__main__':
    main()
