"""Check the CLI --transcribe report of the e2e job (Whisper on CPU) against the fixtures' known text
and line times, and that the follow-up Auto-sync reused the cached analysis.

  python tests/check_transcribe.py transcribe.json [more.json ...] [--expect N] [--after-sync e2e-after.json]"""
import json, os, sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'engine'))
import eval_transcribe as EV  # noqa: E402

# Limits for Whisper small on CPU on the synthesized demo songs (measured on the box: demo_en WER 0.04 with the
# language detected; demo_el - a robotic synthesized Greek voice that small cannot place - WER 0.78 with the
# Language box set to Greek, so the Greek check is mainly: Greek script out, lines timed, nothing invented).
LIMITS = {'demo_en': {'lang': 'en', 'wer': 0.2, 'start': 0.3},
          'demo_el': {'lang': 'el', 'wer': 0.95, 'start': 0.3, 'script': 'greek'}}
argv = sys.argv
files = []
for x in argv[1:]:
    if x.startswith('--'):
        break
    files.append(x)
rep = [r for f in files for r in json.load(open(f, encoding='utf-8'))]
expect = int(argv[argv.index('--expect') + 1]) if '--expect' in argv else len(LIMITS)
ok = len(rep) == expect
for r in rep:
    name = os.path.splitext(r['audio'].replace('\\', '/').split('/')[-1])[0]
    truth = json.load(open(os.path.join(HERE, 'fixtures', name + '.truth.json'), encoding='utf-8'))['lines']
    res = r['result']
    sung = dict(res, lines=[l for l in res['lines'] if not l.get('inst')])
    ev = EV.evaluate(sung, truth)
    lim = LIMITS.get(name, {'lang': None, 'wer': 0.6, 'start': 0.6})
    words_ok = all(len(w) == 4 and 0 <= w[3] <= 1 for l in sung['lines'] for w in l['words'])
    mono = all(a['start'] < b['start'] and a['end'] <= b['start'] + 1e-6 for a, b in zip(sung['lines'], sung['lines'][1:]))
    first_ok = sung['lines'] and sung['lines'][0]['start'] >= truth[0]['start'] - 1.0   # nothing invented in the intro
    tfile = [f for f in r['files'] if f.endswith('.transcript.txt')]
    script_ok = lim.get('script') != 'greek' or all(any('\u0370' <= c <= '\u03ff' or '\u1f00' <= c <= '\u1fff' for c in l['text'])
                                                    for l in sung['lines'])
    good = (ev['wer'] <= lim['wer'] and (lim['lang'] is None or res['language'] == lim['lang']) and words_ok and mono
            and first_ok and ev.get('start_median', 9) <= lim['start'] and res.get('whisper') == 'small' and bool(tfile)
            and res['device'] == 'cpu' and script_ok and len(sung['lines']) >= len(truth) - 1)
    ok &= bool(good)
    print('%s: Whisper %s on %s, language %s, %d lines (truth %d), WER %.3f (limit %.2f), line starts: median %.3f s, '
          'within 0.3 s %s/%s, max %.3f s; amber lines %d; dropped %d; %.1f s -> %s' % (
              name, res.get('whisper'), res['device'], res['language'], len(sung['lines']), len(truth), ev['wer'], lim['wer'],
              ev.get('start_median', -1), ev.get('start_within_0_3'), ev.get('start_found'), ev.get('start_max', -1),
              res.get('low_conf', 0), len(res.get('dropped') or []), res['timings'].get('total', 0), 'PASS' if good else 'FAIL'))
    for l in sung['lines']:
        print('   %6.2f  %.2f  %s%s' % (l['start'], l['conf'], l['text'], '   [unsure: %s]' % ', '.join(
            w[0] for w in l['words'] if w[3] < 0.45) if any(w[3] < 0.45 for w in l['words']) else ''))
if '--after-sync' in argv:
    for r in json.load(open(argv[argv.index('--after-sync') + 1], encoding='utf-8')):
        res = r['result']
        cached = bool(res.get('cached')) and 'separate' not in res['timings']
        ok &= cached
        print('Auto-sync after Transcribe (%s): cached analysis reused: %s, %.1f s' % (
            os.path.basename(r['audio']), cached, res['timings']['total']))
sys.exit(0 if ok else 1)
