"""Build the demo fixtures: espeak-ng speech over a synth bed, with known line times.
English: chorus written once in the .txt but sung twice (tests repeat detection).
Greek: tests uroman romanization. Needs espeak-ng, ffmpeg, numpy, soundfile."""
import json, os, subprocess, tempfile
import numpy as np, soundfile as sf

SR = 44100
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
SONGS = {
    'demo_en': dict(voice='en-us', title='Glass Towers', artist='Ax-Easy Demo', album='Fixtures', lang='en',
                    txt="[Verse]\nGlass towers glowing in the rain\nWe trace the light along the lane\n\n[Chorus]\n"
                        "Hold the line, hold the line tonight\nEvery word will find its time\n\n[Verse 2]\n"
                        "Silent signals crossing over\nMorning comes a little closer\n",
                    sung=[0, 1, 2, 3, 4, 5, 2, 3]),
    'demo_el': dict(voice='el', title='Ήλιος', artist='Ax-Easy Δοκιμή', album='Fixtures', lang='el',
                    txt="[Στροφή]\nΚαλησπέρα κόσμε\nΟ ήλιος ανατέλλει πάλι 🌅\nΤα λόγια βρίσκουν τον ρυθμό τους\n"
                        "Σ’ αγαπώ σαν το πρώτο φως\n",
                    sung=[0, 1, 2, 3]),
}


def tts(text, voice):
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        path = f.name
    subprocess.run(['espeak-ng', '-v', voice, '-s', '140', '-w', path, text.replace('🌅', '')], check=True)
    a, sr = sf.read(path, dtype='float32')
    os.remove(path)
    idx = np.nonzero(np.abs(a) > 0.01)[0]
    a = a[idx[0]:idx[-1] + 1]
    n = int(len(a) * SR / sr)
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype('float32')


def bed(n, seed=1):
    t = np.arange(n) / SR
    chords = [(220, 277.2, 329.6), (196, 246.9, 293.7), (174.6, 220, 261.6), (196, 246.9, 311.1)]
    out = np.zeros(n, 'float32')
    for k in range(int(n / SR / 2) + 1):
        a, b = k * 2 * SR, min(n, (k + 1) * 2 * SR)
        for f in chords[k % 4]:
            out[a:b] += 0.035 * np.sin(2 * np.pi * f * t[a:b]) + 0.012 * np.sin(4 * np.pi * f * t[a:b])
    for k in range(int(n / SR * 2)):  # kick every 0.5 s
        a = int(k * SR / 2)
        ln = min(n - a, int(0.12 * SR))
        if ln > 0:
            tt = np.arange(ln) / SR
            out[a:a + ln] += 0.25 * np.sin(2 * np.pi * (60 + 80 * np.exp(-tt * 40)) * tt) * np.exp(-tt * 25)
    rng = np.random.default_rng(seed)
    for k in range(int(n / SR * 4)):  # hats
        a = int(k * SR / 4 + SR / 8)
        ln = min(n - a, int(0.03 * SR))
        if ln > 0:
            out[a:a + ln] += 0.02 * rng.standard_normal(ln) * np.exp(-np.arange(ln) / SR * 120)
    return out


for name, s in SONGS.items():
    lines = [l for l in s['txt'].splitlines() if l.strip() and not l.startswith('[')]
    clips = [tts(lines[i], s['voice']) for i in s['sung']]
    gap, intro, outro = int(1.1 * SR), int(4.0 * SR), int(3.0 * SR)
    total = intro + sum(len(c) for c in clips) + gap * (len(clips) - 1) + outro
    voc = np.zeros(total, 'float32')
    truth, pos = [], intro
    for i, c in zip(s['sung'], clips):
        voc[pos:pos + len(c)] += 0.8 * c / (np.abs(c).max() + 1e-9)
        truth.append({'line': i, 'text': lines[i], 'start': round(pos / SR, 3), 'end': round((pos + len(c)) / SR, 3)})
        pos += len(c) + gap
    mix = voc + bed(total)
    mix = np.stack([mix, mix * 0.97 + 0.03 * np.roll(mix, 300)], 1)
    mix /= np.abs(mix).max() * 1.12
    wav = os.path.join(tempfile.gettempdir(), name + '.wav')
    sf.write(wav, mix, SR)
    mp3 = os.path.join(HERE, name + '.mp3')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', wav, '-codec:a', 'libmp3lame', '-b:a', '96k', '-id3v2_version', '3',
                    '-metadata', 'title=' + s['title'], '-metadata', 'artist=' + s['artist'], '-metadata', 'album=' + s['album'], mp3],
                   check=True)
    with open(os.path.join(HERE, name + '.txt'), 'w', encoding='utf-8') as f:
        f.write(s['txt'])
    with open(os.path.join(HERE, name + '.truth.json'), 'w', encoding='utf-8') as f:
        json.dump({'duration': round(total / SR, 3), 'lines': truth}, f, ensure_ascii=False, indent=1)
    print(name, '%.1fs' % (total / SR), os.path.getsize(mp3), 'bytes')
