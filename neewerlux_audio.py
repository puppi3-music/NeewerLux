"""Sound-reactive lighting for NeewerLux.

Listens to an audio input device, analyses it a number of times per second and
turns the result into a hue, saturation and brightness for each light.

To react to what your computer is playing (rather than a microphone), route the
output into a loopback device and pick that device here:

  macOS    BlackHole (https://existential.audio/blackhole/). Make a Multi-Output
           Device in Audio MIDI Setup with your speakers + BlackHole, set it as
           the system output, then choose "BlackHole" in the Sound tab.
  Windows  enable "Stereo Mix" in Sound settings, or install VB-Cable.
  Linux    PulseAudio/PipeWire "Monitor of ..." sources show up as inputs.

This module has no Qt dependency. The GUI reads SoundEngine.state for meters and
the engine calls sendFunc({lightIndex: (hue, sat, bri)}) to change the lights.
sounddevice and numpy are optional: AUDIO_AVAILABLE is False without them.
"""

import math
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
    "Beat colour jump": "Each detected beat moves to another palette colour (Auto: any colour), gliding there over part of the time until the next change: Colour fade 75% fills three quarters of it, 95% fades continuously, 0 cuts hard. Brightness follows the bass and flashes on the beat.",
    "Bass pulse": "Brightness pumps with the kick and bass, and the colour follows how hard it hits: soft bass on the first palette colour, hard kicks and each beat toward the last (stays blue on Auto).",
    "Frequency bands": "Light 1 = bass, light 2 = mids, light 3 = highs, repeating, in palette colours 1-3 (Auto: red, green, blue). One light blends all three.",
    "Rainbow drift": "Slides through the palette colours (Auto: the whole colour wheel), faster when it is louder. Beats give it a push.",
}

# Frequency band edges in Hz.
BASS = (20, 160)
MID = (160, 2000)
HIGH = (2000, 12000)

FFT_SIZE = 2048
QUIET_RATIO = 0.18  # level (fourth root of power) below this share of the music level counts as quiet, about -30 dB
QUIET_HOLD = 1.5    # seconds of quiet before MIDI clock beats pause
NOISE_MARGIN = 1.5  # music must be this far over the noise floor (fourth-root scale, about +7 dB) to count
HOP = 512           # samples analysed per step, about 94 steps a second at 48 kHz
KICK = (40, 160)    # Hz: where kick drums are looked for
KICK_MIN_RISE = 0.12  # a kick raises the bass by at least this much (log10 power, about 1.2 dB per bin) over the typical rise
KICK_SHARE = 0.7      # ... and reaches this share of the strongest rise in the last 1.5 s
KICK_ABS_RISE = 0.6    # ... and at least this much (6 dB a bin); kicks measure 1-2.5
MIN_BEAT_GAP = 0.18   # seconds: kicks closer than this count once
TEMPO_MIN_BPM, TEMPO_MAX_BPM = 70, 180
TEMPO_WINDOW = 8.0      # seconds of attacks the tempo is found from
TEMPO_MIN_SECONDS = 4.0  # ... and the least it needs
TEMPO_FIT_EVERY = 0.25  # seconds between estimates
TEMPO_HARMONIC = 0.5    # weight of the repeat two beats on
TEMPO_FAST_SHARE = 0.6  # ... see _estimate
TEMPO_MIN_CONF = 0.15   # autocorrelation at the beat period needed to trust it
ONSET_DELAY = 0.025     # seconds the detected attack lags the real one (measured on synthetic kicks)


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


