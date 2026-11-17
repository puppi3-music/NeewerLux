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
    show.chaseStep = 0
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
        self.assertEqual(show._chaseLit(groups), set())  # no deep flash yet
        seen = []
        for step in range(1, 5):
            show.chaseStep = step
            seen.append(show._chaseLit(groups))
        self.assertEqual(seen, [{1, 5}, {2, 6}, {4, 5}, {1, 6}])

    def test_lone_lights_are_in_no_group(self):
        self.assertEqual(makeShow()._chaseGroups([0, 1, 2]), {})  # no groups given: every light strobes
        self.assertEqual(makeShow(None, {1: "A"})._chaseGroups([0, 1]), {})  # a group of one has nothing to chase round
        self.assertEqual(makeShow({2: 0.3}, {1: "A", 2: "A"})._chaseGroups([1, 2]), {})  # nor one with a single quick light

    def test_only_the_lit_light_takes_the_deep_flash(self):
        show = makeShow()
        show.rollAccent = show.rollFlash = 1.0
        # blue at full saturation: the ripple is ROLL_SWING_MAX
        self.assertEqual(show._rollBrightness(0.0, 10, 90, 240, 100, 0.5, None, True), (90, 90))
        self.assertEqual(show._rollBrightness(0.0, 10, 90, 240, 100, 0.5, None, False), (10 + na.ROLL_SWING_MAX, 90))

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
