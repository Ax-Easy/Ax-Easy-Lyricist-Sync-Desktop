"""Line-timing fixes of 1.1.0 on synthetic MMS emissions (no models needed):
- intro bleed: a vowel-like sound in the intro must not pull a vowel-initial first line,
- vocal-onset snap: no line starts where the vocals stem is silent,
- Whisper cross-check: a first line aligned far ahead of Whisper's word moves to it,
- monotonic, non-overlapping starts; confidence is low for weak lines,
- re-sync from a line keeps it and re-aligns only the lines after it."""
import os, sys, unittest
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'engine'))
import torch  # noqa: E402
import timing as TM  # noqa: E402

LABELS = ['-', 'a', 'i', 'e', 'n', 'o', 'u', 't', 's', 'r', 'm', 'k', 'l', 'd', 'g', 'h', 'y', 'b', 'p', 'w', 'c', 'v',
          'j', 'z', 'f', "'", 'q', 'x', '*']
VOCAB = {c: i for i, c in enumerate(LABELS)}
STAR = VOCAB['*']
FPS = 50.0
FS = 1 / FPS


class Song:
    """Emissions + a VAD energy track built from a list of sung lines and extra sounds."""

    def __init__(self, dur):
        self.n = int(dur * FPS)
        self.p = np.full((self.n, len(LABELS)), 1e-4)
        self.p[:, 0] = 1.0
        self.db = np.full(int(dur * 100), -80.0)

    def sound(self, t0, t1, db=-20.0):
        self.db[int(t0 * 100):int(t1 * 100)] = db

    def chars(self, t, text, prob=0.6, step=0.09):
        """Each letter as a peak (prob) at t, t+step... -> returns end time."""
        for ch in text:
            if ch == ' ':
                t += step
                continue
            f = int(t * FPS)
            self.p[f, VOCAB[ch]] = prob
            self.p[f, 0] = 1 - prob
            t += step
        return t

    def bleed(self, t0, t1, ch='a', prob=0.35, every=0.4):
        t = t0
        while t < t1:
            f = int(t * FPS)
            self.p[f, VOCAB[ch]] = prob
            self.p[f, 0] = 1 - prob
            t += every

    def emission(self):
        p = self.p / self.p.sum(1, keepdims=True)
        return torch.from_numpy(np.log(p).astype('float32'))

    def vad(self):
        return TM.Vad(db=self.db)


def words(text):
    return [w for w in text.lower().split()]


def run(song, lines, anchors=None, star=True):
    em = song.emission()
    occw = [words(l) for l in lines]
    if not star:
        return TM.align_window(em, FS, occw, 0, em.shape[0], VOCAB, STAR, lead=False, trail=False, star_logp=-1e4)
    occ = TM.align_window(em, FS, occw, 0, em.shape[0], VOCAB, STAR)
    vad = song.vad()
    TM.refine(occ, occw, em, FS, vad, anchors, song.n * FS, VOCAB, STAR)
    TM.monotonic(occ, song.n * FS)
    for k, o in enumerate(occ):
        o['conf'], o['why'] = TM.confidence(o, occw[k], vad, (anchors or [[]] * len(occ))[k], anchors is not None)
    return occ


LINES = ['all of the lights', 'over the river cold', 'every road leads home']


def bleed_song():
    s = Song(40)
    s.sound(4, 21, -26)          # vowel-like synth bleeding into the vocals stem
    s.bleed(4.2, 20.5, 'a', 0.45)
    s.sound(26, 38, -12)         # the vocals
    s.chars(26.0, 'all of the lights', prob=0.2)          # weak sung onset on 'a'
    s.p[int(26.0 * FPS), VOCAB['a']] = 0.12
    s.p[int(26.0 * FPS), 0] = 0.88
    s.chars(30.0, 'over the river cold')
    s.chars(34.0, 'every road leads home')
    return s


