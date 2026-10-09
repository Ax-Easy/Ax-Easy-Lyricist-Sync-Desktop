"""Python exporters must be byte-identical to Ax-Easy Lyricist 1.1.0 formats.js."""
import json, os, random, shutil, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
from lyricist_sync import formats as F  # noqa: E402

TEXTS = ['Think of us as a passing season?', 'Καλησπέρα κόσμε', 'Ο ήλιος ανατέλλει 🌅', 'Tom & Jerry <live> "x" \'y\'',
         'שלום עולם', 'Paper lanterns on a quiet river.', 'Σ’ αγαπώ', '   padded   ', '', 'bad\u0001char']


def cases():
    rnd = random.Random(7)
    out = []
    for n in range(60):
        k = rnd.randint(0, 12)
        lines = []
        for i in range(k):
            l = {'text': rnd.choice(TEXTS), 'time': round(rnd.uniform(0, 400), rnd.choice([2, 3, 6]))}
            if rnd.random() < 0.15:
                l['time'] = None
            lines.append(l)
        meta = {'ti': rnd.choice(['Paper Kites', 'Ήλιος', '', 'A]b\nc']), 'ar': rnd.choice(['The Example Band', '', 'Χαρταετοί']),
                'al': rnd.choice(['Demos', '']), 'lang': rnd.choice(['', 'eng', 'ell', 'deu', 'xx'])}
        info = {'filename': rnd.choice(['01 paper kites.mp3', 'Τραγούδι.flac', 'con.wav', '']),
                'title': rnd.choice(['', 'Paper Kites', 'The Example Band - Paper Kites', 'Ήλιος: "Νέο"?']),
                'artist': rnd.choice(['', 'The Example Band', 'Χαρταετοί'])}
        out.append({'lines': lines, 'meta': meta, 'duration': rnd.choice([None, 129.41, 10.0]), 'info': info,
                    'times': [rnd.uniform(0, 4000) for _ in range(20)] + [0.005, 0.015, 1.0049999, 59.995, 3599.9995],
                    'parse': ['1:02.5', '01:02:03,250', '12', '12.', 'x', '', '3:4:5.6', '1:2:3:4']})
    return out


class TestFormats(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_identical_to_plugin(self):
        cs = cases()
        ref = json.loads(subprocess.run(['node', os.path.join(HERE, 'reference', 'run_formats.js')], input=json.dumps(cs),
                                        capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        for c, r in zip(cs, ref):
            for fmt in ('lrc', 'srt', 'vtt', 'ttml'):
                self.assertEqual(F.build(fmt, c['lines'], c['meta'], c['duration']), r[fmt], fmt)
            self.assertEqual(F.build_base_name(c['info']), r['base'])
            self.assertEqual([[F.fmt_lrc_time(x), F.fmt_srt_time(x), F.fmt_ttml_time(x)] for x in c['times']], r['t'])
            self.assertEqual([F.parse_time(x) for x in c['parse']], r['p'])

    def test_explicit_end_capped(self):
        lines = [{'text': 'a', 'time': 1.0, 'end': 5.0}, {'text': 'b', 'time': 3.0, 'end': 3.5}]
        cues = F.build_cues(lines, 10)
        self.assertEqual([(c['start'], c['end']) for c in cues], [(1.0, 3.0), (3.0, 3.5)])

    def test_greek_filename_and_bom(self):
        self.assertEqual(F.build_base_name({'title': 'Ήλιος: "Νέο"?', 'artist': 'Χαρταετοί'}), 'Χαρταετοί - Ήλιος Νέο')
        self.assertEqual(F.encode_file('x', True), b'\xef\xbb\xbfx')
        self.assertEqual(F.decode_text('Καλημέρα'.encode('cp1253'))[0], 'Καλημέρα')


if __name__ == '__main__':
    unittest.main()
