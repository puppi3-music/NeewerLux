"""Tests for running effects offset across the lights: the animation timeline and the sound engine's
offset and colour spread. Run from the repo root:

    uv run --no-sync python -m unittest tests.test_offsets
"""

import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import puppi3s_neewerlux_audio as na  # noqa: E402

try:
    import Puppi3sNeewerLux as app
except Exception:  # bleak or PySide missing
    app = None


def hsi(hue, bri=100):
    return {"mode": "HSI", "hue": hue, "sat": 100, "bri": bri}


# Red held 100 ms, then a 200 ms fade to green held 100 ms
KEYFRAMES = [
    {"hold_ms": 100, "fade_ms": 0, "lights": {"*": hsi(0)}},
    {"hold_ms": 100, "fade_ms": 200, "lights": {"*": hsi(120)}},
]


@unittest.skipIf(app is None, "Puppi3sNeewerLux.py could not be imported")
class TimelineTests(unittest.TestCase):
    def test_first_pass_and_loop_lengths(self):
        tl = app.AnimationTimeline(KEYFRAMES, loop=True)
        self.assertEqual(tl.firstLen, 400)  # frame 0 has nothing to fade from on the first pass
        self.assertEqual(tl.loopLen, 600)   # later passes fade back to red with the last frame's fade
        self.assertIsNone(tl.length)
        self.assertEqual(app.AnimationTimeline(KEYFRAMES, loop=True, maxLoops=3).length, 400 + 2 * 600)
        self.assertEqual(app.AnimationTimeline(KEYFRAMES, loop=False).length, 400)

    def test_speed_scales_times(self):
        tl = app.AnimationTimeline(KEYFRAMES, speed=2.0, loop=True)
        self.assertEqual((tl.firstLen, tl.loopLen), (50 + 150, 50 + 150 + 100))

    def test_positions(self):
        tl = app.AnimationTimeline(KEYFRAMES, loop=True)
        self.assertEqual(tl.position(50)[:3], (0, 0, 50))
        kind, k, u, until = tl.position(200)  # halfway through the fade to green
        self.assertEqual((kind, k, u, until), (0, 1, 100, 100))
        self.assertTrue(tl.fading(kind, k, u))
        kind, k, u, _ = tl.position(450)  # second pass: fading back to red
        self.assertEqual((kind, k, u), (1, 0, 50))
        self.assertTrue(tl.fading(kind, k, u))

    def test_fades_between_keyframes(self):
        tl = app.AnimationTimeline(KEYFRAMES, loop=True)
        params = [hsi(0), hsi(120)]
        self.assertEqual(tl.lightState(params, *tl.position(50)[:3]), hsi(0))
        self.assertEqual(tl.lightState(params, *tl.position(200)[:3])["hue"], 60)
        self.assertEqual(tl.lightState(params, *tl.position(350)[:3]), hsi(120))
        self.assertEqual(tl.lightState(params, *tl.position(500)[:3])["hue"], 60)  # on the way back

    def test_keyframe_without_the_light_keeps_its_last_setting(self):
        tl = app.AnimationTimeline(KEYFRAMES + [{"hold_ms": 100, "fade_ms": 0, "lights": {}}], loop=True)
        params = [hsi(0), hsi(120), None]
        self.assertEqual(tl.lightState(params, *tl.position(450)[:3]), hsi(120))

    def test_mismatched_modes_change_when_the_fade_ends(self):
        tl = app.AnimationTimeline(KEYFRAMES, loop=False)
        params = [hsi(0), {"mode": "CCT", "temp": 56, "bri": 100}]
        self.assertEqual(tl.lightState(params, *tl.position(200)[:3]), hsi(0))
        self.assertEqual(tl.lightState(params, *tl.position(350)[:3])["mode"], "CCT")

    def test_finite_animation_waits_before_and_holds_after(self):
        tl = app.AnimationTimeline(KEYFRAMES, loop=False)
        kind, k, u, until = tl.position(-150, fresh=False)
        self.assertEqual((kind, k, until), (0, 0, 150))  # waits on frame 0 until its turn
        kind, k, u, until = tl.position(1000)
        self.assertEqual(k, 1)
        self.assertEqual(until, float("inf"))

    def test_offset_light_in_an_endless_loop_starts_mid_loop(self):
        tl = app.AnimationTimeline(KEYFRAMES, loop=True)
        # Half a loop behind, a light is already in the steady loop at the start, not waiting
        kind, k, u, _ = tl.position(0 - 300, fresh=False)
        self.assertEqual(kind, 1)
        self.assertEqual(tl.passesDone(0), 0)
        self.assertEqual(tl.passesDone(999), 1)
        self.assertEqual(tl.passesDone(1000), 2)

    def test_offsets_spread_evenly(self):
        delays, shifts = app.animationOffsets([0, 1, 2, 3], 1000, 1.0, 0.5)
        self.assertEqual(delays, {0: 0, 1: 250, 2: 500, 3: 750})
        self.assertEqual(shifts, {0: 0, 1: 45, 2: 90, 3: 135})
        delays, shifts = app.animationOffsets([0, 1], 1000, 0.0, 0.0)
        self.assertEqual(set(delays.values()) | set(shifts.values()), {0})

    def test_light_command_scales_and_shifts(self):
        self.assertEqual(app.animationLightCommand(hsi(300, 80), 0.5, 90), hsi(30, 40))
        cct = {"mode": "CCT", "temp": 56, "bri": 100}
        self.assertEqual(app.animationLightCommand(cct, 1.0, 90), cct)  # white isn't turned


