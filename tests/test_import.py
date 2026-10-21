"""1.4.0 import of .srt / .vtt / .lrc / .ttml (made-up lines only)."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
from lyricist_sync import importers as I, formats as F  # noqa: E402

SRT = """1
00:00:01,000 --> 00:00:03,500
<i>Paper lanterns</i> on the
quiet river

2
00:00:04,000 --> 00:00:06,250
{\\an8}Καλησπέρα, φεγγάρι &amp; αστέρια

3
00:00:07,000 --> 00:00:08,000

"""

VTT = """WEBVTT - made-up demo

NOTE this is a comment
spanning two lines

STYLE
::cue { color: yellow }

intro
00:01.000 --> 00:03.500 align:start position:10% line:0
<v Singer>Glass towers <c.loud>glowing</c> in the rain</v>

00:00:04.000 --> 00:00:06.000
We trace the <00:00:05.000>light along the lane
"""

LRC = """[ti:Glass Towers]
[ar:The Example Band]
[offset:+500]
[00:01.50][00:20.50]Hold the line, hold the line tonight
[00:04.00]Every <00:04.50>word will find its time
[00:06:25]Ο ήλιος ανατέλλει
[00:08.000]
[00:10]Silent signals crossing over
"""

TTML = """<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttp="http://www.w3.org/ns/ttml#parameter"
    ttp:tickRate="10000000" ttp:frameRate="25" xml:lang="en">
 <head><metadata><title>not a line</title></metadata></head>
 <body><div begin="10s">
  <p begin="00:00:01.000" end="00:00:02.500">Morning comes<br/>a little closer</p>
  <p begin="30000000t" dur="1.5s"><span>Paper</span> <span>kites</span></p>
  <p begin="00:00:05:12" end="00:00:06:00">Χαρταετοί στον ουρανό</p>
  <p><span begin="7s" end="7.5s">Every</span> <span begin="7.5s" end="8.25s">step</span></p>
  <p begin="9000ms">Last line without an end</p>
 </div></body></tt>"""


class Import(unittest.TestCase):
    def test_srt(self):
        r = I.parse_bytes(SRT.encode('utf-8'), '.srt')
        L = r['lines']
        self.assertEqual(len(L), 2)                       # the empty cue is dropped
        self.assertEqual(L[0], {'start': 1.0, 'end': 3.5, 'text': 'Paper lanterns on the quiet river'})
        self.assertEqual(L[1]['text'], 'Καλησπέρα, φεγγάρι & αστέρια')
        self.assertEqual(L[1]['end'], 6.25)

    def test_encodings(self):
        for enc, data in (('utf-8-sig', b'\xef\xbb\xbf' + SRT.encode('utf-8')),
                          ('utf-16le', b'\xff\xfe' + SRT.encode('utf-16-le')),
                          ('utf-16be', b'\xfe\xff' + SRT.encode('utf-16-be')),
                          ('utf-16-le', SRT.encode('utf-16-le')),
                          ('windows-1253', SRT.encode('cp1253'))):
            r = I.parse_bytes(data, '.srt')
            self.assertEqual(r['encoding'], enc)
            self.assertEqual(r['lines'][1]['text'], 'Καλησπέρα, φεγγάρι & αστέρια', enc)

    def test_vtt(self):
        L = I.parse_bytes(VTT.encode(), '.vtt')['lines']
        self.assertEqual([l['text'] for l in L], ['Glass towers glowing in the rain', 'We trace the light along the lane'])
        self.assertEqual((L[0]['start'], L[0]['end']), (1.0, 3.5))

    def test_lrc(self):
        r = I.parse_bytes(LRC.encode(), '.lrc')
        L = r['lines']
        self.assertEqual(r['meta']['ar'], 'The Example Band')
        self.assertEqual([l['start'] for l in L], [1.0, 3.5, 5.75, 9.5, 20.0])   # offset +500 ms = 0.5 s earlier
        self.assertEqual(L[0]['text'], 'Hold the line, hold the line tonight')
        self.assertEqual(L[4]['text'], L[0]['text'])                              # two stamps on one line
        self.assertEqual(L[1]['text'], 'Every word will find its time')
        self.assertEqual(L[0]['end'], 3.5)                                        # derived from the next line
        self.assertEqual(L[2]['end'], 7.5)                                        # the empty stamp ends it
        self.assertEqual(L[4]['end'], 20.0 + F.DEFAULT_LAST_CUE)

    def test_ttml(self):
        L = I.parse_bytes(TTML.encode(), '.ttml')['lines']
        self.assertEqual([l['text'] for l in L], ['Morning comes a little closer', 'Paper kites', 'Χαρταετοί στον ουρανό',
                                                  'Every step', 'Last line without an end'])
        self.assertEqual((L[0]['start'], L[0]['end']), (11.0, 12.5))     # div begin=10s adds up
        self.assertEqual((L[1]['start'], L[1]['end']), (13.0, 14.5))     # ticks + dur
        self.assertEqual((L[2]['start'], L[2]['end']), (15.48, 16.0))    # frames at 25 fps
        self.assertEqual((L[3]['start'], L[3]['end']), (17.0, 18.25))    # times from the spans
        self.assertEqual(L[4]['end'], 19.0 + F.DEFAULT_LAST_CUE)

    def test_roundtrip_own_exports(self):
        lines = [{'text': 'Paper lanterns', 'time': 1.0, 'end': 2.0}, {'text': 'Ήλιος & φεγγάρι', 'time': 3.25, 'end': 5.0}]
        for fmt in ('lrc', 'srt', 'vtt', 'ttml'):
            out = F.build(fmt, lines, {'ti': 'Demo', 'lang': 'ell'}, 6.0)
            L = I.parse_bytes(out.encode('utf-8'), '.' + fmt)['lines']
            self.assertEqual([l['text'] for l in L], ['Paper lanterns', 'Ήλιος & φεγγάρι'], fmt)
            self.assertEqual([l['start'] for l in L], [1.0, 3.25], fmt)

    def test_sniff_and_errors(self):
        self.assertEqual(I.parse_bytes(VTT.encode(), '.srt')['format'], 'vtt')
        self.assertEqual(I.parse_bytes(TTML.encode(), '.xml')['format'], 'ttml')
        with self.assertRaises(ValueError):
            I.parse_bytes(b'just some words', '.txt')
        with self.assertRaises(ValueError):
            I.parse_bytes(b'<tt><body>', '.ttml')

    def test_file(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'Δοκιμή.lrc')
        with open(p, 'wb') as f:
            f.write(LRC.encode('utf-8'))
        self.assertTrue(I.is_timed_file(p))
        self.assertEqual(len(I.parse_file(p)['lines']), 5)


if __name__ == '__main__':
    unittest.main()
