"""Engine result vs the known line times of a synthesized fixture."""
import json, sys
res, truth = json.load(open(sys.argv[1], encoding='utf-8')), json.load(open(sys.argv[2], encoding='utf-8'))
print('timings', res['timings'], 'lang', res['language'], 'repeats', res['repeats'])
ok = len(res['lines']) == len(truth['lines'])
errs = []
for a, b in zip(res['lines'], truth['lines']):
    d = a['start'] - b['start']; errs.append(abs(d))
    same = a['idx'] == b['line']
    ok &= same
    print(f"{a['start']:7.2f} truth {b['start']:7.2f} d={d:+.2f} end {a['end']:6.2f}/{b['end']:6.2f} {'R' if a['repeat'] else ' '} {'' if same else 'ORDER! '}{a['text']}")
print('lines %d/%d, max |d| %.2f s, mean %.2f s -> %s' % (len(res['lines']), len(truth['lines']), max(errs), sum(errs) / len(errs), 'PASS' if ok and max(errs) < 0.3 else 'FAIL'))
sys.exit(0 if ok and max(errs) < 0.3 else 1)
