"""Stereo playback with volume and balance.

Why not QMediaPlayer + QAudioOutput: Qt's FFmpeg backend (Windows, Qt 6.12) opens the sound card in its own mix
format. On a 5.1 endpoint (6 channels, e.g. a Sound Blaster set to 5.1) it gets the speaker layout wrong and sends
the left channel to front-right and the right channel to the centre, so the song leans to the right and the front
left speaker is silent. QAudioOutput also has no pan at all.

So the decoded WAV (cache/audio) is played through a QAudioSink opened as plain 16-bit *stereo*; Windows (WASAPI)
and macOS (Core Audio) do the stereo -> speakers mapping themselves, exactly as for any other app. Volume, balance
and the speed (time-stretch, pitch kept) are done here in pure Python, so they work the same on both systems.
The original file (before its WAV is ready, or a WAV this player can't read) still goes through QMediaPlayer.
"""
import array
import math
import os
import sys
import wave

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioOutput, QAudioSink, QMediaDevices, QMediaPlayer

BUFFER_S = 0.25     # sink buffer: what a volume / balance change lags behind, at most
CHUNK_S = 0.05      # written per fill
FILL_MS = 10


def _name(e):
    """Enum member name: PySide6 exposes these as QAudio.* or QtAudio.* depending on the Qt version."""
    return getattr(e, 'name', str(e).rsplit('.', 1)[-1])


def balance_gains(volume, pan):
    """(left, right) gains. volume 0..1; pan -1 (left) .. 0 (centre) .. +1 (right).
    Balance law: the centre is unity on both sides (true stereo); turning towards one side fades the other."""
    v = max(0.0, min(1.0, float(volume)))
    p = max(-1.0, min(1.0, float(pan)))
    return v * min(1.0, 1.0 - p), v * min(1.0, 1.0 + p)


def pan_text(p):
    """Balance as shown in the tooltip: 'Centre', 'L 40', 'R 25' (percent towards that side)."""
    k = int(round(abs(p) * 100))
    return 'Centre' if k == 0 else ('L %d' % k if p < 0 else 'R %d' % k)


def apply_gains(pcm, gl, gr):
    """Interleaved stereo int16 array -> new array with the gains applied (|g| <= 1, so no clipping)."""
    if gl == 1.0 and gr == 1.0:
        return array.array('h', pcm)
    out = array.array('h', bytes(len(pcm) * 2))
    if gl:
        out[0::2] = array.array('h', [int(x * gl) for x in pcm[0::2]])
    if gr:
        out[1::2] = array.array('h', [int(x * gr) for x in pcm[1::2]])
    return out


def to_stereo(pcm, channels):
    if channels == 2:
        return pcm
    n = len(pcm) // channels
    mono = pcm if channels == 1 else pcm[0::channels]
    out = array.array('h', bytes(n * 4))
    out[0::2] = mono[:n]
    out[1::2] = mono[:n] if channels == 1 else pcm[1::channels][:n]
    return out


