"""1.4.0 lyrics clean-up (made-up lines only)."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
from lyricist_sync.lyrics import clean_line, clean_lyrics, split_lines  # noqa: E402


class Cleanup(unittest.TestCase):
    def test_example(self):
        raw = ('[Intro]\n\n\n[Verse 1]\npaper kites above the harbour,\nwe trace the light along the lane.\n\n\n\n'
               '(Chorus)\nhold the line [x2], hold the line tonight!\nwait for me...\n"every word will find its time."\n'
               '\n[Bridge]\n\n¿quién sabe?\nκαλησπέρα φεγγάρι,\nό,τι κι αν πεις.\n(ooh, the night)\n\n\n')
        self.assertEqual(clean_lyrics(raw),
                         'Paper kites above the harbour\nWe trace the light along the lane\n\n'
                         'Hold the line, hold the line tonight!\nWait for me...\n"Every word will find its time"\n\n'
                         '¿Quién sabe?\nΚαλησπέρα φεγγάρι\nΌ,τι κι αν πεις\n(Ooh, the night)')

    def test_line_rules(self):
        self.assertEqual(clean_line('silent signals crossing over.'), 'Silent signals crossing over')
        self.assertEqual(clean_line('morning comes a little closer…'), 'Morning comes a little closer…')
        self.assertEqual(clean_line('is it you?'), 'Is it you?')
        self.assertEqual(clean_line("'glass towers,'"), "'Glass towers'")
        self.assertEqual(clean_line('«ήλιος.»'), '«Ήλιος»')
        self.assertEqual(clean_line('ωραία'), 'Ωραία')
        self.assertEqual(clean_line('élan vital'), 'Élan vital')
        self.assertEqual(clean_line('  [Hook]  every step  '), 'Every step')
        self.assertEqual(clean_line('3 a.m. again.'), '3 a.m. again')
        self.assertEqual(clean_line('ßtraße'), 'Sstraße')

    def test_sections(self):
        for tag in ('[Chorus]', '[Verse 2]', '(Chorus)', '(Pre-Chorus)', '{Intro}', '[Ρεφρέν]', '(x2)', '(Ρεφρέν)',
                    '[Instrumental break]'):
            self.assertEqual(clean_lyrics('one line\n%s\ntwo line' % tag), 'One line\nTwo line', tag)
        self.assertEqual(clean_lyrics('(ooh, the night)'), '(Ooh, the night)')   # sung ad-libs stay

    def test_idempotent_and_lines(self):
        t = clean_lyrics('a.\n\n[Chorus]\n\nb,\nc')
        self.assertEqual(t, 'A\n\nB\nC')
        self.assertEqual(clean_lyrics(t), t)
        self.assertEqual(split_lines(t), ['A', 'B', 'C'])
        self.assertEqual(clean_lyrics(''), '')


if __name__ == '__main__':
    unittest.main()
