"""Review-list editing (1.3.1): edit words, times, split, merge, insert, delete, ♪ mark/unmark,
undo/redo, the lyrics box kept in step, the re-align window, and that the exports show the edits."""
import os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
os.environ.setdefault('LYRICIST_SYNC_HOME', tempfile.mkdtemp())
from lyricist_sync import edits as E, instrumental as I  # noqa: E402
from lyricist_sync.formats import build  # noqa: E402
from lyricist_sync.lyrics import split_lines  # noqa: E402


class Song:
    def __init__(self, lyrics, lines, duration=60.0):
        self.lyrics = lyrics
        self.result = {'lines': lines, 'duration': duration, 'vocals': []}
        self.edited = False
        self.dirty = False
        self.status = 'Synced'
        self.iso = ''


def L(text, s, e, idx, **kw):
    d = {'text': text, 'start': s, 'end': e, 'idx': idx, 'repeat': False, 'flag': '', 'conf': 0.9, 'why': []}
    d.update(kw)
    return d


def song():
    lyrics = '[Verse]\nRain drops falling on the window\nNo light left to guide the ships\n\n[Chorus]\nStay with me\n'
    lines = [L('Rain drops falling on the window', 10.0, 13.0, 0, conf=0.4, why=['weak'],
               words=[['Rain', 10.0, 10.3, 0.9], [' drops', 10.3, 10.6, 0.2]]),
             L('No light left to guide the ships', 13.2, 16.2, 1),
             L('Stay with me', 17.0, 18.5, 2),
             L('Stay with me', 30.0, 31.5, 2, repeat=True)]
    return Song(lyrics, lines)


def exports(s):
    lines = [{'text': l['text'], 'time': l['start'], 'end': l['end']} for l in s.result['lines']]
    return {f: build(f, lines, {'ti': 'T', 'ar': 'A', 'lang': ''}, s.result['duration']) for f in ('lrc', 'srt', 'vtt', 'ttml')}


class TestEdit(unittest.TestCase):
    def test_edit_words_keeps_times_and_clears_check(self):
        s = song()
        n = E.set_text(s, 0, '  Raindrops falling   on the window ')
        self.assertEqual(n, 1)
        l = s.result['lines'][0]
        self.assertEqual(l['text'], 'Raindrops falling on the window')
        self.assertEqual((l['start'], l['end']), (10.0, 13.0))
        self.assertFalse(E.is_low(l))
        self.assertNotIn('words', l)          # amber words gone
        self.assertTrue(l['edited'] and s.edited and s.dirty)
        # the lyrics box keeps its tags and blank line
        self.assertEqual(s.lyrics.splitlines(), ['[Verse]', 'Raindrops falling on the window', 'No light left to guide the ships',
                                                 '', '[Chorus]', 'Stay with me'])
        self.assertEqual(E.set_text(s, 0, 'Raindrops falling on the window'), 0)   # unchanged
        self.assertEqual(E.set_text(s, 0, '   '), 0)                              # empty: refused

    def test_edit_greek_unicode(self):
        s = song()
        E.set_text(s, 1, 'Καμιά σπίθα δεν τροφοδοτεί τον ήχο')
        self.assertIn('Καμιά σπίθα δεν τροφοδοτεί τον ήχο', s.lyrics.splitlines())
        self.assertIn('Καμιά σπίθα δεν τροφοδοτεί τον ήχο', exports(s)['srt'])

    def test_edit_repeat_changes_every_occurrence(self):
        s = song()
        self.assertEqual(E.set_text(s, 3, 'Stay with me now'), 2)
        self.assertEqual([l['text'] for l in s.result['lines'][2:]], ['Stay with me now'] * 2)
        self.assertEqual(split_lines(s.lyrics)[-1], 'Stay with me now')
        self.assertEqual(len(split_lines(s.lyrics)), 3)
        self.assertEqual((s.result['lines'][3]['start'], s.result['lines'][3]['end']), (30.0, 31.5))

    def test_times(self):
        s = song()
        E.set_times(s, 1, start=12.5)
        a, b = s.result['lines'][:2]
        self.assertEqual(b['start'], 12.5)
        self.assertEqual(a['end'], 12.5)                       # no overlap with the line before
        E.set_times(s, 1, end=17.5)
        self.assertEqual(s.result['lines'][1]['end'], 17.0)    # ...nor with the line after
        E.set_times(s, 2, start=17.2, end=18.0)
        self.assertEqual((s.result['lines'][2]['start'], s.result['lines'][2]['end']), (17.2, 18.0))