def read_wav(path):
    """-> (interleaved stereo int16 array, sample rate). Raises on anything but 16-bit PCM."""
    with wave.open(path, 'rb') as w:
        ch, sr, sw = w.getnchannels(), w.getframerate(), w.getsampwidth()
        if sw != 2 or ch < 1:
            raise ValueError('not 16-bit PCM')
        raw = w.readframes(w.getnframes())
    pcm = array.array('h')
    pcm.frombytes(raw[:len(raw) // (2 * ch) * 2 * ch])
    if sys.byteorder != 'little':
        pcm.byteswap()
    return to_stereo(pcm, ch), sr


class Stretcher:
    """WSOLA time-stretch (pitch kept) over an interleaved stereo int16 array, in steps of HOP output frames."""
    HOP = 1024          # output frames per step (23 ms at 44.1 kHz); window = 2 * HOP, Hann, 50 % overlap
    TOL = 512           # search +- frames around the nominal position
    DEC = 16            # similarity on every 16th frame

    def __init__(self, pcm, start_frame, rate):
        self.pcm, self.rate = pcm, rate
        self.n = len(pcm) // 2
        H = self.HOP
        self.win = [0.5 - 0.5 * math.cos(math.pi * i / H) for i in range(2 * H)]  # periodic Hann, w[i]+w[i+H] = 1
        self.pos = float(start_frame)            # nominal analysis position of the next segment
        self.prev = max(0, int(start_frame) - H)  # start of the previous segment (its 2nd half overlaps next)

    def _sim(self, a, b, count, step):
        p = self.pcm
        s = 0
        for k in range(0, count, step):
            i, j = 2 * (a + k), 2 * (b + k)
            s += (p[i] + p[i + 1]) * (p[j] + p[j + 1])
        return s

    def _best(self, nominal):
        H, T, D = self.HOP, self.TOL, self.DEC
        target = self.prev + H
        lo = max(0, nominal - T)
        hi = min(self.n - 2 * H, nominal + T)
        if hi <= lo:
            return max(0, min(nominal, self.n - 2 * H))
        best, best_s = nominal if lo <= nominal <= hi else lo, None
        for c in range(lo, hi + 1, D):
            s = self._sim(target, c, H, D)
            if best_s is None or s > best_s:
                best, best_s = c, s
        for c in range(max(lo, best - D + 2), min(hi, best + D - 1), 2):
            s = self._sim(target, c, H, D // 2)
            if s > best_s:
                best, best_s = c, s
        return best

    def done(self):
        return int(self.pos) + 2 * self.HOP >= self.n

    def step(self):
        """-> (HOP frames of output as interleaved array, source frame at the start of that output)."""
        H, p, w = self.HOP, self.pcm, self.win
        cur = self._best(int(self.pos))
        a, b = 2 * (self.prev + H), 2 * cur
        out = array.array('h', bytes(4 * H))
        for i in range(H):
            wa, wb = w[H + i], w[i]
            k = 2 * i
            out[k] = int(p[a + k] * wa + p[b + k] * wb)
            out[k + 1] = int(p[a + k + 1] * wa + p[b + k + 1] * wb)
        src = self.prev + H
        self.prev = cur
        self.pos += H * self.rate
        return out, src


PS, MS = QMediaPlayer.PlaybackState, QMediaPlayer.MediaStatus


class StereoPlayer(QObject):
    """The subset of QMediaPlayer the window uses, plus setVolume / setPan."""
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    positionChanged = Signal(int)
    errorOccurred = Signal(object, str)
    MediaStatus = QMediaPlayer.MediaStatus
    PlaybackState = QMediaPlayer.PlaybackState

    def __init__(self, parent=None):
        super().__init__(parent)
        self._volume, self._pan, self._rate = 1.0, 0.0, 1.0
        self._pcm, self._sr, self._url = None, 44100, QUrl()
        self._state, self._status = PS.StoppedState, MS.NoMedia
        self._frame = 0                 # source frame of the next sample written (or the paused position)
        self._sink = self._io = None
        self._segs = []                 # (output frame, source frame, rate) for each written chunk
        self._written = 0               # output frames written since the sink started
        self._stretch = None
        self._timer = QTimer(self)
        self._timer.setInterval(FILL_MS)
        self._timer.timeout.connect(self._fill)
        self._last_pos = -1
        # fallback: the original file while its WAV is being made
        self._qp = QMediaPlayer(self)
        self._qo = QAudioOutput(self)
        self._qp.setAudioOutput(self._qo)
        self._qp.playbackStateChanged.connect(lambda s: self._fb() and self.playbackStateChanged.emit(s))
        self._qp.mediaStatusChanged.connect(lambda s: self._fb() and self.mediaStatusChanged.emit(s))
        self._qp.positionChanged.connect(lambda ms: self._fb() and self.positionChanged.emit(ms))
        self._qp.errorOccurred.connect(lambda e, m: self._fb() and self.errorOccurred.emit(e, m))
        self._use_qp = False

    def isAvailable(self):
        return self._qp.isAvailable()

    def _fb(self):
        return self._use_qp

    # ---------------------------------------------------------------- source
    def setSource(self, url):
        self.stop()
        self._url = QUrl(url)
        path = self._url.toLocalFile() if not self._url.isEmpty() else ''
        self._pcm, self._frame = None, 0
        if path and path.lower().endswith('.wav') and os.path.exists(path):
            try:
                self._pcm, self._sr = read_wav(path)
            except Exception:  # noqa: BLE001
                self._pcm = None
            if self._pcm is not None and not self._format_ok():
                self._pcm = None
        if self._pcm is not None or not path:
            self._use_qp = False
            self._qp.setSource(QUrl())
            self._set_status(MS.LoadedMedia if self._pcm is not None else MS.NoMedia)
            self.positionChanged.emit(0)
        else:
            self._use_qp = True
            self._qp.setSource(self._url)
            self._qp.setPlaybackRate(self._rate)

    def source(self):
        return self._url

    def native(self):
        """True when this file plays through the stereo sink (volume and balance both work)."""
        return self._pcm is not None

    def _fmt(self):
        f = QAudioFormat()
        f.setSampleRate(self._sr)
        f.setChannelCount(2)
        f.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        f.setChannelConfig(QAudioFormat.ChannelConfig.ChannelConfigStereo)
        return f

    def _format_ok(self):
        dev = QMediaDevices.defaultAudioOutput()
        return not dev.isNull() and dev.isFormatSupported(self._fmt())

    # ---------------------------------------------------------------- state
    def playbackState(self):
        return self._qp.playbackState() if self._use_qp else self._state

    def mediaStatus(self):
        return self._qp.mediaStatus() if self._use_qp else self._status

    def duration(self):
        if self._use_qp:
            return self._qp.duration()
        return int(len(self._pcm) // 2 * 1000 / self._sr) if self._pcm is not None else 0

    def position(self):
        if self._use_qp:
            return self._qp.position()
        return int(round(self._played_frame() * 1000.0 / self._sr))

    def _set_state(self, s):
        if s != self._state:
            self._state = s
            self.playbackStateChanged.emit(s)

    def _set_status(self, s):
        if s != self._status:
            self._status = s
            self.mediaStatusChanged.emit(s)

    # ---------------------------------------------------------------- volume / balance / speed
    def setVolume(self, v):
        self._volume = max(0.0, min(1.0, float(v)))
        self._qo.setVolume(self._volume)

    def volume(self):
        return self._volume

    def setPan(self, p):
        self._pan = max(-1.0, min(1.0, float(p)))

    def pan(self):
        return self._pan

    def setPlaybackRate(self, r):
        r = float(r or 1.0)
        if self._use_qp:
            self._qp.setPlaybackRate(r)
        if r == self._rate:
            return
        cur = self._played_frame() if self._sink is not None else None
        self._rate = r
        if cur is not None:  # restart from what is heard now, at the new speed
            self._restart(cur)

    def playbackRate(self):
        return self._rate

    # ---------------------------------------------------------------- transport
    def play(self):
        if self._use_qp:
            self._qp.play()
            return
        if self._pcm is None:
            return
        if self._status == MS.EndOfMedia or self._frame >= len(self._pcm) // 2:
            self._frame = 0
        if self._sink is None and not self._start_sink(self._frame):
            return
        self._set_status(MS.BufferedMedia)
        self._set_state(PS.PlayingState)

    def pause(self):
        if self._use_qp:
            self._qp.pause()
            return
        if self._state != PS.PlayingState:
            return
        self._frame = self._played_frame()
        self._stop_sink()
        self._set_state(PS.PausedState)
        self.positionChanged.emit(self.position())

    def stop(self):
        if self._use_qp:
            self._qp.stop()
            return
        self._stop_sink()
        self._frame = 0
        if self._state != PS.StoppedState:
            self._set_state(PS.StoppedState)

    def setPosition(self, ms):
        if self._use_qp:
            self._qp.setPosition(ms)
            return
        if self._pcm is None:
            return
        f = max(0, min(len(self._pcm) // 2, int(round(ms * self._sr / 1000.0))))
        if self._status == MS.EndOfMedia:
            self._set_status(MS.LoadedMedia)
        if self._sink is not None:
            self._restart(f)
        else:
            self._frame = f
        self.positionChanged.emit(int(round(f * 1000.0 / self._sr)))

    # ---------------------------------------------------------------- the sink
    def _start_sink(self, frame):
        sink = QAudioSink(QMediaDevices.defaultAudioOutput(), self._fmt(), self)
        sink.setBufferSize(int(self._sr * BUFFER_S) * 4)
        io = sink.start()
        if io is None or _name(sink.error()) != 'NoError':
            sink.deleteLater()
            self.errorOccurred.emit(QMediaPlayer.Error.ResourceError, 'could not open the audio output')
            return False
        self._sink, self._io = sink, io
        self._frame, self._written, self._segs = frame, 0, []
        self._stretch = None
        self._fill()
        self._timer.start()
        return True

    def _stop_sink(self):
        self._timer.stop()
        if self._sink is not None:
            s, self._sink, self._io = self._sink, None, None
            s.stop()
            s.deleteLater()
        self._stretch = None

    def _restart(self, frame):
        playing = self._sink is not None
        self._stop_sink()
        self._frame = frame
        if playing:
            self._start_sink(frame)

    def _played_frame(self):
        """Source frame being heard now (from the sink's processed time and the write log)."""
        if self._sink is None or not self._segs:
            return self._frame
        out = self._sink.processedUSecs() * self._sr // 1000000
        # what the device has actually played lags what Qt has taken from us by its own buffer
        out = max(0, min(out, self._written))
        seg = self._segs[0]
        for s in self._segs:
            if s[0] <= out:
                seg = s
            else:
                break
        f = seg[1] + (out - seg[0]) * seg[2]
        return max(0, min(len(self._pcm) // 2, int(f)))

    def _fill(self):
        if self._sink is None:
            return
        n = len(self._pcm) // 2
        free = self._sink.bytesFree() // 4
        chunk = max(1, int(self._sr * CHUNK_S))
        gl, gr = balance_gains(self._volume, self._pan)
        while free >= min(chunk, Stretcher.HOP if self._rate != 1.0 else chunk) and self._frame < n:
            if self._rate == 1.0:
                k = min(chunk, free, n - self._frame)
                data, src = self._pcm[2 * self._frame:2 * (self._frame + k)], self._frame
                self._frame += k
            else:
                if self._stretch is None:
                    self._stretch = Stretcher(self._pcm, self._frame, self._rate)
                st = self._stretch
                if st.done():
                    self._frame = n
                    break
                if free < st.HOP:
                    break
                data, src = st.step()
                k = st.HOP
                self._frame = int(st.pos)
            data = apply_gains(data, gl, gr)
            if sys.byteorder != 'little':
                data.byteswap()
            self._segs.append((self._written, src, self._rate))
            if len(self._segs) > 64:
                del self._segs[:-64]
            self._io.write(data.tobytes())
            self._written += k
            free -= k
        pos = self.position()
        if abs(pos - self._last_pos) >= 40:
            self._last_pos = pos
            self.positionChanged.emit(pos)
        if self._frame >= n and self._sink is not None:
            played = self._sink.processedUSecs() * self._sr // 1000000
            if played >= self._written - int(self._sr * 0.02) or _name(self._sink.state()) == 'IdleState':
                self._stop_sink()
                self._frame = n
                self._set_status(MS.EndOfMedia)
                self._set_state(PS.StoppedState)
                self.positionChanged.emit(self.duration())
