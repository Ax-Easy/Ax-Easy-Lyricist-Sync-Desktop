"""Word-level export (1.5.0): the aligner's words reach the files, move with their line, and never go stale."""
import json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
sys.path.insert(0, os.path.join(HERE, '..', 'engine'))
from lyricist_sync import formats as F  # noqa: E402


def line(text, start, end, words=None, at=None, **kw):
    d = {'text': text, 'start': start, 'end': end, 'inst': False}
    if words:
        d['word_times'], d['word_times_at'] = words, start if at is None else at
    d.update(kw)
    return d


def export_lines(result_lines):
    return [{'text': l['text'], 'time': l['start'], 'end': l['end'], 'words': F.line_words(l), 'inst': l.get('inst', False)}
            for l in result_lines]


class WordFileTests(unittest.TestCase):
    def setUp(self):
        self.res = [line('Steel hearts awaken', 4.0, 6.0, [['Steel', 4.0, 4.5], ['hearts', 4.6, 5.2], ['awaken', 5.3, 5.9]]),
                    line('♪', 6.0, 9.0, inst=True),
                    line('Their eyes ignite', 9.0, 11.0)]                    # no word times: stays line-level

    def test_json_has_words_and_flags(self):
        d = json.loads(F.build('words', export_lines(self.res), {'ti': 'Eternal War', 'ar': 'Monitored', 'lang': 'eng'}, 12.0))
        self.assertEqual((d['format'], d['title'], d['artist'], d['language'], d['duration']), ('ax-easy-words', 'Eternal War', 'Monitored', 'en', 12.0))
        a, b, c = d['lines']
        self.assertEqual(a['words'][1], {'w': 'hearts', 'start': 4.6, 'end': 5.2})
        self.assertTrue(b['instrumental'])
        self.assertNotIn('words', b)
        self.assertNotIn('words', c)
        self.assertEqual((c['start'], c['end']), (9.0, 11.0))

    def test_enhanced_lrc(self):
        t = F.build('wlrc', export_lines(self.res), {'ti': 'Eternal War'}, 12.0).splitlines()
        self.assertEqual(t[0], '[ti:Eternal War]')
        self.assertEqual(t[1], '[00:04.00]<00:04.00>Steel <00:04.60>hearts <00:05.30>awaken <00:05.90>')
        self.assertEqual(t[-1], '[00:09.00]Their eyes ignite')

    def test_words_move_with_their_line(self):
        l = self.res[0]
        l['start'], l['end'] = 5.0, 7.0                                           # nudged by hand, one second later
        self.assertEqual(F.line_words(l)[0], ['Steel', 5.0, 5.5])

    def test_a_changed_text_drops_stale_words(self):
        l = self.res[0]
        l['text'] = 'Steel hearts awake'
        self.assertIsNone(F.line_words(l))
        l['text'] = 'Steel hearts awaken'
        self.assertIsNotNone(F.line_words(l))
        l['text'] = 'Steel hearts'                                               # split: the second half no longer fits
        self.assertIsNone(F.line_words(l))

    def test_words_stay_inside_the_cue(self):
        l = self.res[0]
        l['end'] = 5.5
        d = json.loads(F.build('words', export_lines([l]), {}, 8.0))
        self.assertLessEqual(d['lines'][0]['words'][-1]['end'], 5.5)

    def test_line_formats_are_unchanged_by_words(self):
        plain = [{'text': l['text'], 'time': l['start'], 'end': l['end']} for l in self.res]
        for fmt in ('lrc', 'srt', 'vtt', 'ttml'):
            self.assertEqual(F.build(fmt, export_lines(self.res), {}, 12.0), F.build(fmt, plain, {}, 12.0))


class EngineMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import lyricist_engine as E  # noqa: F401
            cls.E = E
        except Exception as e:   # noqa: BLE001  (the engine imports need no torch at module level; skip if they do)
            raise unittest.SkipTest('engine not importable here: %s' % e)

    def al(self, n):
        return [(i * 0.5, i * 0.5 + 0.4, 0.9, []) for i in range(n)]

    def test_words_map_back_to_the_written_ones(self):
        r = self.E.timed_words('Steel hearts awaken', self.al(3))
        self.assertEqual(r, [['Steel', 0.0, 0.4], ['hearts', 0.5, 0.9], ['awaken', 1.0, 1.4]])

    def test_a_silent_token_is_left_out_and_a_split_word_takes_both_spans(self):
        r = self.E.timed_words('Steel & x-ray', self.al(3))
        self.assertEqual(r, [['Steel', 0.0, 0.4], ['x-ray', 0.5, 1.4]])

    def test_a_count_mismatch_gives_no_words(self):
        self.assertIsNone(self.E.timed_words('Steel hearts awaken', self.al(2)))
        self.assertIsNone(self.E.timed_words('', self.al(2)))


if __name__ == '__main__':
    unittest.main()
