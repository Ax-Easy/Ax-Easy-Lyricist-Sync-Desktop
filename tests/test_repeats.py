"""Repeat detection (lines sung more often than written) on synthetic transcripts and on the
real Whisper transcript of a private test song (lines 15-16 sung twice, written once; skipped unless present)."""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'engine'))
import lyricist_engine as E  # noqa: E402

L = [['a1', 'a2', 'a3', 'a4'], ['b1', 'b2', 'b3', 'b4', 'b5'], ['c1', 'c2', 'c3', 'c4'], ['d1', 'd2', 'd3', 'd4']]
L6 = [['g1', 'g2', 'g3'], ['w1', 'w2', 'w3'], ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], ['e1', 'e2', 'e3', 'e4', 'e5'],
      ['s1', 's2', 's3', 's4'], ['m1', 'm2', 'm3', 'm4', 'm5']]


def seq(lines, words):
    return [i + 1 for i in E.expand_repeats(lines, [(w, k, k) for k, w in enumerate(words)])[0]]


class TestRepeats(unittest.TestCase):
    def test_chorus_three_times(self):
        T = ['oh', 'yeah'] + L[0] + L[1] + L[2] + L[1] + L[2] + L[1] + L[2] + ['x'] + L[3] + ['stay', 'stay']
        self.assertEqual(seq(L, T), [1, 2, 3, 2, 3, 2, 3, 4])

    def test_chorus_at_end(self):
        T = [w for l in L6 for w in l] + L6[2] + L6[3]
        self.assertEqual(seq(L6, T), [1, 2, 3, 4, 5, 6, 3, 4])

    def test_no_repeat_with_junk_and_stutter(self):
        self.assertEqual(seq(L, L[0] + L[1] + ['x', 'y'] + L[2] + L[3]), [1, 2, 3, 4])
        self.assertEqual(seq(L, L[0] + L[1] + L[1][:2] + L[2] + L[3]), [1, 2, 3, 4])

    def test_unheard_lines_keep_place(self):
        self.assertEqual(seq(L, L[0] + L[2] + L[3]), [1, 2, 3, 4])
        self.assertEqual(seq(L6, [w for l in L6[:4] for w in l]), [1, 2, 3, 4, 5, 6])

    def test_greek_romanization(self):
        self.assertEqual(E.ctc_words(E.romanize(['Καλησπέρα κόσμε'], 'ell')[0]), ['kalespera', 'kosme'])
        self.assertEqual(E.ctc_words(E.romanize(['Ο ήλιος ανατέλλει πάλι 🌅'], 'ell')[0]), ['o', 'elios', 'anatellei', 'pali'])

    @unittest.skipUnless(os.path.exists('/workspace/autosync/out/whisper_free_vocals.json'), 'private test song transcript not present')
    def test_private_song(self):
        lines = [l.strip() for l in open('/workspace/autosync/lyrics.txt', encoding='utf-8-sig') if l.strip()]
        lw = [E.ctc_words(r) for r in E.romanize(lines)]
        words = [tuple(w) for s in json.load(open('/workspace/autosync/out/whisper_free_vocals.json')) for w in s['words']]
        tw = [(x, s, e) for (w, s, e) in words for x in E.ctc_words(E.romanize([w])[0])]
        order = [i + 1 for i in E.expand_repeats(lw, tw)[0]]
        self.assertEqual(order, list(range(1, 17)) + [15, 16] + list(range(17, 23)))


if __name__ == '__main__':
    unittest.main()
