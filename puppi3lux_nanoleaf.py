"""Nanoleaf panel support for Puppi3Lux.

Drives Nanoleaf panel controllers (Shapes, Canvas, Lines, Elements, Light Panels) through
their local Open API: HTTP on port 16021 for state, UDP extControl streaming for per-panel
colour. Standard library only.

The app's send paths talk to Bleak objects directly (availableLights[i][0] is a BLEDevice,
[1] a BleakClient, and every write is a Neewer byte string handed to write_gatt_char). This
module provides stand-ins with the same surface, NanoleafDevice and NanoleafClient, so a
Nanoleaf row looks like any other row to the rest of the app. NanoleafClient decodes the
Neewer byte strings it is given and turns them into Open API calls.

A row is either the whole device (one light) or one panel of it. All rows of one physical
device share a NanoleafController, which owns the HTTP helper, the panel layout and the
UDP stream.
"""

import asyncio
import colorsys
import json
import math
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

API_PORT = 16021
STREAM_PORT = 60222  # extControl v2 always streams to this port
STREAM_EFFECT = "*ExtControl*"  # what /effects/select reads while the device is in stream mode

# Whole-device colours that come quickly (sound reactive, animations, a dragged slider) are streamed over UDP
# instead of one HTTP PUT each, which takes 70-600 ms on a Shapes set; the stream keeps up with 20+ frames a second.
STREAM_AFTER = 0.5  # a colour this soon after the last one starts the stream, seconds
STREAM_IDLE = 5.0  # with no colour for this long the stream ends and the last colour is PUT, seconds
STREAM_RETRY = 30.0  # after the device refused to stream, PUT for this long before asking again, seconds
# Streamed frames change the panels at once (no fade). A Shapes set showed clean red/blue swaps at 30 a second
# this way, so a streaming device keeps up with the sound engine's fastest rate.
STREAM_INTERVAL = 1 / 30  # seconds per frame a streaming device can show, for the sound engine

CCT_MIN = 1200  # the Open API's colour temperature range
CCT_MAX = 6500

# Shape types in /panelLayout/layout that are not lights. Ids from the Open API docs:
# 1 Rhythm module, 12 Shapes controller, 16 Lines connector, 19 controller cap,
# 20 power connector. Confirm against the real Shapes set.
NON_LIGHT_SHAPE_TYPES = {1, 12, 16, 19, 20}

# Side length of each shape type, from the Open API docs' shape type table (the layout's own sideLength
# is deprecated: Elements report 0). Used to tell which panels stand in the same column.
SHAPE_SIDE = {0: 150, 2: 100, 3: 100, 4: 100, 7: 67, 8: 134, 9: 67, 14: 134, 17: 154, 18: 77,
              29: 50, 30: 180, 31: 180, 32: 180}

# SSDP service types the controllers answer to. Discovery also accepts any reply that
# carries an nl-deviceid header, so an unlisted model still shows up.
SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_SERVICE_TYPES = [
    "nanoleaf_aurora:light",  # Light Panels
    "nanoleaf:nl29",          # Canvas
    "nanoleaf:nl42",          # Shapes hexagons
    "nanoleaf:nl47",          # Shapes triangles
    "nanoleaf:nl48",          # Shapes mini triangles
    "nanoleaf:nl52",          # Elements
    "nanoleaf:nl59",          # Lines
    "ssdp:all",
]

ADDRESS_PREFIX = "NL:"
PANEL_SEPARATOR = "-P"

PAIRING_HINT = ("Hold the power button on the Nanoleaf controller for 5-7 seconds until the "
                "lights flash, then pair within 30 seconds.")


class NanoleafError(Exception):
    pass


class NanoleafUnreachable(NanoleafError):
    """Nothing answered at the address (as opposed to an HTTP error from the device)."""


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _fallbackKelvinToRGB(kelvin):
    """Coarse blackbody approximation, used only until the app registers its own converter."""
    table = [(1200, (255, 82, 0)), (2000, (255, 137, 14)), (2700, (255, 167, 87)),
             (3200, (255, 187, 120)), (4000, (255, 209, 163)), (5000, (255, 228, 206)),
             (5600, (255, 238, 227)), (6500, (255, 254, 250))]
    if kelvin <= table[0][0]:
        return table[0][1]
    for (k0, c0), (k1, c1) in zip(table, table[1:]):
        if kelvin <= k1:
            t = (kelvin - k0) / (k1 - k0)
            return tuple(int(round(a + (b - a) * t)) for a, b in zip(c0, c1))
    return table[-1][1]


_kelvinToRGB = _fallbackKelvinToRGB


def setKelvinConverter(fn):
    """Use the app's Kelvin to RGB converter (convert_K_to_RGB) for per-panel CCT."""
    global _kelvinToRGB
    _kelvinToRGB = fn or _fallbackKelvinToRGB


def clampKelvin(kelvin):
    return max(CCT_MIN, min(CCT_MAX, int(kelvin)))


def hsiToRGB(hue, sat, intensity):
    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360.0, max(0, min(100, sat)) / 100.0,
                                  max(0, min(100, intensity)) / 100.0)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def cctToRGB(kelvin, brightness):
    r, g, b = _kelvinToRGB(clampKelvin(kelvin))
    scale = max(0, min(100, brightness)) / 100.0
    return (int(round(r * scale)), int(round(g * scale)), int(round(b * scale)))


