"""Regression fixtures for the 1.1.0 timing fixes (not shipped; written to tests/hard/):

intro_long  32 s instrumental intro with a vocal-like formant lead synth (bleeds into the
            Demucs vocals stem), then the first line.
intro_hum   intro with a hummed 'mmm/ooh' (synthetic voice with vibrato), an ad-lib
            "Ohhh, I wonder" that is not in the lyrics (as in many real songs), then line 1.
choir       lead lines, a section sung by a 4-voice choir (staggered entries, different
            pitches/voices), and lead lines with backing 'ooh' pads and echoed words that
            overlap the next lead line.
Truth = start of the lead vocal of each line. Needs espeak-ng, ffmpeg, numpy, soundfile."""
import json, os, subprocess, tempfile
import numpy as np, soundfile as sf

SR = 44100
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'hard')
sys_bed = None


def tts(text, voice='en-us', speed=140, pitch=50, gain=0.8):
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        path = f.name
    subprocess.run(['espeak-ng', '-v', voice, '-s', str(speed), '-p', str(pitch), '-w', path, text], check=True)
    a, sr = sf.read(path, dtype='float32')
    os.remove(path)
    idx = np.nonzero(np.abs(a) > 0.01)[0]
    a = a[idx[0]:idx[-1] + 1]
    n = int(len(a) * SR / sr)
    a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype('float32')
    return gain * a / (np.abs(a).max() + 1e-9)


def resonate(x, formants, bw=90.0):
    """Formant filter (sum of 2-pole resonators) via FFT convolution."""
    n = 4096
    t = np.arange(n) / SR
    ir = np.zeros(n)
    for f, g in formants:
        ir += g * np.exp(-np.pi * bw * t) * np.sin(2 * np.pi * f * t)
    y = np.fft.irfft(np.fft.rfft(x, len(x) + n) * np.fft.rfft(ir, len(x) + n))[:len(x)]
    return (y / (np.abs(y).max() + 1e-9)).astype('float32')


def voiced(dur, notes, formants, vib=5.5, depth=0.012, seed=0, breath=0.03):
    """Glottal-pulse 'voice' singing notes [(f0, seconds)] through vowel formants."""
    n = int(dur * SR)
    f0 = np.zeros(n)
    pos = 0
    for f, d in notes:
        k = int(d * SR)
        f0[pos:pos + k] = f
        pos += k
    f0[pos:] = notes[-1][0]
    t = np.arange(n) / SR
    f0 = f0 * (1 + depth * np.sin(2 * np.pi * vib * t))
    ph = np.cumsum(f0 / SR) % 1.0
    src = (ph - 0.5) * 2  # sawtooth ~ glottal pulse
    src += breath * np.random.default_rng(seed).standard_normal(n)
    y = resonate(src, formants)
    env = np.minimum(1, np.minimum(t / 0.25, (dur - t) / 0.35)).clip(0, 1)
    return (y * env).astype('float32')


OOH = [(300, 1.0), (870, 0.5), (2240, 0.2)]
AAH = [(730, 1.0), (1090, 0.6), (2440, 0.25)]
MMM = [(250, 1.0), (1300, 0.08), (2200, 0.04)]


def bed(n, seed=1, lead=None):
    t = np.arange(n) / SR
    chords = [(220, 277.2, 329.6), (196, 246.9, 293.7), (174.6, 220, 261.6), (196, 246.9, 311.1)]
    out = np.zeros(n, 'float32')
    for k in range(int(n / SR / 2) + 1):
        a, b = k * 2 * SR, min(n, (k + 1) * 2 * SR)
        for f in chords[k % 4]:
            out[a:b] += 0.035 * np.sin(2 * np.pi * f * t[a:b]) + 0.012 * np.sin(4 * np.pi * f * t[a:b])
    for k in range(int(n / SR * 2)):
        a = int(k * SR / 2)
        ln = min(n - a, int(0.12 * SR))
        if ln > 0:
            tt = np.arange(ln) / SR
            out[a:a + ln] += 0.25 * np.sin(2 * np.pi * (60 + 80 * np.exp(-tt * 40)) * tt) * np.exp(-tt * 25)
    rng = np.random.default_rng(seed)
    for k in range(int(n / SR * 4)):
        a = int(k * SR / 4 + SR / 8)
        ln = min(n - a, int(0.03 * SR))
        if ln > 0:
            out[a:a + ln] += 0.02 * rng.standard_normal(ln) * np.exp(-np.arange(ln) / SR * 120)
    return out


def write(name, title, txt, mix, truth, total):
    mix = np.stack([mix, mix * 0.97 + 0.03 * np.roll(mix, 300)], 1)
    mix /= np.abs(mix).max() * 1.12
    wav = os.path.join(tempfile.gettempdir(), name + '.wav')
    sf.write(wav, mix, SR)
    os.makedirs(OUT, exist_ok=True)
    mp3 = os.path.join(OUT, name + '.mp3')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', wav, '-codec:a', 'libmp3lame', '-b:a', '128k', '-id3v2_version', '3',
                    '-metadata', 'title=' + title, '-metadata', 'artist=Ax-Easy Tests', '-metadata', 'album=Hard cases', mp3],
                   check=True)
    with open(os.path.join(OUT, name + '.txt'), 'w', encoding='utf-8') as f:
        f.write(txt)
    with open(os.path.join(OUT, name + '.truth.json'), 'w', encoding='utf-8') as f:
        json.dump({'duration': round(total / SR, 3), 'lines': truth}, f, ensure_ascii=False, indent=1)
    print(name, '%.1fs' % (total / SR), [t['start'] for t in truth])


