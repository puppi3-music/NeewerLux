"""A fake Nanoleaf panel controller for tests and for trying the app without hardware.

Implements the parts of the Open API that puppi3s_neewerlux_nanoleaf uses: pairing, /state,
/panelLayout, /effects, and a UDP listener that decodes extControl v2 frames.
Standard library only. Run from the repo root:

    uv run python tests/fake_nanoleaf.py                       # HTTP 16021, UDP 60222 on 127.0.0.1
    uv run python tests/fake_nanoleaf.py --port 16100 --held   # start with the power button "held"

While it runs, type `pair` and Enter to toggle the "power button held" state (pairing only
succeeds while it is held), `state` to print the state, `quit` to stop. Every request and
every decoded UDP frame is printed.
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from puppi3s_neewerlux_nanoleaf import decodeFrameV2  # noqa: E402

TOKEN = "fakeToken0123456789abcdef"

# A small Shapes set: the controller (12), a power connector (20) and four hexagons (7),
# listed out of left-to-right order on purpose.
DEFAULT_LAYOUT = {
    "numPanels": 6,
    "sideLength": 67,
    "positionData": [
        {"panelId": 0, "x": 0, "y": 0, "o": 0, "shapeType": 12},
        {"panelId": 5001, "x": 300, "y": 58, "o": 0, "shapeType": 7},
        {"panelId": 5002, "x": 100, "y": 58, "o": 0, "shapeType": 7},
        {"panelId": 6000, "x": 50, "y": 0, "o": 0, "shapeType": 20},
        {"panelId": 5003, "x": 200, "y": 116, "o": 0, "shapeType": 7},
        {"panelId": 5004, "x": 200, "y": 0, "o": 0, "shapeType": 7},
    ],
}


class FakeNanoleaf:
    def __init__(self, host="127.0.0.1", port=16021, streamPort=60222, buttonHeld=False, verbose=False,
                 supportsV2=True):
        self.host = host
        self.buttonHeld = buttonHeld
        self.verbose = verbose
        self.supportsV2 = supportsV2
        self.layout = json.loads(json.dumps(DEFAULT_LAYOUT))
        self.orientation = 0  # globalOrientation, the canvas rotation set in the Nanoleaf app
        self.state = {
            "on": {"value": True},
            "brightness": {"value": 60, "max": 100, "min": 0},
            "hue": {"value": 30, "max": 360, "min": 0},
            "sat": {"value": 80, "max": 100, "min": 0},
            "ct": {"value": 4000, "max": 6500, "min": 1200},
            "colorMode": "effect",
        }
        self.effect = "Northern Lights"
        self.stateDelay = 0.0  # seconds each PUT /state takes, like real hardware (70-600 ms)
        self.refuseState = False  # answer PUT /state with HTTP 400
        self.requests = []  # (method, path, body)
        self.frames = []  # decoded UDP frames: list of (panelId, (r, g, b), transition)
        self.lock = threading.Lock()
        self.frameEvent = threading.Condition(self.lock)

        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body=None):
                raw = b"" if body is None else json.dumps(body).encode("utf-8")
                self.send_response(status)
                if raw:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                if raw:
                    self.wfile.write(raw)

            def _handle(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                body = None
                if length:
                    try:
                        body = json.loads(self.rfile.read(length).decode("utf-8"))
                    except ValueError:
                        return self._send(400)
                if method == "PUT" and self.path.endswith("/state"):
                    if fake.stateDelay:
                        time.sleep(fake.stateDelay)
                    if fake.refuseState:
                        return self._send(400)
                status, reply = fake.route(method, self.path, body)
                self._send(status, reply)

            def do_GET(self):
                self._handle("GET")

            def do_PUT(self):
                self._handle("PUT")

            def do_POST(self):
                self._handle("POST")

        self.http = ThreadingHTTPServer((host, port), Handler)
        self.port = self.http.server_address[1]
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind((host, streamPort))
        self.udp.settimeout(0.2)
        self.streamPort = self.udp.getsockname()[1]
        self._running = False

    # -- lifecycle --------------------------------------------------------------

    def start(self):
        self._running = True
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        threading.Thread(target=self._udpLoop, daemon=True).start()
        return self

    def stop(self):
        self._running = False
        self.http.shutdown()
        self.http.server_close()
        self.udp.close()

    def _udpLoop(self):
        while self._running:
            try:
                data, _ = self.udp.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                frame = decodeFrameV2(data)
            except Exception:
                frame = [("bad frame", data.hex(), 0)]
            with self.lock:
                if self.effect != "*ExtControl*":  # like the real thing, it ignores frames outside stream mode
                    continue
                self.frames.append(frame)
                self.frameEvent.notify_all()
            if self.verbose:
                print("UDP  " + "  ".join("%s=#%02x%02x%02x" % (pid, *rgb) for pid, rgb, _ in frame))

    def waitForFrames(self, count, timeout=2.0):
        with self.lock:
            self.frameEvent.wait_for(lambda: len(self.frames) >= count, timeout)
            return list(self.frames)

    # -- API ----------------------------------------------------------------------

    def route(self, method, path, body):
        with self.lock:
            self.requests.append((method, path, body))
        if self.verbose:
            print("HTTP %s %s %s" % (method, path, "" if body is None else json.dumps(body)))

        if method == "POST" and path.rstrip("/") == "/api/v1/new":
            if not self.buttonHeld:
                return 403, None
            return 200, {"auth_token": TOKEN}

        prefix = "/api/v1/" + TOKEN
        if not path.startswith("/api/v1/"):
            return 404, None
        if not (path == prefix or path.startswith(prefix + "/")):
            return 401, None
        sub = path[len(prefix):].rstrip("/")

        with self.lock:
            if method == "GET" and sub == "":
                return 200, {"name": "Fake Shapes", "serialNo": "S12345", "model": "NL42",
                             "firmwareVersion": "9.9.9", "state": self.state,
                             "effects": {"select": self.effect},
                             "panelLayout": self._panelLayout()}
            if method == "GET" and sub == "/state":
                return 200, self.state
            if method == "GET" and sub.startswith("/state/"):
                key = sub[len("/state/"):]
                if key in self.state:
                    return 200, self.state[key]
                return 404, None
            if method == "PUT" and sub == "/state":
                for key, val in (body or {}).items():
                    if key in ("on", "brightness", "hue", "sat", "ct") and isinstance(val, dict):
                        self.state[key]["value"] = val.get("value")
                if any(k in (body or {}) for k in ("hue", "sat")):
                    self.state["colorMode"] = "hs"
                    self.effect = "*Solid*"
                if "ct" in (body or {}):
                    self.state["colorMode"] = "ct"
                    self.effect = "*Solid*"
                return 204, None
            if method == "GET" and sub == "/panelLayout":
                return 200, self._panelLayout()
            if method == "GET" and sub == "/panelLayout/layout":
                return 200, self.layout
            if method == "GET" and sub == "/effects/select":
                return 200, self.effect
            if method == "PUT" and sub == "/effects":
                body = body or {}
                if "select" in body:
                    self.effect = body["select"]
                    self.state["colorMode"] = "effect"
                    return 204, None
                write = body.get("write", {})
                if write.get("animType") == "extControl":
                    if write.get("extControlVersion") == "v2":
                        if not self.supportsV2:
                            return 400, None
                        self.effect = "*ExtControl*"
                        return 204, None
                    self.effect = "*ExtControl*"
                    return 200, {"streamControlIpAddr": self.host, "streamControlPort": self.streamPort,
                                 "streamControlProtocol": "udp"}
                return 400, None
        return 404, None

    def _panelLayout(self):
        return {"globalOrientation": {"value": self.orientation, "max": 360, "min": 0}, "layout": self.layout}

    def lastStatePut(self):
        with self.lock:
            puts = [b for m, p, b in self.requests if m == "PUT" and p.endswith("/state")]
        return puts[-1] if puts else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=16021)
    parser.add_argument("--stream-port", type=int, default=60222)
    parser.add_argument("--held", action="store_true", help="start with the power button held (pairing allowed)")
    args = parser.parse_args()

    fake = FakeNanoleaf(args.host, args.port, args.stream_port, args.held, verbose=True).start()
    print("Fake Nanoleaf on http://%s:%d, UDP %d. Button held: %s. Commands: pair, state, quit"
          % (args.host, fake.port, fake.streamPort, fake.buttonHeld))
    try:
        for line in sys.stdin:
            cmd = line.strip().lower()
            if cmd == "pair":
                fake.buttonHeld = not fake.buttonHeld
                print("Button held: %s" % fake.buttonHeld)
            elif cmd == "state":
                print(json.dumps({"effect": fake.effect, "state": fake.state}, indent=2))
            elif cmd in ("quit", "exit", "q"):
                break
    except KeyboardInterrupt:
        pass
    fake.stop()


if __name__ == "__main__":
    main()
