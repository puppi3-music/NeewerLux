"""Tests for how the sound engine flashes lights that take a while to show each change. Run from the repo root:

    uv run --no-sync python -m unittest tests.test_slow_lights
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import puppi3s_neewerlux_audio as na  # noqa: E402


class Engine:
    lightInterval = None


def makeShow():
    """A light show with only what the per-light flashes use (no audio needed)."""
    show = object.__new__(na._LightShow)
    show.engine = Engine()
    show.flashCount = 0
    show.slow = {}
    show.beatFlash = 0.0
    return show


def flashesPerBeat(gap, bpm, beats=32, fps=15):
    """Run beats through one slow light; returns the beats it flashed on (counted from 0)."""
    show = makeShow()
    period = 60.0 / bpm
    dt = 1.0 / fps
    flashed = []
    t = 0.0
    for b in range(beats):
        show.flashCount += 1
        show.beatFlash = 1.0
        flash, _ = show._slowFlash(1, gap, t, dt, True, True, period, 0.0)
        if flash == 1.0:
            flashed.append(b)
        frames = max(1, int(period / dt))
        for _ in range(frames - 1):
            t += dt
            show.beatFlash = max(0.0, show.beatFlash - dt * 4.0)
            show._slowFlash(1, gap, t, dt, False, False, period, 0.0)
        t += dt
    return flashed


class SlowLightTests(unittest.TestCase):
    def test_every_beat_when_a_flash_fits(self):
        self.assertEqual(flashesPerBeat(0.1, 126), list(range(32)))  # Nanoleaf streaming: 0.3 s a flash, 0.48 s a beat

    def test_halves_until_a_flash_fits(self):
        self.assertEqual(flashesPerBeat(0.25, 126), list(range(0, 32, 2)))  # HTTP: 0.75 s a flash
        self.assertEqual(flashesPerBeat(0.5, 126), list(range(0, 32, 4)))  # 1.5 s a flash
        self.assertEqual(flashesPerBeat(0.25, 174), list(range(0, 32, 4)))  # 0.34 s a beat
        self.assertEqual(flashesPerBeat(5.0, 126), list(range(0, 32, na.SLOW_MAX_EVERY)))

    def test_holds_near_the_edge(self):
        # 0.16 s updates need 0.48 s a flash; at 125 BPM a beat is 0.48 s: it flashes every beat, and doesn't flip back
        # to every other beat while the tempo wobbles just around there
        show = makeShow()
        dt = 1.0 / 15
        steps = []
        for b, bpm in enumerate([124, 126, 124, 126, 124, 126, 124, 126]):
            show.flashCount += 1
            show.beatFlash = 1.0
            show._slowFlash(1, 0.16, b * 0.48, dt, True, True, 60.0 / bpm, 0.0)
            steps.append(show.slow[1][2])
        self.assertEqual(steps[0], 1)
        self.assertLessEqual(len(set(steps[2:])), 1)

    def test_flash_lasts_long_enough_to_be_sent(self):
        show = makeShow()
        show.flashCount = 1
        show.beatFlash = 1.0
        show._slowFlash(1, 0.25, 0.0, 1 / 15.0, True, True, 1.0, 0.0)
        flash = 1.0
        for i in range(4):  # the next 0.27 s: still most of the way up when the next update can carry it
            flash, _ = show._slowFlash(1, 0.25, (i + 1) / 15.0, 1 / 15.0, False, False, 1.0, 0.0)
        self.assertGreater(flash, 0.4)

    def test_quick_lights_unchanged(self):
        show = makeShow()
        self.assertEqual(show._lightGap(0), 0.0)
        show.engine.lightInterval = lambda idx: 0.25 if idx == 1 else 0.0
        self.assertEqual((show._lightGap(0), show._lightGap(1)), (0.0, 0.25))
        show.engine.lightInterval = lambda idx: 1 / 0  # a broken report is taken as quick, not as a crash
        self.assertEqual(show._lightGap(0), 0.0)

class Beats:
    def __init__(self, period):
        self.period = period

    def beatPeriod(self):
        return self.period


def rollFlashes(gap, rollHit, perBeat, perAccent=1, hits=64, fps=60):
    """Run roll hits through one slow light; returns the hit indexes it strobed on."""
    show = makeShow()
    show.slowRoll = {}
    show.rollHit = rollHit
    src = Beats(rollHit * perBeat)
    dt = 1.0 / fps
    flashed = []
    for i in range(hits):
        if show._slowRollAccent(1, gap, dt, True, i, perAccent, src) == 1.0:
            flashed.append(i)
        for _ in range(max(0, int(rollHit / dt) - 1)):
            show._slowRollAccent(1, gap, dt, False, i, perAccent, src)
    return flashed


class SlowRollTests(unittest.TestCase):
    def test_strobes_on_every_nth_hit_on_the_beat(self):
        # Nanoleaf streaming (0.3 s a flash), 16ths at 128 BPM (0.117 s a hit): every 4th hit, on each beat
        self.assertEqual(rollFlashes(0.1, 60 / 128 / 4, 4), list(range(0, 64, 4)))
        # 32nds: still on each beat, every 8th hit
        self.assertEqual(rollFlashes(0.1, 60 / 128 / 8, 8), list(range(0, 64, 8)))
        # a slower roll (0.16 s a hit, 0.32 s for two) fits in every 2nd hit, still on the grid
        self.assertEqual(rollFlashes(0.1, 0.16, 4), list(range(0, 64, 2)))

    def test_lands_on_the_quick_lights_deep_flashes(self):
        # quick lights flash deep on every 2nd hit: the slow light keeps to those, every 4th
        self.assertEqual(rollFlashes(0.1, 0.1, 4, perAccent=2), list(range(0, 64, 4)))

    def test_goes_past_a_beat_when_needed(self):
        # HTTP (0.75 s a flash) at 0.47 s a beat: every 2nd beat
        self.assertEqual(rollFlashes(0.25, 60 / 128 / 4, 4), list(range(0, 64, 8)))

    def test_strobe_brightness_uses_the_accent(self):
        show = makeShow()
        show.engine.rollStyle = "Strobe"
        show.rollBegan = 0.0
        self.assertEqual(show._rollBrightness(0.0, 10, 90, 0, 100, 0.5, 1.0), (90, 90))
        self.assertEqual(show._rollBrightness(0.0, 10, 90, 0, 100, 0.5, 0.0), (10, 90))



if __name__ == "__main__":
    unittest.main()
