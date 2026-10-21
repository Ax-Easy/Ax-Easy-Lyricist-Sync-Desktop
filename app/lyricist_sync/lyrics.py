"""Lyrics text handling shared by the GUI, CLI and engine."""
import os
import re

from .formats import decode_text, detect_lang

_TAG = re.compile(r'\[[^\]]*\]|\([^)]*\)|\{[^}]*\}')

# GUI language choice -> (Whisper language code or None for auto, ISO 639-2 for xml:lang / uroman)
LANGS = {
    'auto': (None, ''), 'en': ('en', 'eng'), 'el': ('el', 'ell'), 'de': ('de', 'deu'), 'fr': ('fr', 'fra'),
    'es': ('es', 'spa'), 'it': ('it', 'ita'), 'pt': ('pt', 'por'), 'nl': ('nl', 'nld'), 'tr': ('tr', 'tur'),
    'ru': ('ru', 'rus'), 'bg': ('bg', 'bul'), 'ro': ('ro', 'ron'), 'sq': ('sq', 'sqi'),
}


def split_lines(text):
    """Pasted lyrics -> list of lyric lines. Skips blanks and whole-line tags like [Chorus] or (x2)."""
    out = []
    for raw in str(text or '').replace('\ufeff', '').splitlines():
        s = raw.strip()
        if not s or _TAG.fullmatch(s):
            continue
        out.append(s)
    return out


def resolve_lang(choice, lines):
    """GUI choice ('auto', 'en', 'el', ...) -> (whisper code or None, ISO 639-2)."""
    if choice and choice != 'auto' and choice in LANGS:
        return LANGS[choice]
    iso = detect_lang([{'text': l} for l in lines])
    return ('el', 'ell') if iso == 'ell' else (None, '')  # Latin script: let Whisper detect the language.


def sidecar_lyrics(audio_path):
    """Text of a .txt with the same name next to the audio, or None."""
    base = os.path.splitext(audio_path)[0]
    for ext in ('.txt', '.TXT', '.Txt'):
        p = base + ext
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                return decode_text(f.read())[0], p
    return None, None


# ---------------------------------------------------------------- 1.4.0: clean-up of pasted / imported lyrics
_SECTION_WORDS = (r'chorus|pre[- ]?chorus|post[- ]?chorus|verse|bridge|intro|outro|hook|refrain|interlude|solo|'
                  r'instrumental|break|breakdown|coda|tag|vamp|ad[- ]?lib|repeat|x ?\d+|\d+ ?x|'
                  r'ρεφρέν|ρεφραιν|κουπλέ|στροφή|εισαγωγή|γέφυρα|σόλο|επανάληψη|τέλος|φινάλε')
_SECTION_LINE = re.compile(r'^\s*(?:\[[^\]\n]*\]|\{[^}\n]*\}|\(\s*(?:%s)\b[^)\n]{0,30}\))\s*$' % _SECTION_WORDS, re.I)
_INLINE_TAG = re.compile(r'\s*\[[^\]\n]*\]\s*')
_TRAIL = re.compile(r'(?<![.,])[.,](?=[\s"\'”’»)\]]*$)')   # one '.' or ',' at the end, before closing quotes
_LEAD = re.compile(r'^[\s"\'“”‘’«»(\[¿¡\-–—*]*')


def clean_line(s):
    """One lyric line: inline [..] tags out, a trailing '.' or ',' out ('...', '…', '?', '!' and closing quotes stay),
    the first letter capitalised (after leading quotes / brackets), spaces tidied."""
    s = _INLINE_TAG.sub(' ', s.replace('\ufeff', ''))
    s = re.sub(r'[ \t\u00a0]+', ' ', s).strip()
    s = re.sub(r' +([,.;:!?…])', r'\1', s)   # no space left before punctuation where a tag was
    s = _TRAIL.sub('', s).rstrip()
    k = _LEAD.match(s).end()
    if k < len(s) and s[k].isalpha() and s[k].islower():
        up = s[k].upper()
        s = s[:k] + (up if len(up) == 1 else s[k].title()) + s[k + 1:]
    return s


def clean_lyrics(text):
    """Pasted or imported lyrics -> cleaned text: section-tag lines ([Chorus], [Verse 1], (Chorus), {Intro}, ...)
    removed, every line through clean_line, runs of blank lines collapsed to one (the stanza break), no blank lines
    at the start or end."""
    from .importers import sniff
    if sniff(str(text or '')):   # a timed file (SRT / VTT / LRC / TTML) is imported, never cleaned as plain text
        return text
    out = []
    for raw in str(text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if _SECTION_LINE.match(raw):
            continue
        s = clean_line(raw)
        if not s:
            if out and out[-1] != '':
                out.append('')
            continue
        out.append(s)
    while out and out[-1] == '':
        out.pop()
    return '\n'.join(out)
