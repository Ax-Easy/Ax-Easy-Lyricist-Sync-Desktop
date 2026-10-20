"""1.3.2 player audio: balance / volume gains, true stereo (L and R stay apart and equal), mono files,
the WSOLA speed change (length scales, pitch kept), the knob widget, and StereoPlayer transport + settings."""
import array, math, os, sys, tempfile, unittest, wave
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
os.environ.setdefault('LYRICIST_SYNC_HOME', tempfile.mkdtemp())
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from lyricist_sync import audio as A  # noqa: E402

SR = 44100


def tone(freq, secs, amp=8000, phase=0.0):
    return [int(amp * math.sin(2 * math.pi * freq * i / SR + phase)) for i in range(int(secs * SR))]


def stereo(left, right):
    out = array.array('h', bytes(len(left) * 4))
    out[0::2] = array.array('h', left)
    out[1::2] = array.array('h', right)
    return out


def rms(xs):
    return math.sqrt(sum(x * x for x in xs) / max(1, len(xs)))


def freq(xs):
    """Zero-crossing frequency estimate."""
    z = sum(1 for a, b in zip(xs, xs[1:]) if a < 0 <= b)
    return z * SR / len(xs)


def write_wav(path, pcm, ch):
    with wave.open(path, 'wb') as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


class Gains(unittest.TestCase):
    def test_centre_is_unity_both_sides(self):
        self.assertEqual(A.balance_gains(1.0, 0.0), (1.0, 1.0))

    def test_balance_law(self):
        self.assertEqual(A.balance_gains(1.0, -1.0), (1.0, 0.0))
        self.assertEqual(A.balance_gains(1.0, 1.0), (0.0, 1.0))
        gl, gr = A.balance_gains(1.0, 0.5)
        self.assertAlmostEqual(gl, 0.5)
        self.assertEqual(gr, 1.0)

    def test_volume_and_clamping(self):
        self.assertEqual(A.balance_gains(0.5, 0.0), (0.5, 0.5))
        self.assertEqual(A.balance_gains(2.0, -3.0), (1.0, 0.0))
        self.assertEqual(A.balance_gains(-1, 0), (0.0, 0.0))

    def test_pan_text(self):
        self.assertEqual(A.pan_text(0.0), 'Centre')
        self.assertEqual(A.pan_text(-0.4), 'L 40')
        self.assertEqual(A.pan_text(0.25), 'R 25')
        self.assertEqual(A.pan_text(1.0), 'R 100')


class TrueStereo(unittest.TestCase):
    def test_equal_lr_stays_equal_at_centre(self):
        s = stereo(tone(440, 0.5), tone(440, 0.5))
        out = A.apply_gains(s, *A.balance_gains(1.0, 0.0))
        self.assertEqual(list(out), list(s))
        self.assertEqual(rms(out[0::2]), rms(out[1::2]))

    def test_channels_not_mixed(self):
        # left only: nothing may leak into the right, and the other way round (true stereo, no downmix)
        silent = [0] * 22050
        for gains in ((1.0, 1.0), A.balance_gains(0.7, 0.3), A.balance_gains(0.7, -0.3)):
            out = A.apply_gains(stereo(tone(440, 0.5), silent), *gains)
            self.assertEqual(max(map(abs, out[1::2])), 0)
            out = A.apply_gains(stereo(silent, tone(440, 0.5)), *gains)
            self.assertEqual(max(map(abs, out[0::2])), 0)

    def test_pan_and_volume_levels(self):
        s = stereo(tone(440, 0.5), tone(440, 0.5))
        base = rms(s[0::2])
        out = A.apply_gains(s, *A.balance_gains(1.0, -1.0))
        self.assertAlmostEqual(rms(out[0::2]) / base, 1.0, places=3)
        self.assertEqual(rms(out[1::2]), 0.0)
        out = A.apply_gains(s, *A.balance_gains(0.5, 0.5))
        self.assertAlmostEqual(rms(out[0::2]) / base, 0.25, places=2)
        self.assertAlmostEqual(rms(out[1::2]) / base, 0.5, places=2)

    def test_read_wav_stereo_and_mono(self):
        d = tempfile.mkdtemp()
        st = stereo(tone(440, 0.2), tone(660, 0.2))
        write_wav(os.path.join(d, 's.wav'), st, 2)
        pcm, sr = A.read_wav(os.path.join(d, 's.wav'))
        self.assertEqual(sr, SR)
        self.assertEqual(list(pcm), list(st))
        mono = array.array('h', tone(440, 0.2))
        write_wav(os.path.join(d, 'm.wav'), mono, 1)
        pcm, _ = A.read_wav(os.path.join(d, 'm.wav'))
        self.assertEqual(len(pcm), 2 * len(mono))
        self.assertEqual(list(pcm[0::2]), list(mono))
        self.assertEqual(list(pcm[1::2]), list(mono))  # mono plays in the middle, not on one side


