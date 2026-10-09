"""Transcribe mode without Whisper: hallucination filters, line building, confidence, WER and the
evaluation used for the Stoned / demo numbers. Pure Python (the e2e job runs the real model)."""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'engine'))
sys.path.insert(0, HERE)
import transcribe as TR  # noqa: E402


def seg(start, words, gap=0.05, dur=0.3, p=0.9, **kw):
    """A fake Whisper segment from 'word word …' (each word dur s, gap s apart)."""
    ws, t = [], start
    for w in words.split():
        pp = p
        if w.endswith('?'):
            w, pp = w[:-1], 0.2      # 'word?' = unsure word
        ws.append({'word': ' ' + w, 'start': t, 'end': t + dur, 'probability': pp})
        t += dur + gap
    d = {'start': start, 'end': ws[-1]['end'], 'text': ' ' + ' '.join(w['word'].strip() for w in ws), 'words': ws,
         'avg_logprob': -0.2, 'no_speech_prob': 0.05, 'compression_ratio': 1.3}
    d.update(kw)
    return d


VOC = [(0.0, 300.0)]


class TestFilters(unittest.TestCase):
    def test_filler_and_credits(self):
        for t in ('Thank you for watching!', 'Subtitles by the Amara.org community', 'Υπότιτλοι AUTHORWAVE',
                  '♪♪', '...', 'Hmmmmm Mmmmmm', 'mm hmm', '[Music]', 'I...', ' I... I...', 'Ah…'):
            self.assertTrue(TR.is_filler(t), t)
        for t in ('Thank you, my love', 'Remember us as a system failure', 'Καλησπέρα κόσμε', 'Oh oh oh', 'La la la', 'I... I love you', 'I know'):
            self.assertFalse(TR.is_filler(t), t)

    def test_drop_in_silence_and_no_speech(self):
        segs = [seg(10, 'we broke the code'), seg(40, 'thank you'), seg(60, 'something here', no_speech_prob=0.9, avg_logprob=-1.2),
                seg(70, 'la la la la la la', compression_ratio=3.1), seg(80, 'still here')]
        kept, dropped = TR.filter_segments(segs, [(9.5, 12.0), (59.0, 62.0), (69.0, 82.0)])
        self.assertEqual([s['text'].strip() for s in kept], ['we broke the code', 'still here'])
        reasons = [r for _s, r in dropped]
        self.assertIn('no vocals under it', reasons)
        self.assertTrue(any(r.startswith('no speech') for r in reasons))
        self.assertTrue(any(r.startswith('repetitive') for r in reasons))

    def test_gibberish_dropped(self):
        segs = [seg(0.0, 'gym?', avg_logprob=-3.1), seg(22.0, 'can? you? hear? me?', avg_logprob=-0.9),
                seg(27.0, 'remember us as a system failure', avg_logprob=-0.4)]
        kept, dropped = TR.filter_segments(segs, VOC)
        self.assertEqual([s['text'].strip() for s in kept], ['remember us as a system failure'])
        self.assertTrue(all(r.startswith('gibberish') for _s, r in dropped))

    def test_loop_dropped_chorus_kept(self):
        segs = [seg(10 + 3 * k, 'stay with me') for k in range(8)]
        kept, dropped = TR.filter_segments(segs, VOC)
        self.assertEqual(len(kept), 4)          # a line sung a few times in a row is fine
        self.assertEqual(len(dropped), 4)       # Whisper looping on it is not
        chorus = [seg(10, 'stay with me'), seg(13, 'stay with me'), seg(16, 'another line'), seg(19, 'stay with me')]
        self.assertEqual(len(TR.filter_segments(chorus, VOC)[0]), 4)


