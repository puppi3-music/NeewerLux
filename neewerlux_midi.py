"""MIDI clock input for NeewerLux's Sound tab.

DJ software and drum machines can send MIDI clock: 24 ticks per beat plus Start,
Stop and Continue messages. Following it gives the exact tempo and beat position,
so beat effects land on every beat however busy the bass is.

Traktor: Preferences > MIDI Clock > tick "Send MIDI Clock". Add a Generic MIDI
controller in Controller Manager with Out-Port "Traktor Virtual Output". Then in
the Master Clock panel press the clock-send button. Press Sync there (or stop and
start the clock) to line the count up with the downbeat again.

python-rtmidi is optional: MIDI_AVAILABLE is False without it.
"""

import math
import threading
import time

try:
    import rtmidi
    MIDI_AVAILABLE = True
    MIDI_IMPORT_ERROR = ""
except Exception as e:  # ImportError, or OSError when the MIDI backend is missing
    rtmidi = None
    MIDI_AVAILABLE = False
    MIDI_IMPORT_ERROR = str(e)

TICKS_PER_BEAT = 24
CLOCK, START, CONTINUE, STOP, SONG_POSITION = 0xF8, 0xFA, 0xFB, 0xFC, 0xF2
STALE_AFTER = 0.5  # seconds without a tick before the clock counts as gone


def listPorts():
    """Names of the MIDI inputs, in port order. Empty when MIDI is unavailable."""
    if not MIDI_AVAILABLE:
        return []
    try:
        m = rtmidi.MidiIn()
        ports = m.get_ports()
        m.delete()
        return ports
    except Exception:
        return []


def preferredPort(ports):
    """The port most likely to carry a DJ clock, or None."""
    for want in ("traktor", "rekordbox", "serato", "virtual dj", "clock"):
        for p in ports:
            if want in p.lower():
                return p
    return None


class MidiClock:
    """Follows MIDI clock from one input port.

    Ticks arrive on rtmidi's thread; position() and bpm() are safe from any thread.
    feed() takes raw messages too, so the clock can be tested without a port."""

    def __init__(self):
        self._lock = threading.Lock()
        self._midi = None
        self.portName = ""
        self._reset()

    def _reset(self):
        self._ticks = -1          # index of the last tick since Start; tick 0 is the first beat
        self._lastTick = 0.0      # monotonic time of that tick
        self._period = 0.0        # smoothed seconds per tick
        self.playing = False      # Start/Continue seen without a Stop since

    # --- port ------------------------------------------------------------

    def open(self, portName):
        """Listen on the named port. Returns '' or an error message."""
        self.close()
        if not MIDI_AVAILABLE:
            return "MIDI clock needs the 'python-rtmidi' package (" + MIDI_IMPORT_ERROR + ")"
        try:
            m = rtmidi.MidiIn()
            ports = m.get_ports()
            if portName not in ports:
                m.delete()
                return "MIDI input '" + portName + "' not found"
            m.ignore_types(sysex=True, timing=False, active_sense=True)
            m.set_callback(self._onMessage)
            m.open_port(ports.index(portName))
        except Exception as e:
            return "Could not open MIDI input: " + str(e)
        with self._lock:
            self._reset()
        self._midi = m
        self.portName = portName
        return ""

    def close(self):
        m, self._midi = self._midi, None
        self.portName = ""
        if m is not None:
            try:
                m.cancel_callback()
                m.close_port()
                m.delete()
            except Exception:
                pass

    def _onMessage(self, event, data=None):
        self.feed(event[0], time.monotonic())

    # --- clock -----------------------------------------------------------

    def feed(self, message, now):
        """Handle one MIDI message (list of bytes) received at monotonic time now."""
        if not message:
            return
        status = message[0]
        with self._lock:
            if status == CLOCK:
                if self._ticks >= 0 and self._lastTick:
                    gap = now - self._lastTick
                    if self._period == 0.0:
                        self._period = gap
                    elif gap < self._period * 4:  # a longer gap is a pause, not a tempo
                        # Fast enough to follow a tempo change within a beat or two,
                        # slow enough to iron out per-tick timing jitter.
                        self._period += (gap - self._period) * 0.08
                self._ticks += 1
                self._lastTick = now
            elif status == START:
                self._ticks = -1   # the next tick is beat 0
                self.playing = True
            elif status == CONTINUE:
                self.playing = True
            elif status == STOP:
                self.playing = False
            elif status == SONG_POSITION and len(message) >= 3:
                sixteenths = message[1] | (message[2] << 7)
                self._ticks = sixteenths * (TICKS_PER_BEAT // 4) - 1

    def active(self, now=None):
        """True while ticks are arriving and the tempo is known."""
        now = time.monotonic() if now is None else now
        with self._lock:
            return self._period > 0 and self._ticks >= 0 and now - self._lastTick < STALE_AFTER

    def bpm(self):
        with self._lock:
            return 60.0 / (self._period * TICKS_PER_BEAT) if self._period > 0 else 0.0

    def beatPeriod(self):
        with self._lock:
            return self._period * TICKS_PER_BEAT

    def position(self, at):
        """Beats since Start at monotonic time at (may be a little in the future),
        or None when there is no clock. Beat n starts at exactly n.0."""
        with self._lock:
            if self._period <= 0 or self._ticks < 0:
                return None
            ahead = (at - self._lastTick) / self._period
            # Extrapolate at most half a beat past the last tick: if ticks stop, so do we.
            ahead = max(-1.0, min(ahead, TICKS_PER_BEAT / 2))
            return (self._ticks + ahead) / TICKS_PER_BEAT


class BeatTracker:
    """Turns a running beat position into one 'beat' event per whole beat."""

    def __init__(self):
        self.lastIdx = None

    def step(self, pos):
        """pos is the beat position, or None. Returns (isBeat, beatIndex)."""
        if pos is None:
            self.lastIdx = None
            return False, None
        idx = math.floor(pos)
        if self.lastIdx is None:
            # First reading: only a beat if we are right on it (just after Start).
            self.lastIdx = idx
            return (pos - idx) < 0.05 and idx >= 0, idx
        if idx != self.lastIdx:
            self.lastIdx = idx
            return idx >= 0, idx
        return False, idx
