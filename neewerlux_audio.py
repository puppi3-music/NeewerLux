# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Puppi3
"""Sound-reactive lighting for NeewerLux.

Listens to an audio input device, analyses it a number of times per second and
turns the result into a hue, saturation and brightness for each light.

To react to what your computer is playing (rather than a microphone), route the
output into a loopback device and pick that device here:

  macOS    BlackHole (https://existential.audio/blackhole/). Make a Multi-Output
           Device in Audio MIDI Setup with your speakers + BlackHole, set it as
           the system output, then choose "BlackHole" in the Sound tab.
  Windows  enable "Stereo Mix" in Sound settings, or install VB-Cable.
  Linux    pick a "Monitor of ..." entry: no routing needed. PortAudio's ALSA
           backend can't list PulseAudio/PipeWire monitors, so they are read from
           pactl and recorded through ALSA's "pulse" device (see _linuxMonitors).

This module has no Qt dependency. The GUI reads SoundEngine.state for meters and
the engine calls sendFunc({lightIndex: (hue, sat, bri)}) to change the lights.
sounddevice and numpy are optional: AUDIO_AVAILABLE is False without them.

Times are time.perf_counter(), shared with neewerlux_midi: before Python 3.13,
time.monotonic() only moves every 15.6 ms on Windows.
"""

import colorsys
import contextlib
import math
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque

try:
    import numpy as np
    import sounddevice as sd
    AUDIO_AVAILABLE = True
    AUDIO_IMPORT_ERROR = ""
except Exception as e:  # ImportError, or OSError when PortAudio is missing
    np = None
    sd = None
    AUDIO_AVAILABLE = False
    AUDIO_IMPORT_ERROR = str(e)
    if sys.platform.startswith("linux") and isinstance(e, OSError):  # the Linux wheel doesn't include PortAudio
        AUDIO_IMPORT_ERROR += "; install PortAudio from your distribution, e.g. libportaudio2"

# Mode names, shown in the UI in this order.
MODES = [
    "Spectrum colour",    # hue follows the pitch of the sound, brightness follows loudness
    "Beat colour jump",   # hue jumps on each beat, brightness follows the bass
    "Bass pulse",         # colour and brightness both follow how hard the bass hits
    "Frequency bands",    # lights split into bass / mid / high, each with its own colour
    "Rainbow drift",      # hue keeps moving, faster when the music is louder
]

MODE_HELP = {
    "Spectrum colour": "Low sounds take the first palette colour, high sounds the last (Auto: bass red/orange, vocals green, hats blue/violet). Brightness follows loudness.",
    "Beat colour jump": "Each detected beat moves to another palette colour (Auto: any colour), gliding there over part of the time until the next change: Colour fade 75% fills three quarters of it, 95% fades continuously, 0 cuts hard. Brightness follows the bass while kicks play and flashes on the beat. A loud sound with no kicks holds it up, its colour following the notes (the same chord comes back in the same colour), or changing each bar if the notes don't.",
    "Bass pulse": "Brightness pumps with the kicks and the bass under them, and the colour follows how hard it hits: soft bass on the first palette colour, hard kicks and each beat toward the last (stays blue on Auto).",
    "Frequency bands": "Light 1 = bass, light 2 = mids, light 3 = highs, repeating, in palette colours 1-3 (Auto: red, green, blue). One light blends all three.",
    "Rainbow drift": "Slides through the palette colours (Auto: the whole colour wheel), faster when it is louder. Beats give it a push.",
}

# Frequency band edges in Hz.
BASS = (20, 160)
MID = (160, 2000)
HIGH = (2000, 15000)

FFT_SIZE = 2048
QUIET_RATIO = 0.18  # level (fourth root of power) below this share of the music level counts as quiet, about -30 dB
QUIET_HOLD = 1.5    # seconds of quiet before MIDI clock beats pause
NOISE_MARGIN = 1.5  # music must be this far over the noise floor (fourth-root scale, about +7 dB) to count
HOP = 512           # samples analysed per step, about 94 steps a second at 48 kHz
ANALYSIS_RATE = 48000  # Hz: faster devices are brought down to about this, see _Decimator
BANDS_PER_OCTAVE = 3
LEVELS = ("level", "bass", "mid", "high")
SILENCE = 1e-7      # mean power below this is an effectively silent stream
GAIN_WINDOW = 3.0   # seconds of each level the auto-gain looks back over, several beats' worth
GAIN_PERCENTILES = (10, 95)  # the parts of that history that map to 0 and 1
GAIN_MIN_SPAN = 0.2  # the 0..1 range never gets narrower than this share of its top (fourth-root scale)
KICK = (40, 160)    # Hz: where kick drums are looked for
KICK_MIN_RISE = 0.12  # a kick raises the bass by at least this much (log10 power, about 1.2 dB per bin) over the typical rise
KICK_SHARE = 0.7      # ... and reaches this share of the strongest rise in the last 1.5 s
KICK_ABS_RISE = 0.6    # ... and at least this much (6 dB a bin); kicks measure 1-2.5
KICK_GUIDED_WINDOW = 0.06  # seconds: a rise this close to where the beat grid puts a kick has a lower bar to clear
KICK_GUIDED_SHARE = 0.35   # ... this share of the strongest recent rise, as soft kicks sit well under the loud ones
KICK_GUIDED_RISE = 0.35    # ... at least this much
KICK_GUIDED_SPREAD = 1.5   # ... and this many spreads over the typical rise, not 3
KICK_GUIDED_AGREE = 0.5    # with a MIDI clock, only while this share of recent kicks agree with the offset learned, as a stale one would let in the wrong beats
KICK_GUIDED_FIRM = 0.06    # seconds: a guided kick whose rise clears the usual bar within this long was a full kick all along
FIRST_KICK_GAP = 1.5   # seconds without a kick before the next one counts as a first kick
FIRST_KICK_BEATS = 2.5  # ... or this many usual gaps between kicks, so a short break at a fast tempo counts too
FIRST_KICK_SHORTEST = 1.0  # ... though never fewer seconds than this
FIRST_KICK_WEIGHT = 0.5  # a first kick rises from quiet, so it reads higher than the kicks after it
MIN_BEAT_GAP = 0.18   # seconds: kicks closer than this count once
KICK_ON_BEAT = 0.06   # seconds: with a MIDI clock, a kick must land this close to a whole beat, or to where kicks have been landing against it
KICK_PHASE_KEEP = 16   # recent kicks remembered to learn how far the clock sits from the sound (input and MIDI delays differ per setup)
KICK_PHASE_MIN = 6     # kicks needed before going by them
KICK_PHASE_SHARE = 0.4 # share of those that must land together
KICK_PHASE_MAX = 0.14  # seconds the clock may sit from the sound, and never over 0.3 of a beat, so off-beat bass can't be learned as the kick
KICK_PHASE_FAR_SHARE = 0.6  # share that must land together for a phase further off than that: a clock can sit anywhere against the sound, but it takes strong agreement
KICK_PHASE_FAR_KICKS = 8    # ... counted out of at least this many, so a few off-beat bass notes at the start can't set it
KICK_HOLD_BEATS = 2.25  # beats after a kick that kicks still count as playing (so a kick every 2 beats keeps them on)
KICKLESS_BASS = 0.2   # share of the bass that still reaches the brightness in the beat modes while no kicks play
TEMPO_MIN_BPM, TEMPO_MAX_BPM = 70, 180
SUSTAIN_FROM = 0.65    # share of the loudness with kicks at which a sound with no kicks starts to hold the lights up
SUSTAIN_FULL = 0.82    # ... and the share at which it holds them fully
SUSTAIN_TOP = 0.75     # how high a sound with no kicks holds the lights, leaving room for flashes above it
SUSTAIN_BEAT_TOP = 0.45  # ... or this high when beats are known, so the flash on each beat has room to show
SUSTAIN_FLASH = 0.5    # sustained sound above this flashes on each beat of the clock or detected tempo
SUSTAIN_FADE = 2.5     # share of full brightness per second those flashes fade, slower than a kick's since no kick adds body
SUSTAIN_KICK_HOLD = 1.25  # beats after a kick that kicks still count as playing during sustained sound, so a stray rise can't hold the flashes off
SUSTAIN_DECAY = 0.005  # share per second the loudness with kicks is forgotten, so a quieter next track still counts
SUSTAIN_COLOUR_BEATS = 4  # beats per colour change while a sound with no kicks holds the lights up
SUSTAIN_CHECK = 0.3    # sustained sound above this: rises off the detected tempo's beats aren't kicks