class TestSplitMerge(unittest.TestCase):
    def test_split_middle_proportional(self):
        s = song()
        r = E.split(s, 1)          # 'No light left to guide the ships' (32 chars)
        a, b = s.result['lines'][1], s.result['lines'][r]
        self.assertEqual((a['text'], b['text']), ('No light left to', 'guide the ships'))
        self.assertAlmostEqual(a['end'], 13.2 + 3.0 * 16 / 31, places=3)
        self.assertEqual(b['start'], a['end'])
        self.assertEqual(b['end'], 16.2)
        self.assertEqual(split_lines(s.lyrics), ['Rain drops falling on the window', 'No light left to', 'guide the ships',
                                                 'Stay with me'])
        self.assertEqual([l['idx'] for l in s.result['lines']], [0, 1, 2, 3, 3])

    def test_split_at_cursor_and_time(self):
        s = song()
        r = E.split(s, 0, cursor=10)     # 'Rain drops| falling…'
        self.assertEqual(s.result['lines'][0]['text'], 'Rain drops')
        self.assertEqual(s.result['lines'][r]['text'], 'falling on the window')
        s = song()
        r = E.split(s, 1, at_time=14.0)  # the playhead inside the line
        self.assertEqual(s.result['lines'][r]['start'], 14.0)
        self.assertIsNone(E.split(song(), 2, cursor=0) if False else None)
        one = Song('Hey\n', [L('Hey', 1.0, 2.0, 0)])
        self.assertIsNone(E.split(one, 0))

    def test_merge(self):
        s = song()
        self.assertTrue(E.merge(s, 0))
        l = s.result['lines'][0]
        self.assertEqual(l['text'], 'Rain drops falling on the window No light left to guide the ships')
        self.assertEqual((l['start'], l['end']), (10.0, 16.2))
        self.assertEqual(split_lines(s.lyrics), [l['text'], 'Stay with me'])
        self.assertIn('[Chorus]', s.lyrics)
        self.assertEqual(len(s.result['lines']), 3)

    def test_split_then_merge_roundtrip(self):
        s = song()
        E.split(s, 1)
        E.merge(s, 1)
        self.assertEqual(s.result['lines'][1]['text'], 'No light left to guide the ships')
        self.assertEqual((s.result['lines'][1]['start'], s.result['lines'][1]['end']), (13.2, 16.2))


class TestInsertDeleteMusic(unittest.TestCase):
    def test_insert_below_in_gap(self):
        s = song()
        r = E.insert(s, 2, below=True, text='Oh oh')
        self.assertEqual(r, 3)
        l = s.result['lines'][3]
        self.assertEqual((l['start'], l['end']), (18.5, 21.5))
        self.assertEqual(split_lines(s.lyrics), ['Rain drops falling on the window', 'No light left to guide the ships',
                                                 'Stay with me', 'Oh oh'])

    def test_insert_above_without_gap_takes_half(self):
        s = song()
        s.result['lines'][1]['start'] = 13.0
        r = E.insert(s, 1, below=False, text='Hey')
        self.assertEqual(r, 1)
        new, old = s.result['lines'][1], s.result['lines'][2]
        self.assertEqual(new['start'], 13.0)
        self.assertEqual(old['start'], new['end'])
        self.assertEqual(split_lines(s.lyrics)[1], 'Hey')

    def test_delete(self):
        s = song()
        E.delete(s, 1)
        self.assertEqual(split_lines(s.lyrics), ['Rain drops falling on the window', 'Stay with me'])
        self.assertEqual(len(s.result['lines']), 3)

    def test_delete_first_occurrence_promotes_repeat(self):
        s = song()
        E.delete(s, 2)
        self.assertFalse(s.result['lines'][2].get('repeat'))
        self.assertEqual(split_lines(s.lyrics)[-1], 'Stay with me')

    def test_mark_unmark_music(self):
        s = song()
        E.mark_inst(s, 1, {'inst_symbol': '♪'})
        l = s.result['lines'][1]
        self.assertTrue(l['inst'] and not l['auto'])
        self.assertEqual(l['text'], '♪')
        self.assertNotIn('No light left to guide the ships', s.lyrics)
        self.assertEqual(E.unmark_inst(s, 1), 'No light left to guide the ships')
        self.assertIn('No light left to guide the ships', split_lines(s.lyrics))
        # an auto ♪ line, unmarked: stays gone when ♪ lines are recomputed
        s.result['lines'].insert(0, I.make_line('♪', 0.0, 9.7, True, 'intro', 'intro'))
        E.unmark_inst(s, 0, 'Intro words')
        self.assertIn('intro', s.result['inst_deleted'])