# ---------------------------------------------------------------------------
# Neewer byte strings
# ---------------------------------------------------------------------------

def _checksum(values):
    return sum(v & 255 for v in values) & 255


def decodeCommand(data):
    """Decode a Neewer byte string into a tuple naming what it asks for.

    ("power", on) | ("hsi", hue, sat, intensity) | ("cct", kelvin, brightness)
    | ("brightness", value) | ("temp", kelvin) | ("scene",) | ("query_power",)
    | ("query_channel",) | ("unknown",)
    Kelvin values are unclamped (the byte holds hundreds of K).
    """
    d = list(data)
    if len(d) < 2 or d[0] != 120:
        return ("unknown",)
    tag = d[1]
    try:
        if tag == 129:
            return ("power", d[3] == 1)
        if tag == 134:
            return ("hsi", d[3] | (d[4] << 8), d[5], d[6])
        if tag == 135:
            return ("cct", d[4] * 100, d[3])
        if tag == 130:
            return ("brightness", d[3])
        if tag == 131:
            return ("temp", d[3] * 100)
        if tag == 136:
            return ("scene",)
        if tag == 133:
            return ("query_power",)
        if tag == 132:
            return ("query_channel",)
    except IndexError:
        pass
    return ("unknown",)


def powerReply(on):
    """The notify payload a Neewer light sends in answer to a power query."""
    reply = [120, 2, 1, 1 if on else 2, 0]
    reply[4] = _checksum(reply[:4])
    return bytearray(reply)


# A one-byte reply makes the app treat the channel as unknown ("---") straight away,
# rather than retrying the query until it times out.
CHANNEL_REPLY = bytearray([120])


def stateBodyFor(command):
    """The PUT /state body for a decoded command sent to a whole device, or None."""
    kind = command[0]
    if kind == "power":
        return {"on": {"value": command[1]}}
    if kind == "hsi":
        _, hue, sat, intensity = command
        return {"hue": {"value": max(0, min(360, hue))},
                "sat": {"value": max(0, min(100, sat))},
                "brightness": {"value": max(0, min(100, intensity)), "duration": 0}}
    if kind == "cct":
        _, kelvin, bri = command
        return {"ct": {"value": clampKelvin(kelvin)},
                "brightness": {"value": max(0, min(100, bri)), "duration": 0}}
    if kind == "brightness":
        return {"brightness": {"value": max(0, min(100, command[1])), "duration": 0}}
    if kind == "temp":
        return {"ct": {"value": clampKelvin(command[1])}}
    return None


# ---------------------------------------------------------------------------
# UDP streaming frames
# ---------------------------------------------------------------------------

def encodeFrameV2(colours, transition=1):
    """extControl v2 frame: panel count, then per panel id, R, G, B, W, transition (x100 ms).

    colours is a list of (panelId, (r, g, b)). Counts, ids and transition are big-endian 16-bit.
    """
    out = bytearray(len(colours).to_bytes(2, "big"))
    for panelId, (r, g, b) in colours:
        out += panelId.to_bytes(2, "big")
        out += bytes((r & 255, g & 255, b & 255, 0))
        out += int(transition).to_bytes(2, "big")
    return bytes(out)


def encodeFrameV1(colours, transition=1):
    """extControl v1 frame (Light Panels on older firmware): 8-bit counts and ids, one frame per panel."""
    out = bytearray([len(colours) & 255])
    for panelId, (r, g, b) in colours:
        out += bytes((panelId & 255, 1, r & 255, g & 255, b & 255, 0, int(transition) & 255))
    return bytes(out)


def decodeFrameV2(data):
    """Inverse of encodeFrameV2, for tests and the fake controller."""
    count = int.from_bytes(data[0:2], "big")
    out = []
    for i in range(count):
        p = 2 + i * 8
        out.append((int.from_bytes(data[p:p + 2], "big"), (data[p + 2], data[p + 3], data[p + 4]),
                    int.from_bytes(data[p + 6:p + 8], "big")))
    return out


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _request(method, url, body=None, timeout=3.0):
    """Blocking HTTP call. Returns (status, parsed JSON or None). Raises NanoleafError on network errors."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, b""
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise NanoleafUnreachable("Could not reach the Nanoleaf at " + url.split("/api/")[0] + ": " + str(reason))
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def parseHostPort(text, defaultPort=API_PORT):
    """'192.168.1.20' or '192.168.1.20:16021' (or 'http://...') -> (ip, port)."""
    text = text.strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0]
    if text.count(":") == 1:
        host, port = text.split(":")
        return host, int(port)
    return text, defaultPort


def pair(ip, port=API_PORT, timeout=5.0):
    """Ask the controller for an auth token. The controller must be in pairing mode."""
    status, body = _request("POST", "http://%s:%d/api/v1/new" % (ip, port), timeout=timeout)
    if status == 403:
        raise NanoleafError("The Nanoleaf is not in pairing mode. " + PAIRING_HINT)
    if status not in (200, 201) or not isinstance(body, dict) or "auth_token" not in body:
        raise NanoleafError("Pairing failed (HTTP %s)" % status)
    return body["auth_token"]


def normaliseDeviceId(deviceId):
    """Device ids come as MAC-style strings; strip separators so they fit addresses and filenames."""
    return "".join(c for c in str(deviceId) if c.isalnum()).upper()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _parseSsdpReply(data, sender):
    headers = {}
    for line in data.decode("utf-8", "replace").split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    st = headers.get("st", "") + headers.get("nt", "")
    if "nl-deviceid" not in headers and "nanoleaf" not in st.lower():
        return None
    ip, port = sender[0], API_PORT
    if "location" in headers:
        ip, port = parseHostPort(headers["location"])
    return {"id": normaliseDeviceId(headers.get("nl-deviceid", ip)),
            "name": headers.get("nl-devicename", "Nanoleaf"),
            "model": headers.get("st", ""),
            "ip": ip, "port": port}


def discover(timeout=3.0):
    """SSDP search for Nanoleaf controllers on the local network. Blocking; run it off the GUI thread."""
    found = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.25)
        for st in SSDP_SERVICE_TYPES:
            msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
                   'MAN: "ssdp:discover"\r\nMX: 2\r\nST: ' + st + "\r\n\r\n")
            sock.sendto(msg.encode("ascii"), SSDP_ADDR)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, sender = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            info = _parseSsdpReply(data, sender)
            if info and info["id"] not in found:
                found[info["id"]] = info
    finally:
        sock.close()
    return list(found.values())


def localIPv4():
    """This machine's address on the LAN (the interface the default route uses). Sends nothing."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _probe(ip, port, timeout):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            pass
    except OSError:
        return None
    try:
        # any HTTP answer (a Nanoleaf gives 401 or 403 without a token) confirms it is an API server
        _request("GET", "http://%s:%d/api/v1/" % (ip, port), timeout=1.5)
    except NanoleafError:
        return None
    return {"id": "", "name": "Nanoleaf", "model": "", "ip": ip, "port": port}


