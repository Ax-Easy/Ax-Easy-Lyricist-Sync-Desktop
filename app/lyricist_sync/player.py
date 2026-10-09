"""The built-in player: decode a song once to PCM (sample-accurate seeking, the same samples
the engine aligned against), a peaks envelope for the waveform, and the waveform widget with
line markers, ♪ regions, low-confidence markers and the playhead.

Decoded audio is cached under <home>/cache/audio (WAV + peaks, least recently used are pruned),
so a song is read once and opens instantly afterwards."""
import array
import hashlib
import math
import os
import sys
import threading
import time
import wave

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import paths
from .theme import ACCENT, ACCENT_2
from .widgets import AMBER, STATE

HOP = 0.01            # one peak pair per 10 ms
CACHE_FILES = 8       # decoded songs kept
CACHE_BYTES = 900 * 1024 * 1024
INST = '#8f7bff'      # ♪ regions


def cache_dir():
    d = os.path.join(paths.home(), 'cache', 'audio')
    os.makedirs(d, exist_ok=True)
    return d


def cache_key(path):
    try:
        st = os.stat(path)
        sig = '%s|%d|%d' % (os.path.normcase(os.path.abspath(path)), st.st_size, int(st.st_mtime))
    except OSError:
        sig = os.path.abspath(path)
    return hashlib.sha1(sig.encode('utf-8', 'surrogatepass')).hexdigest()[:20]


def compute_peaks(pcm, channels, sr):
    """pcm: array('h') interleaved. Returns array('b') [max0, min0, max1, min1, ...] per HOP."""
    step = max(1, int(round(sr * HOP))) * channels
    n = len(pcm)
    out = array.array('b')
    sub = channels * (2 if sr > 30000 else 1)  # every other frame is plenty for an envelope
    for a in range(0, n, step):
        s = pcm[a:a + step:sub]
        if not s:
            break
        out.append(max(-127, min(127, max(s) >> 8)))
        out.append(max(-127, min(127, min(s) >> 8)))
    return out


def prune(keep=None, files=CACHE_FILES, max_bytes=CACHE_BYTES):
    d = cache_dir()
    try:
        items = []
        for k in set(os.path.splitext(f)[0] for f in os.listdir(d)):
            fs = [os.path.join(d, k + e) for e in ('.wav', '.peaks', '.json') if os.path.exists(os.path.join(d, k + e))]
            items.append((max(os.path.getmtime(f) for f in fs), sum(os.path.getsize(f) for f in fs), k, fs))
        items.sort(reverse=True)
        total = 0
        for i, (_m, size, k, fs) in enumerate(items):
            total += size
            if k != keep and (i >= files or total > max_bytes):
                for f in fs:
                    try:
                        os.remove(f)
                    except OSError:
                        pass
    except OSError:
        pass


def _qt_stop_hangs():
    try:
        from PySide6 import QtCore
        return tuple(int(x) for x in QtCore.qVersion().split('.')[:2]) < (6, 8)
    except Exception:
        return sys.platform == 'darwin'


_QT_STOP_HANGS = _qt_stop_hangs()
_AFCONVERT = '/usr/bin/afconvert' if sys.platform == 'darwin' and os.path.exists('/usr/bin/afconvert') else None


