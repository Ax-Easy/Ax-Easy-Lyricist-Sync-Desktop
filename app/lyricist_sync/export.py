"""Export: where each song's files go, never-silent overwrites, and writing the formats."""
import os

from .formats import EXTS, build, build_base_name, encode_file

SAVE_MODES = ('beside', 'folder', 'ask')  # next to the audio file (default) / a chosen folder / ask every time


def target_dir(song, settings, asked=None):
    """Per-song override > save mode. Returns None when the user must be asked."""
    if getattr(song, 'out_dir', None):
        return song.out_dir
    mode = settings.get('save_mode', 'beside')
    if mode == 'beside':
        return os.path.dirname(os.path.abspath(song.path))
    if mode == 'folder':
        return settings.get('out_dir') or os.path.join(os.path.expanduser('~'), 'Documents', 'Lyricist Sync')
    return asked


def base_name(song):
    info = {'filename': os.path.basename(song.path), 'title': song.tags.get('title', ''), 'artist': song.tags.get('artist', '')}
    return build_base_name(info), info


def planned_paths(song, out_dir, formats, base=None):
    base = base or base_name(song)[0]
    return [os.path.join(out_dir, base + EXTS[f]) for f in formats]


def keep_both_base(out_dir, base, formats):
    """'Name (2)', 'Name (3)'... the first suffix that is free for every chosen format."""
    n = 2
    while any(os.path.exists(os.path.join(out_dir, '%s (%d)%s' % (base, n, EXTS[f]))) for f in formats):
        n += 1
    return '%s (%d)' % (base, n)


def export_song(song, options, on_conflict=None):
    """Write the chosen formats for one synced song. options: dir, formats, bom.
    on_conflict(song, existing_paths) -> 'overwrite' | 'keep' | 'skip' is asked when files
    exist; without it existing files are never overwritten (keep both).
    Returns the list of files written ([] when skipped)."""
    out_dir = options['dir']
    os.makedirs(out_dir, exist_ok=True)
    formats = options['formats']
    base, info = base_name(song)
    existing = [p for p in planned_paths(song, out_dir, formats, base) if os.path.exists(p)]
    if existing:
        decision = on_conflict(song, existing) if on_conflict else 'keep'
        if decision == 'skip':
            return []
        if decision == 'keep':
            base = keep_both_base(out_dir, base, formats)
    # sung lines linger 0.4 s (cut at the next line); ♪ lines end where they end
    lines = [{'text': l['text'], 'time': l['start'], 'end': l['end'] + (0 if l.get('inst') else 0.4)} for l in song.result['lines']]
    m = {'ti': info['title'], 'ar': info['artist'], 'al': song.tags.get('album', ''), 'lang': song.iso}
    written = []
    for fmt in formats:
        path = os.path.join(out_dir, base + EXTS[fmt])
        text = build(fmt, lines, m, song.result.get('duration'))
        with open(path, 'wb') as f:
            f.write(encode_file(text, bom=(fmt == 'srt' and options.get('bom'))))
        written.append(path)
    return written


def read_tags(path):
    tags = {}
    try:  # tinytag (MIT): MP3/ID3, MP4/M4A, FLAC, Ogg, WAV, AIFF tags (replaced mutagen, GPL, in 1.3.1)
        from tinytag import TinyTag
        t = TinyTag.get(path)
        for k in ('title', 'artist', 'album'):
            v = getattr(t, k, None)
            if v:
                tags[k] = str(v)
    except Exception:
        pass
    return tags
