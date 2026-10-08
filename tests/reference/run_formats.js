// Reads JSON cases on stdin, prints the plugin's outputs as JSON (reference for test_formats.py).
const F = require('./formats.js');
let buf = '';
process.stdin.on('data', d => { buf += d; });
process.stdin.on('end', () => {
  const cases = JSON.parse(buf);
  const out = cases.map(c => ({
    lrc: F.build('lrc', c.lines, c.meta, c.duration),
    srt: F.build('srt', c.lines, c.meta, c.duration),
    vtt: F.build('vtt', c.lines, c.meta, c.duration),
    ttml: F.build('ttml', c.lines, c.meta, c.duration),
    base: F.buildBaseName(c.info),
    t: c.times.map(x => [F.fmtLrcTime(x), F.fmtSrtTime(x), F.fmtTtmlTime(x)]),
    p: c.parse.map(x => F.parseTime(x)),
  }));
  process.stdout.write(JSON.stringify(out));
});
