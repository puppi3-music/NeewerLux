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


class PerPanelTests(AppTestCase):
    """Turning "Show each panel as its own light" on and off (setNanoleafPerPanel, run by the worker)."""

    PANELS = ["NL:S12345-P5002", "NL:S12345-P5003", "NL:S12345-P5004", "NL:S12345-P5001"]  # left to right

    def setUp(self):
        super().setUp()
        # sidecar prefs live next to sys.argv[0]; keep them in the temporary folder
        patcher = mock.patch.object(sys, "argv", [os.path.join(self.tmp.name, "NeewerLux.py")])
        patcher.start()
        self.addCleanup(patcher.stop)
        lightAliases = mock.patch.object(app, "lightAliases", {})
        lightAliases.start()
        self.addCleanup(lightAliases.stop)
        self.save()
        self.run_(app.findDevices())
        self.controller = app.nanoleafControllers["S12345"]
        self.controller.streamPort = self.fake.streamPort

    def tearDown(self):
        for row in app.availableLights:
            if row[1] != "" and row[1].is_connected:
                self.run_(row[1].disconnect())
        super().tearDown()

    def addresses(self):
        return [row[0].address for row in app.availableLights]

    def linked(self):
        return [row[1] != "" and row[1].is_connected for row in app.availableLights]

    def test_one_row_per_panel_streams_one_datagram_per_frame(self):
        self.assertIs(self.run_(app.connectToLight(0, False)), True)
        rows = app.setNanoleafPerPanel(self.loop, "S12345", True, False)

        self.assertEqual(rows, [0, 1, 2, 3])
        self.assertEqual(self.addresses(), self.PANELS)
        self.assertEqual([row[0].name for row in app.availableLights], ["Fake Shapes panel %d" % n for n in range(1, 5)])
        self.assertTrue(all(row[5] is False and row[9] == "LAN" for row in app.availableLights))
        self.assertEqual(self.linked(), [True] * 4)  # it was linked, so the panels are too
        self.assertIs(nl.loadSaved(self.saved)[0]["perPanel"], True)

        # one colour per panel, written the way animations and sound reactive write
        hues = [0, 90, 180, 270]
        for idx, hue in enumerate(hues):
            app.availableLights[idx][3] = app.calculateByteString(True, colorMode="HSI", HSI_H=hue, HSI_S=100, HSI_I=100)
        self.run_(app.parallelWriteToLights(rows))
        frames = self.fake.waitForFrames(1)
        time.sleep(0.2)  # anything more would have arrived by now
        self.assertEqual(len(self.fake.frames), 1)
        frame = {pid: rgb for pid, rgb, _ in frames[0]}
        self.assertEqual(set(frame), {5001, 5002, 5003, 5004})
        self.assertEqual(len(set(frame.values())), 4)  # four distinct colours
        self.assertEqual(frame[5002], nl.hsiToRGB(0, 100, 100))  # panel 1 is the leftmost
        self.assertEqual(frame[5001], nl.hsiToRGB(270, 100, 100))

        # the next frame is again a single datagram
        app.availableLights[0][3] = app.calculateByteString(True, colorMode="HSI", HSI_H=45, HSI_S=100, HSI_I=100)
        self.run_(app.parallelWriteToLights(rows))
        self.fake.waitForFrames(2)
        time.sleep(0.2)
        self.assertEqual(len(self.fake.frames), 2)
        self.assertEqual({pid: rgb for pid, rgb, _ in self.fake.frames[1]}[5002], nl.hsiToRGB(45, 100, 100))

    def test_panels_chase_together_in_a_roll(self):
        self.assertIsNone(app.soundLightGroup(0))  # the whole device is one light: it strobes
        app.setNanoleafPerPanel(self.loop, "S12345", True, False)
        self.assertEqual({app.soundLightGroup(i) for i in range(4)}, {self.controller.id})
        self.assertIsNone(app.soundLightGroup(4))  # past the end

    def test_turning_it_off_restores_the_effect_and_one_row(self):
        self.assertIs(self.run_(app.connectToLight(0, False)), True)
        rows = app.setNanoleafPerPanel(self.loop, "S12345", True, False)
        app.availableLights[0][3] = app.calculateByteString(True, colorMode="HSI", HSI_H=120, HSI_S=100, HSI_I=100)
        self.run_(app.parallelWriteToLights(rows[:1]))
        self.fake.waitForFrames(1)
        self.assertEqual(self.fake.effect, "*ExtControl*")

        self.assertEqual(app.setNanoleafPerPanel(self.loop, "S12345", False, False), [0])
        self.assertEqual(self.addresses(), ["NL:S12345"])
        self.assertEqual(self.fake.effect, "Northern Lights")  # put back when the last panel row closed
        self.assertFalse(self.controller.streaming)
        self.assertEqual(self.linked(), [True])
        self.assertIs(nl.loadSaved(self.saved)[0]["perPanel"], False)

    def test_unlinked_device_learns_its_panels_and_stays_unlinked(self):
        self.assertEqual(self.controller.panels, [])  # never linked, so the layout isn't cached
        rows = app.setNanoleafPerPanel(self.loop, "S12345", True, False)
        self.assertEqual(rows, [0, 1, 2, 3])
        self.assertEqual(self.addresses(), self.PANELS)
        self.assertEqual(self.linked(), [False] * 4)
        self.assertEqual(nl.loadSaved(self.saved)[0]["panels"], [5002, 5003, 5004, 5001])

        # a rescan keeps the panel rows, and a fresh start (new controller from the file) lists them too
        self.run_(app.findDevices())
        self.assertEqual(self.addresses(), self.PANELS)
        app.availableLights = []
        app.nanoleafControllers = {}
        self.run_(app.findDevices())
        self.assertEqual(self.addresses(), self.PANELS)

    def test_unreachable_device_is_left_alone(self):
        self.fake.stop()
        self.assertIsNone(app.setNanoleafPerPanel(self.loop, "S12345", True, False))
        self.assertEqual(self.addresses(), ["NL:S12345"])
        self.assertIs(nl.loadSaved(self.saved)[0]["perPanel"], False)
        self.fake = FakeNanoleaf(port=0, streamPort=0).start()  # for tearDown

    def test_each_panel_keeps_its_own_prefs(self):
        app.setNanoleafPerPanel(self.loop, "S12345", True, False)
        last = self.addresses().index("NL:S12345-P5001")
        app.availableLights[last][2] = "Right"
        app.availableLights[last][8] = 2
        app.saveLightPrefs(last)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "light_prefs", "NLS12345-P5001")))

        # off and on again: the panel rows are rebuilt from their sidecar files
        app.setNanoleafPerPanel(self.loop, "S12345", False, False)
        self.assertEqual(self.addresses(), ["NL:S12345"])
        self.assertEqual(app.availableLights[0][2], "")  # the whole device has prefs of its own
        app.setNanoleafPerPanel(self.loop, "S12345", True, False)
        self.assertEqual(self.addresses()[0], "NL:S12345-P5001")  # a preferred ID puts it first
        row = app.availableLights[0]
        self.assertEqual((row[2], row[8]), ("Right", 2))
        self.assertEqual(app._light_table_label(row), "Right (Fake Shapes panel 4)\n  [LAN]")

        # the name and ID work in HTTP commands and animations
        self.assertEqual(app.lightAliases["NL:S12345-P5001"], {"id": 2, "name": "Right"})
        self.assertEqual(app.returnLightIndexesFromMacAddress("right"), [0])
        self.assertEqual(app.returnLightIndexesFromMacAddress("2"), [0])
        self.assertEqual(app.returnLightIndexesFromMacAddress("nl:s12345-p5001"), [0])


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


