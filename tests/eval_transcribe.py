"""Score a Transcribe result against known lyrics and line times.

  python tests/eval_transcribe.py RESULT.json --truth TRUTH.json [--lyrics LYRICS.txt]

TRUTH.json: {"lines": [{"text", "start", ...}]} = the lines as sung, in order (repeats included).
Prints/returns:
  wer        word error rate of the whole transcript vs the sung lines (normalized words)
  wer_text   WER vs the lyrics file as written (no repeats), when --lyrics is given
  start_*    line-start timing: every true line whose first word Whisper also heard (matched by a
             word-level alignment of the two texts) -> |Whisper start of that word - true start|;
             'line_start_*' does the same only where the transcript also STARTS a line there.
"""
import argparse, difflib, json, os, statistics, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'engine'))
import transcribe as TR  # noqa: E402


def evaluate(res, truth, lyrics_text=None):
    hyp_words = []           # (norm word, start, is_line_start)
    for l in res['lines']:
        for k, w in enumerate(l['words']):
            for j, n in enumerate(TR.norm(w[0])):
                hyp_words.append((n, w[1] if k or j else l['start'], k == 0 and j == 0))
    ref_words = []           # (norm word, line index, is first word)
    for i, l in enumerate(truth):
        for j, n in enumerate(TR.norm(l['text'])):
            ref_words.append((n, i, j == 0))
    hyp_text = ' '.join(l['text'] for l in res['lines'])
    ref_text = ' '.join(l['text'] for l in truth)
    out = {'lines': len(res['lines']), 'true_lines': len(truth)}
    out['wer'], out['errors'], out['ref_words'] = TR.wer(ref_text, hyp_text)
    if lyrics_text:
        out['wer_text'] = TR.wer(lyrics_text, hyp_text)[0]
    sm = difflib.SequenceMatcher(None, [w[0] for w in ref_words], [w[0] for w in hyp_words], autojunk=False)
    d_word, d_line = [], []
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            rw, hw = ref_words[a + k], hyp_words[b + k]
            if rw[2]:
                d = hw[1] - truth[rw[1]]['start']
                d_word.append(d)
                if hw[2]:
                    d_line.append(d)
    ab = [abs(x) for x in d_word]
    lb = [abs(x) for x in d_line]
    out['start_found'] = len(d_word)
    if ab:
        out.update(start_median=statistics.median(ab), start_mean_signed=statistics.mean(d_word), start_max=max(ab),
                   start_within_0_3=sum(x <= 0.3 for x in ab), start_within_0_5=sum(x <= 0.5 for x in ab))
    out['line_start_matched'] = len(lb)
    if lb:
        out.update(line_start_median=statistics.median(lb), line_start_within_0_3=sum(x <= 0.3 for x in lb),
                   line_start_within_0_5=sum(x <= 0.5 for x in lb), line_start_max=max(lb))
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('result')
    ap.add_argument('--truth', required=True)
    ap.add_argument('--lyrics')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--rebuild', action='store_true', help='re-run the filters and line building on the raw Whisper '
                    'segments saved in RESULT (engine CLI output) with the current engine/transcribe.py')
    ap.add_argument('--snap', action='store_true', help='with --rebuild: snap line starts to vocal onsets')
    a = ap.parse_args()
    res = json.load(open(a.result, encoding='utf-8'))
    if a.rebuild:
        kept, _d = TR.filter_segments(res['whisper_segments'], res['vocals'])
        res['lines'] = TR.build_lines(kept, res['vocals'])
        if a.snap:
            TR.snap_starts(res['lines'], res['vocals'])
    tr = json.load(open(a.truth, encoding='utf-8'))
    truth = tr['lines'] if isinstance(tr, dict) else tr
    truth = [l for l in truth if l.get('text') and not l.get('inst')]
    lyr = open(a.lyrics, encoding='utf-8-sig').read() if a.lyrics else None
    r = evaluate(res, truth, lyr)
    r['whisper'] = res.get('whisper')
    r['transcribe_s'] = res.get('timings', {}).get('transcribe')
    print(json.dumps(r, indent=1) if a.json else '  '.join('%s=%s' % (k, round(v, 3) if isinstance(v, float) else v) for k, v in r.items()))