def listInputDevices(rescan=False):
    """Return [(index, name, channels, defaultRate)] for every device that can record.

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
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((i, d["name"], int(d["max_input_channels"]), int(d.get("default_samplerate", 48000))))
    except Exception:
        pass
    return out


def preferredDeviceIndex(devices):
    """Pick the device most likely to carry system output (a loopback device), else the first."""
    keys = ("blackhole", "loopback", "stereo mix", "monitor of", "cable output", "soundflower")
    for i, name, _, _ in devices:
        if any(k in name.lower() for k in keys):
            return i
    return devices[0][0] if devices else None


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
    """Normalises a level to 0..1 between the recent quiet and the recent peak, so the
    quietest moments of the music sit at minimum brightness and the loudest at maximum.
    The peak decays slowly; the floor follows the level down at once and creeps back up.
    The floor stays at least minSpan below the peak, so a steady loud passage doesn't
    stretch tiny wobbles across the whole range."""

    def __init__(self, decayPerSecond=0.25, floorRisePerSecond=0.08, minSpan=0.35):
        self.peak = 1e-6
        self.floor = None
        self.decay = decayPerSecond
        self.rise = floorRisePerSecond
        self.minSpan = minSpan

    def step(self, value, dt):
        self.peak = max(value, self.peak * (1.0 - self.decay * dt), 1e-6)
        self.floor = value if self.floor is None else min(value, self.floor * (1.0 + self.rise * dt))
        lo = min(self.floor, self.peak * (1.0 - self.minSpan))
        return max(0.0, min(1.0, (value - lo) / (self.peak - lo)))


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
        rise = float(np.maximum(0.0, logP - self.prev[0]).mean()) if len(self.prev) == 2 else 0.0
        self.prev.append(logP)
        return rise

    def reset(self):
        self.prev.clear()


class _KickPicker:
    """Fires on a kick: a bass rise well above the typical rise of the last second and a half.
    The bar adapts to the music, so a long 808 or a busy bassline (steady, small rises) doesn't
    hide the kicks and soft kicks in a quiet section still count, and it sits near the strongest
    recent rises, so bass notes between the kicks (smaller rises) don't fire. Sensitivity lowers the bar."""

    def __init__(self, hopRate):
        self.rises = deque(maxlen=max(16, int(1.5 * hopRate)))
        self.armed = True
        self.lastBeat = -10.0

    def step(self, rise, t, sens):
        if len(self.rises) < 16:
            self.rises.append(rise)
            return False
        hist = np.fromiter(self.rises, float, len(self.rises))
        self.rises.append(rise)
        med = float(np.median(hist))
        spread = float(np.median(np.abs(hist - med)))
        # Also near the strongest recent rises, so a bass note between the kicks doesn't count as one.
        bar = max(med + (3.0 * spread + KICK_MIN_RISE) / sens, float(hist.max()) * KICK_SHARE / sens,
                  KICK_ABS_RISE / sens)  # and a real jump, so noise under quiet pads never counts
        if rise < bar:
            self.armed = True
            return False
        fire = self.armed and t - self.lastBeat > MIN_BEAT_GAP
        self.armed = False  # one beat per rise
        if fire:
            self.lastBeat = t
        return fire

    def reset(self):
        self.rises.clear()
        self.armed = True


class _TempoTracker:
    """Finds the tempo and beat phase in the sound, so beats can be fired on time, or a little
    early to make up for Bluetooth delay, instead of after each kick is heard. Every quarter
    second it autocorrelates the last 8 s of attacks to find the beat period (favouring tempos
    near 120 BPM and periods that also repeat at two beats), then lines a comb of beats up with
    the attacks to find where the beats fall. It locks after a few estimates agree and drops
    the lock when the music stops having a clear beat. Same interface as MidiClock."""

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
        if self.agree < 2:  # not yet confirmed: keep the current lock, if any, for now
            if self.locked and abs(period / self.period - 1.0) > 0.04:
                self._unsure()
            return
        if not self.locked or abs(period / self.period - 1.0) > 0.04:  # lock on, or a new tempo
            self.locked, self.period, self.refT, self.refPos = True, period, beatT, 0.0
            self.doubt = 0
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
            self.locked = False
            self.candidate, self.agree, self.doubt = 0.0, 0, 0

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


