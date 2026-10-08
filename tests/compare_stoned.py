"""Compare an engine result JSON with the proven best_stoned run (mms_vocals_rep)."""
import json, statistics, sys
new = json.load(open(sys.argv[1]))
old = json.load(open(sys.argv[2] if len(sys.argv) > 2 else '/workspace/autosync/out/mms_vocals_rep.json'))['lines']
print('timings', new['timings'], 'lang', new['language'], 'lines', len(new['lines']), 'vs', len(old))
ds = []
for k, (a, b) in enumerate(zip(new['lines'], old)):
    same = a['text'] == b['text']
    d = a['start'] - b['start']; ds.append(abs(d))
    print(f"{k+1:2d} new {a['start']:7.2f}-{a['end']:7.2f} old {b['start']:7.2f}-{b['end']:7.2f} d={d:+.2f} {a.get('flag',''):9s} {'R' if a.get('repeat') else ' '} {'' if same else 'TEXT DIFFERS '}{a['text'][:38]}")
print('median |d| %.3f  max %.3f  within 0.05 s: %d/%d  within 0.1 s: %d/%d' % (statistics.median(ds), max(ds), sum(x <= 0.05 for x in ds), len(ds), sum(x <= 0.1 for x in ds), len(ds)))