def place(buf, clip, t):
    a = int(t * SR)
    buf[a:a + len(clip)] += clip[:len(buf) - a]
    return round(a / SR, 3), round((a + len(clip)) / SR, 3)


def song_lines(lines, start, voc, gap=1.0, voice='en-us', pitch=50):
    truth, pos = [], start
    for i, l in enumerate(lines):
        c = tts(l, voice, pitch=pitch)
        s, e = place(voc, c, pos)
        truth.append({'line': i, 'text': l, 'start': s, 'end': e})
        pos = e + gap
    return truth, pos


def intro_long():
    lines = ['Remember us as we were before', 'Under the lights of a quiet town',
             'Nothing was broken, nothing was sold', 'We kept the fire and never let go']
    total = int(52 * SR)
    voc = np.zeros(total, 'float32')
    truth, _ = song_lines(lines, 32.0, voc)
    music = bed(total)
    # vocal-like lead synth over the intro (8-29 s): 'aah' formants, melodic, with vibrato
    melody = [(330, 1.0), (392, 1.0), (440, 2.0), (392, 1.0), (330, 1.0), (294, 2.0)] * 3
    lead = voiced(21.0, melody, AAH, seed=3)
    place(music, 0.22 * lead, 8.0)
    write('intro_long', 'Long Intro', '[Intro]\n\n[Verse]\n' + '\n'.join(lines) + '\n', voc + music, truth, total)


def intro_bleed():
    """Vowel-like 'aah' lead synth over a 22 s intro, loud enough to bleed into the vocals
    stem, and a first line that starts with the same vowel: the classic 'line 1 starts in
    the intro' case."""
    lines = ['All of the lights are fading away', 'Over the river the evening is cold',
             'Every road leads me back to you', 'And I will stay until the morning']
    total = int(44 * SR)
    voc = np.zeros(total, 'float32')
    truth, _ = song_lines(lines, 26.0, voc)
    music = bed(total, seed=7)
    melody = [(220, 2.0), (247, 2.0), (262, 2.0), (247, 2.0), (220, 4.0)] * 2
    lead = voiced(22.0, melody, AAH, seed=9, depth=0.02)
    place(music, 0.55 * lead, 2.0)
    write('intro_bleed', 'Bleeding Intro', '[Intro]\n\n[Verse]\n' + '\n'.join(lines) + '\n', voc + music, truth, total)


def intro_hum():
    lines = ['Think of us as a passing season', 'Every light was turning grey',
             'Hold me closer, hold me down', 'Till the morning finds a way']
    total = int(44 * SR)
    voc = np.zeros(total, 'float32')
    hum = voiced(5.0, [(220, 2.0), (247, 1.5), (196, 1.5)], MMM, seed=5)
    place(voc, 0.5 * hum, 5.0)
    ooh = voiced(3.5, [(262, 1.5), (294, 2.0)], OOH, seed=6)
    place(voc, 0.6 * ooh, 11.0)
    place(voc, tts('Ohhh, I wonder', 'en-us', speed=95, pitch=40, gain=0.7), 15.5)
    place(voc, tts('yeah, yeah', 'en-us', speed=110, pitch=60, gain=0.5), 18.6)
    truth, _ = song_lines(lines, 22.0, voc)
    write('intro_hum', 'Hummed Intro', '\n'.join(lines) + '\n', voc + bed(total, seed=2), truth, total)


def choir():
    lines = ['Walking alone through the city at night', 'Counting the windows that glow in the dark',
             'Sing it together, we are the light', 'Raise up your voices and carry the spark',
             'Morning is calling my name from afar', 'I will be waiting wherever you are']
    total = int(56 * SR)
    voc = np.zeros(total, 'float32')
    truth = []
    pos = 4.0
    for i in range(2):  # lead
        c = tts(lines[i])
        s, e = place(voc, c, pos)
        truth.append({'line': i, 'text': lines[i], 'start': s, 'end': e})
        pos = e + 1.0
    for i in (2, 3):  # choir: 4 voices, staggered entries, different pitches, the lead is not louder
        parts = [('en-us', 35, 0.00), ('en-gb', 60, 0.06), ('en-us+f3', 75, 0.11), ('en-gb-x-rp', 45, 0.16)]
        first = None
        ends = []
        for v, p, off in parts:
            c = tts(lines[i], v, pitch=p, gain=0.45)
            s, e = place(voc, c, pos + off)
            first = s if first is None else min(first, s)
            ends.append(e)
        truth.append({'line': i, 'text': lines[i], 'start': first, 'end': max(ends), 'choir': True})
        pos = max(ends) + 0.8
    for i in (4, 5):  # lead + backing 'ooh' pad + echo of the last words overlapping the next line
        c = tts(lines[i])
        s, e = place(voc, c, pos)
        truth.append({'line': i, 'text': lines[i], 'start': s, 'end': e})
        pad = voiced(e - s + 0.6, [(196, e - s + 0.6)], OOH, seed=10 + i)
        place(voc, 0.25 * pad, s - 0.3)
        echo = ' '.join(lines[i].split()[-2:])
        place(voc, tts(echo, 'en-gb', pitch=70, gain=0.4), e + 0.15)
        pos = e + 0.55  # the echo overlaps the start of the next lead line
    txt = ('[Verse]\n' + '\n'.join(lines[:2]) + '\n\n[Choir]\n' + '\n'.join(lines[2:4]) +
           '\n\n[Outro]\n' + '\n'.join(lines[4:]) + '\n')
    write('choir', 'Choir Test', txt, voc + bed(total, seed=4), truth, total)


if __name__ == '__main__':
    intro_long()
    intro_bleed()
    intro_hum()
    choir()