def scanHosts(hosts, port=API_PORT, timeout=0.6, workers=128):
    """Connect to port 16021 on each host. Unlike SSDP these are outgoing connections, so a
    firewall that drops replies to multicast searches (Windows does by default) does not block them."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(hosts)))) as pool:
        results = pool.map(lambda h: _probe(h, port, timeout), hosts)
        return [r for r in results if r]


def scanSubnet(port=API_PORT, timeout=0.6):
    """Probe every address in this machine's /24 for a Nanoleaf API port. Takes about 1-2 seconds."""
    ip = localIPv4()
    if not ip or ip.startswith("127."):
        return []
    base = ip.rsplit(".", 1)[0]
    return scanHosts([base + "." + str(i) for i in range(1, 255) if base + "." + str(i) != ip], port, timeout)


def discoverAll(timeout=3.0, scan=True):
    """SSDP discovery, plus a /24 address scan for controllers SSDP missed. Blocking."""
    found = discover(timeout)
    if scan:
        known = {d["ip"] for d in found}
        found += [d for d in scanSubnet() if d["ip"] not in known]
    return found


# ---------------------------------------------------------------------------
# Saved devices
# ---------------------------------------------------------------------------

def defaultSavedPath():
    return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "light_prefs", "nanoleaf.json")


def loadSaved(path=None):
    """The paired devices: a list of {id, name, model, ip, port, token, perPanel[, panels]}."""
    path = path or defaultSavedPath()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("id") and d.get("token")] if isinstance(data, list) else []


def saveSaved(devices, path=None):
    path = path or defaultSavedPath()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(devices, f, indent=2)
    os.replace(tmp, path)


def updateSaved(deviceId, path=None, **fields):
    """Change fields of one saved device in place. Returns False if it is not in the file."""
    devices = loadSaved(path)
    for d in devices:
        if d["id"] == deviceId:
            d.update(fields)
            saveSaved(devices, path)
            return True
    return False


def removeSaved(deviceId, path=None):
    """Take one paired device out of the saved file. Returns the removed entry, or None if it was not there."""
    devices = loadSaved(path)
    for i, d in enumerate(devices):
        if d["id"] == deviceId:
            del devices[i]
            saveSaved(devices, path)
            return d
    return None


def revokeToken(ip, port, token, timeout=3.0):
    """Ask the controller to forget a token (DELETE /api/v1/<token>). True if it did; False if it could not
    be reached or refused, which leaves the token on the device but does no harm."""
    try:
        status, _ = _request("DELETE", "http://%s:%d/api/v1/%s" % (ip, int(port), token), timeout=timeout)
    except NanoleafError:
        return False
    return status < 300


def addSaved(entry, path=None):
    """Add or replace (by id) one paired device. Keeps perPanel from an existing entry."""
    devices = loadSaved(path)
    for i, d in enumerate(devices):
        if d["id"] == entry["id"]:
            merged = dict(d)
            merged.update(entry)
            devices[i] = merged
            break
    else:
        devices.append(dict({"perPanel": False}, **entry))
    saveSaved(devices, path)
    return devices


def pairAndDescribe(ip, port=API_PORT, name=None, deviceId=None):
    """Pair, then read the device's name, model and serial. Returns a saved-device entry. Blocking."""
    token = pair(ip, port)
    status, info = _request("GET", "http://%s:%d/api/v1/%s/" % (ip, port, token))
    info = info if isinstance(info, dict) else {}
    # The serial number is the id whenever the device reports one, so pairing from discovery and
    # pairing by IP give the same address. The discovery id is only a fallback.
    return {"id": normaliseDeviceId(info.get("serialNo") or deviceId or ip),
            "name": name or info.get("name") or "Nanoleaf",
            "model": info.get("model", ""),
            "ip": ip, "port": port, "token": token, "perPanel": False}