@unittest.skipIf(app is None, "Puppi3sNeewerLux.py could not be imported")
class EngineTests(unittest.TestCase):
    """The playback thread, with three fake lights and the worker replaced by a recorder."""

    def play(self, keyframes, seconds, **kwargs):
        sent = []  # (seconds since start, light index, command)
        start = time.perf_counter()

        def record(frame, loop):
            t = time.perf_counter() - start
            sent.extend((t, c["idx"], c) for c in frame)
            return True

        with mock.patch.object(app, "availableLights", [["L0"], ["L1"], ["L2"]]), \
             mock.patch.object(app, "animationSendFrame", record), \
             mock.patch.object(app, "runOnGui", lambda f: None), \
             mock.patch.object(app, "showAnimationStopped", lambda: None), \
             mock.patch.object(app, "animRevertOnFinish", False):
            thread = threading.Thread(target=app.animationEngineThread,
                                      args=({"name": "test", "keyframes": keyframes}, None), kwargs=kwargs)
            thread.start()
            thread.join(seconds)
            app.animationStopFlag = True
            thread.join(2)
        self.assertFalse(thread.is_alive())
        return sent

    def firstTime(self, sent, idx, hue):
        return next(t for t, i, c in sent if i == idx and c.get("hue") == hue)

    def test_in_step_without_offset(self):
        sent = self.play(KEYFRAMES, 2, loopOverride=False, fps=30)
        for idx in range(3):
            self.assertEqual(sent[-1 - idx][2]["hue"], 120)
        greens = [self.firstTime(sent, i, 120) for i in range(3)]
        self.assertLess(max(greens) - min(greens), 0.02)

    def test_offset_staggers_the_lights(self):
        sent = self.play(KEYFRAMES, 3, loopOverride=False, fps=30, offset=1.0)
        greens = [self.firstTime(sent, i, 120) for i in range(3)]  # 400 ms long: a third of it apart
        self.assertAlmostEqual(greens[1] - greens[0], 0.133, delta=0.06)
        self.assertAlmostEqual(greens[2] - greens[1], 0.133, delta=0.06)
        self.assertEqual({c["hue"] for t, i, c in sent if t < 0.05}, {0})  # the later lights wait on red

    def test_colour_spread_turns_each_light(self):
        sent = self.play(KEYFRAMES[:1], 1, loopOverride=False, colourSpread=1.0)
        self.assertEqual({i: c["hue"] for t, i, c in sent}, {0: 0, 1: 120, 2: 240})

    def test_strobe_keeps_its_timing(self):
        strobe = [{"hold_ms": 50, "fade_ms": 0, "lights": {"*": hsi(0, 100)}},
                  {"hold_ms": 50, "fade_ms": 0, "lights": {"*": hsi(0, 0)}}]
        sent = self.play(strobe, 0.5, loopOverride=True, fps=5)
        flashes = [t for t, i, c in sent if i == 0 and c["bri"] == 100]
        self.assertGreaterEqual(len(flashes), 4)  # every 100 ms, not every 200 ms frame


