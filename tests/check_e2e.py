"""Check the CLI --report of the e2e job against the fixtures' known line times."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
rep = json.load(open(sys.argv[1], encoding='utf-8'))
ok = True
for r in rep:
    name = os.path.splitext(os.path.basename(r['audio']))[0]
    truth = json.load(open(os.path.join(HERE, 'fixtures', name + '.truth.json'), encoding='utf-8'))['lines']
    res = r['result']
    errs = [abs(a['start'] - b['start']) for a, b in zip(res['lines'], truth)]
    order = [a['idx'] for a in res['lines']] == [b['line'] for b in truth]
    good = order and len(res['lines']) == len(truth) and max(errs) < 0.3
    ok &= good
    print('%s: %d/%d lines, order %s, max error %.3f s, mean %.3f s, %s, %.1f s total (%s) -> %s' % (
        name, len(res['lines']), len(truth), 'OK' if order else 'WRONG', max(errs), sum(errs) / len(errs),
        res['timings'], res['timings']['total'], res['device'], 'PASS' if good else 'FAIL'))
    print('   files:', ', '.join(os.path.basename(f) for f in r['files']))
sys.exit(0 if ok and len(rep) == 2 else 1)