def isAddress(address):
    """True for a Nanoleaf row address (NL:<id> or NL:<id>-P<panel>), any case."""
    return str(address).upper().startswith(ADDRESS_PREFIX)


def deviceIdFromAddress(address):
    """'NL:S123-P5001' -> 'S123'."""
    rest = str(address)[len(ADDRESS_PREFIX):].upper()
    return rest.split(PANEL_SEPARATOR, 1)[0]


def findMovedDevice(entry, hosts=None, port=None, timeout=0.6):
    """Look for a saved device that has a new IP address (DHCP). Blocking.

    Scans hosts (default: this machine's /24) for the API port, asks each hit for its
    info with the saved token, and returns (ip, port) for the one whose serial matches
    entry["id"], or None. A device that does not know the token answers 401 and is skipped.
    """
    port = int(port or entry.get("port", API_PORT))
    found = scanHosts(hosts, port, timeout) if hosts is not None else scanSubnet(port, timeout)
    for hit in found:
        try:
            status, info = _request("GET", "http://%s:%d/api/v1/%s/" % (hit["ip"], hit["port"], entry["token"]),
                                    timeout=2.0)
        except NanoleafError:
            continue
        if status == 200 and isinstance(info, dict) and normaliseDeviceId(info.get("serialNo", "")) == entry["id"]:
            return hit["ip"], hit["port"]
    return None


# ---------------------------------------------------------------------------
# Controller: one per physical device
# ---------------------------------------------------------------------------

def panelPoints(layout, orientation=0):
    """{panel id: (x, y)} for the light panels in a /panelLayout/layout body, as they sit on the wall: the
    canvas rotation set in the Nanoleaf app (/panelLayout/globalOrientation) applied clockwise (the convention
    LumenDesk checked against Nanoleaf's SDK), y upward. The layout's own x/y never include that rotation."""
    angle = math.radians(float(orientation or 0) % 360)
    c, s = math.cos(angle), math.sin(angle)
    points = {}
    for p in layout.get("positionData", []):
        if p.get("shapeType") in NON_LIGHT_SHAPE_TYPES or p.get("panelId", 0) == 0:
            continue
        x, y = float(p.get("x", 0)), float(p.get("y", 0))
        points[p["panelId"]] = (round(x * c + y * s, 2), round(-x * s + y * c, 2))
    return points


# How lights are laid out for Offset, Colour spread and the sound modes that give each light its own part.
# "Light order" goes by the light list; the rest place a Nanoleaf's panels by where they are on the wall.
PATTERNS = ("Light order", "Left to right", "Right to left", "Top to bottom", "Bottom to top",
            "Centre out", "Edges in", "Around", "Random")
LIGHT_ORDER = PATTERNS[0]


RANDOM = "Random"  # every light gets its own place at random, see the app's lightPlaces


def patternWraps(pattern):
    """True when a pattern goes round and comes back to its start (Around), so its last place is not 1."""
    return pattern in ("Around", RANDOM)


def patternPlaces(points, pattern):
    """{key: 0..1}, where each point (x, y with y upward) comes along a pattern: 0 the first, 1 the last.
    Points level with each other share a place, so a sweep moves as a straight edge and Centre out in rings.
    Around goes clockwise from straight up, round to just short of 1. Points all in one place are all 0."""
    if not points:
        return {}
    xs = [p[0] for p in points.values()]
    ys = [p[1] for p in points.values()]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    if pattern == "Around":
        out = {}
        for key, (x, y) in points.items():
            dx, dy = x - cx, y - cy
            out[key] = 0.0 if abs(dx) < 1e-6 and abs(dy) < 1e-6 else (math.atan2(dx, dy) / (2 * math.pi)) % 1.0
        return out
    value = {"Left to right": lambda x, y: x, "Right to left": lambda x, y: -x,
             "Top to bottom": lambda x, y: -y, "Bottom to top": lambda x, y: y,
             "Centre out": lambda x, y: math.hypot(x - cx, y - cy),
             "Edges in": lambda x, y: -math.hypot(x - cx, y - cy)}.get(pattern)
    if value is None:
        return {key: 0.0 for key in points}
    vals = {key: value(x, y) for key, (x, y) in points.items()}
    lo, hi = min(vals.values()), max(vals.values())
    if hi - lo < 1e-6:
        return {key: 0.0 for key in points}
    return {key: (v - lo) / (hi - lo) for key, v in vals.items()}


def orderPanels(layout, orientation=0):
    """Light panel ids from a /panelLayout/layout body, in reading order on the wall: column by column from
    left to right, top to bottom within a column.

    orientation is the canvas rotation set in the Nanoleaf app, applied as in panelPoints. Panels whose rotated
    x lies within a quarter of the smallest panel side of the previous one share a column, so a row of up and
    down triangles, or a jagged hexagon column, does not order by stray units of x."""
    panels = [p for p in layout.get("positionData", [])
              if p.get("shapeType") not in NON_LIGHT_SHAPE_TYPES and p.get("panelId", 0) != 0]
    if not panels:
        return []
    points = [(x, y, pid) for pid, (x, y) in panelPoints(layout, orientation).items()]
    sides = [SHAPE_SIDE.get(p.get("shapeType"), 0) for p in panels]
    sides = [v for v in sides if v > 0] or [layout.get("sideLength") or 100]
    tolerance = min(sides) * 0.25
    points.sort()
    ordered, column, lastX = [], [], None
    for x, y, pid in points:
        if lastX is not None and x - lastX > tolerance:
            ordered += sorted(column, key=lambda q: (-q[0], q[1]))
            column = []
        column.append((y, pid))
        lastX = x
    ordered += sorted(column, key=lambda q: (-q[0], q[1]))
    return [pid for _, pid in ordered]