TEMPO_WINDOW = 8.0      # seconds of attacks the tempo is found from
TEMPO_MIN_SECONDS = 4.0  # ... and the least it needs
TEMPO_FIT_EVERY = 0.25  # seconds between estimates
TEMPO_HARMONIC = 0.5    # weight of the repeat two beats on
TEMPO_FAST_SHARE = 0.6  # ... see _estimate
TEMPO_MIN_CONF = 0.15   # autocorrelation at the beat period needed to trust it
TEMPO_COAST = 60.0      # seconds a tempo is held through a section with no clear beat, as a track keeps its tempo through a breakdown
TEMPO_COAST_AGREE = 16  # estimates in a row (4 s) that must agree before a pulse heard in such a section replaces the held tempo
TEMPO_RESNAP = 0.04     # seconds: two kicks this close to a whole number of beats apart end the hold and set where the beats fall
ONSET_DELAY = 0.025     # seconds the detected attack lags the real one (measured on synthetic kicks)
ROLL = (180, 1500)      # Hz: where snare rolls are looked for
ROLL_WINDOW = 1.5       # seconds of that band each estimate looks at
ROLL_HIT = (0.096, 0.18)  # seconds between hits that count as a roll, about 16ths at 85-155 BPM
ROLL_START, ROLL_END = 0.5, 0.28  # how strongly the hits must repeat over ROLL_WINDOW to keep a roll (a build's broken patterns read about 0.3 between their fills)
ROLL_QUICK = 0.75       # seconds of that band the first look at a new roll takes, so it starts within about a beat and a half
ROLL_QUICK_START = 0.8  # how alike hits must be in that shorter look to start a roll
ROLL_QUICK_OVERLAP = 8  # analysis steps the shorter look must be able to compare at any hit spacing
ROLL_EVEN_GAPS = 5       # evenly spaced gaps between hits in a row that start a roll on their own, about 3/4 s at 128 BPM
ROLL_EVEN_LOOK = 0.9     # seconds of that band searched for them
ROLL_EVEN_DEPTH = 4.0    # dB a hit must stand above the band around it
ROLL_EVEN_SLACK = 0.022  # seconds the gaps between those hits may differ by
ROLL_EVEN_HOLD = 1.0     # seconds a roll stays on after such hits, until the longer looks have caught up
ROLL_KEEP_GAPS, ROLL_KEEP_DEPTH = 3, 3.0  # the looser test that keeps a roll going once it has started
ROLL_MIN_DEPTH = 2.0    # dB the band must pulse by
ROLL_BASS_ROOM = 9.0    # dB the band may sit under the bass during a roll: builds often keep the kick going under it, running grooves sit 17 dB or more under
ROLL_DROP_ROOM = 13.0   # dB under the bass that means the drop has landed
ROLL_UNDER_BASS_EVEN = 1.5  # seconds of unbroken even hits that start a roll under the bass, as a groove's 16ths are also even for a moment
ROLL_NEAR_BASS = 6.0    # dB under the bass that counts as a roll rising through it, as a groove's hits sit far lower
ROLL_NEAR_BASS_EVEN = 0.5  # seconds of even hits that start a roll this close to the bass
ROLL_FIT_EVERY = 0.125  # seconds between estimates
ROLL_FLASH_SHARE = 0.6  # share of the time between hits each flash takes to fade out
ROLL_ACCENT_SHARE = 0.8  # share of the time between accents each one takes to fade
FLASH_SWING = 9          # brightness points: a swing this big counts as half a flash (the guideline says 10; rounding and skipped small sends take up the difference) ...
FLASH_BRIGHT = 80        # ... unless its darker end is at this brightness or above
# Per level: (swings a light may make within FLASH_WINDOW, seconds roll accents must be apart). Swings are one under
# twice the flashes, as a swing that was held back lands just after the last; any closer and the limit cuts accents unevenly.
FLASH_LEVELS = {"Standard": (7, 0.30), "Show": (19, 0.105), "Off": (None, 0.0)}  # 4 and 10 flashes a second, and no limit
FLASH_WINDOW = 1.0       # seconds
FLASH_BURST = 4.0        # seconds a light may flash above the Standard rate, added up over dips, before it falls back to that rate
FLASH_BURST_REST = 8.0   # seconds it must then stay at or under the Standard rate before it may go above it again
BEAT_SETTLE = 0.15       # seconds after a beat its kick may still be rising, as a predicted beat can land just before it
FLASH_BEAT_RESERVE = 4  # swings a rise that isn't a beat must leave free while kicks play: its own fall and the next kick's rise and fall, so bass between kicks can't use them up
ROLL_BUILD_STEP = 2.0    # seconds of a roll at the Show level between halvings of the gap between its deep flashes
ROLL_SWING_MAX = 8       # brightness points the ripple between accents may move, too little to count as a flash
ROLL_SWING_RED = 6       # ... or in saturated red
ROLL_SWELL_TIME = 8.0    # seconds a Swell takes to climb to Max bright
ROLL_SWELL_FROM = 0.25   # highest point of the Min to Max bright range a Swell starts from
ROLL_RELEASE = 1.0       # seconds the lights take to ease down from a roll's top level when it ends
ROLL_GONE_LOOK = 0.2     # seconds with no hit left in the band, just longer than the slowest hit gap, before a roll can count as stopped
ROLL_GONE_DROP = 9.0     # dB the band's loudest point in that time must be under the roll's hits
HARMONY_FFT = 4096       # samples: enough to tell a semitone apart in the band below
HARMONY_EVERY = 4        # analysis steps between looks at the notes, about 23 a second
HARMONY_BAND = (130, 4200)  # Hz: where synths' notes are looked for, above the kick's body and under the hats
HARMONY_PEAK = 2.5       # a spectrum peak counts as a note when this many times the bins around it
HARMONY_NOW, HARMONY_GAP, HARMONY_PAST = 2, 1, 4  # looks making up the current sound, those skipped, and those it is compared to
HARMONY_CHANGE = 0.3     # how different (0..1) the notes must become to count as a note or chord change
HARMONY_REARM = 0.6      # ... and the share of that they must settle under before another can count
HARMONY_TONAL = 0.35     # share of the band's power that must sit in notes for it to count as a synth rather than drums or noise
HARMONY_MIN_GAP = 0.18   # seconds: changes closer than this count once
DROP_QUIET_BEATS = 8     # beats without a kick before the next kick counts as a drop
DROP_LOUDNESS = 0.8      # ... if the sound is this share of its loudness with kicks, so a stray bass note in a breakdown doesn't count
DROP_FADE = 1.6          # share of full brightness per second a drop's flash fades, so it lands with more weight than a kick
KICK_BASS_SHARE = 0.45   # share of the bass that reaches the brightness in the beat modes while kicks play, so a sub under the kicks leaves them room to punch
KICK_BASS_FLOOR = 0.25   # a kick's bass must reach this share (fourth-root scale, about -24 dB) of the kicks so far, unless the rises keep regular time: a thump under a vocal isn't a kick
GAP_WINDOW = 1.5         # seconds of sound a stop is measured against: long enough to span kicks, so the space between kicks isn't a stop
GAP_DEPTH = 14.0         # dB under the median of that time that makes a stop: the lights go dark at once
GAP_EXIT = 7.0           # dB under it that ends one, close to the old level, so noise tails inside the stop don't
GAP_LONGEST = 2.0        # seconds a stop lasts at most: quieter sound after that is just the new level
GAP_RECENT = 0.3         # seconds after a stop that the next kick counts as the music coming back in
GAP_BEAT_AGE = 0.12      # seconds into a stop before predicted beats are held back: a brief dip just before a kick still fires
GAP_DROP = 0.25          # seconds a stop must have lasted for the kick after it to count as a drop
HIT_RISE = 10.0          # dB the sound must jump within a few frames to count as a hit when no kicks are playing
HIT_LOUD = 0.75          # ... and the share of the loudness with kicks it must reach (fourth-root scale)
HIT_MIN_GAP = 0.25       # seconds: hits closer than this count once
HARMONY_COLOUR_BEATS = 2  # beats' worth of time each colour glide takes over when the notes set the colour
ROLL_MODES = ("Beat colour jump", "Bass pulse", "Rainbow drift")  # the modes drum rolls take over


def _blend(a, b, t):
    """Blend two (hue, sat) colours, going the short way round the hue circle."""
    dh = ((b[0] - a[0] + 180) % 360) - 180
    return ((a[0] + dh * t) % 360, a[1] + (b[1] - a[1]) * t)


def _ease(t):
    """Smoothstep: starts and ends gently."""
    return t * t * (3.0 - 2.0 * t)


def paletteAt(pal, t, wrap):
    """Colour at position t (0-1) along a palette. wrap=True loops the last colour back to the first."""
    n = len(pal)
    if n == 1:
        return pal[0]
    x = (t % 1.0) * n if wrap else max(0.0, min(1.0, t)) * (n - 1)
    i = min(int(x), n - 1)
    return _blend(pal[i], pal[(i + 1) % n], x - i)


def _mix(colours, weights):
    """Weighted mix of (hue, sat) colours, averaging hue as an angle."""
    x = y = sat = 0.0
    total = sum(weights)
    if total <= 0:
        return colours[0]
    for (h, s), w in zip(colours, weights):
        x += w * s * math.cos(math.radians(h))
        y += w * s * math.sin(math.radians(h))
        sat += w * s
    return (math.degrees(math.atan2(y, x)) % 360, sat / total)


def _beatStep(n):
    """Palette step per beat: about 0.38 of the way round, never landing on the same cycle twice."""
    if n <= 3:
        return 1
    step = max(1, round(n * 0.382))
    while math.gcd(step, n) != 1:
        step += 1
    return step


def _pactl(*args):
    """Output of a pactl command, or '' when pactl is missing or fails."""
    try:
        return subprocess.run(("pactl",) + args, capture_output=True, encoding="utf-8", errors="replace",
                              timeout=2, env=dict(os.environ, LC_ALL="C")).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _parseMonitors(sources, info):
    """[(source name, description)] of the monitors in `pactl list sources`, the default output's first."""
    monitors = []
    for block in re.split(r"^Source #\d+$", sources, flags=re.M)[1:]:
        name = re.search(r"^\s*Name: (.+)$", block, re.M)
        desc = re.search(r"^\s*Description: (.+)$", block, re.M)
        sink = re.search(r"^\s*Monitor of Sink: (.+)$", block, re.M)
        if name and sink and sink.group(1).strip() != "n/a":
            monitors.append((sink.group(1).strip(), name.group(1).strip(), (desc or name).group(1).strip()))
    default = re.search(r"^Default Sink: (.+)$", info, re.M)
    defaultSink = default.group(1).strip() if default else None
    monitors.sort(key=lambda m: m[0] != defaultSink)  # stable: the rest keep their order
    return [(source, label) for _, source, label in monitors]


def _linuxMonitors(devices):
    """Entries for the PulseAudio/PipeWire monitors, identified by source name (a str, where
    PortAudio devices have an int). Empty when they can't be recorded here, or are already listed."""
    names = [name.lower() for _, name, _, _ in devices]
    if "pulse" not in names or any("monitor of" in n for n in names):
        return []
    return [(source, label, 2, ANALYSIS_RATE) for source, label in _parseMonitors(_pactl("list", "sources"), _pactl("info"))]


def _windowsHostApi(devices):
    """WASAPI's host API index, when it has inputs. Windows lists every device once per host API,
    with MME names cut to 31 characters; WASAPI has full names and the lowest shared-mode delay."""
    if sys.platform != "win32":
        return None
    for i, api in enumerate(sd.query_hostapis()):
        if api["name"] == "Windows WASAPI" and any(devices[d]["max_input_channels"] > 0 for d in api["devices"]):
            return i
    return None


def listInputDevices(rescan=False):
    """Return [(id, name, channels, defaultRate)] for every device that can record. The id is what
    start() takes: PortAudio's device index, or on Linux a monitor's source name.

    PortAudio reads the device list once, so a device plugged in later stays hidden
    until it is restarted: rescan=True does that. Only rescan while no stream is open."""
    if not AUDIO_AVAILABLE:
        return []
    if rescan:
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
    out = []
    try:
        devices = sd.query_devices()
        onlyApi = _windowsHostApi(devices)
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0 and onlyApi in (None, d.get("hostapi")):
                out.append((i, d["name"], int(d["max_input_channels"]), int(d.get("default_samplerate", 48000))))
    except Exception:
        pass
    if sys.platform.startswith("linux"):
        out = _linuxMonitors(out) + out
    return out


def preferredDeviceIndex(devices):
    """Pick the device most likely to carry system output (a loopback device), else the first."""
    keys = ("blackhole", "loopback", "stereo mix", "monitor of", "cable output", "soundflower")
    for i, name, _, _ in devices:
        if isinstance(i, str) or any(k in name.lower() for k in keys):
            return i
    return devices[0][0] if devices else None


def _openInput(device, rate, blocksize, callback, pulseSource=None):
    """Open and start an input stream, in stereo or less if the device allows it (the callback mixes
    any channel count to mono). Some Linux hw: devices and Windows arrays only open at their full count."""
    maxChannels = max(1, int(sd.query_devices(device).get("max_input_channels", 1)))
    extra = None
    if sd.query_hostapis(sd.query_devices(device)["hostapi"])["name"] == "Windows WASAPI":
        extra = sd.WasapiSettings(auto_convert=True)  # shared mode otherwise only takes the Windows mix format
    saved = os.environ.get("PULSE_SOURCE")
    if pulseSource:  # libpulse reads this when ALSA opens the "pulse" device
        os.environ["PULSE_SOURCE"] = pulseSource
    try:
        for channels in dict.fromkeys((min(2, maxChannels), maxChannels)):
            try:
                # latency="low": the default buffers about 85 ms and delivers it in bursts, so kicks would be heard late.
                stream = sd.InputStream(device=device, channels=channels, samplerate=rate, blocksize=blocksize,
                                        latency="low", dtype="float32", callback=callback, extra_settings=extra)
                stream.start()
                return stream
            except sd.PortAudioError as e:
                if channels == maxChannels or "channel" not in str(e).lower():
                    raise
    finally:
        if pulseSource:
            if saved is None:
                os.environ.pop("PULSE_SOURCE", None)
            else:
                os.environ["PULSE_SOURCE"] = saved


@contextlib.contextmanager
def _soundThreadSetup():
    """What the sound thread needs from Windows while it runs: COM, which WASAPI uses and PortAudio
    only set up on the thread that imported it, and 1 ms timers, as waits otherwise wake up to 15.6 ms late."""
    if sys.platform != "win32":
        yield
        return
    import ctypes
    coInit = ctypes.windll.ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED, as PortAudio does
    ctypes.windll.winmm.timeBeginPeriod(1)
    try:
        yield
    finally:
        ctypes.windll.winmm.timeEndPeriod(1)
        if coInit >= 0:
            ctypes.windll.ole32.CoUninitialize()


class _Envelope:
    """Attack/release smoother: rises quickly, falls at a rate set by 'release'."""

    def __init__(self):
        self.value = 0.0

    def step(self, target, attack, release, dt=1.0 / 15):
        """attack/release are the share of the gap closed per frame at 15 fps; other rates match it."""
        k = attack if target > self.value else release
        k = 1.0 - (1.0 - min(1.0, max(0.0, k))) ** (dt * 15.0)
        self.value += (target - self.value) * k
        return self.value


class _AutoGain:
    """Normalises a level to 0..1 between where it has been low and high over the last few
    seconds, so a compressed drop that never dips far pulses as deeply as a sparse intro.
    A level that holds steady sits mid-range: the span stays at least minSpan of the top,
    so tiny wobbles aren't stretched across the whole range."""

    def __init__(self, window=GAIN_WINDOW, minSpan=GAIN_MIN_SPAN):
        self.window = window
        self.minSpan = minSpan
        self.history = deque()  # (time, value), oldest first
        self.time = 0.0

    def step(self, value, dt):
        self.time += dt
        self.history.append((self.time, value))
        while self.time - self.history[0][0] > self.window:
            self.history.popleft()
        values = np.fromiter((v for _, v in self.history), float, len(self.history))
        lo, hi = (float(q) for q in np.percentile(values, GAIN_PERCENTILES))
        hi = max(hi, 1e-6)
        span = self.minSpan * hi
        if hi - lo < span:  # widen around the middle
            mid = (lo + hi) / 2
            lo, hi = mid - span / 2, mid + span / 2
        return max(0.0, min(1.0, (value - lo) / (hi - lo)))

    def forget(self):
        """Drop the history, for when the music has just changed so much that it would only mislead."""
        self.history.clear()


