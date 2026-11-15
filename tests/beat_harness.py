"""Beat-tracking harness for sound mode: feeds known music through the real analyser and light show
with a simulated clock, and scores how well the predicted beats line up with the real ones.

A dev tool, not part of the app. Run from the repo root:

    uv run python tests/beat_harness.py                   # every synthetic case: line, laptop-mic and digital input
    uv run python tests/beat_harness.py --case garage132  # one case
    uv run python tests/beat_harness.py --sweep           # also try other tempo windows
    uv run python tests/beat_harness.py --range 150 170   # every case with this tempo range
    uv run --with soundfile python tests/beat_harness.py --file track.flac --bpm 132 --first-beat 0.41

Synthetic cases are made in code (kick, clap, snare, hat, sub), so true beat and kick times are known
exactly. They are cleaner and simpler than real masters: tune on them, then confirm on real tracks.

Columns:
  lock     seconds until the tempo locked (any tempo)
  ratio    found tempo / true tempo over the scored part (1 is right; 1/2, 2/3 ... are misreads)
  on%      share of scored beats where the grid sits on the beat (within an eighth of a beat)
  sits     where the grid sits most often: on, half (the off-beat), qtr (a 16th off)
  grid50   median grid error in ms at the true beats (beats where the grid is on)
  grid90   90th percentile of the same
  fire%    share of beats in drum sections with a fired beat within 30 ms
  fire50   median error of fired beats in ms (+ late)
  extra    fired beats more than 30 ms from any true beat
  kick%    share of true kicks detected; kfalse = detections with no kick near
  settle   drift cases: seconds from the tempo change until the grid is on (1/8 beat) for 8 beats in a row

--flash adds a table for "Flash on: Kicks" (each detected kick flashes as heard) against "Beats" (the fired
grid beats), run through the app's flash limiter on a model of the light (full flash fading in 0.25 s):
  kpat%    share of true kicks with a kick flash within 80 ms after, at the Standard limit (kShow%: Show)
  klag50   median ms from the true kick to its flash, before any input latency (a sound card adds more)
  kcut     kick flashes the Standard limit held back (kcutS: Show)
  beat%    fire% of the grid beats after the Standard limit; bcut = grid beats it held back
and a table for the real mode (the light show run with "Flash on: Kicks", its flashes through the same model):
  kpat%, kShow%, klag50, kcut, kcutS   as above, from the flashes the light show fired
  kfalse   fired flashes with no true kick within 80 ms before
  col%     share of colour changes within 30 ms of a true beat (Beat colour jump, 1 beat per colour)
  colPer   colour changes per drum beat after the lock (1.0 = one per beat, as with "Beats")
"""

import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import neewerlux_audio as na  # noqa: E402

RATE = 48000
BLOCK = 480  # samples per simulated audio callback, 10 ms
rng = np.random.default_rng(1)


# --- sounds -------------------------------------------------------------------

def _bandNoise(n, lo, hi):
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / RATE)
    spec[(f < lo) | (f > hi)] = 0
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-12)


def _kick():
    t = np.arange(int(0.3 * RATE)) / RATE
    f = 50 + 70 * np.exp(-t / 0.03)
    x = np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.exp(-t / 0.12)
    x[:48] *= np.linspace(0, 1, 48)
    return x


def _realKick(build=0.013):
    """A kick as mastered house kicks measure: a click (over 2 kHz) on the beat, the body swelling in over
    `build` seconds after it. Its own noise, so the other sounds stay the same as with _kick()."""
    t = np.arange(int(0.3 * RATE)) / RATE
    f = 50 + 70 * np.exp(-t / 0.03)
    swell = np.where(t < build, 0.5 - 0.5 * np.cos(np.pi * t / build), 1.0)
    body = np.sin(2 * np.pi * np.cumsum(f) / RATE) * swell * np.exp(-np.maximum(t - build, 0) / 0.12)
    n = int(0.03 * RATE)
    spec = np.fft.rfft(np.random.default_rng(7).standard_normal(n))
    fr = np.fft.rfftfreq(n, 1.0 / RATE)
    spec[(fr < 2000) | (fr > 8000)] = 0
    click = np.fft.irfft(spec, n)
    click *= np.exp(-t[:n] / 0.004) / np.abs(click).max()
    body[:n] += 0.5 * click
    return body / np.abs(body).max()


def _clap():
    n = int(0.2 * RATE)
    t = np.arange(n) / RATE
    noise = _bandNoise(n, 900, 3500)
    env = np.zeros(n)
    for d in (0.0, 0.01, 0.02):  # a clap is a few quick bursts
        k = t >= d
        env[k] += np.exp(-(t[k] - d) / (0.006 if d < 0.02 else 0.07))
    return noise * env / env.max()


