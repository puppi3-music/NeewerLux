"""Tests for the Chase drum-roll style, where each deep flash goes to the next light in turn. Run from the repo root:

    uv run --no-sync python -m unittest tests.test_roll_chase
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import puppi3lux_audio as na  # noqa: E402


class Engine:
    lightInterval = None
    lightGroup = None
    rollStyle = "Chase"
    flashLevel = "Show"
    targets = []


class Beat:
    def __init__(self, period):
        self.period = period

    def beatPeriod(self):
        return self.period


def makeShow(gaps=None, groups=None):
    """A light show with only what a roll's brightness uses (no audio needed). gaps: {light: seconds per update},
    groups: {light: the group it chases round in}."""
    show = object.__new__(na._LightShow)
    show.engine = Engine()
    if gaps:
        show.engine.lightInterval = lambda idx: gaps.get(idx, 0.0)
    if groups:
        show.engine.lightGroup = groups.get
    show.chaseFrom = None
    show.chaseLimiters = {}
    show.limiters = {}
    show.rollBegan = 0.0
    show.rollAccent = show.rollFlash = 0.0
    return show


class ChaseTests(unittest.TestCase):
    def test_goes_round_each_group_in_order(self):
        # 0 is a lone light (a 660 Pro), 1-4 one Nanoleaf's panels (3 slow), 5-6 another's
        show = makeShow({3: 0.3}, {1: "A", 2: "A", 3: "A", 4: "A", 5: "B", 6: "B"})
        groups = show._chaseGroups(range(7))
        self.assertEqual(groups, {"A": [1, 2, 4], "B": [5, 6]})
        show.engine.flashLevel = "Standard"
        show.rollHit = 0.125  # 16ths at 120 BPM: A sweeps a light a hit, B (two lights) a light every 2 hits
        full = []
        for hit in range(6):
            show.rollPos = 10.0 + hit
            weights = show._chaseWeights(groups, 0.5)
            full.append({idx for idx, w in weights.items() if w == 1.0})
        self.assertEqual(full, [{1, 5}, {2, 5, 6}, {4, 6}, {1, 5, 6}, {2, 5}, {4, 5, 6}])  # B half way between is on both
        show.rollPos = 15.5  # half way from 4 to 1: both full, so the group's brightest never dips
        self.assertEqual({idx: w for idx, w in show._chaseWeights(groups, 0.5).items() if idx in (1, 2, 4)}, {1: 1.0, 2: 0.0, 4: 1.0})

    def test_above_standard_it_pops_light_to_light(self):
        show = makeShow(None, {1: "A", 2: "A", 3: "A"})
        groups = show._chaseGroups([1, 2, 3])
        show.rollHit = 0.0625  # 32nds at 120 BPM
        lit = []
        for level in ("Show", "Off"):
            show.engine.flashLevel = level
            show.chaseFrom = None
            seen = []
            for hit in range(4):
                show.rollPos = 20.0 + hit
                weights = show._chaseWeights(groups, 0.5)
                seen.append([idx for idx, w in weights.items() if w == 1.0])
                self.assertEqual(sorted(weights.values())[:2], [0.0, 0.0])  # the rest are dark between pops
            lit.append(seen)
        self.assertEqual(lit[0], [[1], [], [2], []])  # Show: no faster than 0.105 s a pop, so every 2nd hit
        self.assertEqual(lit[1], [[1], [2], [3], [1]])  # Off: every hit
        show.engine.flashLevel = "Show"
        show.chaseLimiters["A"] = na._FlashLimiter()
        show.chaseLimiters["A"].resting = True  # burst used up: back to the sweep, where the group doesn't flash
        show.rollPos = 20.5
        weights = sorted(show._chaseWeights(groups, 0.5).values())
        self.assertEqual(weights[-1], 1.0)
        self.assertGreater(weights[-2], 0.5)  # the next light is already well up

    def test_sweep_keeps_within_the_standard_limit(self):
        """Each light rises and falls once per time round, slow enough for the Standard limit, and the group's brightest
        holds steady, so neither the lights nor the group as one area are held back."""
        maxSwings = na.FLASH_LEVELS["Standard"][0]
        for count in range(2, 7):
            members = list(range(count))
            show = makeShow(None, {i: "A" for i in members})
            show.engine.flashLevel = "Standard"
            show.rollHit, hitsPerSecond, dt = 0.1, 10.0, 1.0 / 60
            groups = show._chaseGroups(members)
            lights = [na._FlashLimiter() for _ in members]
            group = na._FlashLimiter()
            t, tops = 0.0, []
            while t < 6.0:
                show.rollPos = t * hitsPerSecond
                weights = show._chaseWeights(groups, 0.4)
                bris = [show._rollBrightness(t, 10, 90, 240, 100, 0.5, None, weights[i])[0] for i in members]
                sent = [lim.step(b, t, maxSwings) for lim, b in zip(lights, bris)]
                self.assertEqual(sent, [round(b) for b in bris], "%d lights at %.2f s" % (count, t))
                tops.append(max(sent))
                group.step(max(sent), t, maxSwings)
                t += dt
            self.assertEqual(len(set(tops[1:])), 1)  # the group's brightest never moves
            self.assertFalse(group.swings)

    def test_lone_lights_are_in_no_group(self):
        self.assertEqual(makeShow()._chaseGroups([0, 1, 2]), {})  # no groups given: every light strobes
        self.assertEqual(makeShow(None, {1: "A"})._chaseGroups([0, 1]), {})  # a group of one has nothing to chase round
        self.assertEqual(makeShow({2: 0.3}, {1: "A", 2: "A"})._chaseGroups([1, 2]), {})  # nor one with a single quick light

    def test_the_sweep_takes_the_deep_flash(self):
        show = makeShow()
        show.rollAccent = 0.0  # the Strobe's accent plays no part in a grouped light
        show.rollFlash = 1.0
        # blue at full saturation: the ripple is ROLL_SWING_MAX
        self.assertEqual(show._rollBrightness(0.0, 10, 90, 240, 100, 0.5, None, 1.0), (90, 90))
        floor = 10 + (90 - na.ROLL_SWING_MAX - 10) * na.ROLL_RIPPLE_FLOOR
        self.assertEqual(show._rollBrightness(0.0, 10, 90, 240, 100, 0.5, None, 0.0), (floor + na.ROLL_SWING_MAX, 90))
        show.rollFlash = 0.0  # between hits the rest sit on the floor, still under the sweep
        self.assertEqual(show._rollBrightness(0.0, 10, 90, 240, 100, 0.5, None, 0.0), (floor, 90))
        show.rollAccent = 1.0  # a light in no group strobes
        self.assertEqual(show._rollBrightness(0.0, 10, 90, 240, 100, 0.5, None, None), (90 - na.ROLL_SWING_MAX, 90))

    def test_a_slow_light_keeps_its_own_accent(self):
        show = makeShow()
        self.assertEqual(show._rollBrightness(0.0, 10, 90, 240, 100, 0.5, 1.0, False), (90, 90))

    def test_lights_counted_as_one_area(self):
        """A chase on every hit over three lights is under the Standard rate on each light, but over it for the
        lights together, so the burst runs out for the group and the roll falls back to Standard spacing."""
        show = makeShow()
        maxSwings = na.FLASH_LEVELS["Show"][0]
        hit, dt = 0.125, 1.0 / 30
        lights = [na._FlashLimiter() for _ in range(3)]
        accent, step, t, nextHit = 0.0, -1, 0.0, 0.0
        while t < 6.0:
            if t >= nextHit:
                step, accent, nextHit = step + 1, 1.0, nextHit + hit
            bris = [10 + 80 * (accent if i == step % 3 else 0.0) for i in range(3)]
            sent = [lim.step(b, t, maxSwings) for lim, b in zip(lights, bris)]
            show.chaseLimiters.setdefault("A", na._FlashLimiter()).step(max(sent), t, maxSwings)
            accent = max(0.0, accent - dt / (na.ROLL_ACCENT_SHARE * hit))
            t += dt
        self.assertFalse(any(lim.resting for lim in lights))
        self.assertTrue(show.chaseLimiters["A"].resting)

        show.engine.targets = [0, 1, 2]
        show.rollHit = hit
        src = Beat(0.5)
        self.assertEqual(show._hitsPerAccent(src, 10.0), 4)  # resting: Standard spacing, one deep flash a beat
        show.engine.rollStyle = "Strobe"  # the group count only holds a Chase back
        self.assertEqual(show._hitsPerAccent(src, 10.0), 1)
        show.engine.rollStyle = "Chase"
        show.chaseLimiters.clear()
        self.assertEqual(show._hitsPerAccent(src, 10.0), 1)  # built up to every hit


if __name__ == "__main__":
    unittest.main()
