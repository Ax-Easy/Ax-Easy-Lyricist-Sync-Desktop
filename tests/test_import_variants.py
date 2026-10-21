"""Regression tests for the 1.4.0 SRT import bug (DistroKid / LyricPotato exports: no blank line between cues)
and other line-break / encoding variants. Made-up lines only."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
from lyricist_sync import importers as I  # noqa: E402
from lyricist_sync.lyrics import clean_lyrics  # noqa: E402

FIX = os.path.join(HERE, 'fixtures', 'distrokid')
TEXTS = ['Paper kites above the harbour,', 'We trace the light along the lane.', 'Καλησπέρα φεγγάρι,',
         '(hold the line)', '(hold the line)']
STARTS = [12.04, 14.5, 17.2, 20.105, 22.641]
ENDS = [14.32, 17.01, 19.88, 22.4, 24.009]
CUES = list(zip(['00:00:12,040', '00:00:14,500', '00:00:17,200', '00:00:20,105', '00:00:22,641'],
                ['00:00:14,320', '00:00:17,010', '00:00:19,880', '00:00:22,400', '00:00:24,009'], TEXTS))


def srt(sep='\n', blank=False, ms=','):
    out = ''
    for i, (a, b, t) in enumerate(CUES):
        out += '%d%s%s --> %s%s%s%s' % (i + 1, sep, a.replace(',', ms), b.replace(',', ms), sep, t, sep)
        if blank:
            out += sep
    return out


class Variants(unittest.TestCase):
    def check(self, r, fmt='srt'):
        self.assertEqual(r['format'], fmt)
        self.assertEqual([l['text'] for l in r['lines']], TEXTS)
        self.assertEqual([l['start'] for l in r['lines']], STARTS)
        self.assertEqual([l['end'] for l in r['lines']], ENDS)

    def test_distrokid_srt_fixture(self):           # LF, no blank lines between cues (the reported file)
        self.check(I.parse_file(os.path.join(FIX, 'made-up-distrokid.srt')))

    def test_distrokid_ttml_fixture(self):          # LyricPotato comment, default TTML namespace, p begin/end
        self.check(I.parse_file(os.path.join(FIX, 'made-up-distrokid.ttml')), 'ttml')

    def test_srt_equals_ttml(self):
        a = I.parse_file(os.path.join(FIX, 'made-up-distrokid.srt'))['lines']
        b = I.parse_file(os.path.join(FIX, 'made-up-distrokid.ttml'))['lines']
        self.assertEqual(a, b)

    def test_line_breaks(self):
        for sep in ('\n', '\r\n', '\r', '\u2028', '\u2029', '\x85'):
            for blank in (False, True):
                with self.subTest(sep=repr(sep), blank=blank):
                    self.check(I.parse_bytes(srt(sep, blank).encode('utf-8'), '.srt'))

    def test_single_line(self):
        self.check(I.parse_bytes(srt(' ').encode('utf-8'), '.srt'))

    def test_dot_ms(self):
        self.check(I.parse_bytes(srt(ms='.').encode('utf-8'), '.srt'))

    def test_utf16_without_bom(self):
        for enc in ('utf-16-le', 'utf-16-be'):
            for sep in ('\n', '\r\n'):
                with self.subTest(enc=enc, sep=repr(sep)):
                    self.check(I.parse_bytes(srt(sep).encode(enc), '.srt'))
        greek = '1\n00:00:01,000 --> 00:00:02,000\nΚαλησπέρα φεγγάρι μου ωραίο\n'
        self.assertEqual(I.parse_bytes(greek.encode('utf-16-le'), '.srt')['lines'][0]['text'],
                         'Καλησπέρα φεγγάρι μου ωραίο')

    def test_bom_and_wrong_extension(self):
        self.check(I.parse_bytes(b'\xef\xbb\xbf' + srt().encode('utf-8'), '.srt'))
        self.check(I.parse_bytes(srt().encode('utf-8'), '.txt'))

    def test_multiline_cue_and_index_like_text(self):
        t = '1\n00:00:01,000 --> 00:00:02,000\nCount to\n10\n\n2\n00:00:03,000 --> 00:00:04,000\nNext\n'
        lines = I.parse_bytes(t.encode(), '.srt')['lines']
        self.assertEqual([l['text'] for l in lines], ['Count to 10', 'Next'])   # only the line right before the time line is the index
        t = '1\n00:00:01,000 --> 00:00:02,000\nFirst half\nsecond half\n\n2\n00:00:03,000 --> 00:00:04,000\nNext\n'
        self.assertEqual([l['text'] for l in I.parse_bytes(t.encode(), '.srt')['lines']],
                         ['First half second half', 'Next'])

    def test_vtt_without_blank_lines_and_ids(self):
        t = 'WEBVTT\n\nNOTE made up\n\nc1\n00:12.040 --> 00:14.320 align:start\nPaper kites\n\nc2\n00:14.500 --> 00:17.010\nWe trace\n'
        r = I.parse_bytes(t.encode(), '.vtt')
        self.assertEqual([(l['start'], l['text']) for l in r['lines']], [(12.04, 'Paper kites'), (14.5, 'We trace')])
        t = 'WEBVTT\n00:00:12.040 --> 00:00:14.320\nPaper kites\n00:00:14.500 --> 00:00:17.010\nWe trace\n'
        self.assertEqual([l['text'] for l in I.parse_bytes(t.encode(), '.vtt')['lines']], ['Paper kites', 'We trace'])

    def test_cleanup_never_touches_timed_text(self):
        for t in (srt(), srt(' '), open(os.path.join(FIX, 'made-up-distrokid.ttml'), encoding='utf-8').read()):
            self.assertEqual(clean_lyrics(t), t)


if __name__ == '__main__':
    unittest.main()