def _snare():
    n = int(0.2 * RATE)
    t = np.arange(n) / RATE
    return (0.7 * _bandNoise(n, 200, 6000) + 0.3 * np.sin(2 * np.pi * 185 * t)) * np.exp(-t / 0.06)


def _hat():
    n = int(0.06 * RATE)
    t = np.arange(n) / RATE
    return _bandNoise(n, 7000, 16000) * np.exp(-t / 0.015)


def _sub(seconds, hz=49.0):
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    env = np.minimum(1, t / 0.02) * np.minimum(1, (seconds - t) / 0.05).clip(0)
    return np.sin(2 * np.pi * hz * t) * env


SOUNDS = {"kick": (_kick(), 0.8), "clap": (_clap(), 0.35), "snare": (_snare(), 0.35), "hat": (_hat(), 0.08)}


# --- patterns -------------------------------------------------------------------

class Song:
    """Beat times plus sounds placed at beat positions. Positions are in beats from the first beat."""

    def __init__(self, beats):
        self.beats = np.asarray(beats, float)
        self.events = []      # (time, sound name, extra)
        self.kicks = []       # true kick times
        self.drumBeats = []   # beats where flashes are expected (drums playing)
        self.length = float(self.beats[-1] + 1.0)
        self.change = None    # time the tempo starts to change, for cases that change it
        self.sounds = {}      # per-case sounds, used before SOUNDS

    def at(self, pos):
        i = int(math.floor(pos))
        i = min(max(i, 0), len(self.beats) - 2)
        return self.beats[i] + (pos - i) * (self.beats[i + 1] - self.beats[i])

    def hit(self, name, pos, shift=0.0):
        t = self.at(pos) + shift
        self.events.append((t, name, None))
        if name == "kick":
            self.kicks.append(t)

    def sub(self, pos, beats, hz=49.0):
        t0, t1 = self.at(pos), self.at(pos + beats)
        self.events.append((t0, "sub", (t1 - t0, hz)))

    def bar(self, b, kicks=(), claps=(), snares=(), hats=(), drums=True):
        """One 4-beat bar at bar index b; each list holds beat positions inside the bar."""
        base = 4 * b
        for p in kicks:
            self.hit("kick", base + p)
        for p in claps:
            self.hit("clap", base + p)
        for p in snares:
            self.hit("snare", base + p)
        for p in hats:
            self.hit("hat", base + p)
        if drums:
            self.drumBeats.extend(self.beats[base:base + 4])

    def render(self):
        out = np.zeros(int((self.length + 1.0) * RATE))
        for t, name, extra in self.events:
            if name == "sub":
                x, gain = _sub(*extra), 0.3
            else:
                x, gain = self.sounds.get(name) or SOUNDS[name]
            i = int(round(t * RATE))
            n = min(len(x), len(out) - i)
            if n > 0:
                out[i:i + n] += gain * x[:n]
        return out / max(1.0, np.abs(out).max())


def _steady(bpm, seconds, start=0.5):
    return start + np.arange(int(seconds * bpm / 60.0) + 2) * 60.0 / bpm


def _ramp(bpm0, bpm1, rampFrom, rampTo, seconds, start=0.5):
    """Beat times for a tempo steady at bpm0, moving linearly to bpm1 between rampFrom and rampTo seconds."""
    beats, t = [start], start
    while t < seconds + start:
        frac = min(1.0, max(0.0, (t - rampFrom) / (rampTo - rampFrom))) if rampTo > rampFrom else float(t >= rampFrom)
        t += 60.0 / (bpm0 + (bpm1 - bpm0) * frac)
        beats.append(t)
    return beats


HOUSE = dict(kicks=(0, 1, 2, 3), claps=(1, 3), hats=(0.5, 1.5, 2.5, 3.5))


