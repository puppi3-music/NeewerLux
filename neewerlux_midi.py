# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Puppi3
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
TICK_GAIN = 0.12   # share of each tick's timing error taken into the filtered position (see _track)
MIN_TICK_GAP = 0.002  # seconds: a first gap under this (1250 BPM) is ticks delivered together, not a tempo


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
        self._lastTick = 0.0      # monotonic time that tick arrived
        self._tickTime = 0.0      # when that tick should have arrived, with its timing jitter filtered out
        self._tracked = 0         # ticks the filter has seen since it last started over
        self._period = 0.0        # smoothed seconds per tick
        self._longGap = False     # the last gap was too long to be a tempo (see _track)
        self._stopped = False     # Stop seen without a Start/Continue since. Some sources never send Start

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
        self.feed(event[0], time.perf_counter())

    # --- clock -----------------------------------------------------------

    def feed(self, message, now):
        """Handle one MIDI message (list of bytes) received at monotonic time now."""
        if not message:
            return
        status = message[0]
        with self._lock:
            if status == CLOCK:
                if self._ticks >= 0 and self._lastTick:
                    self._track(now, now - self._lastTick)
                else:
                    self._tickTime, self._tracked, self._longGap = now, 1, False
                if not self._stopped:  # a stopped source can keep clocking: that keeps the tempo, not the position
                    self._ticks += 1
                self._lastTick = now
            elif status == START:
                self._ticks = -1   # the next tick is beat 0
                self._stopped = False
            elif status == CONTINUE:
                self._stopped = False
            elif status == STOP:
                self._stopped = True
            elif status == SONG_POSITION and len(message) >= 3:
                sixteenths = message[1] | (message[2] << 7)
                self._ticks = sixteenths * (TICKS_PER_BEAT // 4) - 1

    def _track(self, now, gap):
        """Filter one tick's arrival time (alpha-beta): predict it, then take a share of the error
        into both the position and the tempo. Each tick then counts for little, so timing jitter
        barely shows, yet a tempo change is followed within about a beat."""
        if self._period == 0.0:
            if gap >= MIN_TICK_GAP:
                self._period = gap
            self._tickTime, self._tracked = now, 1
            return
        if gap >= self._period * 4:
            # Once is a pause: pick up from here. Twice running is the tempo itself (a big slowdown, or a bad period).
            if self._longGap:
                self._period = gap
            self._longGap = not self._longGap
            self._tickTime, self._tracked = now, 1
            return
        self._longGap = False
        self._tracked += 1
        n = self._tracked
        # Early on, trust the ticks more: this is a straight-line fit through the ticks so far.
        alpha = max(TICK_GAIN, 2.0 * (2 * n - 1) / (n * (n + 1)))
        beta = max(TICK_GAIN ** 2 / (2.0 - TICK_GAIN), 6.0 / (n * (n + 1)))
        predicted = self._tickTime + self._period
        error = now - predicted
        self._tickTime = predicted + alpha * error
        self._period = max(self._period + beta * error, 1e-4)

    def active(self, now=None):
        """True while ticks are arriving and the tempo is known. Stays True from a Start to its first tick,
        when position() is None: the clock hasn't gone away, so what was learned about it still holds."""
        now = time.perf_counter() if now is None else now
        with self._lock:
            return self._period > 0 and now - self._lastTick < STALE_AFTER

    def bpm(self):
        with self._lock:
            return 60.0 / (self._period * TICKS_PER_BEAT) if self._period > 0 else 0.0

    def beatPeriod(self):
        with self._lock:  # never 0: callers divide by it, and opening a port can clear the tempo just after they read position()
            return self._period * TICKS_PER_BEAT if self._period > 0 else 0.5

    def position(self, at):
        """Beats since Start at monotonic time at (may be a little in the future),
        or None when there is no clock. Beat n starts at exactly n.0. Holds still after a Stop."""
        with self._lock:
            if self._period <= 0 or self._ticks < 0:
                return None
            if self._stopped:
                return self._ticks / float(TICKS_PER_BEAT)
            ahead = (at - self._tickTime) / self._period
            # Extrapolate at most half a beat past the last tick: if ticks stop, so do we.
            ahead = max(-1.0, min(ahead, TICKS_PER_BEAT / 2))
            return (self._ticks + ahead) / TICKS_PER_BEAT


class BeatTracker:
    """Turns a running beat position into one 'beat' event per whole beat.

    A late MIDI tick or a phase correction can pull the position back a little, just under
    the beat already fired. That is held, so the beat doesn't fire again when it recrosses."""

    SLIP = 0.25  # beats: a step back this small is timing noise, a larger one is a new position

    def __init__(self):
        self.lastIdx = None

    def _slipped(self, pos, idx):
        return idx == self.lastIdx - 1 and pos - idx > 1.0 - self.SLIP

    def due(self, pos):
        """True when step(pos) has something to act on: a first reading, a new beat or a jump."""
        if pos is None:
            return False
        idx = math.floor(pos)
        return self.lastIdx is None or (idx != self.lastIdx and not self._slipped(pos, idx))

    def step(self, pos, onBeat=0.05):
        """pos is the beat position, or None. Returns (isBeat, beatIndex).
        onBeat: how far past a whole beat (in beats) a first reading still counts as that beat."""
        if pos is None:
            self.lastIdx = None
            return False, None
        idx = math.floor(pos)
        if self.lastIdx is None or (idx < self.lastIdx and not self._slipped(pos, idx)):
            # First reading, or the position was reset (Start, a new tempo): only a beat if right on it.
            self.lastIdx = idx
            return (pos - idx) < onBeat and idx >= 0, idx
        if idx > self.lastIdx:
            self.lastIdx = idx
            return idx >= 0, idx
        return False, self.lastIdx