class Engine:
    colourSpread = 0.0


def makeShow(spread=0.0):
    show = object.__new__(na._LightShow)
    show.engine = Engine()
    show.engine.colourSpread = spread
    show.beatPeriod = 0.5
    show.hue = 0.0
    show.palIdx = 0
    show.notePitch = None
    show.jumps = {}
    show.delayed = {}
    return show


class SoundSpreadTests(unittest.TestCase):
    def test_shifts_spread_over_the_lights(self):
        self.assertEqual(makeShow(1.0)._spreadShifts([4, 7]), {4: 0.0, 7: 0.5})
        self.assertEqual(set(makeShow(0.0)._spreadShifts([4, 7]).values()), {0.0})

    def test_palette_shift_moves_along_the_palette(self):
        pal = [(0.0, 100.0), (120.0, 100.0), (240.0, 100.0), (60.0, 50.0)]
        self.assertEqual(na.paletteShifted(pal, 0.0, False, 0.0), pal[0])
        self.assertEqual(tuple(na.paletteShifted(pal, 0.0, False, 0.25)), pal[1])
        self.assertEqual(tuple(na.paletteShifted(pal, 1.0, False, 0.25)), pal[0])  # wraps past the last colour

    def test_beat_jump_gives_each_shift_its_own_colour(self):
        show = makeShow()
        cols = show._jumpColour(0.0, None, False, None, 1, 0.0, (0.0, 0.5))
        self.assertEqual(cols, {0.0: (0.0, 100.0), 0.5: (180.0, 100.0)})
        pal = [(0.0, 100.0), (120.0, 100.0), (240.0, 100.0), (60.0, 50.0)]
        cols = makeShow()._jumpColour(0.0, None, False, pal, 1, 0.0, (0.0, 0.25))
        self.assertEqual(cols[0.0], pal[0])
        self.assertEqual(tuple(cols[0.25]), pal[1])

    def test_beat_jump_glides_each_shift(self):
        show = makeShow()
        show._jumpColour(0.0, None, False, None, 1, 0.5, (0.0, 0.5))
        cols = show._jumpColour(1.0, None, True, None, 1, 0.5, (0.0, 0.5))  # a new colour: each starts its glide
        self.assertEqual(cols, {0.0: (0.0, 100.0), 0.5: (180.0, 100.0)})
        cols = show._jumpColour(1.25, None, False, None, 1, 0.5, (0.0, 0.5))  # glide done
        self.assertAlmostEqual(cols[0.0][0], 137.5)
        self.assertAlmostEqual(cols[0.5][0], 317.5)

    def test_spread_colours_in_the_other_modes(self):
        show = makeShow()
        show.engine.baseHue = 240
        sm = {"level": 1.0}
        self.assertEqual(show._lightColour("Spectrum colour", 1, [0, 1], None, sm, 0, 0.5, 0, 1, None, 0.0, 0.5)[0], 320.0)
        self.assertEqual(show._lightColour("Bass pulse", 1, [0, 1], None, sm, 0, 0.5, 0, 1, None, 0.0, 0.5)[0], 60.0)


class SoundOffsetTests(unittest.TestCase):
    def test_delay_holds_commands_back(self):
        show = makeShow()
        shown = [show._delayed(1, t / 10.0, ("c", t), 0.25) for t in range(8)]
        self.assertEqual(shown[:3], [None, None, None])  # nothing a quarter second old yet
        self.assertEqual(shown[3], ("c", 0))
        self.assertEqual(shown[7], ("c", 4))

    def test_no_delay_passes_straight_through(self):
        show = makeShow()
        show._delayed(1, 0.0, "old", 0.5)
        self.assertEqual(show._delayed(1, 0.1, "new", 0.0), "new")
        self.assertNotIn(1, show.delayed)


if __name__ == "__main__":
    unittest.main()
