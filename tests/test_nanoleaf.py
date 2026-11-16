"""Tests for neewerlux_nanoleaf. Run from the repo root:

    uv run --no-sync python -m unittest tests.test_nanoleaf
"""

import asyncio
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import neewerlux_nanoleaf as nl  # noqa: E402
from fake_nanoleaf import FakeNanoleaf, TOKEN  # noqa: E402

UUID = "69400002-b5a3-f393-e0a9-e50e24dcca99"


def hsiBytes(h, s, i):
    v = [120, 134, 4, h & 255, (h & 0xFF00) >> 8, s, i, 0]
    v[7] = nl._checksum(v[:7])
    return bytearray(v)


def cctBytes(bri, temp):
    v = [120, 135, 2, bri, temp, 0]
    v[5] = nl._checksum(v[:5])
    return bytearray(v)


ON = bytearray([120, 129, 1, 1, 251])
OFF = bytearray([120, 129, 1, 2, 252])


class DecodeTests(unittest.TestCase):
    def test_power(self):
        self.assertEqual(nl.decodeCommand(ON), ("power", True))
        self.assertEqual(nl.decodeCommand(OFF), ("power", False))

    def test_hsi(self):
        self.assertEqual(nl.decodeCommand(hsiBytes(300, 75, 40)), ("hsi", 300, 75, 40))

    def test_cct(self):
        self.assertEqual(nl.decodeCommand(cctBytes(80, 56)), ("cct", 5600, 80))

    def test_split_and_scene_and_queries(self):
        self.assertEqual(nl.decodeCommand([120, 130, 1, 42, 0]), ("brightness", 42))
        self.assertEqual(nl.decodeCommand([120, 131, 1, 32, 0]), ("temp", 3200))
        self.assertEqual(nl.decodeCommand([120, 136, 2, 50, 3, 0]), ("scene",))
        self.assertEqual(nl.decodeCommand([120, 133, 0, 253]), ("query_power",))
        self.assertEqual(nl.decodeCommand([120, 132, 0, 252]), ("query_channel",))
        self.assertEqual(nl.decodeCommand([1, 2, 3]), ("unknown",))
        self.assertEqual(nl.decodeCommand([120, 134, 4]), ("unknown",))

    def test_state_bodies(self):
        self.assertEqual(nl.stateBodyFor(("power", True)), {"on": {"value": True}})
        self.assertEqual(nl.stateBodyFor(("hsi", 200, 50, 30)),
                         {"hue": {"value": 200}, "sat": {"value": 50}, "brightness": {"value": 30, "duration": 0}})
        self.assertEqual(nl.stateBodyFor(("cct", 5600, 70)),
                         {"ct": {"value": 5600}, "brightness": {"value": 70, "duration": 0}})
        self.assertIsNone(nl.stateBodyFor(("scene",)))

    def test_cct_clamping(self):
        self.assertEqual(nl.stateBodyFor(("cct", 10000, 50))["ct"]["value"], 6500)
        self.assertEqual(nl.stateBodyFor(("cct", 800, 50))["ct"]["value"], 1200)
        self.assertEqual(nl.stateBodyFor(("temp", 8500, ))["ct"]["value"], 6500)
        self.assertEqual(nl.clampKelvin(3200), 3200)

    def test_power_reply_matches_app_parsing(self):
        # getLightChannelandPower reads [1] == 2 for a power answer and [3] for 1 = on / 2 = standby
        self.assertEqual(list(nl.powerReply(True))[:4], [120, 2, 1, 1])
        self.assertEqual(list(nl.powerReply(False))[:4], [120, 2, 1, 2])