class Stretch(unittest.TestCase):
    def run_rate(self, rate):
        s = stereo(tone(440, 2.0), tone(440, 2.0, phase=1.0))
        st = A.Stretcher(s, 0, rate)
        out = array.array('h')
        while not st.done():
            chunk, _src = st.step()
            out.extend(chunk)
        return s, out

    def test_length_and_pitch(self):
        for rate in (0.5, 0.75, 1.25, 1.5):
            s, out = self.run_rate(rate)
            got = len(out) / len(s)
            self.assertAlmostEqual(got, 1.0 / rate, delta=0.08, msg='rate %s' % rate)
            body = out[2 * 4096:-2 * 4096]
            self.assertAlmostEqual(freq(body[0::2]), 440, delta=12, msg='pitch kept at %s×' % rate)
            self.assertAlmostEqual(freq(body[1::2]), 440, delta=12)
            # level stays (no dips from the overlap-add), and L/R stay balanced
            self.assertGreater(rms(body[0::2]) / rms(s[0::2]), 0.85)
            self.assertAlmostEqual(rms(body[0::2]) / rms(body[1::2]), 1.0, delta=0.05)


class Widgets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_knob(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent
        from lyricist_sync.widgets import Knob
        k = Knob('pan', -1.0, 1.0, 0.0, 'Balance', fmt=A.pan_text)
        seen, saved = [], []
        k.valueChanged.connect(seen.append)
        k.released.connect(saved.append)
        k.setValue(0.6, emit=True)
        self.assertEqual(seen[-1], 0.6)
        self.assertIn('Balance: R 60', k.toolTip())
        k.setValue(5)
        self.assertEqual(k.value(), 1.0)
        k.setValue(0.01)
        self.assertEqual(k.value(), 0.0)  # centre detent
        k.setValue(-0.5)
        ev = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(10, 10), QPointF(10, 10), Qt.LeftButton, Qt.LeftButton,
                         Qt.NoModifier)
        k.mouseDoubleClickEvent(ev)
        self.assertEqual(k.value(), 0.0)  # double-click resets to centre
        self.assertEqual(saved[-1], 0.0)
        v = Knob('volume', 0.0, 1.0, 1.0, 'Volume')
        self.assertIn('Volume: 100 %', v.toolTip())
        v.setValue(0.42)
        self.assertIn('42 %', v.toolTip())
        for dark in (True, False):
            from lyricist_sync.widgets import STATE
            STATE['dark'] = dark
            self.assertFalse(v.grab().isNull())
            self.assertFalse(k.grab().isNull())

    def test_player_transport_without_device(self):
        """StereoPlayer loads the cache WAV, seeks, reports duration, keeps volume / pan, and falls back cleanly."""
        from lyricist_sync.audio import StereoPlayer, MS, PS
        from PySide6.QtCore import QUrl
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'x.wav')
        write_wav(p, stereo(tone(440, 1.0), tone(440, 1.0)), 2)
        pl = StereoPlayer()
        pl.setVolume(0.3)
        pl.setPan(-0.2)
        self.assertEqual((pl.volume(), pl.pan()), (0.3, -0.2))
        pl.setSource(QUrl.fromLocalFile(p))
        if pl.native():
            self.assertEqual(pl.mediaStatus(), MS.LoadedMedia)
            self.assertEqual(pl.duration(), 1000)
            pl.setPosition(500)
            self.assertEqual(pl.position(), 500)
            self.assertEqual(pl.playbackState(), PS.StoppedState)
        pl.setSource(QUrl())
        self.assertEqual(pl.duration(), 0)


if __name__ == '__main__':
    unittest.main()
