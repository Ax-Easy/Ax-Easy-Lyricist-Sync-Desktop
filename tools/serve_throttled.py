"""Local HTTP file server for CI tests: Range/resume support, a bandwidth limit and 404s.

  python tools/serve_throttled.py DIR --port 8765 [--rate 20] [--slow NAME=RATE ...]

--rate is MB/s for every file; --slow gives single files their own rate (to keep the setup
window mid-download long enough for screenshots)."""
import argparse
import http.server
import os
import re
import sys
import time


def make_handler(root, rate, slow):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *args):
            sys.stderr.write('%s %s\n' % (time.strftime('%H:%M:%S'), fmt % args))

        def _file(self):
            name = os.path.basename(self.path.split('?', 1)[0])
            from urllib.parse import unquote
            p = os.path.join(root, unquote(name))
            return p if name and os.path.isfile(p) else None, unquote(name)

        def do_HEAD(self):
            self._serve(head=True)

        def do_GET(self):
            self._serve(head=False)

        def _serve(self, head):
            p, name = self._file()
            if not p:
                body = b'not found'
                self.send_response(404)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                if not head:
                    self.wfile.write(body)
                return
            size = os.path.getsize(p)
            st = os.stat(p)
            etag = '"%x-%x"' % (int(st.st_mtime), size)
            if self.headers.get('If-None-Match') == etag:   # like GitHub's API: 304 for an unchanged answer
                self.send_response(304)
                self.send_header('ETag', etag)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            start, end = 0, size - 1
            m = re.match(r'bytes=(\d+)-(\d*)', self.headers.get('Range', ''))
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                if start >= size:
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */%d' % size)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
            else:
                self.send_response(200)
            self.send_header('Content-Type', 'application/json' if name.endswith('.json') else 'application/octet-stream')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('ETag', etag)
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            if head:
                return
            bps = slow.get(name, rate) * 1e6
            left = end - start + 1
            t0, sent = time.time(), 0
            with open(p, 'rb') as f:
                f.seek(start)
                while left > 0:
                    chunk = f.read(min(left, 256 * 1024))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return
                    left -= len(chunk)
                    sent += len(chunk)
                    if bps > 0:
                        ahead = sent / bps - (time.time() - t0)
                        if ahead > 0:
                            time.sleep(ahead)
    return H


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--rate', type=float, default=0, help='MB/s, 0 = unlimited')
    ap.add_argument('--slow', action='append', default=[], help='NAME=MB/s')
    a = ap.parse_args(argv)
    slow = {k: float(v) for k, v in (s.split('=', 1) for s in a.slow)}
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', a.port), make_handler(os.path.abspath(a.root), a.rate, slow))
    print('serving %s on http://127.0.0.1:%d/ (rate %s MB/s, slow %s)' % (a.root, a.port, a.rate or '∞', slow), flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