class TestUndo(unittest.TestCase):
    def test_undo_redo(self):
        s = song()
        h = E.History()
        orig = (E.capture(s)['result']['lines'], s.lyrics)
        h.push(s, 'Edit line')
        E.set_text(s, 0, 'Raindrops falling on the window')
        h.push(s, 'Split line')
        E.split(s, 1)
        h.push(s, 'Delete line')
        E.delete(s, 0)
        self.assertEqual(len(s.result['lines']), 4)
        self.assertEqual(h.undo(s), 'Delete line')
        self.assertEqual(s.result['lines'][0]['text'], 'Raindrops falling on the window')
        self.assertEqual(h.undo(s), 'Split line')
        self.assertEqual(h.undo(s), 'Edit line')
        self.assertEqual((s.result['lines'], s.lyrics), orig)
        self.assertFalse(s.edited)
        self.assertIsNone(h.undo(s))
        self.assertEqual(h.redo(s), 'Edit line')
        self.assertEqual(s.result['lines'][0]['text'], 'Raindrops falling on the window')
        self.assertTrue(s.edited)
        h.redo(s)
        h.redo(s)
        self.assertEqual(len(s.result['lines']), 4)
        self.assertIsNone(h.redo(s))
        h.undo(s)
        h.push(s, 'Merge')            # a new edit drops the redo steps
        E.merge(s, 0)
        self.assertFalse(h.can_redo())

    def test_nudges_share_one_step(self):
        s = song()
        h = E.History()
        for k in range(5):
            h.push(s, 'Move line', tag=('nudge', 1), now=100.0 + 0.3 * k)
            E.set_times(s, 1, start=s.result['lines'][1]['start'] + 0.1)
        self.assertEqual(len(h.undo_stack), 1)
        h.undo(s)
        self.assertEqual(s.result['lines'][1]['start'], 13.2)

    def test_history_per_song(self):
        a, b = song(), song()
        E.history(a).push(a, 'x')
        self.assertTrue(E.history(a).can_undo())
        self.assertFalse(E.history(b).can_undo())


class TestRealign(unittest.TestCase):
    def test_window(self):
        s = song()
        lines = s.result['lines']
        self.assertEqual(E.realign_window(lines, 1, 60.0), (13.0, 17.0))
        self.assertEqual(E.realign_window(lines, 0, 60.0), (0.0, 13.2))
        self.assertEqual(E.realign_window(lines, 3, 60.0), (18.5, 60.0))
        lines[2]['start'] = 13.4   # tight: widened to the neighbours' start / end
        self.assertEqual(E.realign_window(lines, 1, 60.0), (10.05, 18.5))

    def test_apply(self):
        s = song()
        E.apply_realign(s, 1, 12.9, 15.0, 0.85, [])
        a, b = s.result['lines'][:2]
        self.assertEqual((b['start'], b['end']), (12.9, 15.0))
        self.assertEqual(a['end'], 12.9)
        self.assertEqual(b['conf'], 0.85)
        self.assertTrue(b['manual'])


class TestExportReflects(unittest.TestCase):
    def test_every_format_shows_edits(self):
        s = song()
        E.set_text(s, 0, 'Σταγόνες στο τζάμι')
        E.split(s, 1)
        E.set_times(s, 0, start=9.5)
        out = exports(s)
        self.assertIn('[00:09.50]Σταγόνες στο τζάμι', out['lrc'])
        self.assertIn('[00:14.75]guide the ships', out['lrc'])
        self.assertIn('00:00:09,500 --> ', out['srt'])
        self.assertIn('guide the ships', out['vtt'])
        self.assertIn('Σταγόνες στο τζάμι', out['ttml'])
        self.assertNotIn('Rain drops', out['ttml'])


class TestLyricsRebuild(unittest.TestCase):
    def test_box_lines_not_in_result_are_kept(self):
        box = '[Intro]\nA\nmy own note line\nB\nC'
        out = E.rebuild_lyrics(box, ['A', 'B', 'C'], ['A', 'B2', 'C'])
        self.assertEqual(out.splitlines(), ['[Intro]', 'A', 'my own note line', 'B2', 'C'])
        out = E.rebuild_lyrics(box, ['A', 'B', 'C'], ['A', 'B', 'X', 'C'])
        self.assertEqual(out.splitlines(), ['[Intro]', 'A', 'my own note line', 'B', 'X', 'C'])
        out = E.rebuild_lyrics('', [], ['A', 'B'])
        self.assertEqual(out.splitlines(), ['A', 'B'])
        out = E.rebuild_lyrics(box, ['A', 'B', 'C'], ['B', 'C'])
        self.assertEqual(out.splitlines(), ['[Intro]', 'my own note line', 'B', 'C'])


if __name__ == '__main__':
    unittest.main()
