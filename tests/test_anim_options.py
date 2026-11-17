"""Tests for animation Smoothing, the Random pattern, Nanoleaf panels added while in use, and unpairing.
Run from the repo root:

    uv run --no-sync python -m unittest tests.test_anim_options
"""

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import puppi3s_neewerlux_nanoleaf as nl  # noqa: E402
from test_app_nanoleaf import AppTestCase, app  # noqa: E402


@unittest.skipIf(app is None, "Puppi3sNeewerLux.py could not be imported")
class SmoothingTests(unittest.TestCase):
    KEYFRAMES = [{"hold_ms": 800, "fade_ms": 200}, {"hold_ms": 1000, "fade_ms": 0}]

    def test_off_keeps_the_keyframes(self):
        t = app.AnimationTimeline(self.KEYFRAMES, loop=True)
        self.assertEqual(t.holds, [800, 1000])
        self.assertEqual(t.fades[1], [200, 0])
        self.assertEqual(t.loopLen, 2000)

    def test_half_spends_half_of_each_step_fading_and_keeps_the_timing(self):
        t = app.AnimationTimeline(self.KEYFRAMES, loop=True, smoothing=0.5)
        self.assertEqual(t.fades[1], [500, 500])
        self.assertEqual(t.holds, [500, 500])
        self.assertEqual(t.loopLen, 2000)

    def test_never_shortens_a_longer_fade(self):
        t = app.AnimationTimeline([{"hold_ms": 100, "fade_ms": 900}], loop=True, smoothing=0.2)
        self.assertEqual((t.fades[1][0], t.holds[0]), (900, 100))

    def test_the_first_pass_keeps_its_timing(self):
        # frame 0 has nothing to fade from on the first pass, so smoothing must not take its time away
        frames = [{"hold_ms": 1000, "fade_ms": 0}, {"hold_ms": 1000, "fade_ms": 0}]
        for s in (0.0, 0.5, 1.0):
            t = app.AnimationTimeline(frames, loop=False, smoothing=s)
            self.assertEqual(t.firstLen, 2000, s)
            self.assertEqual(t.position(500)[1], 0, s)  # still on the first keyframe half way through it

    def test_full_smoothing_on_one_frame_still_plays(self):
        t = app.AnimationTimeline([{"hold_ms": 1000}], loop=False, smoothing=1.0)
        self.assertEqual(t.length, 1000)

    def test_full_glides_all_the_way(self):
        frames = [{"hold_ms": 1000, "lights": {"1": {"mode": "HSI", "hue": 0, "sat": 100, "bri": 100}}},
                  {"hold_ms": 1000, "lights": {"1": {"mode": "HSI", "hue": 100, "sat": 100, "bri": 100}}}]
        t = app.AnimationTimeline(frames, loop=True, smoothing=1.0)
        params = [kf["lights"]["1"] for kf in frames]
        kind, k, u, _ = t.position(t.firstLen + 1500, fresh=False)  # half way through the second step
        self.assertEqual(k, 1)
        self.assertTrue(t.fading(kind, k, u))
        self.assertEqual(t.lightState(params, kind, k, u)["hue"], 50)


class Row:
    def __init__(self, address):
        self.address = address


@unittest.skipIf(app is None, "Puppi3sNeewerLux.py could not be imported")
class RandomPatternTests(unittest.TestCase):
    def setUp(self):
        lights = [[Row("AA:%02d" % i)] for i in range(8)]
        patcher = mock.patch.object(app, "availableLights", lights)
        patcher.start()
        self.addCleanup(patcher.stop)
        app.resetRandomPattern()

    def test_every_light_gets_its_own_place_and_keeps_it(self):
        order = list(range(8))
        places = app.lightPlaces(order, "Random")
        self.assertEqual(sorted(places.values()), [i / 8 for i in range(8)])
        self.assertEqual(app.lightPlaces(order, "Random"), places)  # stable from frame to frame

    def test_resolves_by_name(self):
        self.assertEqual(app.resolvePattern("random"), "Random")
        self.assertIn("Random", nl.PATTERNS)


@unittest.skipIf(app is None, "Puppi3sNeewerLux.py could not be imported")
class HTTPAcceptedIPTests(unittest.TestCase):
    def check(self, allowed, ip):
        with mock.patch.object(app, "acceptable_HTTP_IPs", allowed):
            return app.httpIPAccepted(ip)

    def test_ranges_match_from_the_start_only(self):
        defaults = ["127.0.0.1", "192.168.", "10."]
        self.assertTrue(self.check(defaults, "192.168.1.20"))
        self.assertTrue(self.check(defaults, "10.0.0.5"))
        self.assertTrue(self.check(defaults, "127.0.0.1"))
        self.assertFalse(self.check(defaults, "8.8.10.1"))  # contains "10." but is not in 10.x
        self.assertFalse(self.check(defaults, "172.16.10.5"))
        self.assertFalse(self.check(defaults, "127.0.0.10"))

    def test_whole_parts_and_blank_lines(self):
        self.assertFalse(self.check(["192.168.1.1"], "192.168.1.10"))
        self.assertFalse(self.check(["192.168.1"], "192.168.10.4"))
        self.assertTrue(self.check(["192.168.1"], "192.168.1.4"))
        self.assertFalse(self.check(["", "  "], "8.8.8.8"))  # an empty line in the field lets nobody in
        self.assertTrue(self.check(["192.168."], "::ffff:192.168.1.2"))


