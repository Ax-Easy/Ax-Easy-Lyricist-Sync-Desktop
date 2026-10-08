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