class TestLines(unittest.TestCase):
    def test_segments_and_pauses(self):
        segs = [seg(1.0, 'remember us as a system failure'), seg(4.0, 'signal loss in a dying layer'),
                seg(8.0, 'we broke the code'), seg(9.6, 'corrupt and heavy')]   # pause 0.3 s, no punctuation
        lines = TR.build_lines(segs, VOC)
        self.assertEqual([l['text'] for l in lines][:2], ['Remember us as a system failure', 'Signal loss in a dying layer'])
        self.assertAlmostEqual(lines[0]['start'], 1.0)
        self.assertAlmostEqual(lines[1]['start'], 4.0)
        for l in lines:
            self.assertLessEqual(len(l['text']), TR.MAX_CHARS + 8)

    def test_long_segment_split_at_pause(self):
        s = seg(0.0, 'we traced the logs for someone to blame')
        tail = seg(s['end'] + 0.9, 'but in the backend just dead concrete')
        s['words'] += tail['words']
        s['text'] += tail['text']
        s['end'] = tail['end']
        lines = TR.build_lines([s], VOC)
        self.assertEqual([l['text'] for l in lines], ['We traced the logs for someone to blame', 'But in the backend just dead concrete'])
        self.assertAlmostEqual(lines[1]['start'], tail['start'], places=2)

    def test_max_chars(self):
        s = seg(0.0, 'this is a very long line that keeps going and going without any pause at all until the end')
        lines = TR.build_lines([s], VOC)
        self.assertGreater(len(lines), 1)
        for l in lines:
            self.assertLessEqual(len(l['text']), TR.MAX_CHARS + 8, l['text'])
            self.assertGreaterEqual(len(l['text'].split()), 2)

    def test_first_word_of_next_line_moves(self):
        """Whisper ended a segment with the first word of the next line: '…the sound You | killed your…'."""
        segs = [seg(0.0, 'No spark left to power the sound You'), seg(3.0, 'killed your drive with feedback cries')]
        texts = [l['text'] for l in TR.build_lines(segs, VOC)]
        self.assertEqual(texts, ['No spark left to power the sound', 'You killed your drive with feedback cries'])

    def test_confidence_and_amber_words(self):
        segs = [seg(0.0, 'clear words here now'), seg(3.0, 'mumbled? words? here maybe?')]
        lines = TR.build_lines(segs, VOC)
        self.assertGreaterEqual(lines[0]['conf'], TR.LOW_LINE)
        self.assertLess(lines[1]['conf'], TR.LOW_LINE)
        low = [w[0] for w in lines[1]['words'] if w[3] < TR.LOW_WORD]
        self.assertEqual(low, ['mumbled', 'words', 'maybe'])
        self.assertTrue(any('unsure words' in y for y in lines[1]['why']))
        for l in lines:   # every word: [text, start, end, probability]
            for w in l['words']:
                self.assertEqual(len(w), 4)
                self.assertLessEqual(w[1], w[2])

    def test_word_pieces_joined(self):
        s = seg(0.0, 'projected streams on steel')
        s['words'].append({'word': '-cold', 'start': 1.5, 'end': 1.8, 'probability': 0.9})
        s['words'].append({'word': ' mountains', 'start': 1.8, 'end': 2.3, 'probability': 0.9})
        self.assertEqual(TR.build_lines([s], VOC)[0]['text'], 'Projected streams on steel-cold mountains')

    def test_greek(self):
        segs = [seg(4.0, 'Καλησπέρα κόσμε'), seg(6.3, 'Ο ήλιος ανατέλλει πάλι')]
        lines = TR.build_lines(segs, VOC)
        self.assertEqual([l['text'] for l in lines], ['Καλησπέρα κόσμε', 'Ο ήλιος ανατέλλει πάλι'])

    def test_monotonic(self):
        segs = [seg(5.0, 'one two three'), seg(4.9, 'four five six')]
        lines = TR.build_lines(segs, VOC)
        for a, b in zip(lines, lines[1:]):
            self.assertLess(a['start'], b['start'])
            self.assertLessEqual(a['end'], b['start'])


class TestScoring(unittest.TestCase):
    def test_wer(self):
        self.assertEqual(TR.wer('a b c d', 'a b c d')[0], 0.0)
        self.assertAlmostEqual(TR.wer('a b c d', 'a x c')[0], 0.5)          # 1 sub + 1 del
        self.assertEqual(TR.wer("You hit escape and I’m still free.", "you hit escape and i'm still free")[0], 0.0)
        self.assertEqual(TR.wer('Σ’ αγαπώ σαν τρελός', 'σ αγαπω σαν τρελος')[0], 0.0)

    def test_eval(self):
        import eval_transcribe as ev
        truth = [{'text': 'We broke the code', 'start': 10.0}, {'text': 'We pulled the plug', 'start': 13.0}]
        res = {'lines': [l for l in TR.build_lines([seg(10.1, 'we broke the code'), seg(12.8, 'we pulled the plug')], VOC)]}
        r = ev.evaluate(res, truth)
        self.assertEqual(r['wer'], 0.0)
        self.assertEqual(r['start_found'], 2)
        self.assertAlmostEqual(r['start_median'], 0.15, places=2)
        self.assertEqual(r['line_start_matched'], 2)


if __name__ == '__main__':
    unittest.main()