def house126():
    s = Song(_steady(126, 60))
    for b in range(len(s.beats) // 4 - 1):
        s.bar(b, **HOUSE)
    return s


def houseBuild():
    s = Song(_steady(126, 60))
    for b in range(len(s.beats) // 4 - 1):
        if 12 <= b < 14:
            s.bar(b, snares=np.arange(16) / 4.0, hats=(), drums=False)
        elif 14 <= b < 16:
            s.bar(b, snares=np.arange(32) / 8.0, drums=False)
        else:
            s.bar(b, **HOUSE)
    return s


def houseFillBreak():
    s = Song(_steady(126, 60))
    for b in range(len(s.beats) // 4 - 1):
        if b == 11:  # a one-bar fill: kick drops out, snare 16ths on the last two beats
            s.bar(b, kicks=(0,), snares=2 + np.arange(8) / 4.0, hats=(0.5, 1.5))
        elif 16 <= b < 24:  # breakdown: hats and long sub notes, no kicks
            s.bar(b, hats=(0.5, 1.5, 2.5, 3.5), drums=False)
            if b % 2 == 0:
                s.sub(4 * b, 8, 55.0)
        else:
            s.bar(b, **HOUSE)
    return s


def houseLongBreak():
    """House with a 32-bar breakdown (about 61 s, as on real tracks): hats and sub notes, no kicks."""
    s = Song(_steady(126, 100))
    for b in range(len(s.beats) // 4 - 1):
        if 8 <= b < 40:
            s.bar(b, hats=(0.5, 1.5, 2.5, 3.5), drums=False)
            if b % 2 == 0:
                s.sub(4 * b, 8, 55.0)
        else:
            s.bar(b, **HOUSE)
    return s


def silenceGap():
    """House with four bars of digital silence (a track ends, a deck is stopped), then the kicks again."""
    s = Song(_steady(126, 60))
    for b in range(len(s.beats) // 4 - 1):
        if not 12 <= b < 16:
            s.bar(b, **HOUSE)
    return s


def garage132():
    """2-step: kick on 1 and a syncopated one late in the bar, never on 2 or 4; clap on 2 and 4; swung hats."""
    s = Song(_steady(132, 60))
    swing = 0.1  # beats each off 16th is pushed late
    for b in range(len(s.beats) // 4 - 1):
        kicks = (0, 2.5) if b % 2 == 0 else (0, 1.75, 2.5)
        hats = [q + 0.5 for q in range(4)] + [q + 0.25 + swing for q in range(4)]
        s.bar(b, kicks=kicks, claps=(1, 3), hats=hats)
        s.sub(4 * b, 1.5, 49.0)
        s.sub(4 * b + 2.5, 1.0, 55.0)
    return s


def footwork160():
    """3-3-2 kicks, then a bar of triplet bursts; clap on beat 3 only; quiet 16th hats; sub under the kicks."""
    s = Song(_steady(160, 60))
    for b in range(len(s.beats) // 4 - 1):
        if b % 2 == 0:
            kicks = (0, 0.75, 1.5, 2, 2.75, 3.5)
        else:
            kicks = (0, 0.75, 1.5, 2, 2 + 1 / 3.0, 2 + 2 / 3.0, 3, 3.5)
        s.bar(b, kicks=kicks, claps=(2,), hats=np.arange(16) / 4.0)
        s.sub(4 * b, 0.75, 46.0)
        s.sub(4 * b + 2, 0.75, 52.0)
    return s


def dubstep140():
    """Half-time: kick on 1 (plus a pickup kick every other bar), snare and clap on 3, 8th hats; a long sub
    under each bar. Scored against 140, the tempo DJ software shows, though it feels like 70."""
    s = Song(_steady(140, 60))
    for b in range(len(s.beats) // 4 - 1):
        kicks = (0,) if b % 2 == 0 else (0, 2.75)
        s.bar(b, kicks=kicks, claps=(2,), snares=(2,), hats=np.arange(8) / 2.0)
        s.sub(4 * b, 3.5, 41.0 if b % 2 == 0 else 46.0)
    return s


def _note(seconds, hz, attack, harm=(1.0,)):
    t = np.arange(int(seconds * RATE)) / RATE
    x = sum(a * np.sin(2 * np.pi * hz * (k + 1) * t) for k, a in enumerate(harm))
    env = np.minimum(1, t / attack) * np.minimum(1, (seconds - t) / 0.02).clip(0)
    return x * env / np.abs(x).max()


def offbeatBass130():
    """Strobe-like techno: a kick whose body builds over 40 ms, and an off-beat bass note at x.52 as loud as
    the kick that jumps in within one hop; a sub pumping in after each kick, open hats on the off-beats."""
    P = 60 / 130.0
    s = Song(_steady(130, 60))
    r = np.random.default_rng(11)  # own noise, so the shared rng and the other cases stay the same
    n = int(0.12 * RATE)

    def noise(lo, hi):
        spec = np.fft.rfft(r.standard_normal(n))
        f = np.fft.rfftfreq(n, 1.0 / RATE)
        spec[(f < lo) | (f > hi)] = 0
        x = np.fft.irfft(spec, n)
        return x / np.abs(x).max()

    ohat = (noise(2500, 14000) + 0.4 * noise(300, 2000)) * np.exp(-np.arange(n) / RATE / 0.05)
    s.sounds = {"kick": (_realKick(build=0.04), 0.8), "ohat": (ohat, 0.2),
                "off": (_note(0.42 * P, 55.0, 0.006, (1.0, 0.6, 0.35)), 1.0),
                "pump": (_note(0.40 * P, 41.0, 0.1), 0.8)}
    for b in range(len(s.beats) // 4 - 1):
        s.bar(b, kicks=(0, 1, 2, 3), claps=(1, 3), hats=np.arange(16) / 4.0)
        for p in range(4):
            s.hit("ohat", 4 * b + p + 0.5)
            s.hit("off", 4 * b + p + 0.52)
            s.hit("pump", 4 * b + p, shift=0.04)
    return s


def fast200():
    s = Song(_steady(200, 60))
    for b in range(len(s.beats) // 4 - 1):
        s.bar(b, **HOUSE)
    return s


def driftRamp():
    s = Song(_ramp(120, 126, 15, 45, 60))
    s.change = 15.0
    for b in range(len(s.beats) // 4 - 1):
        s.bar(b, **HOUSE)
    return s


def driftJump():
    s = Song(_ramp(120, 124, 30, 30, 60))
    s.change = 30.0
    for b in range(len(s.beats) // 4 - 1):
        s.bar(b, **HOUSE)
    return s


def driftJump6():
    """120 -> 127 at once: over the 4% relock, so the tracker locks again instead of following."""
    s = Song(_ramp(120, 127, 30, 30, 60))
    s.change = 30.0
    for b in range(len(s.beats) // 4 - 1):
        s.bar(b, **HOUSE)
    return s


def strayKick():
    s = Song(_steady(124, 60))
    for b in range(len(s.beats) // 4 - 1):
        s.bar(b, kicks=(1, 2, 3) if b == 16 else (0, 1, 2, 3), claps=(1, 3), hats=(0.5, 1.5, 2.5, 3.5))
    s.hit("kick", 64, shift=0.04)  # bar 16's first kick lands 40 ms late
    return s


# The tempo range a user would set for these cases' genres, tried in a second table by default.
GENRE_RANGES = {"footwork160": (150, 170), "fast200": (170, 210), "dubstep140": (130, 150)}

CASES = {"house126": house126, "houseBuild": houseBuild, "houseFillBreak": houseFillBreak, "houseLongBreak": houseLongBreak,
         "silenceGap": silenceGap,
         "garage132": garage132, "footwork160": footwork160, "fast200": fast200,
         "dubstep140": dubstep140, "offbeatBass130": offbeatBass130,
         "driftRamp": driftRamp, "driftJump": driftJump, "driftJump6": driftJump6, "strayKick": strayKick}


# --- input variants ---------------------------------------------------------------

def laptopMic(x):
    """A guess at a laptop mic across a room: bass rolled off under ~150 Hz, room reverb, a noise floor."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1.0 / RATE)
    hp = (f / 150.0) ** 2 / np.sqrt(1 + (f / 150.0) ** 4)  # second-order high-pass
    lp = 1 / np.sqrt(1 + (f / 9000.0) ** 4)
    y = np.fft.irfft(np.fft.rfft(x) * hp * lp, n)
    tail = int(0.4 * RATE)
    ir = rng.standard_normal(tail) * np.exp(-np.arange(tail) / (0.08 * RATE))
    ir *= 0.25 / np.sqrt((ir ** 2).sum())
    size = 1 << int(math.ceil(math.log2(n + tail)))
    wet = np.fft.irfft(np.fft.rfft(y, size) * np.fft.rfft(ir, size), size)[:n]
    y = y + wet
    y = y / (np.abs(y).max() + 1e-12) * 0.3  # quieter than a line feed
    return y + 0.003 * rng.standard_normal(n)


def lineIn(x):
    """A line feed: the music plus a -80 dB noise floor."""
    return x + 1e-4 * rng.standard_normal(len(x))


def digital(x):
    """A digital feed with exact silence between sounds, as from a loopback device. Hops under the
    silence floor once dropped out of the tempo history, which squeezed its time and read the tempo fast."""
    return x


VARIANTS = {"clean": lineIn, "mic": laptopMic, "digital": digital}


# --- running ---------------------------------------------------------------------

def run(samples, window=None, tempoRange=None, flashOn="Beats", colours=None):
    """Feed samples through the analyser and light show in simulated time. Returns what happened;
    the times the colour changed go into colours, when given."""
    if window is not None:
        na.TEMPO_WINDOW, na.TEMPO_MIN_SECONDS = window, window / 2.0
    engine = na.SoundEngine(lambda frame: True, logFunc=lambda *a: None)
    if tempoRange:
        engine.tempoMin, engine.tempoMax = tempoRange
    engine.mode = "Beat colour jump"
    engine.flashOn = flashOn
    engine.targets = [0]
    engine.clockLeadMs = 0  # fired beats should then land on the true beats themselves
    analyser = na._Analyser(RATE)
    show = na._LightShow(engine, analyser)
    show.lastFull = show.lastFrame = show.lastT = 0.0

    kicks = []
    origKick = analyser.tempo.kick

    def kick(t, *a):
        kicks.append(t)
        origKick(t, *a)
    analyser.tempo.kick = kick

    log = []   # (time, locked, bpm) sampled every block
    fired = []
    lastBeat = show.lastBeat
    lastJump = show.jumpAt
    now, i, nextBlock = 0.0, 0, BLOCK / RATE
    end = len(samples) / RATE
    tempo = analyser.tempo
    while now < end:
        if now >= nextBlock - 1e-9:
            analyser.feed(samples[i:i + BLOCK].astype(np.float32), nextBlock, 1.0)
            i += BLOCK
            nextBlock += BLOCK / RATE
            log.append((now, tempo.locked, tempo.period, tempo.refT, tempo.refPos))
        wait = show.step(now)
        if show.lastBeat != lastBeat:
            lastBeat = show.lastBeat
            fired.append(lastBeat)
        if show.jumpAt != lastJump:
            lastJump = show.jumpAt
            if colours is not None:
                colours.append(lastJump)
        now = min(nextBlock, now + wait) if wait else now + 1e-4
    return log, np.array(fired), np.array(kicks)


def _ratioName(r):
    best = min(((abs(math.log(r / v)), name) for v, name in
                ((0.5, "1/2"), (2 / 3.0, "2/3"), (0.75, "3/4"), (1.0, "1"), (4 / 3.0, "4/3"), (1.5, "3/2"), (2.0, "2"))))
    return best[1] if best[0] < 0.03 else "%.2f" % r


def score(song, log, fired, kicks):
    beats = song.beats[song.beats < song.length - 0.5]
    times = np.array([e[0] for e in log])
    lockT = next((e[0] for e in log if e[1]), None)
    row = {"lock": lockT}
    # The grid at each true beat, read from the tracker state at that moment.
    ratios, offs = [], []
    onAfter = []  # (beat time, grid within 1/8 beat) for beats after a tempo change
    for k, b in enumerate(beats[:-1]):
        j = int(np.searchsorted(times, b)) - 1
        if j < 0 or not log[j][1]:
            if song.change is not None and b >= song.change:
                onAfter.append((b, False))
            continue
        _, _, period, refT, refPos = log[j]
        trueP = beats[k + 1] - b
        ratios.append(trueP / period)
        pos = refPos + (b - refT) / period
        offs.append((pos - round(pos), period))
        if song.change is not None and b >= song.change:
            onAfter.append((b, abs(pos - round(pos)) <= 0.125))
    if onAfter:
        run_ = 0
        for i, (b, ok) in enumerate(onAfter):
            run_ = run_ + 1 if ok else 0
            if run_ == 8:
                row["settle"] = float(onAfter[i - 7][0] - song.change)
                break
    if ratios:
        r = float(np.median(ratios))
        row["ratio"] = _ratioName(r)
        frac = np.array([o for o, _ in offs])
        on = np.abs(frac) <= 0.125
        half = np.abs(frac) >= 0.375
        row["on%"] = 100.0 * on.mean()
        row["sits"] = max((("on", on.mean()), ("half", half.mean()), ("qtr", 1 - on.mean() - half.mean())), key=lambda x: x[1])[0]
        err = np.abs([o * p * 1000 for (o, p), k in zip(offs, on) if k])
        if row["ratio"] == "1" and len(err):
            row["grid50"], row["grid90"] = float(np.median(err)), float(np.percentile(err, 90))
    # Fired beats against the beats in drum sections, after the lock.
    drum = np.array([b for b in song.drumBeats if lockT is not None and b > lockT + 0.5])
    if len(drum) and len(fired):
        d = np.array([fired[np.argmin(np.abs(fired - b))] - b for b in drum])
        hit = np.abs(d) <= 0.03
        row["fire%"] = 100.0 * hit.mean()
        if hit.any():
            row["fire50"] = float(np.median(d[hit]) * 1000)
    if len(fired):
        allB = song.beats
        row["extra"] = int(sum(np.min(np.abs(allB - f)) > 0.03 for f in fired if lockT is not None and f > lockT))
    if song.kicks:
        tk = np.sort(song.kicks)
        if len(kicks):
            found = [np.any((kicks >= t - 0.01) & (kicks <= t + 0.08)) for t in tk]
            row["kick%"] = 100.0 * np.mean(found)
            row["kfalse"] = int(sum(not np.any((tk >= k - 0.08) & (tk <= k + 0.01)) for k in kicks))
        else:
            row["kick%"], row["kfalse"] = 0.0, 0
    return row


COLS = ("lock", "ratio", "on%", "sits", "grid50", "grid90", "fire%", "fire50", "extra", "kick%", "kfalse", "settle")


def throughLimit(times, level, fps=30.0):
    """The flashes at these times that get through the flash limit at this level. A model, not the light show:
    each flash jumps to full brightness and fades out in 0.25 s (as the beat flash does), with frames at fps
    plus one at each flash."""
    times = np.sort(np.asarray(times, float))
    if not len(times):
        return times
    maxSwings = na.FLASH_LEVELS[level][0]
    lim = na._FlashLimiter()
    frames = np.union1d(np.arange(0.0, times[-1] + 1.0, 1.0 / fps), times)
    flash, last, prevOut, k, passed = 0.0, 0.0, None, 0, []
    for t in frames:
        flash = max(0.0, flash - (t - last) * 4.0)
        last = t
        new = k < len(times) and t >= times[k] - 1e-9
        if new:
            flash = 1.0
            while k < len(times) and t >= times[k] - 1e-9:
                k += 1
        out = lim.step(100.0 * flash, t, maxSwings)
        if new and prevOut is not None and out - prevOut >= na.FLASH_SWING:
            passed.append(t)
        prevOut = out
    return np.array(passed)


FLASH_COLS = ("kpat%", "klag50", "kcut", "kShow%", "kcutS", "beat%", "bcut")


def scoreFlash(song, log, fired, kicks):
    """"Flash on: Kicks" against "Beats": how much of the kick pattern shows, how late, and what the limit cuts."""
    row = {}
    tk = np.sort(song.kicks)
    lockT = next((e[0] for e in log if e[1]), None)
    for level, pat, cut in (("Standard", "kpat%", "kcut"), ("Show", "kShow%", "kcutS")):
        shown = throughLimit(kicks, level)
        row[cut] = len(kicks) - len(shown)
        if len(tk):
            hits = [shown[(shown >= t - 0.01) & (shown <= t + 0.08)] for t in tk]
            row[pat] = 100.0 * np.mean([len(h) > 0 for h in hits])
            if level == "Standard":
                lags = [1000 * (h[0] - t) for h, t in zip(hits, tk) if len(h)]
                if lags:
                    row["klag50"] = float(np.median(lags))
    shown = throughLimit(fired, "Standard")
    row["bcut"] = len(fired) - len(shown)
    drum = np.array([b for b in song.drumBeats if lockT is not None and b > lockT + 0.5])
    if len(drum) and len(shown):
        row["beat%"] = 100.0 * np.mean([np.min(np.abs(shown - b)) <= 0.03 for b in drum])
    return row


REAL_COLS = ("kpat%", "klag50", "kcut", "kShow%", "kcutS", "kfalse", "col%", "colPer")


def scoreReal(song, log, fired, kicks, colours):
    """The light show run with "Flash on: Kicks": its own flashes against the kick pattern, its colour changes against the beats."""
    row = scoreFlash(song, log, fired, fired)
    for c in ("beat%", "bcut"):
        row.pop(c, None)
    tk = np.sort(song.kicks)
    if len(tk):
        row["kfalse"] = int(sum(not np.any((tk >= f - 0.08) & (tk <= f + 0.01)) for f in fired))
    lockT = next((e[0] for e in log if e[1]), None)
    col = np.array([c for c in colours if lockT is not None and c > lockT + 0.5])
    if len(col):
        row["col%"] = 100.0 * np.mean([np.min(np.abs(song.beats - c)) <= 0.03 for c in col])
        drum = [b for b in song.drumBeats if b > lockT + 0.5]
        if drum:
            row["colPer"] = len(col) / float(len(drum))
    return row


def printTable(rows, title, cols=COLS):
    print("\n" + title)
    head = "%-30s" % "case" + "".join("%8s" % c for c in cols)
    print(head)
    print("-" * len(head))
    for name, row in rows:
        cells = []
        for c in cols:
            v = row.get(c)
            cells.append("%8s" % ("-" if v is None else ("%.1f" % v if isinstance(v, float) else v)))
        print("%-30s" % name + "".join(cells))


def nmlGrid(nml, path):
    """Traktor's beat grid for this file from a collection .nml, matched by file name: (BPM, anchor
    in seconds) from the AutoGrid cue, or (BPM, None) when the entry has only a tempo."""
    import xml.etree.ElementTree as ET
    name = os.path.basename(path)
    for e in ET.parse(nml).getroot().iter("ENTRY"):
        loc = e.find("LOCATION")
        if loc is None or loc.get("FILE") != name:
            continue
        for cue in e.iter("CUE_V2"):
            grid = cue.find("GRID")
            if cue.get("TYPE") == "4" and grid is not None:
                return float(grid.get("BPM")), float(cue.get("START")) / 1000.0
        tempo = e.find("TEMPO")
        if tempo is not None:
            return float(tempo.get("BPM")), None
    sys.exit("%s: no BPM for %s" % (nml, name))


def traktorOffset(path):
    """Seconds by which Traktor's timeline runs ahead of the decoded audio (Traktor time = decoded time + this),
    as measured to the sample in dj-tools (track-analyzer traktor.audio_offset): an MP3 adds 1152 samples for a
    Xing/Info header frame plus the LAME delay ffmpeg skips (its start_time); an m4a with an edit list subtracts
    the AAC priming, which ffmpeg trims and Traktor doesn't play. Other formats: 0."""
    import json
    import subprocess
    ext = os.path.splitext(path)[1].lower()
    probe = lambda *a: subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", *a, "-of", "json", path],
                                      capture_output=True, text=True).stdout
    try:
        if ext == ".mp3":
            j = json.loads(probe("-show_entries", "stream=start_time,sample_rate"))["streams"][0]
            sr = int(j["sample_rate"])
            with open(path, "rb") as f:
                h = f.read(10)
                f.seek(10 + ((h[6] << 21) | (h[7] << 14) | (h[8] << 7) | h[9]) + (10 if h[5] & 0x10 else 0)
                       if h[:3] == b"ID3" else 0)
                b = f.read(4096)
            k = next((i for i in range(len(b) - 1) if b[i] == 0xFF and b[i + 1] & 0xE0 == 0xE0), None)
            info = k is not None and (b.find(b"Xing", k, k + 200) != -1 or b.find(b"Info", k, k + 200) != -1)
            return (round(float(j.get("start_time", 0)) * sr) + (1152 if info else 0)) / sr
        if ext in (".m4a", ".mp4"):
            j = json.loads(probe("-read_intervals", "%+#1", "-show_entries", "packet=pts_time:stream=sample_rate"))
            return min(0.0, float(j["packets"][0]["pts_time"]))
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return 0.0


def kickOnsets(x):
    """Offline kick onsets from the whole track: the rise of the 40-160 Hz envelope at 1 ms steps.
    Returns (times, strengths) of the local peaks of that rise."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / RATE)
    spec[(f < 40) | (f > 160)] = 0
    low = np.fft.irfft(spec, len(x))
    hop = RATE // 1000
    env = np.sqrt(np.add.reduceat(low * low, np.arange(0, len(low), hop)) / hop)
    env = np.convolve(env, np.ones(5) / 5, "same")
    rise = np.maximum(np.diff(env, prepend=env[0]), 0)
    rise = np.convolve(rise, np.ones(3) / 3, "same")
    # Peaks: the biggest rise within 60 ms either side, above a floor.
    from numpy.lib.stride_tricks import sliding_window_view
    pad = np.pad(rise, 60)
    peak = (rise == sliding_window_view(pad, 121).max(axis=1)) & (rise > 0.1 * np.percentile(rise, 99.5))
    idx = np.nonzero(peak)[0]
    return idx / 1000.0, rise[idx]


def fitGrid(times, w, bpm):
    """Fixed tempo near bpm (within 0.2%) and its phase, fitted over the whole track: the tempo whose
    grid gathers the kick onsets tightest. Returns (bpm, first beat, concentration 0-1)."""
    best = None
    for b in np.linspace(bpm * 0.998, bpm * 1.002, 161):
        p = 60.0 / b
        z = np.sum(w * np.exp(2j * np.pi * times / p))
        r = abs(z) / w.sum()
        if best is None or r > best[2]:
            best = (b, (np.angle(z) / (2 * np.pi) * p) % p, r)
    b, t0, r = best
    p = 60.0 / b
    # Refine the phase: weighted median offset of the strong onsets near the grid.
    off = (times - t0 + p / 2) % p - p / 2
    near = np.abs(off) < 0.04
    if near.any():
        o, ww = off[near], w[near]
        k = np.argsort(o)
        t0 += o[k][np.searchsorted(np.cumsum(ww[k]), ww.sum() / 2)]
    return b, t0 % p, r


def songFromFile(path, bpm, firstBeat, beatsFile):
    import soundfile  # uv run --with soundfile
    try:
        x, rate = soundfile.read(path, always_2d=True)
        x = x.mean(axis=1)
    except soundfile.LibsndfileError:  # m4a and the like: decode with ffmpeg
        import subprocess
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
                             check=True, capture_output=True).stdout
        x, rate = np.frombuffer(raw, np.float32).astype(float), RATE
    if rate != RATE:  # plain linear resample is enough for beat tracking
        x = np.interp(np.arange(int(len(x) * RATE / rate)) * rate / RATE, np.arange(len(x)), x)
    onsets = None
    if beatsFile:
        beats = np.loadtxt(beatsFile)
    else:
        if firstBeat == "auto":
            onsets = kickOnsets(x)
            fit, firstBeat, r = fitGrid(onsets[0], onsets[1], bpm)
            print("auto grid: %.3f BPM (given %.3f), first beat %.3f s, onset concentration %.2f" % (fit, bpm, firstBeat, r))
            bpm = fit
        beats = np.arange(float(firstBeat), len(x) / RATE, 60.0 / bpm)
    s = Song(beats)
    s.length = len(x) / RATE
    if onsets is None:
        s.drumBeats = list(beats)  # unknown sections: every beat counts, so fire% reads low through breakdowns
    else:
        # Beats with a clear kick onset within 25 ms count as kicks and drum beats; the rest
        # (breakdowns, intros without a kick) are left out of fire% and kick%.
        t, w = onsets
        j = np.clip(np.searchsorted(t, beats), 1, len(t) - 1)
        j = np.where(np.abs(t[j - 1] - beats) < np.abs(t[j] - beats), j - 1, j)
        hasKick = (np.abs(t[j] - beats) <= 0.025) & (w[j] > 0.25 * np.median(w[j]))
        s.kicks = list(beats[hasKick])
        s.drumBeats = list(beats[hasKick])
        print("kicks on %d of %d beats" % (hasKick.sum(), len(beats)))
    return s, x


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", choices=sorted(CASES), help="run one synthetic case")
    ap.add_argument("--variant", choices=sorted(VARIANTS), help="only this input variant")
    ap.add_argument("--sweep", action="store_true", help="also run with tempo windows of 4, 6, 12 and 16 s")
    ap.add_argument("--window", type=float, help="tempo window in seconds (default: the app's)")
    ap.add_argument("--range", type=float, nargs=2, metavar=("LO", "HI"),
                    help="tempo range in BPM for every input (default: the app's, plus a genre-range table)")
    ap.add_argument("--file", help="score a real track instead (needs --bpm and --first-beat, or --beats)")
    ap.add_argument("--bpm", type=float)
    ap.add_argument("--first-beat", default="0", help='seconds, or "auto" to fit it (and the BPM within 0.2%%) from the kicks')
    ap.add_argument("--nml", help="take the BPM and beat grid from this Traktor collection (.nml), by file name; "
                    "without a grid anchor the first beat is fitted as with --first-beat auto")
    ap.add_argument("--beats", help="text file with one true beat time per line")
    ap.add_argument("--kick", choices=("synth", "real"), default="synth",
                    help="synthetic kick sound: synth (body from the first sample) or real (click, body 13 ms later)")
    ap.add_argument("--flash", action="store_true", help='also a "Flash on: Kicks" against "Beats" table')
    args = ap.parse_args()
    if args.kick == "real":
        SOUNDS["kick"] = (_realKick(), 0.8)

    default = na.TEMPO_WINDOW
    windows = [args.window or default] + ([w for w in (4.0, 6.0, 12.0, 16.0) if w != default] if args.sweep else [])
    if args.file:
        bpm, fb = args.bpm, args.first_beat
        if args.nml:
            gridBpm, anchor = nmlGrid(args.nml, args.file)
            bpm = bpm or gridBpm
            if anchor is not None and fb in ("0", "auto"):
                shift = traktorOffset(args.file)
                fb = (anchor - shift) % (60.0 / bpm)
                print("nml grid: %.4f BPM, first beat %.3f s (Traktor's timeline %.1f ms ahead of the decode)"
                      % (bpm, fb, shift * 1000))
            elif fb == "0":
                fb = "auto"  # no anchor in the collection: fit it
        fb = fb if fb == "auto" else float(fb)
        song, x = songFromFile(args.file, bpm, fb, args.beats)
        inputs = [(os.path.basename(args.file), song, x)]
    else:
        names = [args.case] if args.case else list(CASES)
        inputs = []
        for name in names:
            song = CASES[name]()
            raw = song.render()
            for v in ([args.variant] if args.variant else list(VARIANTS)):
                inputs.append(("%s/%s" % (name, v), song, VARIANTS[v](raw)))
    rangeNote = " range %g-%g BPM" % tuple(args.range) if args.range else ""
    flashRows, realRows = [], []
    for w in windows:
        rows = []
        for label, song, x in inputs:
            result = run(x, w, args.range)
            rows.append((label, score(song, *result)))
            if w == windows[0]:
                flashRows.append((label, scoreFlash(song, *result)))
                if args.flash:
                    colours = []
                    real = run(x, w, args.range, "Kicks", colours)
                    realRows.append((label, scoreReal(song, *real, colours)))
        printTable(rows, "Tempo window %.0f s%s%s (synthetic results are provisional until checked on real tracks)"
                   % (w, " (app default)" if w == default else "", rangeNote))
    if args.flash:
        printTable(flashRows, "Flash on: Kicks against Beats, tempo window %.0f s%s (light model; no input latency)"
                   % (windows[0], rangeNote), FLASH_COLS)
        printTable(realRows, 'The light show with "Flash on: Kicks", tempo window %.0f s%s (light model; no input latency)'
                   % (windows[0], rangeNote), REAL_COLS)
    genre = [(label, song, x, GENRE_RANGES[label.split("/")[0]]) for label, song, x in inputs
             if label.split("/")[0] in GENRE_RANGES]
    if genre and not args.range and not args.file:
        rows = [("%s %g-%g" % ((label,) + r), score(song, *run(x, args.window, r))) for label, song, x, r in genre]
        printTable(rows, "Genre tempo ranges, tempo window %.0f s" % (args.window or default))


if __name__ == "__main__":
    main()