@unittest.skipIf(app is None or getattr(app, "importError", 1) != 0, "the GUI could not be imported")
class LightTableGroupTests(AppTestCase):
    """A device shown one row per panel is listed as a collapsible group in the light table."""

    @classmethod
    def setUpClass(cls):
        cls.qapp = app.QApplication.instance() or app.QApplication([sys.argv[0]])
        app.loadPrefsFile()

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(sys, "argv", [os.path.join(self.tmp.name, "NeewerLux.py")])
        patcher.start()
        self.addCleanup(patcher.stop)
        # one device per panel (its panels already known, so nothing needs to link) and one whole device
        nl.saveSaved([{"id": "S12345", "name": "Fake Shapes", "model": "NL42", "ip": "127.0.0.1", "port": self.fake.port,
                       "token": TOKEN, "perPanel": True, "panels": [5002, 5003, 5001]},
                      {"id": "S99999", "name": "Other", "model": "NL42", "ip": "127.0.0.1", "port": self.fake.port,
                       "token": TOKEN, "perPanel": False}], self.saved)
        self.run_(app.findDevices())
        self.window = app.MainWindow()
        patcher = mock.patch.object(app, "mainWindow", self.window)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window.updateLights(False, False)
        self.table = self.window.lightTable

    def tearDown(self):
        self.window.hide()
        self.window.deleteLater()
        self.qapp.processEvents()
        super().tearDown()

    def names(self):
        return [self.table.item(r, 0).text().split("\n")[0] for r in range(self.table.rowCount())]

    def selectTableRow(self, row):
        self.table.clearSelection()
        self.table.selectRow(row)

    def test_panels_are_listed_under_their_device(self):
        self.assertEqual([row[0].address for row in app.availableLights],
                         ["NL:S12345-P5002", "NL:S12345-P5003", "NL:S12345-P5001", "NL:S99999"])
        self.assertEqual(self.names(), ["▾ Fake Shapes", "├─ Fake Shapes panel 1", "├─ Fake Shapes panel 2",
                                        "└─ Fake Shapes panel 3", "Other"])
        self.assertEqual(self.table.item(0, 1).text(), "NL:S12345")
        self.assertEqual(self.table.item(0, 2).text(), "NOT\nLINKED")
        self.assertEqual([self.table.verticalHeaderItem(r).text() for r in range(5)], ["▾", "1", "2", "3", "4"])

        # rows and availableLights indexes differ: the worker's updates still reach the right row
        self.window.setTheTable(["", "", "", "Connecting..."], 3)
        self.assertEqual(self.table.item(4, 3).text(), "Connecting...")
        self.assertEqual(self.window.returnTableInfo(3, 3), "Connecting...")

    def test_selecting_the_device_selects_its_panels(self):
        self.selectTableRow(0)
        self.assertEqual(self.window.selectedLights(), [0, 1, 2])
        self.selectTableRow(2)
        self.assertEqual(self.window.selectedLights(), [1])
        self.window.selectRows([2, 3])
        self.assertEqual(sorted(i.row() for i in self.table.selectionModel().selectedRows()), [3, 4])

    def test_collapse_and_expand(self):
        self.selectTableRow(2)  # panel 2
        self.window._toggleGroupAt(0)
        self.assertEqual([self.table.isRowHidden(r) for r in range(5)], [False, True, True, True, False])
        self.assertTrue(self.table.item(0, 0).text().startswith("▸ Fake Shapes"))
        # one hidden panel is deselected, not widened to the whole device
        self.assertEqual(self.window.selectedLights(), [])

        # all of its panels selected: the device's row takes their selection, the same lights
        self.window._toggleGroupAt(0)
        self.window.selectRows([0, 1, 2])
        self.window._toggleGroupAt(0)
        self.assertEqual([i.row() for i in self.table.selectionModel().selectedRows()], [0])
        self.assertEqual(self.window.selectedLights(), [0, 1, 2])

        # all the panels of a collapsed device select its row; a rebuilt table stays collapsed
        self.window.selectRows([0, 1, 2])
        self.assertEqual([i.row() for i in self.table.selectionModel().selectedRows()], [0])
        self.window.updateLights(False, False)
        self.assertTrue(self.table.isRowHidden(1))

        # only some of them expand it, so just those are selected
        self.window.selectRows([1])
        self.assertFalse(self.table.isRowHidden(2))
        self.assertEqual(self.window.selectedLights(), [1])
        self.window._toggleGroupAt(0)  # collapse again for the checks below
        self.assertTrue(self.table.isRowHidden(1))

        self.window._toggleGroupAt(0)
        self.assertEqual([self.table.isRowHidden(r) for r in range(5)], [False] * 5)
        self.assertTrue(self.table.item(0, 0).text().startswith("▾ Fake Shapes"))
        self.window._toggleGroupAt(4)  # a light on its own: nothing to collapse
        self.assertFalse(any(self.table.isRowHidden(r) for r in range(5)))


if __name__ == "__main__":
    unittest.main()
