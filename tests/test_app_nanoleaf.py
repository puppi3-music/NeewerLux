"""Nanoleaf paths through NeewerLux.py itself, against tests/fake_nanoleaf.py. Run from the repo root:

    uv run --no-sync python -m unittest tests.test_app_nanoleaf

No Bluetooth or real Nanoleaf is needed: the Bluetooth scan is replaced by one that fails (as on
a machine without an adapter), and the saved-device file points at a temporary copy. The dialog
test runs Qt offscreen.
"""

import asyncio
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import neewerlux_nanoleaf as nl  # noqa: E402
from fake_nanoleaf import FakeNanoleaf, TOKEN  # noqa: E402

try:
    import NeewerLux as app
except Exception:  # bleak or PySide missing
    app = None


async def noBluetooth(*args, **kwargs):
    raise OSError("No Bluetooth adapters found.")


@unittest.skipIf(app is None, "NeewerLux.py could not be imported")
class AppTestCase(unittest.TestCase):
    """Fresh fake, saved file and app globals for each test."""

    def setUp(self):
        self.fake = FakeNanoleaf(port=0, streamPort=0).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = os.path.join(self.tmp.name, "nanoleaf.json")
        for patcher in (mock.patch.object(nl, "defaultSavedPath", lambda: self.saved),
                        mock.patch.object(app.BleakScanner, "discover", noBluetooth),
                        mock.patch.object(app, "threadAction", ""),
                        mock.patch.object(app, "availableLights", []),
                        mock.patch.object(app, "nanoleafControllers", {})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        self.loop.close()
        self.fake.stop()
        self.tmp.cleanup()

    def save(self, ip="127.0.0.1"):
        nl.saveSaved([{"id": "S12345", "name": "Fake Shapes", "model": "NL42", "ip": ip, "port": self.fake.port,
                       "token": TOKEN, "perPanel": False}], self.saved)

    def run_(self, coro):
        return self.loop.run_until_complete(coro)


class AppPathTests(AppTestCase):
    def test_scan_adds_row_without_bluetooth(self):
        self.save()
        self.run_(app.findDevices())
        self.assertEqual(len(app.availableLights), 1)
        row = app.availableLights[0]
        self.assertEqual(row[0].address, "NL:S12345")
        self.assertEqual(row[4], [1200, 6500])  # colour temperature range
        self.assertIs(row[5], False)  # never CCT-only
        self.assertEqual(row[9], "LAN")
        self.assertEqual(app._light_table_label(row), "Fake Shapes\n  [LAN]")
        self.assertEqual(app._light_signal_text(row), "LAN")

        # a rescan keeps the one row and the one controller
        controller = row[0].controller
        self.run_(app.findDevices())
        self.assertEqual(len(app.availableLights), 1)
        self.assertIs(app.availableLights[0][0].controller, controller)
        self.assertIs(app.nanoleafControllers["S12345"], controller)

    def test_connect_send_and_read_power(self):
        self.save()
        self.run_(app.findDevices())
        self.assertIs(self.run_(app.connectToLight(0, False)), True)
        self.assertIsInstance(app.availableLights[0][1], nl.NanoleafClient)

        app.calculateByteString(colorMode="HSI", HSI_H=200, HSI_S=90, HSI_I=40)
        self.run_(app.writeToLight([0], False))
        self.run_(app.availableLights[0][0].controller.settle())  # state PUTs go out from a thread
        self.assertEqual(self.fake.lastStatePut(),
                         {"hue": {"value": 200}, "sat": {"value": 90}, "brightness": {"value": 40, "duration": 0}})

        app.calculateByteString(colorMode="CCT", temp=32, brightness=70)
        self.run_(app.writeToLight([0], False))
        self.run_(app.availableLights[0][0].controller.settle())  # state PUTs go out from a thread
        self.assertEqual(self.fake.lastStatePut(), {"ct": {"value": 3200}, "brightness": {"value": 70, "duration": 0}})

        app.setPowerBytestring("OFF")
        self.run_(app.writeToLight([0], False))
        self.run_(app.getLightChannelandPower(0))
        self.assertEqual(app.availableLights[0][7][0], "STBY")

        self.assertEqual(app.returnLightIndexesFromMacAddress("nl:s12345"), [0])
        self.run_(app.disconnectFromLight(0, False))
        self.assertFalse(app.availableLights[0][1].is_connected)

    def test_connect_finds_device_after_ip_change(self):
        self.save(ip="127.0.0.2")  # nothing answers there
        self.run_(app.findDevices())
        app.nanoleafControllers["S12345"].relocateHosts = ["127.0.0.1"]
        self.assertIs(self.run_(app.connectToLight(0, False)), True)
        self.assertEqual(app.nanoleafControllers["S12345"].ip, "127.0.0.1")
        self.assertEqual(nl.loadSaved(self.saved)[0]["ip"], "127.0.0.1")
        self.run_(app.disconnectFromLight(0, False))

    def test_cli_light_lookup(self):
        self.save()
        self.run_(app.connectToOneLight("nl:s12345"))  # the CLI lower-cases its arguments
        self.assertEqual([row[0].address for row in app.availableLights], ["NL:S12345"])
        app.availableLights = []
        self.run_(app.connectToOneLight("nl:nothere"))
        self.assertEqual(app.availableLights, [])

    def test_nanoleaf_pair_argument(self):
        for argv, expected in ((["NeewerLux.py", "--nanoleaf_pair", "10.0.0.152"], "10.0.0.152"),
                               (["NeewerLux.py", "nanoleaf_pair=10.0.0.152:16021"], "10.0.0.152:16021")):
            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(app.processCommands(), ["NANOLEAF_PAIR", True, expected])


@unittest.skipIf(app is None or getattr(app, "importError", 1) != 0, "the GUI could not be imported")
class PairDialogTests(AppTestCase):
    """The Add Nanoleaf button and dialog, offscreen."""

    @classmethod
    def setUpClass(cls):
        cls.qapp = app.QApplication.instance() or app.QApplication([sys.argv[0]])
        app.loadPrefsFile()  # defaults only, so nobody's own prefs change the window

    def setUp(self):
        super().setUp()
        found = lambda timeout=3.0, scan=True: [{"id": "", "name": "Nanoleaf", "model": "",
                                                 "ip": "127.0.0.1", "port": self.fake.port}]
        patcher = mock.patch.object(nl, "discoverAll", found)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = app.MainWindow()
        patcher = mock.patch.object(app, "mainWindow", self.window)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        dlg = getattr(self.window, "_nanoleafDialog", None)
        if dlg is not None:
            dlg.hide()
        # hide, not close: closeEvent is the app's shutdown (unlinks lights, saves prefs)
        self.window.hide()
        self.window.deleteLater()
        self.pump(0.1)
        super().tearDown()

    def pump(self, seconds, until=None):
        end = time.time() + seconds
        while time.time() < end:
            self.qapp.processEvents()
            if until is not None and until():
                return
            time.sleep(0.02)

    def test_search_and_pair(self):
        button = self.window.addNanoleafButton
        self.assertFalse(button.isHidden())
        button.click()
        dlg = self.window._nanoleafDialog
        self.pump(3, until=lambda: dlg.foundList.count() > 0)
        self.assertEqual(dlg.foundList.item(0).text(), "Nanoleaf  (127.0.0.1:%d)" % self.fake.port)

        dlg.foundList.setCurrentRow(0)
        self.assertEqual(dlg.addressField.text(), "127.0.0.1:%d" % self.fake.port)

        # the controller is not in pairing mode yet: the hint is shown and nothing is saved
        dlg.pairButton.click()
        self.pump(3, until=lambda: dlg.pairButton.isEnabled())
        self.assertIn("not in pairing mode", dlg.statusLabel.text())
        self.assertEqual(nl.loadSaved(self.saved), [])

        self.fake.buttonHeld = True
        app.threadAction = ""  # no worker thread here to pick up what the window queued at start
        dlg.pairButton.click()
        self.pump(3, until=lambda: dlg.pairButton.isEnabled())
        self.assertIn("Paired Fake Shapes (NL:S12345)", dlg.statusLabel.text())
        self.assertEqual([(d["id"], d["ip"], d["port"]) for d in nl.loadSaved(self.saved)],
                         [("S12345", "127.0.0.1", self.fake.port)])
        self.assertEqual(app.threadAction, "discover")  # the worker lists it next

        # searching again marks it as added
        dlg.searchButton.click()
        self.pump(3, until=lambda: "already added" in dlg.foundList.item(0).text())
        self.assertIn("already added", dlg.foundList.item(0).text())


if __name__ == "__main__":
    unittest.main()
