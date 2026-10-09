"""♪ lines in instrumental parts (app/lyricist_sync/instrumental.py) and their export."""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
from lyricist_sync import instrumental as I  # noqa: E402
from lyricist_sync import formats as F  # noqa: E402


def song(vocals=True):
    """intro 0-12 (a hum at 4-5 s), 4 lines, a 14 s solo, 2 lines, a 20 s outro."""
    lines = [
        {'text': 'one', 'start': 12.0, 'end': 14.5, 'idx': 0, 'conf': 0.9},
        {'text': 'two', 'start': 15.0, 'end': 17.0, 'idx': 1, 'conf': 0.9},
        {'text': 'three', 'start': 17.5, 'end': 20.0, 'idx': 2, 'conf': 0.4},
        {'text': 'four', 'start': 20.5, 'end': 23.0, 'idx': 3, 'conf': 0.9},   # held note to 24.2
        {'text': 'five', 'start': 38.0, 'end': 40.0, 'idx': 4, 'conf': 0.9},
        {'text': 'six', 'start': 40.5, 'end': 43.0, 'idx': 5, 'conf': 0.9},
    ]
    r = {'lines': lines, 'duration': 63.0}
    if vocals:
        r['vocals'] = [[4.0, 5.0], [11.9, 24.2], [30.0, 30.6], [37.9, 43.1]]
    return r


class Gaps(unittest.TestCase):
    def test_intro_solo_outro(self):
        r = song()
        n = I.apply(r)
        self.assertEqual(n, 3)
        got = [(l.get('kind'), l['start'], l['end']) for l in r['lines'] if l.get('inst')]
        self.assertEqual(got, [('intro', 0.0, 11.7), ('break', 24.2, 37.7), ('outro', 43.1, 63.0)])
        texts = [l['text'] for l in r['lines']]
        self.assertEqual(texts, ['♪', 'one', 'two', 'three', 'four', '♪', 'five', 'six', '♪'])
        four = r['lines'][4]
        self.assertEqual((four['end'], four['end0']), (24.2, 23.0))   # the previous line ends where the gap starts

    def test_threshold_and_switches(self):
        r = song()
        I.apply(r, {'inst_gap': 15})
        self.assertEqual([l.get('kind') for l in r['lines'] if l.get('inst')], ['outro'])
        I.apply(r, {'inst_gap': 3, 'inst_edges': False})
        self.assertEqual([l.get('kind') for l in r['lines'] if l.get('inst')], ['break'])
        self.assertEqual(r['lines'][3]['end'], 24.2)
        I.apply(r, {'inst_on': False})
        self.assertFalse(any(l.get('inst') for l in r['lines']))
        self.assertEqual(r['lines'][3]['end'], 23.0)                   # original end restored
        self.assertEqual(I.settings_of({'inst_gap': 99})['inst_gap'], 30.0)
        self.assertEqual(I.settings_of({'inst_gap': 1})['inst_gap'], 3.0)

    def test_hold_is_capped(self):
        r = song()
        r['vocals'][1] = [11.9, 40.0]   # bleed: the stem never goes quiet
        I.apply(r)
        brk = [l for l in r['lines'] if l.get('kind') == 'break'][0]
        self.assertEqual(brk['start'], 23.0 + I.HOLD)

    def test_without_vocal_regions(self):
        r = song(vocals=False)   # results from 1.1.0
        I.apply(r)
        self.assertEqual([(l.get('kind'), l['start']) for l in r['lines'] if l.get('inst')],
                         [('intro', 0.0), ('break', 23.0), ('outro', 43.0)])

    def test_symbol(self):
        for sym in I.SYMBOLS:
            r = song()
            I.apply(r, {'inst_symbol': sym})
            self.assertEqual({l['text'] for l in r['lines'] if l.get('inst')}, {sym})

    def test_delete_insert(self):
        r = song()
        I.apply(r)
        self.assertTrue(I.delete(r, 0))                     # the intro
        self.assertFalse(I.delete(r, 0))                    # 'one' is not a ♪ line
        r['lines'][0]['start'] = 12.3                       # nudging doesn't bring it back
        I.apply(r)
        self.assertEqual([l.get('kind') for l in r['lines'] if l.get('inst')], ['break', 'outro'])
        row = I.insert(r, 1.0)
        self.assertEqual(r['lines'][row]['start'], 1.0)
        self.assertEqual(r['lines'][row]['end'], 12.0)      # 0.3 s before 'one'
        self.assertFalse(r['lines'][row]['auto'])
        I.apply(r, {'inst_symbol': '♫'})
        self.assertEqual(sum(1 for l in r['lines'] if l.get('inst')), 3)
        self.assertEqual(r['lines'][0]['text'], '♫')
        # a manual ♪ inside a sung line ends that line
        row = I.insert(r, 16.0)
        two = [l for l in r['lines'] if l['text'] == 'two'][0]
        self.assertEqual(two['end'], 16.0)

    def test_order_and_never_aligned(self):
        r = song()
        I.apply(r)
        sung = I.sung(r['lines'])
        self.assertEqual([l['idx'] for l in sung], list(range(6)))
        starts = [l['start'] for l in r['lines']]
        self.assertEqual(starts, sorted(starts))
        for a, b in zip(r['lines'], r['lines'][1:]):
            self.assertLessEqual(a['end'], b['start'] + 1e-9)

    def test_fixtures(self):
        for sub, name, want in (('fixtures', 'demo_en', []), ('fixtures', 'demo_el', []), ('hard', 'choir', ['outro'])):
            with open(os.path.join(HERE, sub, name + '.result.json'), encoding='utf-8') as f:
                r = json.load(f)
            I.apply(r)
            self.assertEqual([l.get('kind') for l in r['lines'] if l.get('inst')], want, name)


class Export(unittest.TestCase):
    def test_all_formats(self):
        r = song()
        I.apply(r)
        lines = [{'text': l['text'], 'time': l['start'], 'end': l['end'] + (0 if l.get('inst') else 0.4)} for l in r['lines']]
        lrc = F.build('lrc', lines, {}, r['duration'])
        self.assertIn('[00:00.00]♪', lrc)
        self.assertIn('[00:24.20]♪', lrc)
        srt = F.build('srt', lines, {}, r['duration'])
        self.assertIn('00:00:24,200 --> 00:00:37,700\n♪', srt)
        vtt = F.build('vtt', lines, {}, r['duration'])
        self.assertIn('00:00:24.200 --> 00:00:37.700\n♪', vtt)
        ttml = F.build('ttml', lines, {}, r['duration'])
        self.assertIn('>♪</p>', ttml)

    def test_export_song(self):
        from lyricist_sync.export import export_song
        d = tempfile.mkdtemp()
        try:
            class S:
                pass
            s = S()
            s.path, s.tags, s.iso, s.out_dir = os.path.join(d, 'x.mp3'), {}, 'eng', None
            s.result = song()
            I.apply(s.result)
            files = export_song(s, {'dir': d, 'formats': ['lrc', 'srt'], 'bom': False})
            with open([f for f in files if f.endswith('.srt')][0], encoding='utf-8') as fh:
                srt = fh.read()
            # the sung line before the solo lingers to the ♪, the ♪ ends 0.3 s before the next line
            self.assertIn('00:00:20,500 --> 00:00:24,200\nfour', srt)
            self.assertIn('00:00:24,200 --> 00:00:37,700\n♪', srt)
            self.assertIn('00:00:43,100 --> 00:01:03,000\n♪', srt)
        finally:
            shutil.rmtree(d)


if __name__ == '__main__':
    unittest.main()