class _Range:
    """Rescales a 0..1 value to 0..1 between its recent lowest and highest, so a value that only
    wanders through a narrow band still sweeps the whole range. The edges jump out to new
    extremes at once and close in slowly; they never come closer than minSpan."""

    def __init__(self, closePerSecond=0.04, minSpan=0.15):
        self.lo = self.hi = None
        self.close = closePerSecond
        self.minSpan = minSpan

    def step(self, value, dt):
        if self.lo is None:
            self.lo = self.hi = value
        self.lo = min(value, self.lo + self.close * dt)
        self.hi = max(value, self.hi - self.close * dt)
        lo, hi = self.lo, self.hi
        if hi - lo < self.minSpan:  # widen around the middle
            mid = (lo + hi) / 2
            lo, hi = mid - self.minSpan / 2, mid + self.minSpan / 2
        return max(0.0, min(1.0, (value - lo) / (hi - lo)))


class _SoundGate:
    """Tells music from quiet. The reference level follows the music. While it is quiet the
    reference sinks slowly, so music turned right down is heard again within seconds, but
    never below a margin over the measured noise floor, so a long pause never makes room
    noise count as music."""

    def __init__(self, decayPerSecond=0.05, quietDecayPerSecond=0.05):
        self.ref = 0.0
        self.floor = 0.0          # lowest recent level: room noise, or the quietest music frames
        self.decay = decayPerSecond
        self.quietDecay = quietDecayPerSecond
        self.lastSound = None

    def step(self, value, now, dt):
        if value > 0:  # follows the level down at once, back up slowly (3 %/s)
            self.floor = value if self.floor <= 0 else min(value, self.floor * (1.0 + 0.03 * dt))
        if value > self.ref * QUIET_RATIO and value > 0:
            self.ref = max(value, self.ref * (1.0 - self.decay * dt))
            self.lastSound = now
        else:
            keep = self.floor * NOISE_MARGIN / QUIET_RATIO  # threshold stays this far over the noise
            self.ref = min(self.ref, max(keep, self.ref * (1.0 - self.quietDecay * dt)))
        return self.lastSound is not None and now - self.lastSound < QUIET_HOLD


class _Rise:
    """How sharply a spectrum is rising: the average increase (log scale) of each bin over the
    hop two before. Bins more than 30 dB under the recent peak count as that level, so noise in
    near-empty bins doesn't look like attacks. Level-independent: a quiet kick rises as much as a loud one."""

    def __init__(self):
        self.prev = deque(maxlen=2)
        self.peak = 1e-12

    def step(self, power, dt):
        self.peak = max(float(power.max()), self.peak * (1.0 - 0.3 * dt), 1e-12)
        logP = np.log10(power + self.peak * 1e-3)
        # The floor is today's, not the one the old hop was measured against: out of silence the
        # peak was tiny then, and the first sound would read as a rise far bigger than any kick.
        floor = math.log10(self.peak * 1e-3)
        rise = float(np.maximum(0.0, logP - np.maximum(self.prev[0], floor)).mean()) if len(self.prev) == 2 else 0.0
        self.prev.append(logP)
        return rise

    def reset(self):
        self.prev.clear()


def _wrapPhase(x, period):
    """x seconds, brought to within half a beat either side of zero."""
    return (x + period / 2.0) % period - period / 2.0


class _KickPicker:
    """Finds kicks as bass rises well above the typical rise of the last second and a half: the
    bar adapts to the music, so a long 808 or a busy bassline (steady, small rises) doesn't hide
    the kicks and soft kicks in a quiet section still count, and it sits near the strongest recent
    rises, so smaller rises between the kicks don't count. Kick sensitivity lowers the bar. A bass note
    as loud and sudden as a kick counts too: on real recordings neither its pitch nor a click tells
    them apart, so with a MIDI clock _LightShow keeps only the rises that land on a beat. Where
    the beat grid expects a kick the bar is lower: soft kicks and off-beat bass rise about as much
    as each other, and only their timing tells them apart."""

    def __init__(self, hopRate):
        self.rises = deque(maxlen=max(16, int(1.5 * hopRate)))
        self.armed = True
        self.lastBeat = -10.0
        self.firstUntil = -10.0  # rises before this time belong to a first kick
        self.gaps = deque(maxlen=4)  # the latest gaps between kicks
        self.guided = False  # the latest kick only cleared the lower bar for an expected beat
        self.firmBeat = -10.0  # the latest guided kick that went on to clear the usual bar

    def step(self, rise, t, sens, expected=None):
        """True on the hop of a rise that counts as a kick. expected(t) says if the beat grid puts a kick at t."""
        if len(self.rises) < 16:  # too early to fire, so too early to set the bar
            self.rises.append(min(rise, KICK_ABS_RISE))
            return False
        if rise < (KICK_ABS_RISE if expected is None else min(KICK_ABS_RISE, KICK_GUIDED_RISE)) / sens:  # under the lowest the bar can be: no need to work it out
            self._remember(rise, t)
            self.armed = True
            return False
        hist = np.fromiter(self.rises, float, len(self.rises))
        med = float(np.median(hist))
        spread = float(np.median(np.abs(hist - med)))
        # Also near the strongest recent rises, so a bass note between the kicks doesn't count as one.
        bar = max(med + (3.0 * spread + KICK_MIN_RISE) / sens, float(hist.max()) * KICK_SHARE / sens,
                  KICK_ABS_RISE / sens)  # and a real jump, so noise under quiet pads never counts
        guided = rise < bar and expected is not None and expected(t)
        if guided:
            bar = max(med + (KICK_GUIDED_SPREAD * spread + KICK_MIN_RISE) / sens, float(hist.max()) * KICK_GUIDED_SHARE / sens,
                      KICK_GUIDED_RISE / sens)
        if rise < bar:
            self._remember(rise, t)
            self.armed = True
            return False
        fire = self.armed and t - self.lastBeat > MIN_BEAT_GAP
        self.armed = False  # one beat per rise
        if fire:
            gap = t - self.lastBeat
            if gap > self._firstKickGap():
                self.firstUntil = t + 0.06  # about as long as one rise lasts
            self.gaps.append(gap)
            self.lastBeat = t
            self.guided = guided
        elif self.guided and not guided and t - self.lastBeat <= KICK_GUIDED_FIRM:
            self.guided = False  # the lower bar only caught it early
            self.firmBeat = self.lastBeat
        self._remember(rise, t)
        return fire

    def _firstKickGap(self):
        """Seconds without a kick after which the next one rises from quiet. Goes by the usual gap
        between kicks, so kicks two beats apart at a slow tempo don't each count as a first kick."""
        if len(self.gaps) < self.gaps.maxlen:
            return FIRST_KICK_GAP
        return min(FIRST_KICK_GAP, max(FIRST_KICK_SHORTEST, FIRST_KICK_BEATS * float(np.median(self.gaps))))

    def keepsTime(self):
        """Did the latest kick come at the usual spacing? Regular kicks are kicks even if the tempo found is off."""
        if len(self.gaps) < self.gaps.maxlen:
            return False
        gaps = list(self.gaps)
        return abs(gaps[-1] - float(np.median(gaps[:-1]))) <= KICK_ON_BEAT

    def _remember(self, rise, t):
        self.rises.append(rise * FIRST_KICK_WEIGHT if t < self.firstUntil else rise)

    def reset(self):
        self.rises.clear()
        self.gaps.clear()
        self.armed = True


