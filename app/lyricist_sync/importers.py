"""1.4.0: read timed lyric / subtitle files (.srt, .vtt, .lrc, .ttml) into timed lines.

parse_file(path) / parse_bytes(data, ext) -> {'format', 'encoding', 'lines': [{'start', 'end', 'text'}]}

Choices (documented in the manual):
- An SRT / VTT cue with several text lines becomes ONE lyric line, its lines joined with a space: in subtitle
  files a line break is display wrapping, and one cue is one timed phrase.
- HTML / VTT / ASS-style tags are removed and entities decoded; empty cues are dropped.
- Where the format has no end time (LRC, TTML p with only begin), a line ends where the next one starts; the
  last one after DEFAULT_LAST_CUE seconds (or at the audio's end once it's known). An LRC stamp with no text
  ends the line before it.
- LRC: [mm:ss], [mm:ss.xx], [mm:ss.xxx], [mm:ss:xx]; several stamps on one line repeat it; [offset:±ms] applied;
  enhanced <mm:ss.xx> word stamps removed; [ti:] [ar:] ... tags kept as metadata.
- TTML: <p> (or <span> when the p has no times) begin / end / dur, in clock (hh:mm:ss.fff, hh:mm:ss:ff) or
  offset (12.5s, 500ms, 1.5m, 1h, 25f, 1000t) form, with ttp:tickRate, ttp:frameRate (+ frameRateMultiplier,
  subFrameRate); times of nested div / body add up (par containers).
"""
import html
import os
import re
import xml.etree.ElementTree as ET

from .formats import DEFAULT_LAST_CUE

EXTS = ('.srt', '.vtt', '.lrc', '.ttml', '.xml', '.dfxp')


def decode(data):
    """Bytes -> (text, encoding): BOM (UTF-8 / UTF-16 LE / BE), BOM-less UTF-16 (NUL bytes), UTF-8, else Windows-1253."""
    if data[:3] == b'\xef\xbb\xbf':
        return data[3:].decode('utf-8', 'replace'), 'utf-8-sig'
    if data[:2] == b'\xff\xfe':
        return data[2:].decode('utf-16-le', 'replace'), 'utf-16le'
    if data[:2] == b'\xfe\xff':
        return data[2:].decode('utf-16-be', 'replace'), 'utf-16be'
    head = data[:400]
    if len(head) >= 4 and head.count(b'\x00') > len(head) // 4:
        odd = sum(1 for b in head[1::2] if b == 0)
        enc = 'utf-16-le' if odd >= len(head[1::2]) // 2 else 'utf-16-be'
        return data.decode(enc, 'replace'), enc
    try:
        return data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        return data.decode('cp1253', 'replace'), 'windows-1253'


_TAG = re.compile(r'<[^>]*>')
_ASS = re.compile(r'\{\\[^}]*\}')


