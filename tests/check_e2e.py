"""Check the CLI --report of the e2e job against the fixtures' known line times.

  python tests/check_e2e.py e2e.json [--expect N]"""
import json, os, sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # Greek file names on a cp1252 console
HERE = os.path.dirname(os.path.abspath(__file__))
rep = json.load(open(sys.argv[1], encoding='utf-8'))
expect = int(sys.argv[sys.argv.index('--expect') + 1]) if '--expect' in sys.argv else 2
ok = True


def truth_of(name):
    for sub in ('fixtures', 'hard'):
        p = os.path.join(HERE, sub, name + '.truth.json')
        if os.path.exists(p):
            return json.load(open(p, encoding='utf-8'))['lines']
    raise SystemExit('no truth for %s' % name)


for r in rep:
    name = os.path.splitext(r['audio'].replace('\\', '/').split('/')[-1])[0]
    truth = truth_of(name)
    res = r['result']
    L = [l for l in res['lines'] if not l.get('inst')]   # ♪ lines are not aligned lines
    A = sorted(res['lines'], key=lambda l: l['start'])
    inst = [l for l in res['lines'] if l.get('inst')]
    # every ♪ line sits in a gap: after the sung line before it ends, before the next one starts
    inst_ok = all((k == 0 or A[k - 1]['end'] <= l['start'] + 1e-3) and (k + 1 == len(A) or l['end'] <= A[k + 1]['start'] + 1e-3)
                  for k, l in enumerate(A) if l.get('inst'))
    errs = [abs(a['start'] - b['start']) for a, b in zip(L, truth)]
    order = [a['idx'] for a in L] == [b['line'] for b in truth]
    mono = all(L[k]['start'] < L[k + 1]['start'] and L[k]['end'] <= L[k + 1]['start'] + 1e-6 for k in range(len(L) - 1))
    first_ok = L[0]['start'] >= truth[0]['start'] - 0.3   # no line before the singing starts
    conf = all(isinstance(a.get('conf'), (int, float)) for a in L)
    lrc = [f for f in r['files'] if f.endswith('.lrc')]
    inst_exported = not inst or not lrc or all(l['text'] in open(lrc[0], encoding='utf-8-sig').read() for l in inst)
    good = order and mono and first_ok and conf and len(L) == len(truth) and max(errs) < 0.3 and inst_ok and inst_exported
    ok &= good
    low = [k + 1 for k, a in enumerate(L) if a.get('conf', 1) < 0.6]
    print('%s: %d/%d lines, order %s, monotonic %s, first line %.2f s (truth %.2f), max error %.3f s, mean %.3f s, '
          'low-confidence lines %s, %s, %.1f s total (%s) -> %s' % (
              name, len(L), len(truth), 'OK' if order else 'WRONG', 'OK' if mono else 'NO', L[0]['start'], truth[0]['start'],
              max(errs), sum(errs) / len(errs), low or 'none', res['timings'], res['timings']['total'], res['device'],
              'PASS' if good else 'FAIL'))
    print('   music lines: %s%s' % (', '.join('%s %.2f-%.2f' % (l.get('kind'), l['start'], l['end']) for l in inst) or 'none',
                             '' if inst_ok and inst_exported else ' -> BAD (overlap or missing from the LRC)'))
    print('   files:', ', '.join(os.path.basename(f) for f in r['files']))
sys.exit(0 if ok and len(rep) == expect else 1)