class TestTiming(unittest.TestCase):
    def test_intro_bleed_old_vs_new(self):
        s = bleed_song()
        old = run(s, LINES, star=False)
        new = run(s, LINES)
        print('\n  intro bleed: line 1 truth 26.00 s | 1.0.0 method %.2f s | 1.1.0 %.2f s (%s)' % (
            old[0]['start'], new[0]['start'], ', '.join(new[0].get('fix', [])) or '-'))
        self.assertLess(old[0]['start'], 21.0)              # the 1.0.0 behaviour: starts in the intro
        self.assertAlmostEqual(new[0]['start'], 26.0, delta=0.15)
        self.assertAlmostEqual(new[1]['start'], 30.0, delta=0.15)

    def test_snap_to_vocal_onset(self):
        s = Song(20)
        s.sound(5.3, 9, -12)
        s.chars(5.0, 'hold the line', prob=0.5)  # aligned peaks start 0.3 s before the vocals
        s.sound(10, 14, -12)
        s.chars(10.0, 'every word')
        occ = run(s, ['hold the line', 'every word'])
        self.assertGreaterEqual(occ[0]['start'], 5.3 - 0.02)
        self.assertLess(occ[0]['start'], 5.5)
        self.assertIn('onset', occ[0]['fix'])

    def test_whisper_cross_check(self):
        s = Song(40)
        s.sound(3, 21, -14)          # hummed intro (vocal, so VAD is on)
        s.bleed(3.2, 20.5, 'r', 0.5)
        s.sound(22, 36, -12)
        s.chars(22.0, 'remember us', prob=0.3)
        s.chars(28.0, 'as a system failure')
        anchors = [[(0, 22.05, 22.5, 0.0), (1, 22.6, 22.9, 0.0)], [(0, 28.0, 28.3, 0.0)]]
        occ = run(s, ['remember us', 'as a system failure'], anchors)
        self.assertAlmostEqual(occ[0]['start'], 22.0, delta=0.3)

    def test_monotonic_with_overlap(self):
        s = Song(20)
        s.sound(2, 16, -12)
        s.chars(2.0, 'sing it together')
        s.chars(3.4, 'sing it together', prob=0.3)   # choir echo overlapping the next line
        s.chars(3.9, 'raise your voices')
        s.chars(8.0, 'carry the spark')
        occ = run(s, ['sing it together', 'raise your voices', 'carry the spark'])
        st = [o['start'] for o in occ]
        self.assertEqual(st, sorted(st))
        for a, b in zip(occ, occ[1:]):
            self.assertLessEqual(a['end'], b['start'] + 1e-6)
            self.assertGreaterEqual(b['start'] - a['start'], TM.MIN_STEP - 1e-6)

    def test_confidence_flags_weak_line(self):
        s = Song(20)
        s.sound(2, 12, -12)
        s.chars(2.0, 'clear line here', prob=0.8)
        s.chars(6.0, 'mumbled words', prob=0.06)
        occ = run(s, ['clear line here', 'mumbled words'], [[(0, 2.0, 2.2, 0), (1, 2.3, 2.5, 0), (2, 2.6, 2.8, 0)], []])
        self.assertGreater(occ[0]['conf'], TM.LOW_CONF)
        self.assertLess(occ[1]['conf'], TM.LOW_CONF)
        self.assertTrue(occ[1]['why'])

    def test_resync_from_line(self):
        s = Song(30)
        s.sound(2, 28, -12)
        for t, l in ((2.0, 'one two three'), (6.0, 'four five six'), (10.0, 'seven eight nine'), (14.0, 'ten eleven twelve')):
            s.chars(t, l)
        lines = ['one two three', 'four five six', 'seven eight nine', 'ten eleven twelve']
        em = s.emission()
        occw = [words(l) for l in lines]
        anchor = 6.1  # VAG fixed line 2 by hand
        part = TM.align_window(em, FS, occw[1:], int(anchor * FPS) - 1, em.shape[0], VOCAB, STAR, lead=False)
        self.assertAlmostEqual(part[1]['start'], 10.0, delta=0.1)
        self.assertAlmostEqual(part[2]['start'], 14.0, delta=0.1)
        self.assertGreaterEqual(part[0]['start'], anchor - 0.05)


if __name__ == '__main__':
    unittest.main(verbosity=2)