def clean_text(s):
    s = _ASS.sub('', s)
    s = re.sub(r'<br\s*/?>', ' ', s, flags=re.I)
    s = _TAG.sub('', s)
    s = html.unescape(s).replace('\u00a0', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def _clock(s):
    """'hh:mm:ss.fff' / 'mm:ss.fff' / 'hh:mm:ss,fff' -> seconds."""
    s = s.strip().replace(',', '.')
    parts = s.split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except ValueError:
        return None


def finish(lines, duration=None):
    """Sort, drop empties, derive missing / overlapping ends, round to ms."""
    out = [l for l in lines if l.get('text') and l.get('start') is not None]
    out.sort(key=lambda l: l['start'])
    for i, l in enumerate(out):
        nxt = out[i + 1]['start'] if i + 1 < len(out) else None
        e = l.get('end')
        if e is None or e <= l['start']:
            e = nxt if nxt is not None else (duration if duration and duration > l['start'] else l['start'] + DEFAULT_LAST_CUE)
        l['start'], l['end'] = round(max(0.0, l['start']), 3), round(max(e, l['start']), 3)
    return [{'start': l['start'], 'end': l['end'], 'text': l['text']} for l in out]


# ---------------------------------------------------------------- SRT / VTT
_ARROW = re.compile(r'^\s*(\S+)\s*-->\s*(\S+)')


def parse_cues(text, vtt=False):
    lines = []
    blocks = re.split(r'\n\s*\n', text.replace('\r\n', '\n').replace('\r', '\n').strip('\n\ufeff'))
    for b in blocks:
        rows = [r for r in b.split('\n')]
        if vtt and rows and (rows[0].startswith('WEBVTT') or rows[0].split(' ')[0] in ('NOTE', 'STYLE', 'REGION')):
            continue
        k = next((i for i, r in enumerate(rows) if '-->' in r), None)
        if k is None:
            continue
        m = _ARROW.match(rows[k])
        if not m:
            continue
        a, z = _clock(m.group(1)), _clock(m.group(2))   # VTT cue settings after the end time are ignored
        if a is None:
            continue
        txt = clean_text(' '.join(r.strip() for r in rows[k + 1:] if r.strip()))
        lines.append({'start': a, 'end': z, 'text': txt})
    return lines


# ---------------------------------------------------------------- LRC
_STAMP = re.compile(r'\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]')
_META = re.compile(r'^\[([a-zA-Z#]+):(.*)\]\s*$')


def parse_lrc(text):
    meta, raw, offset = {}, [], 0.0
    for row in text.replace('\r', '\n').split('\n'):
        row = row.strip().lstrip('\ufeff')
        if not row:
            continue
        mm = _META.match(row)
        if mm and not _STAMP.match(row):
            k, v = mm.group(1).lower(), mm.group(2).strip()
            if k == 'offset':
                try:
                    offset = float(v) / 1000.0
                except ValueError:
                    pass
            else:
                meta[k] = v
            continue
        stamps, pos = [], 0
        while True:
            m = _STAMP.match(row, pos)
            if not m:
                break
            frac = m.group(3) or '0'
            t = int(m.group(1)) * 60 + int(m.group(2)) + int(frac) / (10 ** len(frac))
            stamps.append(t)
            pos = m.end()
        if not stamps:
            continue
        txt = clean_text(re.sub(r'<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>', '', row[pos:]))
        for t in stamps:
            raw.append((t - offset, txt))
    raw.sort(key=lambda x: x[0])
    lines = []
    for i, (t, txt) in enumerate(raw):
        if not txt:
            if lines and lines[-1]['end'] is None:
                lines[-1]['end'] = t    # an empty stamp ends the line before it
            continue
        lines.append({'start': t, 'end': None, 'text': txt})
    return lines, meta


# ---------------------------------------------------------------- TTML
def _local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def _attr(el, name):
    for k, v in el.attrib.items():
        if _local(k) == name:
            return v
    return None


class _Rates:
    def __init__(self, root):
        def num(n, d):
            try:
                return float((_attr(root, n) or '').split()[0])
            except (ValueError, IndexError):
                return d
        self.frame = num('frameRate', 30.0)
        mul = (_attr(root, 'frameRateMultiplier') or '').split()
        if len(mul) == 2:
            try:
                self.frame *= float(mul[0]) / float(mul[1])
            except (ValueError, ZeroDivisionError):
                pass
        self.sub = num('subFrameRate', 1.0)
        self.tick = num('tickRate', self.frame * self.sub if _attr(root, 'frameRate') else 1.0)

    def time(self, s):
        if not s:
            return None
        s = s.strip()
        m = re.fullmatch(r'(\d+(?:\.\d+)?)(h|ms|m|s|f|t)', s)
        if m:
            v, u = float(m.group(1)), m.group(2)
            return {'h': v * 3600, 'm': v * 60, 's': v, 'ms': v / 1000.0, 'f': v / self.frame,
                    't': v / (self.tick or 1.0)}[u]
        m = re.fullmatch(r'(\d+):(\d{2}):(\d{2})(?:\.(\d+))?', s)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + (float('0.' + m.group(4)) if m.group(4) else 0)
        m = re.fullmatch(r'(\d+):(\d{2}):(\d{2}):(\d+)(?:\.(\d+))?', s)
        if m:
            fr = int(m.group(4)) + (int(m.group(5)) / self.sub if m.group(5) else 0)
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + fr / self.frame
        return _clock(s)


def _text(el):
    parts = []
    def walk(e):
        if _local(e.tag) == 'br':
            parts.append(' ')
        elif e.text:
            parts.append(e.text)
        for c in e:
            walk(c)
            if c.tail:
                parts.append(c.tail)
    walk(el)
    return clean_text(''.join(parts))


def parse_ttml(text):
    root = ET.fromstring(re.sub(r'^\ufeff', '', text).encode('utf-8'))
    R = _Rates(root)
    lines = []

    def span_times(p, base):
        b = e = None
        for sp in p.iter():
            if sp is p or _local(sp.tag) != 'span':
                continue
            sb = R.time(_attr(sp, 'begin'))
            if sb is None:
                continue
            se = R.time(_attr(sp, 'end'))
            sd = R.time(_attr(sp, 'dur'))
            sb += base
            se = se + base if se is not None else (sb + sd if sd is not None else None)
            b = sb if b is None else min(b, sb)
            if se is not None:
                e = se if e is None else max(e, se)
        return b, e

    def walk(el, base):
        name = _local(el.tag)
        if name in ('head', 'metadata', 'styling', 'layout'):
            return
        if name == 'p':
            b, e, d = R.time(_attr(el, 'begin')), R.time(_attr(el, 'end')), R.time(_attr(el, 'dur'))
            if b is None:
                b, e2 = span_times(el, base)
                e = e2 if e is None else e + base
            else:
                b += base
                e = e + base if e is not None else (b + d if d is not None else None)
            lines.append({'start': b, 'end': e, 'text': _text(el)})
            return
        own = R.time(_attr(el, 'begin'))
        for c in el:
            walk(c, base + (own or 0.0))

    walk(root, 0.0)
    return lines


# ---------------------------------------------------------------- entry points
def sniff(text):
    t = text.lstrip('\ufeff \t\r\n')
    if t.startswith('WEBVTT'):
        return 'vtt'
    if t.startswith('<'):
        return 'ttml'
    if re.match(r'\[(\d{1,3}:\d|[a-zA-Z]+:)', t):
        return 'lrc'
    if '-->' in t:
        return 'srt'
    return None


def parse_bytes(data, ext='', duration=None):
    text, enc = decode(data)
    ext = ext.lower().lstrip('.')
    fmt = {'srt': 'srt', 'vtt': 'vtt', 'lrc': 'lrc', 'ttml': 'ttml', 'xml': 'ttml', 'dfxp': 'ttml'}.get(ext) or sniff(text)
    sn = sniff(text)
    if sn and sn != fmt and (ext not in ('srt', 'vtt', 'lrc', 'ttml') or (fmt, sn) == ('srt', 'vtt')):
        fmt = sn   # trust the content over a misleading extension (.xml, .txt, a .srt that is really WebVTT)
    meta = {}
    if fmt == 'srt':
        lines = parse_cues(text)
    elif fmt == 'vtt':
        lines = parse_cues(text, vtt=True)
    elif fmt == 'lrc':
        lines, meta = parse_lrc(text)
    elif fmt == 'ttml':
        try:
            lines = parse_ttml(text)
        except ET.ParseError as e:
            raise ValueError('not valid TTML/XML: %s' % e)
    else:
        raise ValueError('not a subtitle or lyric file (.srt, .vtt, .lrc, .ttml)')
    lines = finish(lines, duration)
    if not lines:
        raise ValueError('no timed lines found')
    return {'format': fmt, 'encoding': enc, 'lines': lines, 'meta': meta}


def parse_file(path, duration=None):
    with open(path, 'rb') as f:
        data = f.read()
    return parse_bytes(data, os.path.splitext(path)[1], duration)


def is_timed_file(path):
    return os.path.splitext(path)[1].lower() in EXTS
