"""Tests for Pattern: laying a Nanoleaf's panels out by where they are on the wall for Offset, Colour spread
and the sound modes that give each light its own part. Run from the repo root:

    uv run --no-sync python -m unittest tests.test_patterns
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import puppi3lux_audio as na  # noqa: E402
import puppi3lux_nanoleaf as nl  # noqa: E402
from fake_nanoleaf import FakeNanoleaf, TOKEN  # noqa: E402

try:
    import Puppi3Lux as app
except Exception:  # bleak or PySide missing
    app = None

# The fake's four hexagons sit in a diamond round (200, 58): 5003 at the top, 5001 right, 5004 bottom, 5002 left.
DIAMOND = {5001: (300.0, 58.0), 5002: (100.0, 58.0), 5003: (200.0, 116.0), 5004: (200.0, 0.0)}


class PatternGeometryTests(unittest.TestCase):
    def test_sweeps(self):
        self.assertEqual(nl.patternPlaces(DIAMOND, "Left to right"), {5002: 0.0, 5003: 0.5, 5004: 0.5, 5001: 1.0})
        self.assertEqual(nl.patternPlaces(DIAMOND, "Right to left"), {5002: 1.0, 5003: 0.5, 5004: 0.5, 5001: 0.0})
        self.assertEqual(nl.patternPlaces(DIAMOND, "Top to bottom"), {5003: 0.0, 5001: 0.5, 5002: 0.5, 5004: 1.0})
        self.assertEqual(nl.patternPlaces(DIAMOND, "Bottom to top"), {5003: 1.0, 5001: 0.5, 5002: 0.5, 5004: 0.0})

    def test_rings(self):
        # top and bottom are 58 from the centre, left and right 100
        self.assertEqual(nl.patternPlaces(DIAMOND, "Centre out"), {5003: 0.0, 5004: 0.0, 5001: 1.0, 5002: 1.0})
        self.assertEqual(nl.patternPlaces(DIAMOND, "Edges in"), {5003: 1.0, 5004: 1.0, 5001: 0.0, 5002: 0.0})

    def test_around_goes_clockwise_from_the_top(self):
        self.assertEqual(nl.patternPlaces(DIAMOND, "Around"), {5003: 0.0, 5001: 0.25, 5004: 0.5, 5002: 0.75})
        self.assertTrue(nl.patternWraps("Around"))
        self.assertFalse(nl.patternWraps("Left to right"))

    def test_points_in_one_place_and_unknown_patterns(self):
        self.assertEqual(nl.patternPlaces({1: (5, 5), 2: (5, 5)}, "Left to right"), {1: 0.0, 2: 0.0})
        self.assertEqual(nl.patternPlaces({1: (5, 5), 2: (5, 5)}, "Around"), {1: 0.0, 2: 0.0})
        self.assertEqual(nl.patternPlaces(DIAMOND, "Light order"), {k: 0.0 for k in DIAMOND})
        self.assertEqual(nl.patternPlaces({}, "Around"), {})

    def test_panel_points_follow_canvas_rotation(self):
        layout = {"positionData": [{"panelId": 0, "x": 0, "y": 0, "shapeType": 12},
                                   {"panelId": 1, "x": 100, "y": 0, "shapeType": 7},
                                   {"panelId": 2, "x": 0, "y": 100, "shapeType": 7}]}
        self.assertEqual(nl.panelPoints(layout), {1: (100.0, 0.0), 2: (0.0, 100.0)})
        # turned 90 degrees clockwise: what was to the right is now below, what was above is to the right
        self.assertEqual(nl.panelPoints(layout, 90), {1: (0.0, -100.0), 2: (100.0, 0.0)})

    def test_saved_positions_are_read_back(self):
        self.assertEqual(nl._loadPositions({"1": [1, 2], "x": [3, 4], "2": "bad", "3": [5]}), {1: (1.0, 2.0)})
        self.assertEqual(nl._loadPositions(None), {})


class SavedPositionTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeNanoleaf(port=0, streamPort=0).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.savedPath = os.path.join(self.tmp.name, "nanoleaf.json")

    def tearDown(self):
        self.fake.stop()
        self.tmp.cleanup()

    def test_layout_positions_are_kept_and_saved(self):
        entry = {"id": "S12345", "name": "Fake", "ip": "127.0.0.1", "port": self.fake.port, "token": TOKEN, "perPanel": True}
        nl.saveSaved([entry], self.savedPath)
        c = nl.NanoleafController(entry, savedPath=self.savedPath)
        asyncio.run(c.loadLayout())
        self.assertEqual(c.positions, DIAMOND)
        self.assertEqual({d.panelId: d.position for d in c.devices()}, DIAMOND)
        self.assertIsNone(nl.NanoleafDevice(c).position)  # the whole device has no one place
        # a controller made from the saved file knows them before it connects
        again = nl.NanoleafController(nl.loadSaved(self.savedPath)[0], savedPath=False)
        self.assertEqual(again.positions, DIAMOND)


def panelLights(positions=DIAMOND, deviceId="S1"):
    """availableLights-style entries for a Nanoleaf shown per panel, in its own (left-to-right) order."""
    entry = {"id": deviceId, "name": "Wall", "ip": "127.0.0.1", "token": "t", "perPanel": True,
             "panels": [5002, 5003, 5004, 5001], "positions": {str(k): list(v) for k, v in positions.items()}}
    c = nl.NanoleafController(entry, savedPath=False)
    return [[d] for d in c.devices()]


@unittest.skipIf(app is None, "Puppi3Lux.py could not be imported")
class LightPlacesTests(unittest.TestCase):
    def test_light_order_is_unchanged(self):
        with mock.patch.object(app, "availableLights", panelLights()):
            self.assertEqual(app.lightPlaces([0, 1, 2, 3]), {0: 0.0, 1: 0.25, 2: 0.5, 3: 0.75})

    def test_panels_spread_over_their_stretch(self):
        # a Neewer light, the four panels (5002, 5003, 5004, 5001), another Neewer light
        lights = [["neewer"]] + panelLights() + [["neewer"]]
        with mock.patch.object(app, "availableLights", lights):
            places = app.lightPlaces(list(range(6)), "Top to bottom")
            # the Neewer lights keep their place; the panels share places 1 to 4 by height
            self.assertEqual(places[0], 0.0)
            self.assertEqual(places[5], 5 / 6)
            self.assertEqual((places[2], places[1], places[4], places[3]), (1 / 6, 2.5 / 6, 2.5 / 6, 4 / 6))
            # Around takes the whole stretch and one more, so 100% offset comes back round evenly
            around = app.lightPlaces(list(range(6)), "Around")
            self.assertEqual((around[2], around[4], around[3], around[1]), (1 / 6, 2 / 6, 3 / 6, 4 / 6))

    def test_animation_offsets_follow_the_pattern(self):
        with mock.patch.object(app, "availableLights", panelLights()):
            delays, shifts = app.animationOffsets([0, 1, 2, 3], 1000, 1.0, 1.0, "Centre out")
            # top and bottom (lights 1 and 2) in step at the start, left and right (0 and 3) together after them
            self.assertEqual(delays[1], delays[2])
            self.assertEqual(delays[0], delays[3])
            self.assertEqual(delays[1], 0.0)
            self.assertEqual(delays[0], 750.0)
            self.assertEqual(shifts[0], 270)

    def test_pattern_names(self):
        self.assertEqual(app.resolvePattern("left-to-right"), "Left to right")
        self.assertEqual(app.resolvePattern("CENTER_OUT"), "Centre out")
        self.assertEqual(app.resolvePattern("around"), "Around")
        self.assertEqual(app.resolvePattern("sideways"), "Light order")
        self.assertEqual(app.resolvePattern(None), "Light order")

    def test_animation_suggestions(self):
        anims = {"Waves": {"suggest": {"offset": 40, "pattern": "centre-out"}}, "Plain": {}, "Odd": {"suggest": {"offset": "x", "spread": 250}}}
        with mock.patch.object(app, "savedAnimations", anims):
            self.assertEqual(app.animationSuggestion("waves"), (40, 0, "Centre out"))  # any case, as HTTP names come
            self.assertIsNone(app.animationSuggestion("Plain"))
            self.assertIsNone(app.animationSuggestion("Missing"))
            self.assertEqual(app.animationSuggestion("Odd"), (0, 100, "Light order"))  # bad values are clamped

    def test_shipped_suggestions_are_valid(self):
        import json
        folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "light_prefs", "animations")
        found = 0
        for f in os.listdir(folder):
            with open(os.path.join(folder, f), encoding="utf-8") as fh:
                anim = json.load(fh)
            sug = anim.get("suggest")
            if sug is None:
                continue
            found += 1
            self.assertIn(sug.get("pattern", "Light order"), nl.PATTERNS, f)
            self.assertTrue(0 <= sug.get("offset", 0) <= 100 and 0 <= sug.get("spread", 0) <= 100, f)
            # only for animations that set every light: numbered ones already stagger themselves
            self.assertEqual({k for kf in anim["keyframes"] for k in kf["lights"]}, {"*"}, f)
        self.assertGreater(found, 10)

    def test_ui_lists_the_same_patterns(self):
        import puppi3lux_ui as ui
        self.assertEqual(tuple(ui.LIGHT_PATTERNS), nl.PATTERNS)
        self.assertEqual(app.LIGHT_ORDER, nl.LIGHT_ORDER)
        self.assertEqual(na.LIGHT_ORDER, nl.LIGHT_ORDER)


class Engine:
    colourSpread = 1.0
    lightInterval = None
    pattern = "Bottom to top"

    def __init__(self, places):
        self.lightGroup = lambda idx: "A"
        self.lightPlaces = lambda targets, pattern: places


class SoundPatternTests(unittest.TestCase):
    def makeShow(self, places):
        show = object.__new__(na._LightShow)
        show.engine = Engine(places)
        show.hue = 0.0
        return show

    def test_places_come_from_the_app(self):
        show = self.makeShow({0: 0.5, 1: 0.0})
        self.assertEqual(show._places([0, 1]), {0: 0.5, 1: 0.0})
        self.assertEqual(show._spreadShifts([0, 1]), {0: 0.5, 1: 0.0})
        # a fn that leaves a light out falls back to light order
        self.assertEqual(self.makeShow({0: 0.5})._places([0, 1]), {0: 0.0, 1: 0.5})

    def test_chase_follows_the_pattern(self):
        show = self.makeShow({0: 0.9, 1: 0.1, 2: 0.5})
        self.assertEqual(show._chaseGroups([0, 1, 2], show._places([0, 1, 2])), {"A": [1, 2, 0]})
        self.assertEqual(show._chaseGroups([0, 1, 2]), {"A": [0, 1, 2]})  # no places: light order

    def test_frequency_bands_take_a_third_each(self):
        show = self.makeShow({})
        sm = {"bass": 0.9, "mid": 0.5, "high": 0.1, "level": 0.5}
        bands = [show._lightColour("Frequency bands", pos, [0, 1, 2, 3], None, sm, 0, 0, 0, 1, None, 0.0, 0.0, place)[2]
                 for pos, place in enumerate((0.0, 0.2, 0.5, 0.9))]
        self.assertEqual(bands, [0.9, 0.9, 0.5, 0.1])  # bottom two bass, then mid, highs at the top
        show.engine.pattern = "Light order"
        bands = [show._lightColour("Frequency bands", pos, [0, 1, 2, 3], None, sm, 0, 0, 0, 1, None, 0.0, 0.0, 0.0)[2]
                 for pos in range(4)]
        self.assertEqual(bands, [0.9, 0.5, 0.1, 0.9])  # light order still takes turns

    def test_rainbow_drift_uses_the_place(self):
        show = self.makeShow({})
        sm = {"level": 0.5}
        self.assertEqual(show._lightColour("Rainbow drift", 0, [0, 1], None, sm, 0, 0, 0, 1, None, 0.0, 0.0, 0.5)[0], 180.0)


if __name__ == "__main__":
    unittest.main()