class AudioCache(QObject):
    """load(path) -> ready(path, wav_path, peaks, duration) or failed(path, message).
    One decode at a time; selecting another song cancels the running one."""
    ready = Signal(str, str, object, float)
    failed = Signal(str, str)
    _done = Signal(str, str, object, float, str)
    _fallback = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._af = set()   # macOS: paths being converted by afconvert
        self._fallback.connect(self._start_qt)
        self._dec = None
        self._path = None
        self._chunks = []
        self._fmt = None
        self._mem = {}   # path -> (wav, peaks, duration) for this session
        self._done.connect(self._finished_thread)

    def get(self, path):
        return self._mem.get(path)

    def load(self, path):
        if path in self._mem:
            wav, peaks, dur = self._mem[path]
            if os.path.exists(wav):
                QTimer.singleShot(0, lambda: self.ready.emit(path, wav, peaks, dur))
                return
        key = cache_key(path)
        base = os.path.join(cache_dir(), key)
        if os.path.exists(base + '.wav') and os.path.exists(base + '.peaks'):
            try:
                peaks = array.array('b')
                with open(base + '.peaks', 'rb') as f:
                    peaks.frombytes(f.read())
                with wave.open(base + '.wav', 'rb') as w:
                    dur = w.getnframes() / float(w.getframerate())
                now = time.time()
                for e in ('.wav', '.peaks'):
                    os.utime(base + e, (now, now))
                self._mem[path] = (base + '.wav', peaks, dur)
                QTimer.singleShot(0, lambda: self.ready.emit(path, base + '.wav', peaks, dur))
                return
            except (OSError, EOFError, wave.Error):
                pass
        self._start(path)

    def _start(self, path):
        if _AFCONVERT and os.path.splitext(path)[1].lower() not in ('.ogg', '.oga', '.opus'):
            # macOS: Core Audio's afconvert decodes MP3/AAC/M4A/WAV/AIFF/FLAC reliably and fast; Qt 6.7's
            # QAudioDecoder never finished MP3s on the macOS CI runners. Falls back to Qt if it fails.
            self.cancel()
            if path not in self._af:
                self._af.add(path)
                threading.Thread(target=self._afconvert, args=(path,), daemon=True).start()
            return
        self._start_qt(path)

    def _afconvert(self, path):
        import subprocess
        base = os.path.join(cache_dir(), cache_key(path))
        tmp = base + '.af.wav'
        try:
            r = subprocess.run([_AFCONVERT, '-f', 'WAVE', '-d', 'LEI16@44100', '-c', '2', path, tmp],
                               capture_output=True, timeout=600)
            if r.returncode != 0 or not os.path.exists(tmp):
                raise RuntimeError((r.stderr or b'').decode('utf-8', 'replace').strip()[:200] or 'afconvert failed')
            with wave.open(tmp, 'rb') as w:
                ch, sr, sw = w.getnchannels(), w.getframerate(), w.getsampwidth()
                raw = w.readframes(w.getnframes())
            if sw != 2:
                raise RuntimeError('unexpected sample width %d' % sw)
            pcm = array.array('h')
            pcm.frombytes(raw[:len(raw) // 2 * 2])
            if sys.byteorder != 'little':
                pcm.byteswap()
            peaks = compute_peaks(pcm, ch, sr)
            os.replace(tmp, base + '.wav')
            with open(base + '.peaks', 'wb') as f:
                peaks.tofile(f)
            prune(keep=cache_key(path))
            self._af.discard(path)
            self._done.emit(path, base + '.wav', peaks, len(pcm) / float(ch * sr), '')
        except Exception:  # noqa: BLE001
            try:
                os.remove(tmp)
            except OSError:
                pass
            self._af.discard(path)
            self._fallback.emit(path)

    def _start_qt(self, path):
        from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
        if self._dec is not None:
            if self._path == path:
                return
            self.cancel()
        dec = QAudioDecoder(self)
        f = QAudioFormat()
        f.setSampleRate(44100)
        f.setChannelCount(2)
        f.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        dec.setAudioFormat(f)
        dec.setSource(QUrl.fromLocalFile(path))
        self._dec, self._path, self._chunks, self._fmt = dec, path, [], None
        dec.bufferReady.connect(self._buffer)
        dec.finished.connect(self._decoded)
        dec.error.connect(lambda _e, d=dec: self._error(d))
        dec.start()

    def cancel(self):
        if self._dec is not None:
            d = self._dec
            self._dec = None
            try:
                d.bufferReady.disconnect()
                d.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            if _QT_STOP_HANGS:
                # Qt 6.7 (the macOS build): QAudioDecoder.stop() while the FFmpeg backend is decoding never
                # returns (seen when another song is selected mid-decode). Let it run to the end unobserved
                # and delete it then; its output is ignored.
                self._orphans = [o for o in getattr(self, '_orphans', []) if o is not None] + [d]

                def _gone(_=None, d=d):
                    if d in self._orphans:
                        self._orphans.remove(d)
                        d.deleteLater()
                d.finished.connect(_gone)
                d.error.connect(_gone)
            else:
                d.stop()
                d.deleteLater()
        self._chunks = []

    def _buffer(self):
        d = self._dec
        if d is None:
            return
        b = d.read()
        if not b.isValid():
            return
        if self._fmt is None:
            fm = b.format()
            self._fmt = (fm.sampleRate(), fm.channelCount(), fm.sampleFormat())
        self._chunks.append(bytes(b.constData()))

    def _error(self, d):
        if d is not self._dec:
            return
        path, msg = self._path, d.errorString()
        self.cancel()
        self.failed.emit(path, msg or 'could not decode the audio')

    def _decoded(self):
        d, path, chunks, fmt = self._dec, self._path, self._chunks, self._fmt
        self._dec, self._chunks = None, []
        if d is not None:
            d.deleteLater()
        if not chunks or not fmt:
            self.failed.emit(path, 'no audio decoded')
            return
        threading.Thread(target=self._write, args=(path, chunks, fmt), daemon=True).start()

    def _write(self, path, chunks, fmt):
        """Worker thread: WAV + peaks to the cache."""
        from PySide6.QtMultimedia import QAudioFormat
        sr, ch, sf = fmt
        try:
            if sf != QAudioFormat.SampleFormat.Int16:
                raise ValueError('unexpected sample format %s' % sf)
            raw = b''.join(chunks)
            pcm = array.array('h')
            pcm.frombytes(raw[:len(raw) // 2 * 2])
            if sys.byteorder != 'little':
                pcm.byteswap()
            peaks = compute_peaks(pcm, ch, sr)
            key = cache_key(path)
            base = os.path.join(cache_dir(), key)
            with wave.open(base + '.wav.part', 'wb') as w:
                w.setnchannels(ch)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(raw)
            os.replace(base + '.wav.part', base + '.wav')
            with open(base + '.peaks', 'wb') as f:
                peaks.tofile(f)
            prune(keep=key)
            self._done.emit(path, base + '.wav', peaks, len(pcm) / float(ch * sr), '')
        except Exception as e:  # noqa: BLE001
            self._done.emit(path, '', None, 0.0, '%s: %s' % (e.__class__.__name__, e))

    def _finished_thread(self, path, wav, peaks, dur, err):
        if err:
            self.failed.emit(path, err)
            return
        self._mem[path] = (wav, peaks, dur)
        self.ready.emit(path, wav, peaks, dur)


def fmt_clock(t):
    t = max(0.0, t or 0.0)
    return '%d:%05.2f' % (int(t // 60), t - 60 * int(t // 60))


class Waveform(QWidget):
    """Peaks with line starts, ♪ regions, amber low-confidence markers and the playhead.
    Click to seek, wheel to zoom (around the cursor), Shift+wheel to scroll,
    double-click to see the whole song. Drag a line marker to retime that line."""
    seek = Signal(float)
    select = Signal(int)
    retime = Signal(int, float)

    GRAB = 5   # px around a marker that grabs it

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.peaks = None
        self.duration = 0.0
        self.lines = []
        self.sel = -1
        self.pos = 0.0
        self.t0 = 0.0
        self.span = 0.0          # 0 = whole song
        self.message = 'Select a song to see its waveform'
        self.follow = True
        self._cache = None
        self._drag = None        # (row, t)
        self._press = None
        self._lines_ver = 0

    # ---------------------------------------------------------------- data
    def clear(self, message=''):
        self.peaks, self.duration, self.lines, self.sel = None, 0.0, [], -1
        self.pos, self.t0, self.span = 0.0, 0.0, 0.0
        self.message = message
        self._cache = None
        self.update()

    def set_audio(self, peaks, duration):
        self.peaks, self.duration = peaks, duration
        self.t0, self.span = 0.0, 0.0
        self.message = ''
        self._cache = None
        self.update()

    def set_lines(self, lines, sel=-1):
        self.lines = lines or []
        self.sel = sel
        self._lines_ver += 1
        self.update()

    def set_selected(self, row):
        if row != self.sel:
            self.sel = row
            self.update()

    def set_position(self, t, playing=False):
        old = self.pos
        self.pos = t
        if playing and self.follow and self.span and not (self.t0 <= t <= self.t0 + self.view_span() * 0.92):
            self.t0 = max(0.0, min(t - self.view_span() * 0.08, self.duration - self.view_span()))
            self._cache = None
            self.update()
            return
        x0, x1 = self.x_of(old), self.x_of(t)
        self.update(int(min(x0, x1)) - 8, 0, int(abs(x1 - x0)) + 17, self.height())

    # ---------------------------------------------------------------- geometry
    def view_span(self):
        return self.span or self.duration or 1.0

    def plot(self):
        return QRectF(self.rect()).adjusted(1, 1, -1, -17)

    def x_of(self, t):
        r = self.plot()
        return r.left() + (t - self.t0) / self.view_span() * r.width()

    def t_of(self, x):
        r = self.plot()
        return min(max(0.0, self.t0 + (x - r.left()) / max(1.0, r.width()) * self.view_span()), self.duration or 0.0)

    def zoom(self, factor, at_t=None):
        if not self.duration:
            return
        span = self.view_span()
        at = self.pos if at_t is None else at_t
        new = min(self.duration, max(1.0, span * factor))
        frac = (at - self.t0) / span
        self.span = 0.0 if new >= self.duration - 1e-6 else new
        self.t0 = 0.0 if not self.span else max(0.0, min(at - frac * new, self.duration - new))
        self._cache = None
        self.update()

    def pan(self, dt):
        if not self.span:
            return
        self.t0 = max(0.0, min(self.t0 + dt, self.duration - self.span))
        self._cache = None
        self.update()

    # ---------------------------------------------------------------- painting
    def _wave_pixmap(self):
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, self.t0, self.span, STATE['dark'], id(self.peaks))
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        r = self.plot()
        mid = r.center().y()
        half = r.height() / 2 - 3
        pk = self.peaks
        n = len(pk) // 2 if pk is not None else 0
        if n:
            col = QColor(255, 255, 255, 120) if STATE['dark'] else QColor(30, 36, 52, 110)
            q.setPen(QPen(col, 1))
            w = int(r.width())
            per = self.view_span() / HOP / max(1, w)
            for x in range(w):
                i0 = int((self.t0 / HOP) + x * per)
                i1 = max(i0 + 1, int((self.t0 / HOP) + (x + 1) * per))
                if i0 >= n:
                    break
                seg = pk[2 * i0:2 * min(i1, n)]
                hi, lo = max(seg[0::2]), min(seg[1::2])
                y0 = mid - hi / 127.0 * half
                y1 = mid - lo / 127.0 * half
                q.drawLine(QPointF(r.left() + x + 0.5, y0), QPointF(r.left() + x + 0.5, max(y1, y0 + 1)))
        q.end()
        self._cache = (key, pm)
        return pm

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = STATE['dark']
        full = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = QPainterPath()
        bg.addRoundedRect(full, 10, 10)
        p.fillPath(bg, QColor(0, 0, 0, 46) if dark else QColor(255, 255, 255, 120))
        p.setPen(QPen(QColor(255, 255, 255, 30) if dark else QColor(20, 25, 40, 30), 1))
        p.drawPath(bg)
        p.setClipPath(bg)
        txt = QColor(255, 255, 255, 150) if dark else QColor(30, 36, 52, 150)
        if not self.duration:
            p.setPen(txt)
            p.drawText(self.rect(), Qt.AlignCenter, self.message)
            return
        r = self.plot()
        # ♪ regions and the selected line's span, under the waveform
        for i, l in enumerate(self.lines):
            x0, x1 = self.x_of(l['start']), self.x_of(l.get('end', l['start']))
            if x1 < r.left() or x0 > r.right():
                continue
            if l.get('inst'):
                c = QColor(INST)
                c.setAlpha(60 if dark else 46)
                p.fillRect(QRectF(x0, r.top(), max(1.0, x1 - x0), r.height()), c)
                if x1 - x0 > 18:
                    f = QFont(self.font())
                    f.setPointSizeF(max(8.0, f.pointSizeF()))
                    p.setFont(f)
                    p.setPen(QColor(INST).lighter(130) if dark else QColor(INST).darker(130))
                    p.drawText(QRectF(x0 + 4, r.top() + 2, x1 - x0 - 6, 16), Qt.AlignLeft | Qt.AlignVCenter, l['text'])
            elif i == self.sel:
                c = QColor(ACCENT)
                c.setAlpha(34)
                p.fillRect(QRectF(x0, r.top(), max(1.0, x1 - x0), r.height()), c)
        p.drawPixmap(0, 0, self._wave_pixmap())
        # line start markers
        for i, l in enumerate(self.lines):
            t = self._drag[1] if self._drag and self._drag[0] == i else l['start']
            x = self.x_of(t)
            if x < r.left() - 1 or x > r.right() + 1:
                continue
            conf = l.get('conf')
            low = conf is not None and conf < 0.6 and not l.get('inst')
            if l.get('inst'):
                c = QColor(INST)
            elif low:
                c = QColor(AMBER)
            else:
                c = QColor(ACCENT)
            c.setAlpha(255 if i == self.sel else 170)
            p.setPen(QPen(c, 2.0 if (i == self.sel or low) else 1.2))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            if low or i == self.sel:
                p.setBrush(c)
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(x, r.top() + 4), 3.2, 3.2)
        # time ruler
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        p.setFont(f)
        p.setPen(txt)
        span = self.view_span()
        step = next((s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120) if r.width() / span * s >= 64), 300)
        t = math.ceil(self.t0 / step) * step
        while t <= self.t0 + span:
            x = self.x_of(t)
            p.drawLine(QPointF(x, r.bottom() + 1), QPointF(x, r.bottom() + 4))
            p.drawText(QRectF(min(max(x - 30, r.left()), r.right() - 60), r.bottom() + 3, 60, 13),
                       Qt.AlignLeft if x - 30 < r.left() else Qt.AlignRight if x + 30 > r.right() else Qt.AlignCenter,
                       ('%d:%02d' % (int(t) // 60, int(t) % 60)) if step >= 1 else '%.1f' % t)
            t += step
        # playhead
        x = self.x_of(self.pos)
        if r.left() - 1 <= x <= r.right() + 1:
            pc = QColor('#ffffff') if dark else QColor('#1b2030')
            p.setPen(QPen(pc, 1.6))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            tri = QPainterPath()
            tri.moveTo(x - 5, r.top())
            tri.lineTo(x + 5, r.top())
            tri.lineTo(x, r.top() + 6)
            tri.closeSubpath()
            p.fillPath(tri, pc)

    # ---------------------------------------------------------------- mouse
    def marker_at(self, x):
        best, bd = -1, self.GRAB + 1
        for i, l in enumerate(self.lines):
            d = abs(self.x_of(l['start']) - x)
            if d < bd:
                best, bd = i, d
        return best

    def _limits(self, row):
        lo = max([l['start'] for k, l in enumerate(self.lines) if k != row and l['start'] <= self.lines[row]['start']] or [0.0])
        hi = min([l['start'] for k, l in enumerate(self.lines) if k != row and l['start'] > self.lines[row]['start']] or [self.duration])
        return (lo + 0.05 if lo > 0 else 0.0), hi - 0.05

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or not self.duration:
            return
        x = e.position().x()
        m = self.marker_at(x)
        self._press = (x, m)
        if m >= 0:
            self._drag = (m, self.lines[m]['start'])
        else:
            self.seek.emit(self.t_of(x))

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._drag and e.buttons() & Qt.LeftButton:
            row = self._drag[0]
            lo, hi = self._limits(row)
            self._drag = (row, min(max(self.t_of(x), lo), hi))
            self.update()
            return
        self.setCursor(Qt.SizeHorCursor if self.duration and self.marker_at(x) >= 0 else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if self._drag:
            row, t = self._drag
            self._drag = None
            moved = self._press and abs(e.position().x() - self._press[0]) > 2
            if moved:
                self.retime.emit(row, round(t, 3))
            else:
                self.select.emit(row)
                self.seek.emit(self.lines[row]['start'])
            self.update()
        self._press = None

    def mouseDoubleClickEvent(self, e):
        self.span, self.t0 = 0.0, 0.0
        self._cache = None
        self.update()

    def wheelEvent(self, e):
        if not self.duration:
            return
        d = e.angleDelta()
        if e.modifiers() & Qt.ShiftModifier or abs(d.x()) > abs(d.y()):
            amount = d.x() or d.y()
            self.pan(-amount / 120.0 * self.view_span() * 0.15)
        else:
            self.zoom(0.8 ** (d.y() / 120.0), self.t_of(e.position().x()))
        e.accept()

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)