class _TempoTracker:
    """Finds the tempo and beat phase in the sound, so beats can be fired on time, or a little
    early to make up for Bluetooth delay, instead of after each kick is heard. Every quarter
    second it autocorrelates the last 8 s of attacks to find the beat period (favouring tempos
    near 120 BPM and periods that also repeat at two beats), then lines a comb of beats up with
    the attacks to find where the beats fall. It locks after a few estimates agree. When the music
    stops having a clear beat it holds the tempo and carries on counting, since a breakdown keeps
    the track's tempo, and the first two kicks back set where the beats fall, so the drop lands on
    the grid at once. Same interface as MidiClock."""

    def __init__(self, hopRate):
        self.hopRate = hopRate
        n = int(TEMPO_WINDOW * hopRate)
        self.env = deque(maxlen=n)
        self.times = deque(maxlen=n)
        self.reset()

    def reset(self):
        self.env.clear()
        self.times.clear()
        self.period = 0.0
        self.refT = self.refPos = 0.0
        self.locked = False
        self.candidate = 0.0
        self.agree = self.doubt = 0
        self.nextFit = 0.0
        self.coast = None   # when the hold began, while the tempo is held with no clear beat
        self.lastKick = None
        self.gaps = deque(maxlen=3)  # gaps between kicks that didn't fit the held tempo

    def add(self, t, onset):
        self.env.append(onset)
        self.times.append(t)

    def active(self, now=None):
        return self.locked

    def bpm(self):
        return 60.0 / self.period if self.locked else 0.0

    def beatPeriod(self):
        return self.period

    def position(self, at):
        return self.refPos + (at - self.refT) / self.period if self.locked else None

    def update(self, now):
        if now < self.nextFit or len(self.env) < TEMPO_MIN_SECONDS * self.hopRate:
            return
        self.nextFit = now + TEMPO_FIT_EVERY
        est = self._estimate()
        if est is None:
            self._unsure()
            return
        period, beatT = est
        if self.candidate and abs(period / self.candidate - 1.0) < 0.04:
            self.agree += 1
        else:
            self.candidate, self.agree = period, 0
        if self.coast is not None and abs(period / self.period - 1.0) <= 0.04:
            return  # the attacks of a breakdown (hats, pads) say nothing about where the beats fall
        if self.agree < (TEMPO_COAST_AGREE if self.coast is not None else 2):  # not yet confirmed: keep the current lock, if any, for now
            if self.locked and abs(period / self.period - 1.0) > 0.04:
                self._unsure()
            return
        if not self.locked or abs(period / self.period - 1.0) > 0.04:  # lock on, or a new tempo
            self.locked, self.period, self.refT, self.refPos = True, period, beatT, 0.0
            self.doubt = 0
            self.coast = None
            return
        # Same tempo: follow small drifts gently, keeping the position continuous so no beat is skipped or doubled.
        self.refPos, self.refT = self.position(now), now
        self.period += (period - self.period) * 0.3
        p = self.position(beatT)
        self.refPos -= (p - round(p)) * 0.4
        self.doubt = 0

    def _unsure(self):
        self.doubt += 1
        if self.doubt >= 8:  # about 2 s without a clear beat
            self.candidate, self.agree, self.doubt = 0.0, 0, 0
            if self.locked and self.coast is None:
                self.coast = self.times[-1]

    def checkCoast(self, now, lastKick, rolling):
        """Start holding the tempo when the kicks have stopped (a breakdown), and let go after too long."""
        if self.locked and self.coast is None and self.lastKick is not None and not rolling \
                and now - lastKick > max(2.0, 4.0 * self.period):  # music with no kicks at all has no breakdown to hold through
            self.coast = now
        if self.coast is not None and rolling:  # a roll keeps the track's tempo: the hold's time starts again when it ends
            self.coast = now
        if self.coast is not None and now - self.coast > TEMPO_COAST:
            self.reset()

    def kick(self, t):
        """A kick was heard at time t. While holding, two in a row that fit the tempo set where the beats fall."""
        if self.coast is not None and self.locked and self.lastKick is not None:
            beats = (t - self.lastKick) / self.period
            if 1 <= round(beats) <= 4 and abs(beats - round(beats)) * self.period < TEMPO_RESNAP:
                p = self.position(t - ONSET_DELAY)
                self.refPos -= p - round(p)
                self.coast = None
                self.doubt = 0
                self.gaps.clear()
            else:
                self.gaps.append(t - self.lastKick)
                if len(self.gaps) == self.gaps.maxlen and max(self.gaps) - min(self.gaps) < 2.0 * TEMPO_RESNAP:
                    self.coast = None  # steady kicks that don't fit: the next track has come in, so listen for its tempo as usual
        self.lastKick = t

    def _estimate(self):
        """(period in seconds, time of a recent beat), or None when there is no clear beat."""
        o = np.asarray(self.env, float)
        n = len(o)
        o = o - o.mean()
        f = np.fft.rfft(o, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]
        if ac[0] <= 1e-12:
            return None
        ac /= ac[0]
        lo = max(2, int(self.hopRate * 60.0 / TEMPO_MAX_BPM))
        hi = min(n // 2 - 1, int(math.ceil(self.hopRate * 60.0 / TEMPO_MIN_BPM)))
        if hi <= lo + 1:
            return None
        lags = np.arange(lo, hi + 1)
        score = ac[lags] + TEMPO_HARMONIC * ac[np.minimum(2 * lags, n - 1)]
        score *= np.exp(-0.5 * np.log2(60.0 * self.hopRate / lags / 120.0) ** 2)
        L = int(lags[int(np.argmax(score))])
        # Twice as fast, if that tempo is in range and repeats nearly as strongly: drum'n'bass
        # repeats most every two beats, and would otherwise lock at half speed.
        half = int(round(L / 2.0))
        if half >= lo and ac[half] >= TEMPO_FAST_SHARE * ac[L]:
            L = half + int(np.argmax(ac[half - 1:half + 2])) - 1
        if ac[L] < TEMPO_MIN_CONF:
            return None
        y0, y1, y2 = ac[L - 1], ac[L], ac[L + 1]
        den = y0 - 2.0 * y1 + y2
        P = L + (0.5 * (y0 - y2) / den if den < 0 else 0.0)
        P = min(max(P, L - 0.5), L + 0.5)
        # Phase: the offset whose comb of beats (recent ones weighing most) catches the most attack.
        K = max(1, min(16, int((n - P) // P)))
        ph = np.arange(int(math.ceil(P)))
        k = np.arange(K)
        idx = (n - 1 - ph[:, None] - np.round(k * P)[None, :]).astype(int)
        p = int(np.argmax((o[idx] * 0.85 ** k).sum(axis=1)))
        return P / self.hopRate, self.times[n - 1 - p] - ONSET_DELAY


class _RollFinder:
    """Finds drum rolls: fast, even pulses in the snare's range that stand above the bass, as in
    the build before a drop. Speed alone won't do, since a groove's 16ths are just as fast: they
    repeat less evenly in this band and sit under the bass."""

    def __init__(self, hopRate):
        self.hopRate = hopRate
        size = int(ROLL_WINDOW * hopRate)
        self.snare = deque(maxlen=size)
        self.bass = deque(maxlen=size)
        self.minLag = int(round(ROLL_HIT[0] * hopRate))
        self.maxLag = int(round(ROLL_HIT[1] * hopRate))
        self.slow = np.ones(int(0.5 * hopRate) | 1)  # odd length: half a second, longer than any hit gap
        self.slow /= len(self.slow)
        self.recent = max(1, int(0.25 * hopRate))
        self.gone = max(1, int(ROLL_GONE_LOOK * hopRate))
        self.quick = int(ROLL_QUICK * hopRate)
        self.evenSize = int(ROLL_EVEN_LOOK * hopRate)
        self.evenSlack = max(1, int(round(ROLL_EVEN_SLACK * hopRate)))
        self.near = np.ones(int(0.3 * hopRate) | 1)  # odd length: a little longer than any hit gap
        self.lastFit = -10.0
        self.reset()

    def reset(self):
        self.snare.clear()
        self.bass.clear()
        self.active = False
        self.period = 0.0
        self.streak = 0
        self.holdUntil = 0.0
        self.evenSince = None  # when even hits under the bass began

    def _stop(self):
        self.active = False
        self.streak = 0
        self.holdUntil = 0.0
        self.evenSince = None

    def add(self, snare, bass):
        self.snare.append(snare)
        self.bass.append(bass)

    def update(self, now):
        if len(self.snare) < self.snare.maxlen or now - self.lastFit < ROLL_FIT_EVERY:
            return
        self.lastFit = now
        snare = np.fromiter(self.snare, float, len(self.snare))
        bass = np.fromiter(self.bass, float, len(self.bass))
        # The drop has landed: stop at once. Medians, so a single kick under the roll doesn't count.
        if not self._overBass(snare[-self.recent:], bass[-self.recent:], ROLL_DROP_ROOM):
            self._stop()
            return
        # The hits have stopped, as in the gap before a drop: end it now, not when the repeat fades from the window.
        if snare[-self.gone:].max() * 10.0 ** (ROLL_GONE_DROP / 10.0) < np.percentile(snare[:-self.gone], 90):
            self._stop()
            return
        quick, quickLag = self._quickRepeat(snare[-self.quick:], bass[-self.quick:])
        steady, steadyLag = self._steadyRepeat(snare, bass)
        evenGap = self._evenGap(snare[-self.evenSize:], bass[-self.evenSize:], ROLL_EVEN_GAPS, ROLL_EVEN_DEPTH)
        if evenGap or (self.active and self._evenGap(snare[-self.evenSize:], bass[-self.evenSize:], ROLL_KEEP_GAPS, ROLL_KEEP_DEPTH)):
            self.holdUntil = now + ROLL_EVEN_HOLD
        if steady >= ROLL_START:
            self.period = steadyLag / self.hopRate
        elif quick >= ROLL_QUICK_START:
            self.period = quickLag / self.hopRate
        elif evenGap:
            self.period = evenGap / self.hopRate
        startsRoll = bool(evenGap)
        if evenGap and not self.active and not self._overBass(snare[-self.evenSize:], bass[-self.evenSize:], 0.0):
            self.evenSince = now if self.evenSince is None else self.evenSince
            near = self._overBass(snare[-self.recent:], bass[-self.recent:], ROLL_NEAR_BASS)
            startsRoll = now - self.evenSince >= (ROLL_NEAR_BASS_EVEN if near else ROLL_UNDER_BASS_EVEN)
        else:
            self.evenSince = None
        if startsRoll:
            self.active = True
        if quick >= ROLL_QUICK_START or (self.active and steady >= ROLL_START):
            self.streak += 1
            self.active = self.active or self.streak >= 2
        elif not self.active or (max(quick, steady) < ROLL_END and now >= self.holdUntil):
            self.active = False
            self.streak = 0

    def _overBass(self, snare, bass, room=ROLL_BASS_ROOM):
        return np.median(snare) * 10.0 ** (room / 10.0) >= np.median(bass)

    def _pulse(self, snare, bass):
        """The band's beating with its slow build taken out, or None if it is under the bass or too shallow."""
        if not self._overBass(snare, bass, ROLL_BASS_ROOM if self.active else 0.0):
            return None
        trim = len(self.slow) // 2
        level = 10.0 * np.log10(snare + 1e-12)
        pulse = (level - np.convolve(level, self.slow, "same"))[trim:-trim]
        return pulse if pulse.std() >= ROLL_MIN_DEPTH else None

    def _steadyRepeat(self, snare, bass):
        """How strongly the band repeats at a roll's speed over the long window, 0..1, and at what lag."""
        pulse = self._pulse(snare, bass)
        if pulse is None:
            return 0.0, 0
        corr = np.correlate(pulse, pulse, "full")[len(pulse) - 1:]
        corr /= corr[0]
        lag = self.minLag + int(np.argmax(corr[self.minLag:self.maxLag + 1]))
        return float(corr[lag]), lag

    def _quickRepeat(self, snare, bass):
        """As _steadyRepeat for the short window. Each lag is scored only over the part that overlaps,
        since in so few steps the plain measure above would mark slower rolls down."""
        pulse = self._pulse(snare, bass)
        if pulse is None:
            return 0.0, 0
        best, bestLag = 0.0, 0
        for lag in range(self.minLag, min(self.maxLag, len(pulse) - ROLL_QUICK_OVERLAP) + 1):
            a, b = pulse[:-lag], pulse[lag:]
            size = math.sqrt(float((a * a).sum() * (b * b).sum()))
            score = float((a * b).sum()) / size if size > 0 else 0.0
            if score > best:
                best, bestLag = score, lag
        return best, bestLag

    def _evenGap(self, snare, bass, count, depth):
        """The steps between the newest hits if the last count gaps are even and at a roll's speed, else 0.
        Goes by the hits themselves, which show within a few hits, before a repeat measure can be sure."""
        if not self._overBass(snare, bass):
            return 0
        level = 10.0 * np.log10(snare + 1e-12)
        pulse = level - np.convolve(level, self.near, "same") / np.convolve(np.ones(len(level)), self.near, "same")
        reach = max(2, self.minLag // 2)
        hits = [i for i in range(reach, len(pulse) - reach)
                if pulse[i] >= depth and pulse[i] == pulse[i - reach:i + reach + 1].max()]
        if len(hits) <= count:
            return 0
        gaps = np.diff(hits[-(count + 1):])
        if gaps.min() < self.minLag or gaps.max() > self.maxLag or gaps.max() - gaps.min() > self.evenSlack:
            return 0
        return float(np.median(gaps))


class _Harmony:
    """Follows the notes of whatever is tonal, synths above all, however loud they are: how much of the
    sound is notes rather than drums or noise, and each moment the notes change. Works on the shape of
    the spectrum, so it behaves the same at any input level."""

    def __init__(self, rate):
        self.window = np.hanning(HARMONY_FFT).astype(np.float32)
        freqs = np.fft.rfftfreq(HARMONY_FFT, 1.0 / rate)
        self.lo, self.hi = (int(np.searchsorted(freqs, f)) for f in HARMONY_BAND)
        self.pitchClass = (np.round(12.0 * np.log2(freqs[self.lo:self.hi] / 440.0) + 69).astype(int)) % 12
        self.around = np.ones(9) / 9.0
        self.looks = deque(maxlen=HARMONY_NOW + HARMONY_GAP + HARMONY_PAST)
        self.reset()

    def reset(self):
        self.looks.clear()
        self.tonal = 0.0       # share of the band's power in notes, smoothed
        self.armed = True
        self.lastChange = -10.0
        self.pitch = None      # pitch class (0 = C) of the strongest note at the latest change
        self.changed = False   # a change happened since the last light frame

    def step(self, samples, t):
        mag = np.abs(np.fft.rfft(samples * self.window))[self.lo:self.hi]
        power = mag * mag
        total = float(power.sum())
        if total <= 0:
            return
        peaks = (mag > np.roll(mag, 1)) & (mag > np.roll(mag, -1)) & (mag > HARMONY_PEAK * np.convolve(mag, self.around, "same"))
        peaks[0] = peaks[-1] = False
        spread = peaks | np.roll(peaks, 1) | np.roll(peaks, -1)  # a note's power also fills the bins beside its peak
        self.tonal += (float(power[spread].sum()) / total - self.tonal) * 0.25
        chroma = np.bincount(self.pitchClass[peaks], weights=mag[peaks], minlength=12)
        self.looks.append(chroma)
        if len(self.looks) < self.looks.maxlen or self.tonal < HARMONY_TONAL:
            return
        looks = list(self.looks)
        now = np.sum(looks[-HARMONY_NOW:], axis=0)
        past = np.sum(looks[:HARMONY_PAST], axis=0)
        size = math.sqrt(float(now.dot(now)) * float(past.dot(past)))
        change = 1.0 - float(now.dot(past)) / size if size > 0 else 0.0
        if change < HARMONY_CHANGE * HARMONY_REARM:
            self.armed = True
        elif change >= HARMONY_CHANGE and self.armed and t - self.lastChange >= HARMONY_MIN_GAP:
            self.armed = False
            self.lastChange = t
            self.pitch = int(np.argmax(now))
            self.changed = True

    def take(self):
        """The pitch class of the note change since the last call, or None."""
        changed, self.changed = self.changed, False
        return self.pitch if changed else None


class _Decimator:
    """Brings a high sample rate down to about ANALYSIS_RATE, keeping every factor-th sample after
    a low-pass filter. The analysis sizes are fixed in samples, so without this a 96 or 192 kHz
    device would get a much shorter window and only a bin or two for the kick. Works on blocks of
    any size; the filter's delay is under 0.2 ms."""

    def __init__(self, factor):
        self.factor = factor
        n = 8 * factor + 1
        h = np.sinc((np.arange(n) - n // 2) / float(factor)) * np.hanning(n + 2)[1:-1]
        self.taps = (h / h.sum()).astype(np.float32)
        self.tail = np.zeros(n - 1, dtype=np.float32)  # the end of the last block
        self.skip = 0                                  # samples to pass over before the next one kept

    def process(self, x):
        if self.factor == 1:
            return x
        joined = np.concatenate((self.tail, x))
        y = np.convolve(joined, self.taps, mode="valid")
        self.tail = joined[-(len(self.taps) - 1):]
        out = y[self.skip::self.factor]
        self.skip = (self.skip - len(y)) % self.factor
        return out


def _aWeight(f):
    """A-weighting as a power gain (1.0 at 1 kHz): how much of a frequency's power the ear notices."""
    f2 = f * f
    amp = 12194.0 ** 2 * f2 ** 2 / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)) * (f2 + 12194.0 ** 2))
    return (amp * 1.2589) ** 2


class _Analyser:
    """Turns sound into levels, a per-band spectrum and kicks. Knows nothing about devices,
    threads or lights, so a test can feed it samples directly."""

    def __init__(self, rate):
        self.rate = float(rate)
        self.hopRate = self.rate / HOP
        self._window = np.hanning(FFT_SIZE).astype(np.float32)
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / self.rate)

        def bins(lo, hi):
            return slice(int(np.searchsorted(freqs, lo)), int(np.searchsorted(freqs, hi)))

        self._ranges = (("bass", bins(*BASS)), ("mid", bins(*MID)), ("high", bins(*HIGH)))
        self._audible = bins(40, 12000)
        self._kick = bins(*KICK)
        self._snare = bins(*ROLL)

        # Bands a third of an octave wide (at least one bin), since hearing goes by octaves and
        # FFT bins are evenly spaced: above 2 kHz the bins outnumber everything below.
        lo = self._audible.start
        hi = self._audible.stop
        count = int(math.log2(12000.0 / 40.0) * BANDS_PER_OCTAVE)
        edges = np.searchsorted(freqs, 40.0 * 2.0 ** (np.arange(count) / float(BANDS_PER_OCTAVE)))
        edges = np.unique(np.append(edges[edges < hi], hi))
        self._bandStart = edges[:-1] - lo
        self._bandWidth = np.diff(edges).astype(np.float32)
        centres = np.sqrt(freqs[edges[:-1]] * freqs[edges[1:] - 1])
        self.bandLogF = np.log(centres)
        self._bandA = _aWeight(centres).astype(np.float32)
        self._restBands = slice(int(np.searchsorted(centres, KICK[1])), int(np.searchsorted(centres, 8000.0)))

        self._kickRise, self._restRise = _Rise(), _Rise()
        self.kicks = _KickPicker(self.hopRate)
        self.kickExpected = None  # set by the light show: does the beat grid put a kick at this time?
        self.tempo = _TempoTracker(self.hopRate)
        self.roll = _RollFinder(self.hopRate)
        self.harmony = _Harmony(self.rate)
        self._longHist = np.zeros(HARMONY_FFT, dtype=np.float32)  # the last HARMONY_FFT samples
        self._hopCount = 0
        self.heard = False  # set by the light show: kicks and tempo only count while music is heard

        self._hist = np.zeros(FFT_SIZE, dtype=np.float32)  # the last FFT_SIZE samples
        self._pending = np.zeros(0, dtype=np.float32)      # samples not yet analysed
        self._peak = None      # loudest hop since the last light frame, per level
        self._colour = None    # summed band amplitudes since the last light frame
        self.kickSeen = False  # a kick was detected since the last light frame

    def feed(self, samples, endT, sens):
        """Analyse every whole hop of new sound, so no kick falls between light frames.
        endT is the monotonic time of the last sample."""
        pending = np.concatenate((self._pending, samples))
        hops = len(pending) // HOP
        for h in range(hops):
            self._hop(pending[h * HOP:(h + 1) * HOP], endT - (len(pending) - (h + 1) * HOP) / self.rate, sens)
        self._pending = pending[hops * HOP:]

    def _hop(self, block, t, sens):
        self._hist[:-HOP] = self._hist[HOP:]
        self._hist[-HOP:] = block
        self._longHist[:-HOP] = self._longHist[HOP:]
        self._longHist[-HOP:] = block
        self._hopCount += 1
        power = np.abs(np.fft.rfft(self._hist * self._window)) ** 2
        audible = power[self._audible]
        bands = np.add.reduceat(audible, self._bandStart) / self._bandWidth
        heardBands = bands * self._bandA

        # "level" adds up how loud each band sounds, a fourth root being close to how loudness
        # grows with power, so the biggest band (nearly always the bass) can't stand for the mix.
        lv = {"power": float(audible.mean()), "level": float(np.sqrt(np.sqrt(heardBands)).mean()) ** 4}
        for name, r in self._ranges:
            lv[name] = float(power[r].mean())
        colour = np.sqrt(heardBands)
        if self._peak is None:
            self._peak, self._colour = lv, colour
        else:
            self._peak = {k: max(self._peak[k], v) for k, v in lv.items()}
            self._colour = self._colour + colour

        dt = 1.0 / self.hopRate
        kickPower = power[self._kick]
        kr = self._kickRise.step(kickPower, dt)
        rr = self._restRise.step(bands[self._restBands], dt)
        if self.heard and lv["power"] >= SILENCE:
            if self.kicks.step(kr, t, sens, self.kickExpected) and lv["bass"] > 1e-6:
                self.kickSeen = True
                self.tempo.kick(t)
            self.tempo.add(t, kr + 0.5 * rr)
            self.roll.add(float(power[self._snare].mean()), float(kickPower.mean()))
            if self._hopCount % HARMONY_EVERY == 0:
                self.harmony.step(self._longHist, t)

    def hasLevels(self):
        return self._peak is not None

    def takeLevels(self):
        """(levels, band amplitudes) since the last call, or (None, None) with no new sound."""
        taken = self._peak, self._colour
        self._peak = self._colour = None
        return taken

    def takeKick(self):
        kick, self.kickSeen = self.kickSeen, False
        return kick

    def updateTempo(self, now):
        self.tempo.update(now)
        self.roll.update(now)
        self.tempo.checkCoast(now, self.kicks.lastBeat, self.roll.active)

    def pause(self):
        """No music: start the kick and tempo search afresh when it comes back."""
        self.tempo.reset()
        self.roll.reset()
        self.harmony.reset()
        self.kicks.reset()
        self._kickRise.reset()
        self._restRise.reset()


def _isSaturatedRed(hue, sat):
    """Whether this colour is one the flash guidelines treat as saturated red (red is at least 80% of the light)."""
    r, g, b = (c ** 2.2 for c in colorsys.hsv_to_rgb(hue / 360.0, sat / 100.0, 1.0))
    return r >= 0.8 * (r + g + b)


def rollRipple(hue, sat):
    """Brightness points roll hits may ripple between accents. Hits come several times a second, the
    rate most likely to affect people with photosensitive epilepsy, so each moves too little to count as a flash."""
    return ROLL_SWING_RED if _isSaturatedRed(hue, sat) else ROLL_SWING_MAX


class _FlashLimiter:
    """Keeps one light to a limit of flashes in a second, counted the WCAG way, a flash being a
    pair of opposite swings of 10% of full output or more, with the darker end below 80%. It works on the
    final brightness, so it holds whatever caused the flashing. A swing over the limit is cut short until one is free."""

    def __init__(self):
        self.extreme = self.extremeAt = None  # the top or bottom of the current swing, and when it was reached
        self.direction = 0   # +1 rising, -1 falling, 0 not known yet
        self.swings = deque()
        self.burstUsed = 0.0   # seconds spent above the Standard rate since the last full rest
        self.burstSeen = self.aboveAt = None  # the last step, and the last time the rate was above Standard
        self.resting = False   # the burst is used up: held to the Standard rate until the rest has passed

    def _burstCap(self, now, maxSwings):
        """The swings allowed now: a level above Standard only gets its own limit for a short burst."""
        standard = FLASH_LEVELS["Standard"][0]
        if maxSwings <= standard:
            return maxSwings
        elapsed = now - self.burstSeen if self.burstSeen is not None else 0.0
        self.burstSeen = now
        if sum(now - t < FLASH_WINDOW for t in self.swings) > standard:
            self.burstUsed += elapsed
            self.aboveAt = now
        elif self.aboveAt is not None and now - self.aboveAt >= FLASH_BURST_REST:
            self.burstUsed, self.aboveAt = 0.0, None
        self.resting = self.burstUsed >= FLASH_BURST
        return standard if self.resting else maxSwings

    def step(self, bri, now, maxSwings, reserve=0):
        """The brightness to send. A rise is refused while fewer than reserve swings would be left afterwards, which keeps them for the beats."""
        bri = round(bri)
        maxSwings = self._burstCap(now, maxSwings)
        if self.extreme is None:
            self.extreme, self.extremeAt = bri, now
            return bri
        moved = bri - self.extreme
        if moved * self.direction > 0:  # further the same way
            self.extreme, self.extremeAt = bri, now
        elif abs(moved) <= 1:  # resting here: the next swing starts when the light moves off, not when it arrived
            self.extremeAt = now
        elif abs(moved) >= FLASH_SWING and min(bri, self.extreme) < FLASH_BRIGHT:
            # Swings are dated by the turning point they start from, as a slow fade can hide how close together those are.
            while self.swings and self.extremeAt - self.swings[0] >= FLASH_WINDOW:
                self.swings.popleft()
            if len(self.swings) >= maxSwings - (reserve if moved > 0 else 0):
                self.extremeAt = now  # held at the turning point, which so moves along with the time
                return self.extreme + math.copysign(FLASH_SWING - 1, moved)
            self.swings.append(self.extremeAt)
            self.direction = 1 if moved > 0 else -1
            self.extreme, self.extremeAt = bri, now
        return bri


class _LightShow:
    """Turns the analysis into light colours, frame by frame, using the engine's current settings."""

    def __init__(self, engine, analyser):
        from neewerlux_midi import BeatTracker
        self.engine = engine
        self.analyser = analyser
        self.gains = {k: _AutoGain() for k in LEVELS}
        self.envs = {k: _Envelope() for k in LEVELS + ("centroid", "colour", "sustain")}
        self.gate = _SoundGate()
        self.cenRange = _Range()
        self.tracker = BeatTracker()
        self.rollTracker = BeatTracker()
        self.kickCentre = 0.0  # seconds the MIDI clock sits from the sound, as learned from kicks
        self.kickCentreKnown = False  # kicks have agreed on where they land against the MIDI clock
        self.kickPhase = deque(maxlen=KICK_PHASE_KEEP)  # seconds each recent kick landed from the MIDI clock's nearest beat
        self.heldPhase = None  # (time, phase) of a guided kick, kept back until its rise shows if it was a full kick
        self.rollPos = self.rollHit = None  # while a roll plays: position in hits, seconds per hit
        self.swellAt = self.swellFrom = None  # when this roll's Swell began, and the level it began at
        self.rollBegan = None  # when this roll began, which a brief dropout doesn't reset
        self.rollFlash = 0.0
        self.rollAccent = 0.0  # with the flash limit on, the deep flash on the beat within a roll, 1 down to 0
        self.rollTop = {}      # each light's top level on a roll's latest frame, which the fade after the roll starts from
        self.rollEnd = None    # when the roll being faded out ended
        self.rollKicked = False  # the first kick since has landed: the fade goes down with that kick's flash
        self.gainsBeforeKick = False  # a roll played, and no kick has landed since: the auto-gain still remembers its thin bass
        self.srcName = None
        self.heard = False
        self.raw = self.colour = None  # the levels of the last frame, reused when a beat arrives before new sound

        self.lastBeat = 0.0
        self.beatFlash = 0.0
        self.sustainFlash = False  # the latest flash came from sustained sound, not a kick
        self.dropFlash = False  # a kick that counts as a drop has just landed
        self.dropping = False   # the flash now fading is a drop's
        self.kickAfterRoll = False  # this frame's kick is the first since a roll
        self.gapLevels = deque()  # (time, dB) of the recent sound a stop is measured against
        self.lastDb = deque(maxlen=3)  # dB of the last few frames, for hits
        self.gapRef = self.gapSince = None  # while the music has stopped: the dB it stopped from, and when
        self.gapEnded = -10.0
        self.gapLength = 0.0   # how long the latest stop lasted
        self.lastHit = -10.0
        self.hitRise = 0.0  # dB the sound just jumped by
        self.kickBass = 0.0  # how hard kicks hit the bass (fourth-root scale), slowly forgotten
        self.limiters = {}     # each light's _FlashLimiter
        self.beatHit = 1.0     # how hard the bass hit around the last beat, 0..1
        self.beatPeriod = 0.5  # seconds between beats, measured from the kicks when nothing predicts them
        self.beatCount = 0
        self.notePitch = None  # pitch class waiting to set the next colour, while a synth plays with no kicks
        self.lastNote = -10.0  # when the notes last set the colour
        self.colourKick = 0.0  # "Bass pulse": the beat's push on the colour, fading slower than the flash
        self.lastKick = -10.0  # when a kick last reached a frame
        self.kickLevel = 0.0   # how loud the music is with kicks playing (fourth-root scale), slowly forgotten
        self.bassShare = 1.0   # how much of the bass reaches the brightness in the beat modes
        self.jumpFrom = self.jumpTo = None  # "Beat colour jump": glide from this colour to that one
        self.jumpAt = 0.0
        self.hue = float(engine.baseHue)
        self.palIdx = 0

        self.lastSent = {}
        self.lastFull = self.lastFrame = self.lastT = time.perf_counter()
        analyser.kickExpected = self._kickExpected

    def _beatSource(self, now):
        """Where beats come from: MIDI clock while it runs, else the tempo found in the sound, else each kick as it is heard."""
        clock = self.engine.clock
        if clock is not None and clock.active(now):
            return clock, "clock"
        if self.engine.predictBeats and self.heard and self.analyser.tempo.active(now):
            return self.analyser.tempo, "tempo"
        return None, "audio"

    def _kicksPlaying(self, now, src):
        period = src.beatPeriod() if src is not None else self.beatPeriod
        hold = SUSTAIN_KICK_HOLD if self.envs["sustain"].value > SUSTAIN_CHECK else KICK_HOLD_BEATS
        return now - self.lastKick < hold * period

    def _rollGrid(self, src, srcPos):
        """(position in roll hits, seconds per hit) while a roll plays over a known beat, else (None, None).
        Hits are placed on the beat grid rather than as heard, so they get the same lead as the beats."""
        roll = self.analyser.roll
        if not roll.active or srcPos is None:
            return None, None
        hitsPerBeat = max(2, round(src.beatPeriod() / roll.period))
        return srcPos * hitsPerBeat, src.beatPeriod() / hitsPerBeat

    def _kickPhaseCentre(self, period):
        """Where kicks have been landing against the MIDI clock, in seconds. Keeps the last answer until kicks agree on
        a new one, so a messy patch doesn't send it back to zero. A phase within reach needs less agreement than one far off."""
        seen = self.kickPhase
        if len(seen) < KICK_PHASE_MIN:
            return self.kickCentre
        width = KICK_ON_BEAT / 2.0
        reach = min(KICK_PHASE_MAX, 0.3 * period)
        together = lambda c: [_wrapPhase(x - c, period) for x in seen if abs(_wrapPhase(x - c, period)) <= width]
        best = max(seen, key=lambda c: (len(together(c)), -abs(c)))
        if abs(best) > reach and len(together(best)) < KICK_PHASE_FAR_SHARE * max(len(seen), KICK_PHASE_FAR_KICKS):
            best = max((c for c in seen if abs(c) <= reach), key=lambda c: (len(together(c)), -abs(c)), default=None)
        if best is not None and len(together(best)) >= KICK_PHASE_SHARE * len(seen):
            self.kickCentre = _wrapPhase(best + float(np.median(together(best))), period)
            self.kickCentreKnown = True
        return self.kickCentre

    def _kickExpected(self, t):
        """Does the beat grid put a kick at hop time t? Allows for where kicks have been landing against a MIDI clock."""
        src, name = self._beatSource(t)
        pos = src.position(t) if src is not None else None
        if pos is None or (name == "clock" and not self.kickCentreKnown):  # a clock's grid means nothing until its offset is known
            return False
        period = src.beatPeriod()
        if name == "clock" and sum(abs(_wrapPhase(x - self.kickCentre, period)) <= KICK_ON_BEAT / 2.0 for x in self.kickPhase) < KICK_GUIDED_AGREE * len(self.kickPhase):
            return False
        pos -= ONSET_DELAY / period
        off = (pos - round(pos)) * period
        return abs(_wrapPhase(off - (self.kickCentre if name == "clock" else 0.0), period)) <= KICK_GUIDED_WINDOW

    def _kickOnBeat(self, now, src, name):
        """Did the last kick land on a whole beat of its source? Reads the source without the beat lead,
        since a kick is heard on the beat itself, not when the lights fire ahead of it. Against a MIDI
        clock it goes by where kicks have been landing, as the clock and the sound arrive with different delays."""
        pos = src.position(now)
        if pos is None:
            return True
        period = src.beatPeriod()
        pos -= (now - (self.analyser.kicks.lastBeat - ONSET_DELAY)) / period
        off = (pos - round(pos)) * period
        centre = 0.0
        if name == "clock":
            kicks = self.analyser.kicks
            if self.heldPhase is not None and kicks.firmBeat == self.heldPhase[0]:  # by now its rise has shown it was a full kick
                self.kickPhase.append(self.heldPhase[1])
            self.heldPhase = None
            if kicks.guided:  # a kick let in by the learned offset would only confirm it, unless its rise goes on to clear the usual bar
                self.heldPhase = (kicks.lastBeat, off)
            else:
                self.kickPhase.append(off)
            centre = self._kickPhaseCentre(period)
        return abs(_wrapPhase(off - centre, period)) <= KICK_ON_BEAT

    def step(self, now):
        """One pass of the loop. Sends a frame if one is due. Returns the seconds to wait, or 0 to go straight on."""
        a = self.analyser
        interval = 1.0 / max(1, min(30, int(self.engine.fps)))
        if self.heard:
            a.updateTempo(now)
        src, name = self._beatSource(now)
        if name != self.srcName:  # positions of different sources don't line up
            self.tracker.step(None)
            self.rollTracker.step(None)
            self.srcName = name
            self.kickPhase.clear()
            self.heldPhase = None
            self.kickCentre = 0.0
            self.kickCentreKnown = False
        lead = max(0, self.engine.clockLeadMs) / 1000.0
        srcPos = src.position(now + lead) if src is not None else None
        if srcPos is not None and name == "clock" and self.kickCentreKnown:
            # Fire on the kicks, not the raw clock: DJ software sends its clock ahead of the audio it plays.
            # Taken off the position, as the clock only reads a tick into its past.
            srcPos -= self.kickCentre / src.beatPeriod()
        self.rollPos, self.rollHit = self._rollGrid(src, srcPos)
        # With beats predicted, a kick only needs its own frame if it is the first one back.
        beatDue = (a.kickSeen and (src is None or not self._kicksPlaying(now, src))) or self.tracker.due(srcPos) or self.rollTracker.due(self.rollPos)

        if not beatDue and (not a.hasLevels() or now - self.lastFrame < interval) or (beatDue and not a.hasLevels() and self.raw is None):
            wait = min(interval - (now - self.lastFrame), HOP / a.rate)
            if srcPos is not None:  # wake right at the next predicted beat
                wait = min(wait, (math.floor(srcPos) + 1 - srcPos) * src.beatPeriod() + 0.001)
            if self.rollPos is not None:
                wait = min(wait, (math.floor(self.rollPos) + 1 - self.rollPos) * self.rollHit + 0.001)
            return max(0.001, wait)
        self._frame(now, src, name, srcPos, lead)
        return 0

    def _frame(self, now, src, name, srcPos, lead):
        e, a = self.engine, self.analyser
        dt = max(1e-3, now - self.lastT)
        self.lastT = self.lastFrame = now
        if a.hasLevels():  # else a beat is due before new sound arrived: reuse the last levels
            self.raw, self.colour = a.takeLevels()
        raw = self.raw
        kick = a.takeKick()
        # A rise off the beat is a bassline or a synth, and must not keep the beats going. The detected tempo
        # is only trusted for this during sustained sound and on irregular rises: after a break it may be stale, and the drop must count.
        if kick and (name == "clock" or (name == "tempo" and self.envs["sustain"].value > SUSTAIN_CHECK and not a.kicks.keepsTime())) \
                and not self._kickOnBeat(now, src, name):
            kick = False
        # A rise far under the kicks so far is a thump in a break, unless it keeps time like a quieter kick would.
        self.kickBass *= 1.0 - SUSTAIN_DECAY * dt
        if kick:
            kickBass = math.sqrt(math.sqrt(raw["bass"]))
            if kickBass < KICK_BASS_FLOOR * self.kickBass and not a.kicks.keepsTime():
                kick = False
            else:
                self.kickBass = max(self.kickBass, kickBass)

        if a.roll.active:
            self.gainsBeforeKick = True
        self.kickAfterRoll = bool(kick and self.gainsBeforeKick and not a.roll.active)
        if self.kickAfterRoll:  # the drop has landed: measure the levels against it alone
            self.gainsBeforeKick = False
            for gain in self.gains.values():
                gain.forget()
            self.rollKicked = bool(self.rollTop)

        # Silence gate: below this the stream is effectively silent.
        silent = raw["power"] < SILENCE
        heard = self.gate.step(0.0 if silent else math.sqrt(math.sqrt(raw["power"])), now, dt)
        self.heard = a.heard = heard
        if not heard:
            a.pause()
            self.rollPos = self.rollHit = None  # the pause has just cleared the beat these were worked out from

        stopped = self._updateGap(now, raw, heard, kick)

        # Perceptual-ish scaling (compress), normalise, apply brightness sensitivity. The level is
        # already normalised to its recent range, so a plain multiplier would only clip at 1.
        # Brightness sensitivity bends the curve instead: >100% lifts quiet parts, <100% leaves only peaks.
        curve = 1.0 / max(0.05, float(e.brightSensitivity))
        # While no music is heard (a pause, room noise on a mic) the lights rest at minimum
        # and the auto-gain holds, so it never turns noise up to full brightness.
        norm = {}
        for k in LEVELS:
            n = self.gains[k].step(math.sqrt(math.sqrt(raw[k])), dt) if heard and not silent else 0.0
            norm[k] = min(1.0, n ** curve) if n > 0 else 0.0

        centroid = self._centroid(silent, dt)
        flashBefore = self.beatFlash
        beat, colourBeat, every = self._readBeat(now, src, name, srcPos, lead, kick, silent)
        freshFlash = beat or self.beatFlash > flashBefore
        if beat:
            if src is None and 0.25 < now - self.lastBeat < 2.0:
                self.beatPeriod += (now - self.lastBeat - self.beatPeriod) * 0.3
            self.lastBeat = now
            self.sustainFlash = False
            self.dropping, self.dropFlash = self.dropFlash, False
            self.beatFlash = 1.0
            self.beatHit = norm["bass"]
        elif now - self.lastBeat < BEAT_SETTLE:
            # A predicted beat can land just before the kick it marks (lead time, timing drift), so keep
            # taking the hardest bass for a moment after the beat.
            self.beatHit = max(self.beatHit, norm["bass"])
        if not freshFlash:  # a new flash shows at full height on its own frame
            self.beatFlash = max(0.0, self.beatFlash - dt * (DROP_FADE if self.dropping else SUSTAIN_FADE if self.sustainFlash else 4.0))
        rollHit, hitIdx = self.rollTracker.step(self.rollPos)
        if rollHit:
            self.rollFlash = 1.0
            if hitIdx % self._hitsPerAccent(src, now) == 0:
                self.rollAccent = 1.0
        elif self.rollPos is None:
            self.rollFlash = self.rollAccent = 0.0
        else:
            self.rollFlash = max(0.0, self.rollFlash - dt / (ROLL_FLASH_SHARE * self.rollHit))
            self.rollAccent = max(0.0, self.rollAccent - dt / (ROLL_ACCENT_SHARE * self._hitsPerAccent(src, now) * self.rollHit))
        rollFade = self._rollFade(now)

        release = 1.0 - min(0.95, max(0.0, e.smoothing))
        sm = {k: self.envs[k].step(norm[k], 0.85, release * 0.6, dt) for k in LEVELS}
        cen = self.envs["centroid"].step(centroid, release * 0.5, release * 0.5, dt)
        # Each beat flashes as hard as its kick: a soft kick a little, a hard one fully. With nothing
        # heard (a clock running without sound), every beat flashes fully.
        hit = 0.3 + 0.7 * self.beatHit if heard and not self.dropping else 1.0
        # "Bass pulse" colour glides instead of following the flash frame by frame: the flash jumps to
        # full in one frame and is gone in a quarter second, which shows as colour jumps.
        self.colourKick = max(self.colourKick - dt * 1.2, self.beatFlash * 0.8 * hit)
        colourFade = min(0.95, max(0.0, float(e.colourFade)))
        # Bass with no kicks (a held sub, a bassline on its own) shouldn't hold the beat modes up.
        share = KICK_BASS_SHARE if self._kicksPlaying(now, src) else KICKLESS_BASS
        self.bassShare = share if share > self.bassShare else self.bassShare + (share - self.bassShare) * min(1.0, dt * 4.0)
        bass = max(sm["bass"] * self.bassShare, self._sustain(now, src, raw, kick, heard, release, dt) * (KICK_BASS_SHARE - self.bassShare) / (KICK_BASS_SHARE - KICKLESS_BASS))
        colourPos = self.envs["colour"].step(max(bass, self.colourKick), 0.75, 0.7 * (1.0 - colourFade), dt)

        mode = e.mode
        pal = list(e.palette) if e.palette else None
        jumpCol = None
        if mode == "Beat colour jump":
            jumpCol = self._jumpColour(now, src, colourBeat, pal, every, colourFade)
        elif mode == "Rainbow drift":
            speed = 20 + 200 * sm["level"]
            if pal:  # same time per colour as the built-in rainbow takes per 60 degrees
                speed *= 6.0 / len(pal) if len(pal) > 1 else 1.0
            self.hue = (self.hue + dt * speed + (40 if beat else 0)) % 360

        # Resend everything now and then: a light that reconnected, or a new light that took a
        # dropped light's index, would otherwise wait until the colour changes enough.
        if now - self.lastFull > 2.0:
            self.lastSent = {}
            self.lastFull = now
        frame = {}
        targets = list(e.targets)
        reserve = FLASH_BEAT_RESERVE if mode in ROLL_MODES and self.rollPos is None and not freshFlash \
            and now - self.lastBeat >= BEAT_SETTLE and (self._kicksPlaying(now, src) or (src is not None and self.envs["sustain"].value > SUSTAIN_FLASH)) else 0
        maxSwings = FLASH_LEVELS[e.flashLevel][0]
        if maxSwings is None:  # with the limit off nothing is counted, so turning it back on starts afresh
            self.limiters.clear()
        for pos, idx in enumerate(targets):
            h, sat, amt = self._lightColour(mode, pos, targets, pal, sm, bass, cen, colourPos, hit, jumpCol)
            lo, hiB = sorted((int(e.minBri), int(e.maxBri)))
            sat = sat * e.saturation / 100.0
            if self.rollPos is not None and mode in ROLL_MODES:
                bri, self.rollTop[idx] = self._rollBrightness(now, lo, hiB, h, sat, amt)
            else:
                bri = lo + (hiB - lo) * max(0.0, min(1.0, amt))
                if rollFade and mode in ROLL_MODES and idx in self.rollTop:
                    bri = max(bri, lo + (self.rollTop[idx] - lo) * rollFade)  # a kick still shows through the fade
            if stopped and (name != "clock" or e.clockNeedsSound):
                bri = lo
            if maxSwings is not None:
                bri = self.limiters.setdefault(idx, _FlashLimiter()).step(bri, now, maxSwings, reserve)
            cmd = (int(round(h)) % 361, int(round(sat)), int(round(bri)))
            # Only send when something visibly changed.
            prev = self.lastSent.get(idx)
            if prev is None or abs(prev[0] - cmd[0]) >= 3 or abs(prev[2] - cmd[2]) >= 2 or abs(prev[1] - cmd[1]) >= 3:
                frame[idx] = cmd

        if stopped or not heard:  # the sound has gone: nothing from a roll comes back afterwards
            self.rollTop.clear()
            self.rollEnd = None

        e.state.update(level=sm["level"], bass=sm["bass"], mid=sm["mid"], high=sm["high"],
                       beat=self.beatFlash > 0.5, heard=heard)
        if targets:
            first = frame.get(targets[0], self.lastSent.get(targets[0]))
            if first:
                e.state.update(hue=first[0], sat=first[1], bri=first[2])
        if frame:
            try:
                if e.sendFunc(frame):
                    self.lastSent.update(frame)
                    e.state["error"] = ""  # a one-off failure shouldn't stay on screen
            except Exception as ex:
                e.state["error"] = str(ex)

    def _hitsPerAccent(self, src, now):
        """Roll hits from one deep flash to the next, always landing on the beat: as few as keep within the flash limit,
        except that above Standard a roll starts at one per beat and halves the gap every ROLL_BUILD_STEP seconds."""
        e = self.engine
        period = src.beatPeriod()
        perBeat = max(1, round(period / self.rollHit))
        building = e.flashLevel != "Standard" and not any(self.limiters[i].resting for i in e.targets if i in self.limiters)
        gap = FLASH_LEVELS[e.flashLevel if building else "Standard"][1]
        divisors = [hits for hits in range(1, perBeat + 1) if perBeat % hits == 0]
        fewest = next((hits for hits in divisors if hits * self.rollHit >= gap), perBeat * math.ceil(gap / period))
        if not building:
            return fewest
        hits = perBeat
        for _ in range(int((now - self.rollBegan) / ROLL_BUILD_STEP) if self.rollBegan is not None else 0):
            hits = max((d for d in divisors if d * 2 <= hits), default=1)
        return max(hits, fewest)

    def _sustain(self, now, src, raw, kick, heard, release, dt):
        """0..1, how far a sound with no kicks should hold the beat modes up: a synth as loud as the music
        was with kicks holds them, while a quieter pad or bassline doesn't. Before any kick nothing does."""
        loudness = math.sqrt(math.sqrt(raw["level"])) if heard else 0.0
        self.kickLevel *= 1.0 - SUSTAIN_DECAY * dt
        if kick or self._kicksPlaying(now, src):
            self.kickLevel = max(self.kickLevel, loudness)
        share = loudness / self.kickLevel if self.kickLevel > 0 else 0.0
        target = max(0.0, min(1.0, (share - SUSTAIN_FROM) / (SUSTAIN_FULL - SUSTAIN_FROM)))
        return self.envs["sustain"].step(target, 0.85, max(0.5, release * 0.6), dt) * (SUSTAIN_TOP if src is None else SUSTAIN_BEAT_TOP)

    def _updateGap(self, now, raw, heard, kick):
        """Is the music stopped right now? Measured against the sound of the last moments, a median, so it
        catches a cut before a drop and not the space between kicks, where the median is already low."""
        db = 10.0 * math.log10(max(raw["power"], 1e-12))
        self.hitRise = db - min(self.lastDb) if self.lastDb else 0.0
        self.lastDb.append(db)
        if self.gapSince is not None:
            if kick or not heard or db >= self.gapRef - GAP_EXIT or now - self.gapSince > GAP_LONGEST:
                self.gapLength = now - self.gapSince
                self.gapSince = None
                self.gapEnded = now
                self.gapLevels.clear()
            return self.gapSince is not None
        while self.gapLevels and now - self.gapLevels[0][0] > GAP_WINDOW:
            self.gapLevels.popleft()
        if heard and len(self.gapLevels) >= 5:
            ref = float(np.median([d for _, d in self.gapLevels]))
            if db < ref - GAP_DEPTH:
                self.gapRef, self.gapSince = ref, now
                return True
        if heard:
            self.gapLevels.append((now, db))
        return False

    def _centroid(self, silent, dt):
        """Where the sound sits on a log-frequency scale, 0 = deep bass, 1 = bright highs."""
        total = float(self.colour.sum())
        if total <= 0 or silent or not self.heard:  # silence or no music: hold the last colour
            return self.envs["centroid"].value
        c = float((self.analyser.bandLogF * self.colour).sum() / total)
        c = max(0.0, min(1.0, (c - math.log(80)) / (math.log(5000) - math.log(80))))
        return self.cenRange.step(c, dt)  # stretch over the range this music actually covers, so every colour shows

    def _readBeat(self, now, src, name, srcPos, lead, kick, silent):
        """(is this frame a beat, does the colour change on it, beats per colour)."""
        e = self.engine
        beatIdx = None
        gridBeat = False
        kicksPlaying = self._kicksPlaying(now, src)
        pitch = self.analyser.harmony.take()
        stopped = self.gapSince is not None and now - self.gapSince >= GAP_BEAT_AGE
        if kick:
            quietBeats = (now - self.lastKick) / max(0.05, src.beatPeriod() if src is not None else self.beatPeriod)
            # A kick is seen as its rise begins, so the sound around it may not have reached full level on this frame.
            loud = self.kickLevel > 0 and max(math.sqrt(math.sqrt(self.raw["level"])), math.sqrt(math.sqrt(self.raw["bass"]))) >= DROP_LOUDNESS * self.kickLevel
            self.dropFlash = self.lastKick > 0 and (((quietBeats >= DROP_QUIET_BEATS or self.kickAfterRoll) and loud) or (now - self.gapEnded < GAP_RECENT and self.gapLength >= GAP_DROP))
            self.lastKick = now
        if src is not None:
            # The position already runs ahead by the lead, so the first beat after a clock Start reads that far past it.
            onBeat = min(0.95, 0.1 + lead / max(0.05, src.beatPeriod()))
            beat, beatIdx = self.tracker.step(srcPos, onBeat)
            gridBeat = beat
            if name == "tempo" or e.clockNeedsSound:
                # Keep counting the bar, but only flash to kicks. The beat fires ahead of its kick, so it
                # goes by whether kicks have been playing, and the first kick back fires as it is heard,
                # unless it is the kick a flash already led.
                if not self.heard or stopped:
                    beat = False
                elif not kicksPlaying:
                    beat = kick and now - self.lastBeat > lead + KICK_ON_BEAT
                elif kick and now - self.gapEnded < GAP_RECENT and now - self.lastBeat > 0.25 * src.beatPeriod():
                    beat = True  # the kick the stop held back
                elif beat and now - self.lastBeat < 0.5 * src.beatPeriod():
                    beat = False  # a phase correction stepped back over a beat: don't fire it twice
            e.state.update(beatSource=name, bpm=src.bpm(), kicks=kicksPlaying or kick,
                           beatInBar=(beatIdx % 4) + 1 if name == "clock" and beatIdx is not None and beatIdx >= 0 else 0)
        else:
            beat = kick and self.heard and not silent
            e.state.update(beatSource="audio", bpm=0.0, beatInBar=0)
        every = max(1, int(e.beatsPerColour))
        if beat:
            self.beatCount += 1
        # A loud sound with no kicks flashes on the beats it's missing, without changing colour on each one.
        if gridBeat and not beat and not kicksPlaying and self.heard and not stopped and self.envs["sustain"].value > SUSTAIN_FLASH:
            self.beatFlash = self.beatHit = 1.0
            self.sustainFlash = True
        # A sudden loud hit with no kicks playing (a stab, a pickup into the next section) lands at once.
        if not beat and not kick and not kicksPlaying and self.heard and not stopped and self.hitRise >= HIT_RISE and self.kickLevel > 0 \
                and math.sqrt(math.sqrt(self.raw["level"])) >= HIT_LOUD * self.kickLevel and now - self.lastHit >= HIT_MIN_GAP and now - self.lastBeat >= HIT_MIN_GAP:
            self.lastHit = now
            self.beatFlash = self.beatHit = 1.0
            self.sustainFlash = True
        # A synth with no kicks: its notes choose the colour, so the same chord comes back in the same colour.
        period = src.beatPeriod() if src is not None else self.beatPeriod
        sustained = not kicksPlaying and self.heard and self.envs["sustain"].value > SUSTAIN_CHECK
        if pitch is not None and sustained and not beat and now - self.lastNote >= 0.9 * period:
            self.notePitch, self.lastNote = pitch, now
            if src is None and self.envs["sustain"].value > SUSTAIN_FLASH:  # no beats known: the notes are the only timing there is
                self.beatFlash = self.beatHit = 1.0
                self.sustainFlash = True
            return False, True, HARMONY_COLOUR_BEATS
        # No notes to go by (a noise sweep, one held chord): change on the bar instead.
        if gridBeat and not beat and sustained and beatIdx is not None and beatIdx % SUSTAIN_COLOUR_BEATS == 0 \
                and now - self.lastNote >= SUSTAIN_COLOUR_BEATS * period:
            return False, True, SUSTAIN_COLOUR_BEATS
        if name == "clock" and beatIdx is not None:  # count from the clock's downbeat, so changes land on bar lines
            return beat, beat and beatIdx % every == 0, every
        return beat, beat and (self.beatCount - 1) % every == 0, every

    def _jumpColour(self, now, src, colourBeat, pal, every, colourFade):
        """Each colour change glides over a share of the time until the next one, set by Colour fade
        (75% fills three quarters of it, 0 = a hard cut), from wherever the last glide had got to.
        A short fixed glide is only a frame or two once Bluetooth drops busy frames, so it still jumps."""
        period = src.beatPeriod() if src is not None else self.beatPeriod
        fade = max(0.1, period) * every * colourFade
        shown = self.jumpTo if self.jumpFrom is None or fade <= 0 else \
            _blend(self.jumpFrom, self.jumpTo, _ease(min(1.0, (now - self.jumpAt) / fade)))
        if colourBeat and self.notePitch is not None:  # round the circle of fifths, so related chords get neighbouring colours
            fifths = self.notePitch * 7 % 12
            self.notePitch = None
            self.hue = fifths * 30.0
            if pal:
                self.palIdx = fifths % len(pal)
        elif colourBeat:
            self.hue = (self.hue + 137.5) % 360
            if pal:
                self.palIdx = (self.palIdx + _beatStep(len(pal))) % len(pal)
        target = tuple(pal[self.palIdx % len(pal)]) if pal else (self.hue, 100.0)
        if target != self.jumpTo:  # a new colour on the beat, or the palette was changed
            self.jumpFrom, self.jumpTo, self.jumpAt = shown, target, now
            shown = self.jumpFrom if self.jumpFrom is not None and fade > 0 else target
        return shown

    def _lightColour(self, mode, pos, targets, pal, sm, bass, cen, colourPos, hit, jumpCol):
        """(hue, saturation, brightness 0..1) for the light at this position."""
        if mode == "Spectrum colour":
            h, sat = paletteAt(pal, cen, False) if pal else (cen * 280.0, 100.0)
            return h, sat, sm["level"]
        if mode == "Beat colour jump":
            # The bass, not the whole mix, so it dips between kicks.
            return jumpCol[0], jumpCol[1], max(bass, self.beatFlash)
        if mode == "Bass pulse":
            # Colour follows the same pump, smoothed: soft bass on the first colour, a hard kick or a
            # beat (audio or MIDI clock) glides up toward the last and eases back down.
            h, sat = paletteAt(pal, colourPos, False) if pal else (float(self.engine.baseHue), 100.0)
            return h, sat, max(bass, self.beatFlash * 0.8 * hit)
        if mode == "Frequency bands":
            bandCols = [pal[i % len(pal)] for i in range(3)] if pal else [(0.0, 100.0), (120.0, 100.0), (240.0, 100.0)]
            if len(targets) == 1:
                b, m, hi = sm["bass"], sm["mid"], sm["high"]
                h, sat = _mix(bandCols, (b, m, hi))
                return h, sat, max(b, m, hi)
            band = pos % 3
            h, sat = bandCols[band]
            return h, sat, sm[("bass", "mid", "high")[band]]
        # Rainbow drift
        off = pos / max(1, len(targets))
        h, sat = paletteAt(pal, self.hue / 360.0 + off, True) if pal else ((self.hue + off * 360.0) % 360, 100.0)
        return h, sat, max(sm["level"], self.beatFlash * 0.7)

    def _rollFade(self, now):
        """How much of a finished roll's level still shows, 1 as it ends down to 0. A roll that comes
        back before the fade is over keeps its Swell, so a brief dropout doesn't restart the climb."""
        if self.rollPos is not None:
            self.rollEnd = None
            self.rollKicked = False
            return 0.0
        if self.rollEnd is None and self.rollTop:
            self.rollEnd = now
        fade = 1.0 - (now - self.rollEnd) / ROLL_RELEASE if self.rollEnd is not None else 0.0
        if self.rollKicked:
            fade = min(fade, self.beatFlash)
        if fade <= 0.0:
            self.rollEnd = self.swellAt = self.rollBegan = None
            self.rollKicked = False
            self.rollTop.clear()
            return 0.0
        return fade

    def _rollBrightness(self, now, lo, hi, h, sat, amt):
        """(brightness, top level) 0..100 while a drum roll plays: a smooth climb in Swell, one pulse per
        hit in Strobe (deep on the beat under the flash limit), and in Strobe + Swell those pulses under a ceiling that climbs like the Swell."""
        style = self.engine.rollStyle
        if self.rollBegan is None:
            self.rollBegan = now
        if style != "Strobe":
            if self.swellAt is None:
                self.swellAt, self.swellFrom = now, max(0.0, min(amt, ROLL_SWELL_FROM))
            done = min(1.0, (now - self.swellAt) / ROLL_SWELL_TIME)
            hi = lo + (hi - lo) * (self.swellFrom + (1.0 - self.swellFrom) * done * done)
            if style == "Swell":
                return hi, hi
        ripple = min(rollRipple(h, sat), hi - lo)  # the limit counts flashes, not their depth, so accents can use the whole range
        return lo + (hi - ripple - lo) * self.rollAccent + ripple * self.rollFlash, hi


class SoundEngine:
    """Captures audio, analyses it and drives lights. One instance per app."""

    def __init__(self, sendFunc, logFunc=print):
        self.sendFunc = sendFunc
        self.log = logFunc

        # Settings, safe to change while running.
        self.mode = MODES[0]
        self.brightSensitivity = 1.0  # response curve: >1 lifts quiet parts, <1 leaves only peaks
        self.kickSensitivity = 1.0    # kick bar: >1 counts softer kicks, <1 only the strongest
        self.minBri = 5            # %
        self.maxBri = 100          # %
        self.saturation = 100      # %
        self.baseHue = 240         # degrees, used by "Bass pulse" when there is no palette
        self.palette = None        # None = each mode's built-in colours, else [(hue 0-360, sat 0-100), ...]
        self.smoothing = 0.5       # 0 = twitchy, 0.95 = very smooth (brightness and levels)
        self.colourFade = 0.75     # how long colour changes glide in Bass pulse and Beat colour jump, 0..0.95
        self.rollStyle = "Strobe"  # drum rolls: "Strobe" pulses on each hit, "Swell" climbs smoothly to Max bright, "Strobe + Swell" does both
        self.flashLevel = "Standard"  # how many flashes a second each light is held to: a key of FLASH_LEVELS
        self.fps = 15
        self.targets = []          # light indexes to drive
        self.clock = None          # a neewerlux_midi.MidiClock: beats come from it while it has ticks
        self.clockLeadMs = 50      # fire clock beats this early, to make up for Bluetooth delay
        self.beatsPerColour = 1    # "Beat colour jump": change colour every this many beats
        self.clockNeedsSound = True  # MIDI clock beats only fire while kicks are heard (Traktor clocks on when stopped)
        self.predictBeats = True   # without a clock, find the tempo in the sound and fire beats on time

        # Live state for the GUI (read-only from outside).
        self.state = {"level": 0.0, "bass": 0.0, "mid": 0.0, "high": 0.0,
                      "hue": 0.0, "sat": 100, "bri": 0, "beat": False, "error": "", "opened": False,
                      "beatSource": "audio", "bpm": 0.0, "beatInBar": 0, "heard": False, "kicks": False}

        self._stream = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._queue = deque(maxlen=1000)  # captured blocks waiting for analysis, about 10 s
        self._rate = 48000
        self._decim = 1            # keep every this-many-th sample
        self.running = False

    # --- capture ---------------------------------------------------------

    def _onAudio(self, indata, frames, timeInfo, status):
        now = time.perf_counter()
        self._lastAudio = now
        mono = indata.mean(axis=1) if indata.ndim > 1 else np.array(indata)
        self._queue.append((now, mono.astype(np.float32, copy=False)))  # deque.append is thread-safe

    def _takeAudio(self):
        """All blocks captured since the last call, as (samples, monotonic time of the last sample)."""
        blocks = []
        while self._queue:
            blocks.append(self._queue.popleft())
        if not blocks:
            return None, None
        return np.concatenate([b for _, b in blocks]), blocks[-1][0]

    def start(self, deviceIndex):
        """Start listening and driving lights. Returns '' or an error message.

        The device is opened on the sound thread, not here: on macOS the first open
        waits for the microphone permission prompt, and that must not freeze the GUI.
        Watch state["opened"] / state["error"] for the outcome."""
        if not AUDIO_AVAILABLE:
            return "Sound needs the 'sounddevice' and 'numpy' packages (" + AUDIO_IMPORT_ERROR + ")"
        self.stop()
        self.state.update(error="", opened=False)
        self._stop = threading.Event()  # fresh event: an old thread still opening a device keeps its own, set one
        self.running = True
        self._thread = threading.Thread(target=self._threadMain, args=(deviceIndex, self._stop), name="soundThread", daemon=True)
        self._thread.start()
        return ""

    def _threadMain(self, deviceIndex, stopEvent):
        with _soundThreadSetup():
            self._openAndRun(deviceIndex, stopEvent)

    def _openAndRun(self, deviceIndex, stopEvent):
        try:
            pulseSource = deviceIndex if isinstance(deviceIndex, str) else None
            if pulseSource:
                deviceIndex = next(i for i, d in enumerate(sd.query_devices()) if d["name"] == "pulse")
            info = sd.query_devices(deviceIndex)
            # A monitor is resampled by the sound server if it runs at another rate, and "pulse" reports a nominal one.
            self._rate = ANALYSIS_RATE if pulseSource else int(info.get("default_samplerate", 48000))
            self._decim = max(1, int(round(self._rate / float(ANALYSIS_RATE))))
            self._queue.clear()
            stream = _openInput(deviceIndex, self._rate, HOP * self._decim, self._onAudio, pulseSource)
        except Exception as e:
            if stopEvent is self._stop:
                self.state["error"] = "Could not open audio device: " + str(e)
                self.running = False
            return
        if stopEvent.is_set():  # stopped (or restarted) while waiting for the device
            stream.stop(); stream.close()
            return
        self._stream = stream
        self.state["opened"] = True
        self.log("Sound reactive started on '" + str(info.get("name")) + "' at " + str(self._rate) + " Hz")
        try:
            self._run(stopEvent)
        except Exception as e:  # report it instead of stopping without a word
            self.state["error"] = "Sound engine error: " + type(e).__name__ + ": " + str(e)
            self.log(self.state["error"])
        finally:
            try:
                stream.stop(); stream.close()
            except Exception:
                pass
            if stopEvent is self._stop:  # a restart while the stream was closing owns these now
                self._stream = None
                self.running = False
            self.log("Sound reactive stopped")

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)  # a thread stuck opening the device is a daemon; leave it
            self._thread = None
        self.running = False
        self.state.update(level=0.0, bass=0.0, mid=0.0, high=0.0, bri=0, beat=False)

    # --- analysis --------------------------------------------------------

    def _run(self, stopEvent):
        decimator = _Decimator(self._decim)
        analyser = _Analyser(self._rate / float(self._decim))
        show = _LightShow(self, analyser)
        started = self._lastAudio = time.perf_counter()
        while not stopEvent.is_set():
            # Callbacks stopped: device unplugged or failed. PulseAudio can hold a new stream back for
            # about 2 s while an idle sink finishes a long block, so the first seconds get more slack.
            now = time.perf_counter()
            if now - self._lastAudio > (4.0 if now - started < 6.0 else 2.0):
                self.state["error"] = "The audio device stopped sending sound (unplugged?)"
                break
            new, endT = self._takeAudio()
            if new is not None:
                analyser.feed(decimator.process(new), endT, max(0.05, float(self.kickSensitivity)))
            wait = show.step(time.perf_counter())
            if wait:
                stopEvent.wait(wait)
