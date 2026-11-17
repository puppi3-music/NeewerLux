"""SoundEngine.remapLights: rows moving under a running sound session (Nanoleaf panels added or taken off)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import puppi3lux_audio as audio


class RemapLightsTest(unittest.TestCase):
    def setUp(self):
        self.engine = audio.SoundEngine(lambda frame: True, logFunc=lambda *a: None)

    def test_targets_follow_their_lights(self):
        self.engine.targets = [0, 1, 2, 3]
        self.engine.remapLights({0: 0, 2: 1, 3: 2})  # row 1 was taken off
        self.assertEqual(self.engine.targets, [0, 1, 2])

    def test_two_changes_before_a_frame_chain(self):
        self.engine.targets = [0, 1, 2]
        self.engine.remapLights({0: 1, 1: 2, 2: 3})  # a row went in at the top
        self.engine.remapLights({1: 0, 3: 1})  # then that row and the old row 1 went
        self.assertEqual(self.engine.targets, [0, 1])
        self.assertEqual(self.engine._takeRemap(), {0: 0, 2: 1})
        self.assertIsNone(self.engine._takeRemap())


if __name__ == "__main__":
    unittest.main()
