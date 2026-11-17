"""Tests for where light_prefs lives: next to the program, except in the macOS app, which keeps it in
~/Library/Application Support and copies the shipped presets and animations there. Run from the repo root:

    uv run --no-sync python -m unittest tests.test_prefs_dir
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import puppi3lux_nanoleaf as nanoleaf  # noqa: E402

try:
    import Puppi3Lux as app
except Exception:  # bleak or PySide missing
    app = None


@unittest.skipIf(app is None, "Puppi3Lux.py could not be imported")
class TestPrefsDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.macDir = os.path.join(self.home, "Library", "Application Support", "Puppi3Lux", "light_prefs")

    def patchMacApp(self):
        for patcher in (mock.patch.object(app, "_isFrozenExe", True),
                        mock.patch.object(sys, "frozen", True, create=True),
                        mock.patch.object(sys, "platform", "darwin"),
                        mock.patch.object(os.path, "expanduser", lambda path: path.replace("~", self.home, 1))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_next_to_the_program(self):
        with mock.patch.object(sys, "argv", [os.path.join(self.tmp.name, "Puppi3Lux.py")]):
            expected = os.path.join(self.tmp.name, "light_prefs")
            self.assertEqual(app.lightPrefsDir(), expected)
            self.assertEqual(nanoleaf.defaultSavedPath(), os.path.join(expected, "nanoleaf.json"))

    def test_macos_app_uses_application_support(self):
        self.patchMacApp()
        self.assertEqual(app.lightPrefsDir(), self.macDir)
        self.assertEqual(nanoleaf.defaultSavedPath(), os.path.join(self.macDir, "nanoleaf.json"))

    def makeBundle(self):
        bundle = os.path.join(self.tmp.name, "bundle", "light_prefs")
        os.makedirs(os.path.join(bundle, "animations"))
        for name, text in (("animations/Breathe.json", "shipped breathe"), ("animations/Strobe.json", "shipped strobe"),
                           ("customLights.prefs.default", "template v1")):
            with open(os.path.join(bundle, name), "w") as f:
                f.write(text)
        patcher = mock.patch.object(app, "_resource_path", lambda name: os.path.join(self.tmp.name, "bundle", name))
        patcher.start()
        self.addCleanup(patcher.stop)
        return bundle

    def read(self, name):
        with open(os.path.join(self.macDir, name)) as f:
            return f.read()

    def test_macos_app_copies_shipped_files_once_per_version(self):
        self.patchMacApp()
        bundle = self.makeBundle()
        app.seedBundledPrefs()
        self.assertEqual(self.read("animations/Breathe.json"), "shipped breathe")
        self.assertEqual(self.read("customLights.prefs.default"), "template v1")

        # The user edits one animation and deletes another; the same version doesn't put them back
        with open(os.path.join(self.macDir, "animations", "Breathe.json"), "w") as f:
            f.write("mine")
        os.remove(os.path.join(self.macDir, "animations", "Strobe.json"))
        with open(os.path.join(bundle, "customLights.prefs.default"), "w") as f:
            f.write("template v2")
        app.seedBundledPrefs()
        self.assertEqual(self.read("animations/Breathe.json"), "mine")
        self.assertFalse(os.path.exists(os.path.join(self.macDir, "animations", "Strobe.json")))
        self.assertEqual(self.read("customLights.prefs.default"), "template v2")  # templates always refresh

        # A new version adds missing shipped animations, still without overwriting the user's
        with mock.patch.object(app, "PUPPI3LUX_VERSION", "99.0.0"):
            app.seedBundledPrefs()
        self.assertEqual(self.read("animations/Strobe.json"), "shipped strobe")
        self.assertEqual(self.read("animations/Breathe.json"), "mine")

    def test_seeding_does_nothing_outside_the_macos_app(self):
        self.makeBundle()
        with mock.patch.object(sys, "argv", [os.path.join(self.tmp.name, "Puppi3Lux.py")]):
            app.seedBundledPrefs()
            self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "light_prefs")))


if __name__ == "__main__":
    unittest.main()
