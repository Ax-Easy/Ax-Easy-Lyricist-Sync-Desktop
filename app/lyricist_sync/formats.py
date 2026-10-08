"""Exporters, a line-for-line port of Ax-Easy Lyricist 1.1.0 assets/js/formats.js.

Output is byte-identical to the plugin for the same input (tests/test_formats.py runs
both).  One addition: a line may carry an explicit "end" (the aligned end of the sung
line); it is capped at the next line's start, so cues never overlap.  Without "end"
the plugin rule applies (a line ends where the next one starts).
"""
import math
import re

DEFAULT_LAST_CUE = 4  # Seconds, when the audio duration is unknown.


def _round(x):
    """JavaScript Math.round (half up)."""
    return math.floor(x + 0.5)


def _is_num(t):
    return isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t)


def _pad(n, ln):
    return str(n).rjust(ln, '0')


def fmt_lrc_time(t):
    cs = _round(max(0, t) * 100)
    return _pad(cs // 6000, 2) + ':' + _pad((cs % 6000) // 100, 2) + '.' + _pad(cs % 100, 2)


def _fmt_clock(t, sep):
    ms = _round(max(0, t) * 1000)
    return (_pad(ms // 3600000, 2) + ':' + _pad((ms % 3600000) // 60000, 2) + ':' +
            _pad((ms % 60000) // 1000, 2) + sep + _pad(ms % 1000, 3))


def fmt_srt_time(t):
    return _fmt_clock(t, ',')


def fmt_vtt_time(t):
    return _fmt_clock(t, '.')


fmt_ttml_time = fmt_vtt_time


def parse_time(s):
    """'ss', 'ss.xx', 'm:ss', 'mm:ss.xx', 'hh:mm:ss,mmm' -> seconds or None."""
    if s is None:
        return None
    s = str(s).strip().replace(',', '.', 1)
    if not s:
        return None
    m = re.fullmatch(r'(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d*)?)', s)
    if not m:
        return None
    h = mi = 0
    sec = float(m.group(3))
    if m.group(1) is not None and m.group(2) is not None:
        h, mi = int(m.group(1)), int(m.group(2))
    elif m.group(1) is not None:
        mi = int(m.group(1))
    total = h * 3600 + mi * 60 + sec
    return _round(total * 1000) / 1000 if math.isfinite(total) else None


def build_cues(lines, duration=None):
    """lines: [{'text', 'time', optional 'end'}] -> sorted cues [{'start','end','text'}]."""
    stamped = []
    for i, l in enumerate(lines or []):
        if l and _is_num(l.get('time')) and str(l.get('text') or '').strip() != '':
            stamped.append({'start': l['time'], 'text': str(l['text']).strip(), 'i': i, 'end': l.get('end')})
    stamped.sort(key=lambda c: (c['start'], c['i']))
    cues = []
    for k, c in enumerate(stamped):
        if k + 1 < len(stamped):
            end = stamped[k + 1]['start']
        elif _is_num(duration) and duration > c['start']:
            end = duration
        else:
            end = c['start'] + DEFAULT_LAST_CUE
        if _is_num(c['end']):
            end = min(c['end'], end)
        cues.append({'start': c['start'], 'end': max(end, c['start']), 'text': c['text']})
    return cues


def _clean_meta(v):
    return re.sub(r'[\r\n\]]+', ' ', str(v or '')).strip()


def build_lrc(lines, meta=None):
    meta = meta or {}
    out = []
    for k in ('ti', 'ar', 'al'):
        v = _clean_meta(meta.get(k))
        if v:
            out.append('[' + k + ':' + v + ']')
    for c in build_cues(lines, None):
        out.append('[' + fmt_lrc_time(c['start']) + ']' + c['text'])
    return '\n'.join(out) + '\n' if out else ''


def build_srt(lines, duration=None):
    return '\n'.join(str(k + 1) + '\n' + fmt_srt_time(c['start']) + ' --> ' + fmt_srt_time(c['end']) + '\n' + c['text'] + '\n'
                     for k, c in enumerate(build_cues(lines, duration)))


def _escape_vtt(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def build_vtt(lines, duration=None):
    cues = [fmt_vtt_time(c['start']) + ' --> ' + fmt_vtt_time(c['end']) + '\n' + _escape_vtt(c['text']) + '\n'
            for c in build_cues(lines, duration)]
    return 'WEBVTT\n\n' + '\n'.join(cues)


BCP47 = {
    'ell': 'el', 'gre': 'el', 'eng': 'en', 'deu': 'de', 'ger': 'de', 'fra': 'fr', 'fre': 'fr', 'spa': 'es', 'ita': 'it',
    'ara': 'ar', 'heb': 'he', 'rus': 'ru', 'por': 'pt', 'nld': 'nl', 'dut': 'nl', 'tur': 'tr', 'jpn': 'ja', 'zho': 'zh',
    'chi': 'zh', 'kor': 'ko', 'pol': 'pl', 'swe': 'sv', 'nor': 'no', 'dan': 'da', 'fin': 'fi', 'bul': 'bg', 'ron': 'ro',
    'rum': 'ro', 'ukr': 'uk', 'srp': 'sr', 'hrv': 'hr', 'alb': 'sq', 'sqi': 'sq', 'hin': 'hi', 'fas': 'fa', 'per': 'fa',
}
_LETTER = re.compile('[A-Za-z\u00C0-\u024F\u0400-\u04FF\u0590-\u05FF\u0600-\u06FF\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]')


def detect_lang(lines):
    """'ell' when >= 30% of letters are Greek, else 'eng' (same rule as the plugin)."""
    text = ' '.join(l.get('text') or '' for l in (lines or []) if l)
    letters = greek = 0
    for ch in text:
        c = ord(ch)
        if 0x0370 <= c <= 0x03FF or 0x1F00 <= c <= 0x1FFF:
            greek += 1
            letters += 1
        elif _LETTER.match(ch):
            letters += 1
    return 'ell' if letters and greek / letters >= 0.3 else 'eng'


def bcp47(code, lines):
    c = str(code or '').lower()
    if len(c) != 3:
        c = detect_lang(lines)
    return BCP47.get(c, c)


_XML_BAD = re.compile('[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]')


def xml_escape(s):
    return (_XML_BAD.sub('', str(s)).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&apos;'))


def build_ttml(lines, meta=None, duration=None):
    meta = meta or {}
    cues = build_cues(lines, duration)
    lang = bcp47(meta.get('lang'), lines)
    title = str(meta.get('ti') or '').strip()
    artist = str(meta.get('ar') or '').strip()
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata" '
           'xmlns:itunes="http://music.apple.com/lyric-ttml-internal" itunes:timing="Line" xml:lang="' + xml_escape(lang) + '">']
    if title or artist:
        out += ['  <head>', '    <metadata>']
        if title:
            out.append('      <ttm:title>' + xml_escape(title) + '</ttm:title>')
        if artist:
            out += ['      <ttm:agent type="person" xml:id="v1">',
                    '        <ttm:name type="full">' + xml_escape(artist) + '</ttm:name>',
                    '      </ttm:agent>']
        out += ['    </metadata>', '  </head>']
    if not cues:
        out.append('  <body/>')
    else:
        end = cues[-1]['end']
        out.append('  <body dur="' + fmt_ttml_time(end) + '">')
        # The div starts at 0 so <p> times are absolute for Apple's reader and strict TTML.
        out.append('    <div begin="' + fmt_ttml_time(0) + '" end="' + fmt_ttml_time(end) + '">')
        for c in cues:
            out.append('      <p begin="' + fmt_ttml_time(c['start']) + '" end="' + fmt_ttml_time(c['end']) + '"' +
                       (' ttm:agent="v1"' if artist else '') + '>' + xml_escape(c['text']) + '</p>')
        out += ['    </div>', '  </body>']
    out.append('</tt>')
    return '\n'.join(out) + '\n'


def build(fmt, lines, meta=None, duration=None):
    if fmt == 'srt':
        return build_srt(lines, duration)
    if fmt == 'vtt':
        return build_vtt(lines, duration)
    if fmt == 'ttml':
        return build_ttml(lines, meta, duration)
    return build_lrc(lines, meta)


def _js_len(s):
    return len(s.encode('utf-16-le')) // 2


def sanitize_filename(name):
    """Safe on Windows/macOS while keeping spaces and Unicode (Greek etc.)."""
    s = re.sub('[\u0000-\u001f\u007f]', '', str(name or ''))
    s = re.sub(r'[<>:"/\\|?*]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'[. ]+$', '', s)
    s = re.sub(r'^[. ]+', '', s)
    if re.fullmatch(r'(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?', s, re.I | re.S):
        s = '_' + s
    if _js_len(s) > 150:
        s = s.encode('utf-16-le')[:300].decode('utf-16-le', 'ignore').strip()
    return s or 'lyrics'


def build_base_name(info):
    """'Artist - Title' from ID3 title/artist, then [ti:], then the audio filename."""
    info = info or {}
    file_base = re.sub(r'\.[^.]+$', '', str(info.get('filename') or ''))
    title = str(info.get('title') or '').strip() or str(info.get('ti') or '').strip() or file_base
    artist = str(info.get('artist') or '').strip()
    base = title
    if artist and not title.lower().startswith(artist.lower() + ' - '):
        base = artist + ' - ' + title
    return sanitize_filename(base)


def encode_file(text, bom=False):
    text = str(text)
    if text.startswith('\ufeff'):
        text = text[1:]
    return (('\ufeff' if bom else '') + text).encode('utf-8')


def decode_text(data):
    """Bytes -> (text, encoding). BOM-aware; UTF-8, else Greek Windows-1253 (as the plugin)."""
    if data[:3] == b'\xef\xbb\xbf':
        return data[3:].decode('utf-8', 'replace'), 'utf-8-sig'
    if data[:2] == b'\xff\xfe':
        return data[2:].decode('utf-16-le', 'replace'), 'utf-16le'
    if data[:2] == b'\xfe\xff':
        return data[2:].decode('utf-16-be', 'replace'), 'utf-16be'
    try:
        return data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        return data.decode('cp1253', 'replace'), 'windows-1253'


EXTS = {'ttml': '.ttml', 'lrc': '.lrc', 'srt': '.srt', 'vtt': '.vtt'}