class ColourTests(unittest.TestCase):
    def test_hsi_to_rgb(self):
        self.assertEqual(nl.hsiToRGB(0, 100, 100), (255, 0, 0))
        self.assertEqual(nl.hsiToRGB(120, 100, 100), (0, 255, 0))
        self.assertEqual(nl.hsiToRGB(240, 100, 50), (0, 0, 128))
        self.assertEqual(nl.hsiToRGB(360, 0, 100), (255, 255, 255))

    def test_cct_uses_registered_converter(self):
        try:
            nl.setKelvinConverter(lambda k: (k // 100, 0, 0))
            self.assertEqual(nl.cctToRGB(5600, 100), (56, 0, 0))
            self.assertEqual(nl.cctToRGB(9000, 50), (32, 0, 0))  # clamped to 6500, then halved
        finally:
            nl.setKelvinConverter(None)
        self.assertEqual(nl.cctToRGB(6500, 0), (0, 0, 0))


class FrameTests(unittest.TestCase):
    def test_v2_encoding(self):
        frame = nl.encodeFrameV2([(5001, (1, 2, 3)), (300, (255, 0, 128))], transition=1)
        self.assertEqual(frame, bytes([0, 2, 0x13, 0x89, 1, 2, 3, 0, 0, 1, 0x01, 0x2C, 255, 0, 128, 0, 0, 1]))
        self.assertEqual(nl.decodeFrameV2(frame), [(5001, (1, 2, 3), 1), (300, (255, 0, 128), 1)])

    def test_v1_encoding(self):
        self.assertEqual(nl.encodeFrameV1([(7, (9, 8, 7))], transition=2), bytes([1, 7, 1, 9, 8, 7, 0, 2]))

    def test_panel_order_and_filtering(self):
        layout = {"positionData": [
            {"panelId": 0, "x": 0, "y": 0, "shapeType": 12},
            {"panelId": 3, "x": 300, "y": 0, "shapeType": 7},
            {"panelId": 1, "x": 100, "y": 0, "shapeType": 7},
            {"panelId": 9, "x": 50, "y": 0, "shapeType": 20},
            {"panelId": 2, "x": 200, "y": 0, "shapeType": 7},
            {"panelId": 4, "x": 200, "y": 100, "shapeType": 7},
        ]}
        self.assertEqual(nl.orderPanels(layout), [1, 4, 2, 3])

    def test_host_port(self):
        self.assertEqual(nl.parseHostPort("10.0.0.5"), ("10.0.0.5", 16021))
        self.assertEqual(nl.parseHostPort(" 10.0.0.5:1234 "), ("10.0.0.5", 1234))
        self.assertEqual(nl.parseHostPort("http://10.0.0.5:16021/"), ("10.0.0.5", 16021))

    def test_ssdp_reply(self):
        reply = (b"HTTP/1.1 200 OK\r\nST: nanoleaf:nl42\r\nLocation: http://192.168.1.50:16021\r\n"
                 b"nl-deviceid: 12:AB:34:CD:56:EF\r\nnl-devicename: Shapes 1A2B\r\n\r\n")
        self.assertEqual(nl._parseSsdpReply(reply, ("192.168.1.50", 1900)),
                         {"id": "12AB34CD56EF", "name": "Shapes 1A2B", "model": "nanoleaf:nl42",
                          "ip": "192.168.1.50", "port": 16021})
        self.assertIsNone(nl._parseSsdpReply(b"HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\n\r\n", ("1.2.3.4", 1900)))


class SavedTests(unittest.TestCase):
    def test_round_trip_and_merge(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "light_prefs", "nanoleaf.json")
            self.assertEqual(nl.loadSaved(path), [])
            nl.addSaved({"id": "A", "name": "One", "ip": "1.1.1.1", "port": 16021, "token": "t"}, path)
            devices = nl.loadSaved(path)
            self.assertEqual(devices[0]["perPanel"], False)
            devices[0]["perPanel"] = True
            nl.saveSaved(devices, path)
            nl.addSaved({"id": "A", "name": "One", "ip": "1.1.1.2", "port": 16021, "token": "t2"}, path)
            devices = nl.loadSaved(path)
            self.assertEqual(len(devices), 1)
            self.assertEqual((devices[0]["ip"], devices[0]["token"], devices[0]["perPanel"]), ("1.1.1.2", "t2", True))


class FakeControllerTests(unittest.TestCase):
    """Round trips against tests/fake_nanoleaf.py on 127.0.0.1."""

    def setUp(self):
        self.fake = FakeNanoleaf(port=0, streamPort=0).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.savedPath = os.path.join(self.tmp.name, "nanoleaf.json")

    def tearDown(self):
        self.fake.stop()
        self.tmp.cleanup()

    def makeController(self, perPanel=False):
        entry = {"id": "S12345", "name": "Fake Shapes", "ip": "127.0.0.1", "port": self.fake.port,
                 "token": TOKEN, "perPanel": perPanel}
        nl.saveSaved([entry], self.savedPath)
        c = nl.NanoleafController(entry, savedPath=self.savedPath)
        c.streamPort = self.fake.streamPort
        return c

    def test_pairing(self):
        with self.assertRaises(nl.NanoleafError) as ctx:
            nl.pair("127.0.0.1", self.fake.port)
        self.assertIn("pairing mode", str(ctx.exception))
        self.fake.buttonHeld = True
        self.assertEqual(nl.pair("127.0.0.1", self.fake.port), TOKEN)
        entry = nl.pairAndDescribe("127.0.0.1", self.fake.port)
        self.assertEqual((entry["id"], entry["name"], entry["model"]), ("S12345", "Fake Shapes", "NL42"))

    def test_address_scan(self):
        found = nl.scanHosts(["127.0.0.1"], self.fake.port)
        self.assertEqual([(d["ip"], d["port"]) for d in found], [("127.0.0.1", self.fake.port)])
        self.assertEqual(nl.scanHosts(["127.0.0.1"], 1, timeout=0.3), [])

    def test_unreachable(self):
        c = nl.NanoleafController({"id": "X", "ip": "127.0.0.1", "port": 1, "token": "t"}, savedPath=False)
        c.relocateHosts = []  # nowhere else to look
        client = nl.NanoleafClient(nl.NanoleafDevice(c))
        with self.assertRaises(nl.NanoleafError):
            asyncio.run(client.connect())
        self.assertFalse(client.is_connected)

    def test_find_moved_device(self):
        entry = {"id": "S12345", "ip": "127.0.0.2", "port": self.fake.port, "token": TOKEN}
        self.assertEqual(nl.findMovedDevice(entry, hosts=["127.0.0.1"]), ("127.0.0.1", self.fake.port))
        # a different serial, or a token this device does not know, is not a match
        self.assertIsNone(nl.findMovedDevice(dict(entry, id="OTHER"), hosts=["127.0.0.1"]))
        self.assertIsNone(nl.findMovedDevice(dict(entry, token="wrong"), hosts=["127.0.0.1"]))
        self.assertIsNone(nl.findMovedDevice(entry, hosts=[]))

    def test_connect_recovers_after_ip_change(self):
        entry = {"id": "S12345", "name": "Fake Shapes", "ip": "127.0.0.2", "port": self.fake.port,
                 "token": TOKEN, "perPanel": False}
        nl.saveSaved([entry], self.savedPath)
        c = nl.NanoleafController(entry, savedPath=self.savedPath)
        c.relocateHosts = ["127.0.0.1"]

        async def run():
            # two rows connecting at once share one search
            a, b = nl.NanoleafClient(c.devices()[0]), nl.NanoleafClient(nl.NanoleafDevice(c))
            await asyncio.gather(a.connect(), b.connect())
            self.assertTrue(a.is_connected and b.is_connected)
            await a.write_gatt_char(UUID, ON)
            await a.disconnect()
            await b.disconnect()

        asyncio.run(run())
        self.assertEqual(c.ip, "127.0.0.1")
        self.assertEqual(nl.loadSaved(self.savedPath)[0]["ip"], "127.0.0.1")
        self.assertTrue(self.fake.state["on"]["value"])

    def test_no_second_search_within_interval(self):
        c = nl.NanoleafController({"id": "S12345", "ip": "127.0.0.2", "port": self.fake.port, "token": TOKEN},
                                  savedPath=False)
        c.relocateHosts = []

        async def run():
            self.assertFalse(await c.relocate())
            c.relocateHosts = ["127.0.0.1"]
            self.assertFalse(await c.relocate())  # too soon after the last search
            c.relocateInterval = 0
            self.assertTrue(await c.relocate())

        asyncio.run(run())
        self.assertEqual(c.ip, "127.0.0.1")

    def test_whole_device(self):
        c = self.makeController()

        async def run():
            device = c.devices()[0]
            self.assertEqual((device.address, device.name), ("NL:S12345", "Fake Shapes"))
            client = nl.NanoleafClient(device)
            with self.assertRaises(nl.NanoleafError):
                await client.write_gatt_char(UUID, ON)
            await client.connect()
            self.assertTrue(client.is_connected)

            await client.write_gatt_char(UUID, hsiBytes(200, 90, 40), False)
            self.assertEqual(self.fake.lastStatePut(),
                             {"hue": {"value": 200}, "sat": {"value": 90}, "brightness": {"value": 40, "duration": 0}})
            await client.write_gatt_char(UUID, cctBytes(70, 85), False)
            self.assertEqual(self.fake.state["ct"]["value"], 6500)
            await client.write_gatt_char(UUID, OFF, False)
            self.assertFalse(self.fake.state["on"]["value"])

            received = []
            await client.start_notify(UUID, lambda sender, data: received.append(bytes(data)))
            await client.write_gatt_char(UUID, bytearray([120, 133, 0, 253]))
            await client.write_gatt_char(UUID, bytearray([120, 132, 0, 252]))
            await client.stop_notify(UUID)
            self.assertEqual(received[0][1:4], bytes([2, 1, 2]))  # power answer, standby
            self.assertEqual(received[1], bytes([120]))

            puts = len([r for r in self.fake.requests if r[0] == "PUT"])
            await client.write_gatt_char(UUID, bytearray([120, 136, 2, 50, 3, 0]))  # scene: ignored
            self.assertEqual(len([r for r in self.fake.requests if r[0] == "PUT"]), puts)
            await client.disconnect()
            self.assertFalse(client.is_connected)

        asyncio.run(run())
        self.assertEqual(self.fake.frames, [])

    def test_latest_wins_while_busy(self):
        c = self.makeController()

        async def run():
            client = nl.NanoleafClient(c.devices()[0])
            await client.connect()
            before = len(self.fake.requests)
            await asyncio.gather(*[client.write_gatt_char(UUID, hsiBytes(h, 100, 50)) for h in (10, 20, 30, 40)])
            return before

        before = asyncio.run(run())
        puts = [b for m, p, b in self.fake.requests[before:] if m == "PUT"]
        self.assertLessEqual(len(puts), 2)  # the first, then everything that arrived meanwhile merged into one
        self.assertEqual(self.fake.state["hue"]["value"], 40)

    def test_per_panel_streaming(self):
        nl.setKelvinConverter(lambda k: (255, 200, 100))
        self.addCleanup(nl.setKelvinConverter, None)
        c = self.makeController(perPanel=True)

        async def run():
            await c.loadLayout()
            devices = c.devices()
            self.assertEqual([d.address for d in devices],
                             ["NL:S12345-P5002", "NL:S12345-P5003", "NL:S12345-P5004", "NL:S12345-P5001"])
            self.assertEqual(devices[0].name, "Fake Shapes panel 1")
            clients = [nl.NanoleafClient(d) for d in devices]
            for cl in clients:
                await cl.connect()

            # one "frame" from parallelWriteToLights: every panel written in one gather
            await asyncio.gather(
                clients[0].write_gatt_char(UUID, hsiBytes(0, 100, 100), False),
                clients[1].write_gatt_char(UUID, hsiBytes(120, 100, 100), False),
                clients[2].write_gatt_char(UUID, hsiBytes(240, 100, 100), False),
                clients[3].write_gatt_char(UUID, cctBytes(100, 56), False),
            )
            await asyncio.sleep(0)
            frames = await asyncio.to_thread(self.fake.waitForFrames, 1)
            await asyncio.sleep(0.2)  # catch any stray extra datagram
            self.assertEqual(len(self.fake.frames), 1)
            self.assertEqual(frames[0], [(5002, (255, 0, 0), 1), (5003, (0, 255, 0), 1),
                                         (5004, (0, 0, 255), 1), (5001, (255, 200, 100), 1)])
            self.assertEqual(self.fake.effect, "*ExtControl*")

            # second frame: one panel off, one recoloured; every panel is resent
            await asyncio.gather(clients[1].write_gatt_char(UUID, OFF, False),
                                 clients[2].write_gatt_char(UUID, hsiBytes(60, 100, 100), False))
            frames = await asyncio.to_thread(self.fake.waitForFrames, 2)
            self.assertEqual(frames[1], [(5002, (255, 0, 0), 1), (5003, (0, 0, 0), 1),
                                         (5004, (255, 255, 0), 1), (5001, (255, 200, 100), 1)])

            received = []
            await clients[1].start_notify(UUID, lambda s, d: received.append(bytes(d)))
            await clients[1].write_gatt_char(UUID, bytearray([120, 133, 0, 253]))
            self.assertEqual(received[0][3], 2)  # this panel reports standby

            # the device is released only when the last row disconnects
            for cl in clients[:-1]:
                await cl.disconnect()
            self.assertTrue(c.streaming)
            await clients[-1].disconnect()
            self.assertFalse(c.streaming)

        asyncio.run(run())
        self.assertEqual(self.fake.effect, "Northern Lights")  # restored
        self.assertEqual(self.fake.state["brightness"]["value"], 60)
        self.assertEqual(nl.loadSaved(self.savedPath)[0]["panels"], [5002, 5003, 5004, 5001])

    def test_restore_solid_colour(self):
        self.fake.effect = "*Solid*"
        self.fake.state["colorMode"] = "hs"
        self.fake.state["hue"]["value"] = 123
        c = self.makeController(perPanel=True)

        async def run():
            await c.loadLayout()
            client = nl.NanoleafClient(c.devices()[0])
            await client.connect()
            await client.write_gatt_char(UUID, hsiBytes(0, 100, 100))
            await asyncio.to_thread(self.fake.waitForFrames, 1)
            self.assertEqual(self.fake.state["hue"]["value"], 123)
            await client.disconnect()

        asyncio.run(run())
        self.assertEqual(self.fake.lastStatePut()["hue"], {"value": 123})
        self.assertEqual(self.fake.state["brightness"]["value"], 60)

    def test_whole_device_colour_ends_stream(self):
        c = self.makeController(perPanel=True)

        async def run():
            await c.loadLayout()
            panel = nl.NanoleafClient(c.devices()[0])
            whole = nl.NanoleafClient(nl.NanoleafDevice(c))
            await panel.connect()
            await whole.connect()
            await panel.write_gatt_char(UUID, hsiBytes(0, 100, 100))
            self.assertTrue(c.streaming)
            await asyncio.to_thread(self.fake.waitForFrames, 1)
            await whole.write_gatt_char(UUID, hsiBytes(100, 100, 100))
            self.assertFalse(c.streaming)
            await panel.write_gatt_char(UUID, hsiBytes(200, 100, 100))  # re-enters streaming
            self.assertTrue(c.streaming)
            frames = await asyncio.to_thread(self.fake.waitForFrames, 2)
            self.assertEqual(len(frames), 2)
            self.assertEqual(frames[1][0][1], (0, 170, 255))
            await panel.disconnect()
            await whole.disconnect()

        asyncio.run(run())
        streamStarts = [b for m, p, b in self.fake.requests if m == "PUT" and p.endswith("/effects") and "write" in b]
        self.assertEqual(len(streamStarts), 2)

    def test_v1_fallback(self):
        self.fake.supportsV2 = False
        c = self.makeController(perPanel=True)

        async def run():
            await c.loadLayout()
            client = nl.NanoleafClient(c.devices()[0])
            await client.connect()
            await client.write_gatt_char(UUID, hsiBytes(0, 100, 100))
            self.assertEqual(c._streamVersion, "v1")
            self.assertEqual(c._streamAddr, ("127.0.0.1", self.fake.streamPort))
            await client.disconnect()

        asyncio.run(run())


class AddressTests(unittest.TestCase):
    def test_address_helpers(self):
        self.assertTrue(nl.isAddress("nl:s1-p5"))
        self.assertFalse(nl.isAddress("D0:A8:11:22:33:44"))
        self.assertEqual(nl.deviceIdFromAddress("NL:S23220H3960"), "S23220H3960")
        self.assertEqual(nl.deviceIdFromAddress("nl:s1-p5001"), "S1")

    def test_update_saved(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nanoleaf.json")
            nl.saveSaved([{"id": "A", "ip": "1.1.1.1", "token": "t"}, {"id": "B", "ip": "2.2.2.2", "token": "u"}], path)
            self.assertTrue(nl.updateSaved("B", path, ip="2.2.2.9"))
            self.assertFalse(nl.updateSaved("C", path, ip="3.3.3.3"))
            self.assertEqual([x["ip"] for x in nl.loadSaved(path)], ["1.1.1.1", "2.2.2.9"])


class BatchStringTests(unittest.TestCase):
    """parseBatchString in NeewerLux.py learns the NL: prefix."""

    @classmethod
    def setUpClass(cls):
        try:
            import NeewerLux
        except Exception as e:  # bleak or PySide missing
            raise unittest.SkipTest("NeewerLux.py could not be imported: %s" % e)
        cls.app = NeewerLux

    def parse(self, text):
        return self.app.parseBatchString(text)

    def test_nanoleaf_addresses(self):
        self.assertEqual(self.parse("NL:S1:HSI:0:100:50"),
                         [{"light": "NL:S1", "mode": "HSI", "hue": 0, "sat": 100, "bri": 50}])
        self.assertEqual(self.parse("NL:S1-P5:OFF"), [{"light": "NL:S1-P5", "mode": "OFF"}])
        self.assertEqual(self.parse("nl:S23220H3960:CCT:5600:80"),
                         [{"light": "NL:S23220H3960", "mode": "CCT", "temp": 56, "bri": 80}])

    def test_mixed_with_other_forms(self):
        cmds = self.parse("1:HSI:240:100:50;NL:S1:ON;D0:A8:11:22:33:44:CCT:32:20;*:OFF")
        self.assertEqual([c["light"] for c in cmds], ["1", "NL:S1", "D0:A8:11:22:33:44", "*"])
        self.assertEqual([c["mode"] for c in cmds], ["HSI", "ON", "CCT", "OFF"])

    def test_bare_prefix_is_skipped(self):
        self.assertEqual(self.parse("NL:ON"), [])


if __name__ == "__main__":
    unittest.main()