def _loadPositions(saved):
    """{panel id: (x, y)} from the saved file's {"id": [x, y]}; anything malformed is left out."""
    out = {}
    if isinstance(saved, dict):
        for pid, xy in saved.items():
            try:
                out[int(pid)] = (float(xy[0]), float(xy[1]))
            except (TypeError, ValueError, IndexError):
                pass
    return out


class NanoleafController:
    """Shared by all rows of one device: HTTP, layout, power and the UDP stream."""

    def __init__(self, entry, savedPath=None):
        self.id = entry["id"]
        self.name = entry.get("name") or "Nanoleaf"
        self.model = entry.get("model", "")
        self.ip = entry["ip"]
        self.port = int(entry.get("port", API_PORT))
        self.token = entry["token"]
        self.perPanel = bool(entry.get("perPanel", False))
        self.panels = list(entry.get("panels", []))  # ordered light panel ids, cached from the layout
        self.positions = _loadPositions(entry.get("positions"))  # panel id -> (x, y) on the wall, cached too
        self.savedPath = savedPath
        self.relocateHosts = None  # hosts to search when the device moves; None = this machine's /24 (tests narrow it)
        self.relocateInterval = 60.0  # seconds between searches, so connect retries do not rescan every time
        self._lastRelocate = None
        self._relocating = None  # future while a search runs, shared by rows connecting at once
        self.transition = 0  # stream transition time, in 100 ms steps; 0 changes the panels at once
        self.streamPort = STREAM_PORT  # tests point this at the fake
        self.streamAfter = STREAM_AFTER  # tests change these
        self.streamIdle = STREAM_IDLE

        self._clients = set()
        self._layoutLoaded = False

        # Whole-device state, latest-wins, sent from a thread of its own: a PUT takes 70-600 ms on real
        # hardware, and a write that waited for it would hold every other light in the same frame.
        self._stateLock = threading.Condition()
        self._pendingState = None  # body waiting for the sender; later writes merge into it
        self._stateThread = None  # the sender, while it has something to do
        self._stateIdle = threading.Event()
        self._stateIdle.set()
        self._stateError = None  # a failed PUT, raised from the next write so the app still hears of it
        self.putTime = 0.25  # seconds a PUT /state takes, averaged
        self._lastWhole = None  # when the last whole-device colour came
        self._wholeBody = {}  # that colour as a PUT /state body, sent when the stream ends
        self._wantStream = False  # the sender should start the whole-device stream
        self.wholeStreaming = False  # whole-device colours go out over the stream
        self._finishWhole = False  # end the whole-device stream now, not after STREAM_IDLE
        self._noStreamUntil = 0.0

        # per-panel streaming
        self.streaming = False
        self._streamVersion = "v2"
        self._streamAddr = None
        self._sock = None
        self._entering = None  # future while entering stream mode
        self._saved = None  # (effect name, state) to restore when streaming ends
        self.panelColours = {}  # panelId -> (r, g, b) as last requested
        self.panelOn = {}  # panelId -> bool
        self._flushHandle = None
        self._inflight = 0

    # -- addresses -----------------------------------------------------------

    @property
    def address(self):
        return ADDRESS_PREFIX + self.id

    def panelAddress(self, panelId):
        return self.address + PANEL_SEPARATOR + str(panelId)

    def devices(self):
        """The rows for this device: one for the whole device, or one per panel in per-panel mode."""
        if self.perPanel and self.panels:
            return [NanoleafDevice(self, pid, n + 1) for n, pid in enumerate(self.panels)]
        return [NanoleafDevice(self)]

    # -- HTTP ----------------------------------------------------------------

    def _url(self, path):
        return "http://%s:%d/api/v1/%s%s" % (self.ip, self.port, self.token, path)

    async def http(self, method, path, body=None):
        return await asyncio.to_thread(_request, method, self._url(path), body)

    async def loadLayout(self):
        status, body = await self.http("GET", "/panelLayout")
        if status == 401 or status == 403:
            raise NanoleafError("The Nanoleaf rejected the saved token; pair it again.")
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("layout"), dict):
            raise NanoleafError("Could not read the panel layout (HTTP %s)" % status)
        orientation = body.get("globalOrientation", {})
        orientation = orientation.get("value", 0) if isinstance(orientation, dict) else 0
        panels = orderPanels(body["layout"], orientation)
        positions = panelPoints(body["layout"], orientation)
        changed = panels != self.panels or positions != self.positions
        self.panels = panels
        self.positions = positions
        self._layoutLoaded = True
        if changed and self.savedPath is not False:
            self._savePanels()
        return panels

    def _savePanels(self):
        try:
            updateSaved(self.id, self.savedPath, panels=self.panels,
                        positions={str(pid): list(xy) for pid, xy in self.positions.items()})
        except OSError:
            pass

    def update(self, entry):
        """Take new details from the saved file (after pairing again, or an IP fix)."""
        self.name = entry.get("name") or self.name
        self.model = entry.get("model", self.model)
        self.ip = entry["ip"]
        self.port = int(entry.get("port", API_PORT))
        self.token = entry["token"]

    # -- IP changes -------------------------------------------------------------

    async def relocate(self):
        """Search the network for this device at a new address. Returns True if it moved.

        Searches at most once per relocateInterval; rows connecting at the same time share one search."""
        if self._relocating is not None:
            return await asyncio.shield(self._relocating)
        now = time.monotonic()
        if self._lastRelocate is not None and now - self._lastRelocate < self.relocateInterval:
            return False
        self._lastRelocate = now
        self._relocating = asyncio.get_running_loop().create_future()
        moved = False
        try:
            entry = {"id": self.id, "token": self.token, "port": self.port}
            hit = await asyncio.to_thread(findMovedDevice, entry, self.relocateHosts)
            if hit and hit != (self.ip, self.port):
                self.ip, self.port = hit
                moved = True
                if self.savedPath is not False:
                    try:
                        updateSaved(self.id, self.savedPath, ip=self.ip, port=self.port)
                    except OSError:
                        pass
        finally:
            self._relocating.set_result(moved)
            self._relocating = None
        return moved

    # -- connection refcount --------------------------------------------------

    async def open(self, client):
        if not self._clients or not self._layoutLoaded:
            tried = (self.ip, self.port)
            try:
                await self.loadLayout()  # also checks the device is reachable and the token is good
            except NanoleafUnreachable:
                # DHCP may have given it a new address: find it by serial with the saved token.
                # Another row may have found it while this one was failing; then just retry.
                if (self.ip, self.port) == tried and not await self.relocate():
                    raise
                await self.loadLayout()
        self._clients.add(client)

    async def close(self, client):
        self._clients.discard(client)
        if not self._clients:
            with self._stateLock:
                self._finishWhole = True
                self._stateLock.notify_all()
            await self.settle()  # a last colour or power-off still goes out
            await self.stopStreaming()

    # -- whole device ---------------------------------------------------------

    @property
    def updateInterval(self):
        """Seconds between colour updates this device can show, for the sound engine."""
        if self.streaming:
            return max(STREAM_INTERVAL, self.transition * 0.1)
        return self.putTime

    async def putState(self, body):
        """PUT /state, latest-wins, without waiting for the device: the body merges into the one waiting to
        go and a sender thread sends it. Raises the failure of an earlier PUT, if one failed since."""
        with self._stateLock:
            if self.wholeStreaming:  # power while streaming: end the stream, then send it with the last colour
                self._wholeBody.update(body)
                self._finishWhole = True
                body = None
            elif any(k in body for k in ("hue", "sat", "ct")) and self.streaming:
                # a colour sent to the whole device ends the per-panel stream on the controller
                self._endStream(restore=False)
            if body:
                self._pendingState = dict(self._pendingState or {}, **body)
            error = self._wake()
        if error is not None:
            raise error

    def setWhole(self, body, rgb):
        """A whole-device colour: body for PUT /state, rgb for the stream. Never waits for the device.
        Raises the failure of an earlier PUT, if one failed since."""
        with self._stateLock:
            now = time.monotonic()
            quick = self._lastWhole is not None and now - self._lastWhole < self.streamAfter
            self._lastWhole = now
            self._wholeBody = dict(body)
            if self.streaming and not self.wholeStreaming:  # the panels are streaming already: join in
                self.wholeStreaming = True
                self._saved = None
            if self.wholeStreaming:
                for pid in self.panels:
                    self.panelColours[pid] = tuple(rgb)
                    self.panelOn[pid] = True
                self._sendFrame()
            else:
                if quick and self.panels and now >= self._noStreamUntil:
                    self._wantStream = True
                self._pendingState = dict(self._pendingState or {}, **body)
            error = self._wake()
        if error is not None:
            raise error

    def _wake(self):
        """Start the sender, or wake it. Called holding _stateLock; returns the error to raise, if any."""
        error, self._stateError = self._stateError, None
        if self._stateThread is None:
            self._stateIdle.clear()
            self._stateThread = threading.Thread(target=self._sender, name="nanoleafState", daemon=True)
            self._stateThread.start()
        else:
            self._stateLock.notify_all()
        return error

    def _sender(self):
        """Sends whole-device PUTs one at a time, newest only, and starts and ends the whole-device stream."""
        while True:
            with self._stateLock:
                while True:
                    if self._wantStream and not self.streaming:
                        self._wantStream = False
                        self._pendingState = None  # the stream carries the colour from here
                        action = "enter"
                        break
                    self._wantStream = False
                    if self._pendingState:
                        action, body, self._pendingState = "put", self._pendingState, None
                        break
                    if self.wholeStreaming:
                        idle = time.monotonic() - (self._lastWhole or 0.0)
                        if self._finishWhole or idle >= self.streamIdle:
                            self._endStream(restore=False)
                            self.wholeStreaming = False
                            action, body = "put", self._wholeBody  # also takes the device out of stream mode
                            break
                        self._stateLock.wait(self.streamIdle - idle)
                        continue
                    self._finishWhole = False
                    self._stateThread = None
                    self._stateIdle.set()
                    return
            if action == "enter":
                self._enterWholeStream()
                continue
            try:
                t = time.monotonic()
                status, _ = _request("PUT", self._url("/state"), body)
                self.putTime += (time.monotonic() - t - self.putTime) * 0.3
                if status >= 400:
                    raise NanoleafError("The Nanoleaf refused the state change (HTTP %s)" % status)
            except NanoleafError as e:
                with self._stateLock:
                    self._stateError = e

    def _enterWholeStream(self):
        try:
            self._startStreamingSync()
        except NanoleafError:
            with self._stateLock:
                self._noStreamUntil = time.monotonic() + STREAM_RETRY
                self._pendingState = dict(self._wholeBody)  # the colour the stream would have shown
            return
        with self._stateLock:
            self.wholeStreaming = True
            self._saved = None  # it ends on the last colour, not on what ran before
            # Writes that came while the stream started wait in _pendingState. Sending them now would put the device
            # back on a solid colour and out of stream mode; the stream carries the newest colour from _wholeBody, and
            # a power change ends the stream as it would have had it come a moment later (see putState).
            pending, self._pendingState = self._pendingState, None
            if pending and "on" in pending:
                self._wholeBody["on"] = pending["on"]
                self._finishWhole = True
            body = self._wholeBody
            if "ct" in body:
                rgb = cctToRGB(body["ct"]["value"], body.get("brightness", {}).get("value", 100))
            else:
                rgb = hsiToRGB(body.get("hue", {}).get("value", 0), body.get("sat", {}).get("value", 0),
                               body.get("brightness", {}).get("value", 100))
            for pid in self.panels:
                self.panelColours[pid] = rgb
                self.panelOn[pid] = True
            self._sendFrame()

    async def settle(self, timeout=10.0):
        """Wait until every whole-device state write has been sent."""
        if not self._stateIdle.is_set():
            await asyncio.to_thread(self._stateIdle.wait, timeout)

    async def getPower(self):
        await self.settle()  # a power change still on its way would otherwise read as the old state
        status, body = await self.http("GET", "/state/on")
        if status != 200 or not isinstance(body, dict):
            raise NanoleafError("Could not read the power state (HTTP %s)" % status)
        return bool(body.get("value"))

    # -- per panel --------------------------------------------------------------

    async def setPanel(self, panelId, rgb=None, on=None):
        """Set a panel's colour and/or power. Writes in the same event-loop turn go out as one datagram."""
        if rgb is not None:
            self.panelColours[panelId] = tuple(rgb)
            if on is None:
                on = True
        if on is not None:
            self.panelOn[panelId] = on
        # Count writes still in progress so a frame goes out only once all of them have landed:
        # writes waiting for stream mode to start resume a loop turn or two later than the first.
        self._inflight += 1
        try:
            await self._ensureStreaming()
        finally:
            self._inflight -= 1
            if self.streaming:
                self._scheduleFlush()

    def _scheduleFlush(self):
        if self._flushHandle is None and self._inflight == 0:
            self._flushHandle = asyncio.get_running_loop().call_soon(self._flush)

    def frameColours(self):
        out = []
        for pid in self.panels or sorted(self.panelColours):
            if pid not in self.panelColours and pid not in self.panelOn:
                continue
            rgb = self.panelColours.get(pid, (255, 255, 255)) if self.panelOn.get(pid, True) else (0, 0, 0)
            out.append((pid, rgb))
        return out

    def _flush(self):
        self._flushHandle = None
        self._sendFrame()

    def _sendFrame(self):
        if not self.streaming or self._sock is None:
            return
        colours = self.frameColours()
        if not colours:
            return
        encode = encodeFrameV2 if self._streamVersion == "v2" else encodeFrameV1
        try:
            self._sock.sendto(encode(colours, self.transition), self._streamAddr)
        except OSError:
            pass  # a dropped frame; the next one carries every panel again

    async def _ensureStreaming(self):
        if self.streaming:
            return
        if self._entering is None:
            self._entering = asyncio.get_running_loop().create_future()
            try:
                await self._startStreaming()
                self._entering.set_result(True)
            except Exception as e:
                self._entering.set_exception(e)
                self._entering.exception()  # mark retrieved; waiters re-raise it
                raise
            finally:
                self._entering = None
        else:
            await asyncio.shield(self._entering)

    async def checkStream(self, resume=True):
        """Notice the device leaving stream mode behind our back: a tap or swipe on the panels, or the Nanoleaf
        app, picks another effect and the frames we send are then ignored. Marks the stream ended and, with resume,
        enters stream mode again and resends every panel's colour (keeping what to put back when we finish).
        Returns True if the stream had been lost."""
        if not self.streaming or self._entering is not None:
            return False
        status, effect = await self.http("GET", "/effects/select")
        if status != 200 or not isinstance(effect, str) or effect == STREAM_EFFECT:
            return False
        with self._stateLock:
            whole = self.wholeStreaming
            # Taking it back keeps _saved, so stopping still puts back the effect from before. Otherwise the effect
            # just picked is the one to keep: the next stream saves (and later puts back) that one instead.
            self._endStream(restore=resume)
            self.wholeStreaming = False
            self._stateLock.notify_all()
        if resume and not whole:
            await self._ensureStreaming()
            self._sendFrame()
        return True

    async def _startStreaming(self):
        await asyncio.to_thread(self._startStreamingSync)

    def _startStreamingSync(self):
        def http(method, path, body=None):
            return _request(method, self._url(path), body)

        if self._saved is None:
            status, effect = http("GET", "/effects/select")
            status2, state = http("GET", "/state")
            self._saved = (effect if isinstance(effect, str) else None,
                           state if isinstance(state, dict) else {})
        # stream colours are scaled by the global brightness, so stream at full brightness
        http("PUT", "/state", {"on": {"value": True}, "brightness": {"value": 100, "duration": 0}})
        status, body = http("PUT", "/effects", {"write": {
            "command": "display", "animType": "extControl", "extControlVersion": "v2"}})
        if status < 300:
            self._streamVersion = "v2"
            self._streamAddr = (self.ip, self.streamPort)
        else:
            status, body = http("PUT", "/effects", {"write": {
                "command": "display", "animType": "extControl"}})
            if status >= 300 or not isinstance(body, dict):
                raise NanoleafError("The Nanoleaf would not enter streaming mode (HTTP %s)" % status)
            self._streamVersion = "v1"
            self._streamAddr = (body.get("streamControlIpAddr", self.ip), int(body.get("streamControlPort", self.streamPort)))
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.streaming = True

    def _endStream(self, restore):
        self.streaming = False
        if self._flushHandle is not None:
            self._flushHandle.cancel()
            self._flushHandle = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        if not restore:
            self._saved = None

    async def stopStreaming(self):
        """Leave stream mode and put back the effect and brightness from before it started."""
        wasStreaming = self.streaming
        self._endStream(restore=True)
        saved, self._saved = self._saved, None
        if not wasStreaming or saved is None:
            return
        effect, state = saved
        body = {}
        if effect and not effect.startswith("*"):
            await self.http("PUT", "/effects", {"select": effect})
        else:
            # *Solid* / *Static* / *Dynamic* cannot be re-selected by name; put the colour back instead
            if state.get("colorMode") == "ct" and "ct" in state:
                body["ct"] = {"value": state["ct"].get("value")}
            elif "hue" in state:
                body["hue"] = {"value": state["hue"].get("value")}
                body["sat"] = {"value": state.get("sat", {}).get("value", 100)}
        if "brightness" in state:
            body["brightness"] = {"value": state["brightness"].get("value"), "duration": 0}
        if "on" in state:
            body["on"] = {"value": bool(state["on"].get("value"))}
        if body:
            await self.http("PUT", "/state", body)


