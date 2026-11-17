"""Tests for the renames to Puppi3Lux: old HTTP paths still work, and settings saved
under the old Puppi3sNeewerLux and NeewerLux names are picked up. Run from the repo root:

    uv run --no-sync python -m unittest tests.test_rename
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import Puppi3Lux as app
except Exception:  # bleak or PySide missing
    app = None


@unittest.skipIf(app is None, "Puppi3Lux.py could not be imported")
class TestHTTPPaths(unittest.TestCase):
    def test_old_prefixes_are_rewritten(self):
        self.assertEqual(app.modernHTTPPath("/NeewerLux/doAction?list"), "/Puppi3Lux/doAction?list")
        self.assertEqual(app.modernHTTPPath("/NeewerLite-Python/doAction?use_preset=2"),
                         "/Puppi3Lux/doAction?use_preset=2")
        self.assertEqual(app.modernHTTPPath("/NeewerLux/batch"), "/Puppi3Lux/batch")
        self.assertEqual(app.modernHTTPPath("/Puppi3sNeewerLux/doAction?list"), "/Puppi3Lux/doAction?list")

    def test_current_and_other_paths_are_left_alone(self):
        for path in ("/Puppi3Lux/doAction?list", "/", "/favicon.ico", "/x/NeewerLux/doAction?list"):
            self.assertEqual(app.modernHTTPPath(path), path)


@unittest.skipIf(app is None, "Puppi3Lux.py could not be imported")
class TestPrefsMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.new = {ext: os.path.join(d, "Puppi3Lux" + ext) for ext in (".prefs", ".geometry", ".log")}
        for name, ext in (("globalPrefsFile", ".prefs"), ("geometryPrefsFile", ".geometry"), ("logFilePath", ".log")):
            patcher = mock.patch.object(app, name, self.new[ext])
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, name, text):
        with open(os.path.join(self.tmp.name, name), "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def test_old_files_are_renamed(self):
        self.write("NeewerLux.prefs", "httpPort=9000")
        self.write("NeewerLux.geometry", "geo")
        app.migrateRenamedPrefsFiles()
        self.assertEqual(self.read(self.new[".prefs"]), "httpPort=9000")
        self.assertEqual(self.read(self.new[".geometry"]), "geo")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "NeewerLux.prefs")))
        self.assertFalse(os.path.exists(self.new[".log"]))  # there was no old log

    def test_puppi3s_neewerlux_files_are_renamed_and_beat_older_ones(self):
        self.write("Puppi3sNeewerLux.prefs", "httpPort=9001")
        self.write("NeewerLux.prefs", "httpPort=9000")
        self.write("NeewerLux.log", "log")
        app.migrateRenamedPrefsFiles()
        self.assertEqual(self.read(self.new[".prefs"]), "httpPort=9001")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "Puppi3sNeewerLux.prefs")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "NeewerLux.prefs")))  # left alone
        self.assertEqual(self.read(self.new[".log"]), "log")

    def test_new_file_wins(self):
        self.write("NeewerLux.prefs", "old")
        self.write("Puppi3Lux.prefs", "new")
        app.migrateRenamedPrefsFiles()
        self.assertEqual(self.read(self.new[".prefs"]), "new")
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "NeewerLux.prefs")))


if __name__ == "__main__":
    unittest.main()