class PanelChangeTests(AppTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(sys, "argv", [os.path.join(self.tmp.name, "Puppi3sNeewerLux.py")])
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (("lightAliases", {}), ("preAnimationStates", {}), ("animationRunning", False)):
            p = mock.patch.object(app, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.save()
        self.run_(app.findDevices())
        self.controller = app.nanoleafControllers["S12345"]
        self.controller.streamPort = self.fake.streamPort
        self.run_(app.connectToLight(0, False))
        app.setNanoleafPerPanel(self.loop, "S12345", True, False)

    def tearDown(self):
        for row in app.availableLights:
            if row[1] != "" and row[1].is_connected:
                self.run_(row[1].disconnect())
        super().tearDown()

    def test_a_new_panel_gets_a_linked_row_and_bumps_the_generation(self):
        gen = app.nanoleafLayoutGeneration
        with self.fake.lock:
            self.fake.layout["positionData"].append({"panelId": 5005, "x": 400, "y": 58, "o": 0, "shapeType": 7})
        app.refreshNanoleafPanels(self.loop, False)
        addresses = [row[0].address for row in app.availableLights]
        self.assertIn("NL:S12345-P5005", addresses)
        self.assertEqual(len(addresses), 5)
        self.assertTrue(all(row[1] != "" and row[1].is_connected for row in app.availableLights))
        self.assertEqual(app.nanoleafLayoutGeneration, gen + 1)

        # and taking one off drops its row
        with self.fake.lock:
            self.fake.layout["positionData"] = [p for p in self.fake.layout["positionData"] if p["panelId"] != 5001]
        app.refreshNanoleafPanels(self.loop, False)
        addresses = [row[0].address for row in app.availableLights]
        self.assertNotIn("NL:S12345-P5001", addresses)
        self.assertEqual(len(addresses), 4)

    def test_nothing_changes_when_the_layout_is_the_same(self):
        gen = app.nanoleafLayoutGeneration
        app.refreshNanoleafPanels(self.loop, False)
        self.assertEqual(app.nanoleafLayoutGeneration, gen)

    def test_a_rescan_also_checks_an_unlinked_nanoleaf(self):
        for row in app.availableLights:
            self.run_(row[1].disconnect())
            row[1] = ""
        with self.fake.lock:
            self.fake.layout["positionData"].append({"panelId": 5005, "x": 400, "y": 58, "o": 0, "shapeType": 7})
        app.refreshNanoleafPanels(self.loop, False)  # the timed check leaves an unlinked device alone
        self.assertEqual(len(app.availableLights), 4)
        app.refreshNanoleafPanels(self.loop, False, includeUnlinked=True)  # what Rescan does
        self.assertIn("NL:S12345-P5005", [row[0].address for row in app.availableLights])

    def test_a_tap_that_changes_effect_is_taken_back(self):
        hsi = app.calculateByteString(True, colorMode="HSI", HSI_H=120, HSI_S=100, HSI_I=100)
        for row in app.availableLights:
            row[3] = hsi
        self.run_(app.parallelWriteToLights(list(range(len(app.availableLights)))))
        self.fake.waitForFrames(1)
        self.assertTrue(self.controller.streaming)
        self.assertFalse(self.run_(self.controller.checkStream()))  # still streaming: nothing to do
        with self.fake.lock:
            self.fake.effect = "Northern Lights"  # someone tapped the panels
        frames = len(self.fake.frames)
        self.assertTrue(self.run_(self.controller.checkStream(resume=True)))
        self.assertEqual(self.fake.effect, "*ExtControl*")  # back in stream mode
        self.fake.waitForFrames(frames + 1)
        self.assertEqual(len(self.fake.frames[-1]), 4)  # every panel resent

    def test_an_effect_picked_while_idle_is_the_one_kept(self):
        hsi = app.calculateByteString(True, colorMode="HSI", HSI_H=120, HSI_S=100, HSI_I=100)
        for row in app.availableLights:
            row[3] = hsi
        self.run_(app.parallelWriteToLights(list(range(len(app.availableLights)))))
        self.fake.waitForFrames(1)
        self.assertIsNotNone(self.controller._saved)
        with self.fake.lock:
            self.fake.effect = "Northern Lights"  # tapped with nothing running: they want this effect now
        self.assertTrue(self.run_(self.controller.checkStream(resume=False)))
        self.assertFalse(self.controller.streaming)
        self.assertIsNone(self.controller._saved)  # so the next stream saves (and puts back) Northern Lights

    def test_a_failed_check_backs_off(self):
        self.controller.ip = "127.0.0.1"
        self.controller.port = 1  # nothing listens here
        with mock.patch.object(app, "nanoleafCheckBackoff", {}):
            app.refreshNanoleafPanels(self.loop, False)
            self.assertIn("S12345", app.nanoleafCheckBackoff)
            with mock.patch.object(self.controller, "loadLayout") as load:
                app.refreshNanoleafPanels(self.loop, False)
                load.assert_not_called()  # left alone for a while: each try can hold the worker

    def test_unpair_forgets_the_device(self):
        self.assertTrue(app.unpairNanoleaf(self.loop, "S12345", False))
        self.assertEqual(app.availableLights, [])
        self.assertNotIn("S12345", app.nanoleafControllers)
        self.assertEqual(nl.loadSaved(self.saved), [])
        self.assertTrue(getattr(self.fake, "revoked", False))

    def test_unpair_keeps_the_token_when_the_file_cannot_be_written(self):
        with mock.patch.object(nl, "removeSaved", side_effect=OSError("read-only")):
            self.assertFalse(app.unpairNanoleaf(self.loop, "S12345", False))
        self.assertFalse(getattr(self.fake, "revoked", False))  # still in nanoleaf.json, so it must keep working


if __name__ == "__main__":
    unittest.main()