# ---------------------------------------------------------------------------
# Bleak stand-ins
# ---------------------------------------------------------------------------

class NanoleafDevice:
    """Stands in for a BLEDevice in availableLights[i][0]."""

    def __init__(self, controller, panelId=None, panelNumber=None):
        self.controller = controller
        self.panelId = panelId
        self.panelNumber = panelNumber

    @property
    def name(self):
        if self.panelId is None:
            return self.controller.name
        return "%s panel %d" % (self.controller.name, self.panelNumber or 0)

    @property
    def address(self):
        if self.panelId is None:
            return self.controller.address
        return self.controller.panelAddress(self.panelId)

    @property
    def ip(self):
        return self.controller.ip

    @property
    def token(self):
        return self.controller.token

    @property
    def position(self):
        """This panel's (x, y) on the wall, y upward, or None for the whole device or an unknown layout."""
        if self.panelId is None:
            return None
        return self.controller.positions.get(self.panelId)

    def __repr__(self):
        return "NanoleafDevice(%s, %s)" % (self.address, self.name)


class NanoleafClient:
    """Stands in for a BleakClient in availableLights[i][1]."""

    def __init__(self, device, *args, **kwargs):
        self.device = device
        self.controller = device.controller
        self.address = device.address
        self._connected = False
        self._notify = None

    @property
    def is_connected(self):
        return self._connected

    @property
    def updateInterval(self):
        """Seconds between colour updates the device can show (read by the sound engine)."""
        return self.controller.updateInterval

    async def connect(self, **kwargs):
        await self.controller.open(self)
        self._connected = True
        return True

    async def disconnect(self):
        if self._connected:
            self._connected = False
            await self.controller.close(self)
        return True

    async def start_notify(self, uuid, callback, **kwargs):
        self._notify = (uuid, callback)

    async def stop_notify(self, uuid):
        self._notify = None

    def _reply(self, payload):
        if self._notify is not None:
            uuid, callback = self._notify
            callback(uuid, payload)

    async def write_gatt_char(self, uuid, data, response=False):
        if not self._connected:
            raise NanoleafError("Not connected to " + self.address)
        command = decodeCommand(data)
        kind = command[0]

        if kind == "query_power":
            pid = self.device.panelId
            if pid is not None and pid in self.controller.panelOn:
                on = self.controller.panelOn[pid]
            elif pid is None and self.controller.wholeStreaming:
                on = True
            else:
                on = await self.controller.getPower()
            self._reply(powerReply(on))
            return
        if kind == "query_channel":
            self._reply(CHANNEL_REPLY)
            return

        if self.device.panelId is None:
            body = stateBodyFor(command)
            if kind == "hsi":
                self.controller.setWhole(body, hsiToRGB(command[1], command[2], command[3]))
            elif kind == "cct":
                self.controller.setWhole(body, cctToRGB(command[1], command[2]))
            elif body is not None:
                await self.controller.putState(body)
            return

        pid = self.device.panelId
        if kind == "power":
            await self.controller.setPanel(pid, on=command[1])
        elif kind == "hsi":
            await self.controller.setPanel(pid, rgb=hsiToRGB(command[1], command[2], command[3]))
        elif kind == "cct":
            await self.controller.setPanel(pid, rgb=cctToRGB(command[1], command[2]))
        # brightness-only, temp-only and scenes are not sent to panels: the app only splits
        # commands for CCT-only lights, which a Nanoleaf never is.