class SoundEngine:
    """Captures audio, analyses it and drives lights. One instance per app."""

    def __init__(self, sendFunc, logFunc=print):
        self.sendFunc = sendFunc
        self.log = logFunc

        # Settings, safe to change while running.
        self.mode = MODES[0]
        self.sensitivity = 1.0     # response curve: >1 lifts quiet parts and finds more beats, <1 only peaks
        self.minBri = 5            # %
        self.maxBri = 100          # %
        self.saturation = 100      # %
        self.baseHue = 240         # degrees, used by "Bass pulse" when there is no palette
        self.palette = None        # None = each mode's built-in colours, else [(hue 0-360, sat 0-100), ...]
        self.smoothing = 0.5       # 0 = twitchy, 0.95 = very smooth (brightness and levels)
        self.colourFade = 0.75     # how long colour changes glide in Bass pulse and Beat colour jump, 0..0.95
        self.fps = 15
        self.targets = []          # light indexes to drive
        self.clock = None          # a neewerlux_midi.MidiClock: beats come from it while it has ticks
        self.clockLeadMs = 50      # fire clock beats this early, to make up for Bluetooth delay
        self.beatsPerColour = 1    # "Beat colour jump": change colour every this many beats
        self.clockNeedsSound = True  # MIDI clock beats only fire while music is heard (Traktor clocks on when stopped)
        self.predictBeats = True   # without a clock, find the tempo in the sound and fire beats on time

        # Live state for the GUI (read-only from outside).
        self.state = {"level": 0.0, "bass": 0.0, "mid": 0.0, "high": 0.0,
                      "hue": 0.0, "sat": 100, "bri": 0, "beat": False, "error": "", "opened": False,
                      "beatSource": "audio", "bpm": 0.0, "beatInBar": 0, "heard": False}

        self._stream = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._queue = deque(maxlen=1000)  # captured blocks waiting for analysis, about 10 s
        self._rate = 48000
        self.running = False

    # --- capture ---------------------------------------------------------

    def _onAudio(self, indata, frames, timeInfo, status):
        now = time.monotonic()
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
        self._thread = threading.Thread(target=self._openAndRun, args=(deviceIndex, self._stop), name="soundThread", daemon=True)
        self._thread.start()
        return ""

    def _openAndRun(self, deviceIndex, stopEvent):
        try:
            info = sd.query_devices(deviceIndex)
            self._rate = int(info.get("default_samplerate", 48000))
            channels = max(1, min(2, int(info.get("max_input_channels", 1))))
            self._queue.clear()
            stream = sd.InputStream(device=deviceIndex, channels=channels, samplerate=self._rate,
                                    blocksize=512, dtype="float32", callback=self._onAudio)
            stream.start()
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
            self._run()
        except Exception as e:  # report it instead of stopping without a word
            self.state["error"] = "Sound engine error: " + type(e).__name__ + ": " + str(e)
            self.log(self.state["error"])
        finally:
            try:
                stream.stop(); stream.close()
            except Exception:
                pass
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

    def _run(self):
        rate = self._rate
        hopRate = rate / float(HOP)
        window = np.hanning(FFT_SIZE).astype(np.float32)
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / rate)
        masks = {name: (freqs >= lo) & (freqs < hi) for name, (lo, hi) in
                 (("bass", BASS), ("mid", MID), ("high", HIGH))}
        audible = (freqs >= 40) & (freqs < 12000)
        kickBins = (freqs >= KICK[0]) & (freqs < KICK[1])
        restBins = (freqs >= KICK[1]) & (freqs < 8000)
        logF = np.log(np.maximum(freqs, 1.0))

        gains = {k: _AutoGain() for k in ("level", "bass", "mid", "high")}
        envs = {k: _Envelope() for k in ("level", "bass", "mid", "high", "centroid", "colour")}
        gate = _SoundGate()
        cenRange = _Range()
        kickRise, restRise = _Rise(), _Rise()
        kicks = _KickPicker(hopRate)
        tempo = _TempoTracker(hopRate)
        lastBeat = 0.0
        beatFlash = 0.0
        beatHit = 1.0  # how hard the bass hit around the last beat, 0..1
        jumpFrom = jumpTo = None  # "Beat colour jump": glide from this colour to that one
        jumpAt = 0.0
        beatPeriod = 0.5  # seconds between beats, measured from the kicks when nothing predicts them
        colourKick = 0.0  # "Bass pulse": the beat's push on the colour, fading slower than the flash
        hue = float(self.baseHue)
        palIdx = 0
        beatCount = 0
        from neewerlux_midi import BeatTracker
        tracker = BeatTracker()
        srcName = None
        lastSent = {}
        lastFull = time.monotonic()

        hist = np.zeros(FFT_SIZE, dtype=np.float32)  # the last FFT_SIZE samples
        pending = np.zeros(0, dtype=np.float32)        # samples not yet analysed
        peak = None          # loudest hop since the last light frame, per band
        specSum = None       # summed spectrum since the last light frame, for the centroid
        kickSeen = False     # a kick was detected since the last light frame
        lastRaw = lastSpec = None
        heard = False
        lastFrame = lastT = time.monotonic()

        self._lastAudio = time.monotonic()
        while not self._stop.is_set():
            if time.monotonic() - self._lastAudio > 2.0:  # callbacks stopped: device unplugged or failed
                self.state["error"] = "The audio device stopped sending sound (unplugged?)"
                break
            interval = 1.0 / max(1, min(30, int(self.fps)))
            sens = max(0.05, float(self.sensitivity))

            # Analyse every hop of new sound, so no kick falls between light frames.
            new, endT = self._takeAudio()
            if new is not None:
                pending = np.concatenate((pending, new))
                hops = len(pending) // HOP
                for h in range(hops):
                    hist[:-HOP] = hist[HOP:]
                    hist[-HOP:] = pending[h * HOP:(h + 1) * HOP]
                    tHop = endT - (len(pending) - (h + 1) * HOP) / rate
                    spec = np.abs(np.fft.rfft(hist * window))
                    power = spec ** 2
                    lv = {"level": float(power[audible].mean())}
                    for name, m in masks.items():
                        lv[name] = float(power[m].mean())
                    if peak is None:
                        peak, specSum = lv, spec[audible].copy()
                    else:
                        peak = {k: max(peak[k], v) for k, v in lv.items()}
                        specSum += spec[audible]
                    kr = kickRise.step(power[kickBins], 1.0 / hopRate)
                    rr = restRise.step(power[restBins], 1.0 / hopRate)
                    if heard and lv["level"] >= 1e-7:
                        if kicks.step(kr, tHop, sens) and lv["bass"] > 1e-6:
                            kickSeen = True
                        tempo.add(tHop, kr + 0.5 * rr)
                pending = pending[hops * HOP:]

            now = time.monotonic()
            if heard:
                tempo.update(now)
                if tempo.locked and now - kicks.lastBeat > max(2.0, 4.0 * tempo.period):
                    tempo.reset()  # the kicks stopped (a breakdown): follow the sound until they come back

            # Where beats come from: MIDI clock while it runs, else the tempo found in the sound,
            # else each kick as it is heard.
            clock = self.clock
            if clock is not None and clock.active(now):
                src, name = clock, "clock"
            elif self.predictBeats and heard and tempo.active(now):
                src, name = tempo, "tempo"
            else:
                src, name = None, "audio"
            if name != srcName:  # positions of different sources don't line up
                tracker.step(None)
                srcName = name
            lead = max(0, self.clockLeadMs) / 1000.0
            srcPos = src.position(now + lead) if src is not None else None
            beatDue = (kickSeen and src is None) or \
                (srcPos is not None and tracker.lastIdx is not None and math.floor(srcPos) != tracker.lastIdx)

            if peak is None and (lastRaw is None or not beatDue) or (now - lastFrame < interval and not beatDue):
                wait = min(interval - (now - lastFrame), HOP / float(rate))
                if srcPos is not None:  # wake right at the next predicted beat
                    wait = min(wait, (math.floor(srcPos) + 1 - srcPos) * src.beatPeriod() + 0.001)
                self._stop.wait(max(0.001, wait))
                continue
            dt = max(1e-3, now - lastT)
            lastT = lastFrame = now
            if peak is not None:  # else a beat is due before new sound arrived: reuse the last levels
                lastRaw, lastSpec = peak, specSum
            raw, spec, peak, specSum = lastRaw, lastSpec, None, None
            kick, kickSeen = kickSeen, False

            # Silence gate: below this the stream is effectively silent.
            silent = raw["level"] < 1e-7
            heard = gate.step(0.0 if silent else math.sqrt(math.sqrt(raw["level"])), now, dt)
            if not heard:  # a pause: start the tempo search afresh when the music comes back
                tempo.reset()
                kicks.reset()

            # Perceptual-ish scaling (compress), normalise, apply sensitivity. The level is
            # already normalised to its recent peak, so a plain multiplier would only clip at 1.
            # Sensitivity bends the curve instead: >100% lifts quiet parts, <100% leaves only peaks.
            curve = 1.0 / sens
            # While no music is heard (a pause, room noise on a mic) the lights rest at minimum
            # and the auto-gain holds, so it never turns noise up to full brightness.
            norm = {}
            for k, v in raw.items():
                n = gains[k].step(math.sqrt(math.sqrt(v)), dt) if heard and not silent else 0.0
                norm[k] = min(1.0, n ** curve) if n > 0 else 0.0

            # Spectral centroid on a log-frequency scale, 0 = deep bass, 1 = bright highs.
            total = float(spec.sum())
            if total > 0 and not silent and heard:
                c = float((logF[audible] * spec).sum() / total)
                centroid = (c - math.log(80)) / (math.log(5000) - math.log(80))
                centroid = max(0.0, min(1.0, centroid))
                # Stretch over the range this music actually covers, so every colour shows.
                centroid = cenRange.step(centroid, dt)
            else:  # silence or no music: hold the last colour
                centroid = envs["centroid"].value

            beatIdx = None
            if src is not None:
                beat, beatIdx = tracker.step(srcPos)
                if name == "tempo" and beat and now - lastBeat < 0.5 * src.beatPeriod():
                    beat = False  # a phase correction stepped back over a beat: don't fire it twice
                if name == "clock" and self.clockNeedsSound and not heard:
                    beat = False  # keep counting the bar, but don't flash to a stopped deck
                self.state.update(beatSource=name, bpm=src.bpm(),
                                  beatInBar=(beatIdx % 4) + 1 if name == "clock" and beatIdx is not None and beatIdx >= 0 else 0)
            else:
                beat = kick and heard and not silent
                self.state.update(beatSource="audio", bpm=0.0, beatInBar=0)
            every = max(1, int(self.beatsPerColour))
            if beat:
                beatCount += 1
            if name == "clock" and beatIdx is not None:  # count from the clock's downbeat, so changes land on bar lines
                colourBeat = beat and beatIdx % every == 0
            else:
                colourBeat = beat and (beatCount - 1) % every == 0
            if beat:
                if src is None and 0.25 < now - lastBeat < 2.0:
                    beatPeriod += (now - lastBeat - beatPeriod) * 0.3
                lastBeat = now
                beatFlash = 1.0
                beatHit = norm["bass"]
            elif now - lastBeat < 0.15:
                # A predicted beat can land just before the kick it marks (lead time, timing drift), so keep
                # taking the hardest bass for a moment after the beat.
                beatHit = max(beatHit, norm["bass"])
            beatFlash = max(0.0, beatFlash - dt * 4.0)

            release = 1.0 - min(0.95, max(0.0, self.smoothing))
            sm = {}
            for k in ("level", "bass", "mid", "high"):
                sm[k] = envs[k].step(norm[k], 0.85, release * 0.6, dt)
            cen = envs["centroid"].step(centroid, release * 0.5, release * 0.5, dt)
            # "Bass pulse" colour glides instead of following the flash frame by frame: the flash jumps to
            # full in one frame and is gone in a quarter second, which shows as colour jumps.
            hitNow = 0.3 + 0.7 * beatHit if heard else 1.0
            colourKick = max(colourKick - dt * 1.2, beatFlash * 0.8 * hitNow)
            colourFade = min(0.95, max(0.0, float(self.colourFade)))
            colourPos = envs["colour"].step(max(sm["bass"], colourKick), 0.75, 0.7 * (1.0 - colourFade), dt)

            mode = self.mode
            pal = list(self.palette) if self.palette else None
            if mode == "Beat colour jump":
                # Each colour change glides over a share of the time until the next one, set by Colour fade
                # (75% fills three quarters of it, 0 = a hard cut), from wherever the last glide had got to.
                # A short fixed glide is only a frame or two once Bluetooth drops busy frames, so it still jumps.
                period = src.beatPeriod() if src is not None else beatPeriod
                gap = max(0.1, period) * every
                fade = gap * colourFade
                shown = jumpTo if jumpFrom is None or fade <= 0 else \
                    _blend(jumpFrom, jumpTo, _ease(min(1.0, (now - jumpAt) / fade)))
                if colourBeat:
                    hue = (hue + 137.5) % 360
                    if pal:
                        palIdx = (palIdx + _beatStep(len(pal))) % len(pal)
                target = tuple(pal[palIdx % len(pal)]) if pal else (hue, 100.0)
                if target != jumpTo:  # a new colour on the beat, or the palette was changed
                    jumpFrom, jumpTo, jumpAt = shown, target, now
                    shown = jumpFrom if jumpFrom is not None and fade > 0 else target
                jumpCol = shown
            elif mode == "Rainbow drift":
                speed = 20 + 200 * sm["level"]
                if pal:  # same time per colour as the built-in rainbow takes per 60 degrees
                    speed *= 6.0 / len(pal) if len(pal) > 1 else 1.0
                hue = (hue + dt * speed + (40 if beat else 0)) % 360

            # Resend everything now and then: a light that reconnected, or a new light that took a
            # dropped light's index, would otherwise wait until the colour changes enough.
            if now - lastFull > 2.0:
                lastSent = {}
                lastFull = now
            frame = {}
            targets = list(self.targets)
            for pos, idx in enumerate(targets):
                sat = 100.0
                if mode == "Spectrum colour":
                    amt = sm["level"]
                    h, sat = paletteAt(pal, cen, False) if pal else (cen * 280.0, 100.0)
                elif mode == "Beat colour jump":
                    amt = max(sm["bass"], beatFlash)  # the bass, not the whole mix, so it dips between kicks
                    h, sat = jumpCol
                elif mode == "Bass pulse":
                    # Each beat flashes as hard as its kick: a soft kick a little, a hard one fully. With
                    # nothing heard (a clock running without sound), every beat flashes fully as before.
                    hit = 0.3 + 0.7 * beatHit if heard else 1.0
                    amt = max(sm["bass"], beatFlash * 0.8 * hit)
                    # Colour follows the same pump, smoothed: soft bass on the first colour, a hard kick or a
                    # beat (audio or MIDI clock) glides up toward the last and eases back down.
                    h, sat = paletteAt(pal, colourPos, False) if pal else (float(self.baseHue), 100.0)
                elif mode == "Frequency bands":
                    bandCols = [pal[i % len(pal)] for i in range(3)] if pal else [(0.0, 100.0), (120.0, 100.0), (240.0, 100.0)]
                    if len(targets) == 1:
                        b, m, hi = sm["bass"], sm["mid"], sm["high"]
                        h, sat = _mix(bandCols, (b, m, hi))
                        amt = max(b, m, hi)
                    else:
                        band = pos % 3
                        (h, sat), amt = bandCols[band], sm[("bass", "mid", "high")[band]]
                else:  # Rainbow drift
                    amt = max(sm["level"], beatFlash * 0.7)
                    off = pos / max(1, len(targets))
                    h, sat = paletteAt(pal, hue / 360.0 + off, True) if pal else ((hue + off * 360.0) % 360, 100.0)

                lo, hiB = sorted((int(self.minBri), int(self.maxBri)))
                bri = int(round(lo + (hiB - lo) * max(0.0, min(1.0, amt))))
                cmd = (int(round(h)) % 361, int(round(sat * self.saturation / 100.0)), bri)
                # Only send when something visibly changed.
                prev = lastSent.get(idx)
                if prev is None or abs(prev[0] - cmd[0]) >= 3 or abs(prev[2] - cmd[2]) >= 2 or abs(prev[1] - cmd[1]) >= 3:
                    frame[idx] = cmd

            self.state.update(level=sm["level"], bass=sm["bass"], mid=sm["mid"], high=sm["high"],
                              beat=beatFlash > 0.5, heard=heard)
            if targets:
                first = frame.get(targets[0], lastSent.get(targets[0]))
                if first:
                    self.state.update(hue=first[0], sat=first[1], bri=first[2])

            if frame:
                try:
                    if self.sendFunc(frame):
                        lastSent.update(frame)
                except Exception as e:
                    self.state["error"] = str(e)
