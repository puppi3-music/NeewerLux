"""Check neewerlux_nanoleaf against a real Nanoleaf before the app integration. A dev tool.

Run from the repo root:

    uv run python tests/nanoleaf_hw_check.py --discover        # list controllers on the network
    uv run python tests/nanoleaf_hw_check.py 192.168.1.50      # pair (or reuse the saved token) and run the checks

Steps, each waiting for Enter so you can look at the panels:
  1. pair, or reuse the token saved in light_prefs/nanoleaf.json, and save the device there
  2. print the raw layout with shape types, and which panels count as lights (left to right)
  3. whole device: red, green, blue through HSI, then 2700 K and 6500 K through CCT
  4. per panel: light the panels one at a time in left-to-right order
  5. per panel: a moving rainbow for a few seconds, printing the frame rate
  6. disconnect, which should put back the effect that was running before
"""

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import neewerlux_nanoleaf as nl  # noqa: E402

UUID = "nanoleaf-check"
SAVED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "light_prefs", "nanoleaf.json")


def hsi(h, s, i):
    return bytearray([120, 134, 4, h & 255, (h >> 8) & 255, s, i, 0])


def cct(bri, temp):
    return bytearray([120, 135, 2, bri, temp, 0])


def pause(msg):
    input("\n" + msg + "  [Enter]")


def getEntry(ip, port):
    for d in nl.loadSaved(SAVED):
        if d["ip"] == ip and int(d.get("port", nl.API_PORT)) == port:
            print("Using the saved token for %s (%s)" % (d["name"], d["id"]))
            return d
    print(nl.PAIRING_HINT)
    pause("Hold the button now, then")
    entry = nl.pairAndDescribe(ip, port)
    nl.addSaved(entry, SAVED)
    print("Paired: %s, model %s, id %s. Saved to %s" % (entry["name"], entry["model"], entry["id"], SAVED))
    return entry


async def run(entry, seconds):
    controller = nl.NanoleafController(entry, savedPath=SAVED)
    status, layout = await controller.http("GET", "/panelLayout/layout")
    print("\nLayout (HTTP %s): %s panels, side length %s" % (status, layout.get("numPanels"), layout.get("sideLength")))
    for p in layout.get("positionData", []):
        skip = p.get("shapeType") in nl.NON_LIGHT_SHAPE_TYPES or p.get("panelId") == 0
        print("  id %-6s x %-5s y %-5s o %-4s shapeType %-3s %s" % (p.get("panelId"), p.get("x"), p.get("y"), p.get("o"),
                                                              p.get("shapeType"), "(skipped)" if skip else ""))

    whole = nl.NanoleafClient(nl.NanoleafDevice(controller))
    await whole.connect()
    print("Light panels, left to right: %s" % controller.panels)

    replies = []
    await whole.start_notify(UUID, lambda s, d: replies.append(bytes(d)))
    await whole.write_gatt_char(UUID, bytearray([120, 133, 0, 253]))
    print("Power query answer: %s" % ("ON" if replies and replies[0][3] == 1 else "STBY"))

    pause("Step 3: whole-device colours.")
    await whole.write_gatt_char(UUID, bytearray([120, 129, 1, 1, 251]))
    for label, cmd in [("red", hsi(0, 100, 100)), ("green", hsi(120, 100, 100)), ("blue", hsi(240, 100, 100)),
                       ("2700 K", cct(100, 27)), ("6500 K", cct(100, 65))]:
        print("  " + label)
        await whole.write_gatt_char(UUID, cmd)
        await asyncio.sleep(1.5)

    pause("Step 4: panels one at a time, left to right.")
    controller.perPanel = True
    clients = [nl.NanoleafClient(d) for d in controller.devices()]
    for c in clients:
        await c.connect()
    for n, c in enumerate(clients):
        print("  panel %d (id %s)" % (n + 1, c.device.panelId))
        await asyncio.gather(*[o.write_gatt_char(UUID, hsi(0, 0, 100) if o is c else hsi(0, 0, 0)) for o in clients])
        await asyncio.sleep(0.6)

    pause("Step 5: rainbow for %d seconds." % seconds)
    frames, start = 0, time.monotonic()
    while time.monotonic() - start < seconds:
        offset = int((time.monotonic() - start) * 120)
        await asyncio.gather(*[c.write_gatt_char(UUID, hsi((offset + i * 360 // len(clients)) % 360, 100, 100))
                               for i, c in enumerate(clients)])
        frames += 1
        await asyncio.sleep(1 / 30)
    print("  %d frames in %d s (%.1f fps sent)" % (frames, seconds, frames / seconds))

    pause("Step 6: disconnect and restore the previous effect.")
    for c in clients:
        await c.disconnect()
    await whole.disconnect()
    print("Done. The panels should be back on the effect from before step 4.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("host", nargs="?", help="controller ip[:port]")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--seconds", type=int, default=8)
    args = parser.parse_args()

    if args.discover or not args.host:
        print("Searching (SSDP, then a scan of this machine's /24 network)...")
        found = nl.discoverAll(4.0)
        for d in found:
            how = "SSDP" if d["id"] else "address scan"
            print("%-20s %-16s %s:%s  %s  (%s)" % (d["name"], d["id"] or "-", d["ip"], d["port"], d["model"], how))
        if not found:
            print("Nothing found. Pass the IP address instead.")
        return

    ip, port = nl.parseHostPort(args.host)
    asyncio.run(run(getEntry(ip, port), args.seconds))


if __name__ == "__main__":
    main()
