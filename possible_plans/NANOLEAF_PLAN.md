# Nanoleaf panel support for NeewerLux

## Context

NeewerLux only drives Neewer lights over Bluetooth. The goal is to control Nanoleaf panel sets (Shapes, Canvas, Lines, Elements, Light Panels) from the same light table, presets, animations, sound-reactive engine, HTTP API and web UI.

Decisions already made:
- Target the panel controllers' local Open API (HTTP on port 16021, UDP streaming on 60222). Essentials bulbs and strips are out of scope.
- A Nanoleaf appears as **one light** by default. A per-device preference expands it into **one row per panel**.
- The Rust rewrite plan is updated later, after this ships. It is not part of this work.
- Development hardware: a Nanoleaf Shapes set. Shapes support extControl v2 streaming. Their layout includes the controller and connector pieces as shape types, so those must be filtered out of the panel list. Confirm the shape type ids against `GET /panelLayout/layout` on the real set.

## Approach: Nanoleaf objects that stand in for Bleak objects

Every send path in [NeewerLux.py](NeewerLux.py) calls `availableLights[i][1].write_gatt_char(...)` directly (about 15 sites), and 58 places read `availableLights[i][0].name` / `.address`. Rather than refactor all of them, the new module provides two classes with the same surface as the Bleak objects, so an `availableLights` entry for a Nanoleaf has the usual ten fields and the rest of the app does not need to know.

| Slot | Neewer | Nanoleaf stand-in |
|---|---|---|
| `[0]` | `BLEDevice` (`.name`, `.address`) | `NanoleafDevice` (`.name`, `.address`, plus ip, token, panelId) |
| `[1]` | `BleakClient` | `NanoleafClient` with `is_connected`, `connect()`, `disconnect()`, `write_gatt_char()`, `start_notify()`, `stop_notify()` |
| `[5]` | CCT-only flag | always `False` |
| `[9]` | RSSI | `"LAN"` |

`write_gatt_char` decodes the Neewer byte string it is given:

| Bytes | Meaning | Whole-device action | Per-panel action |
|---|---|---|---|
| `[120,129,1,1/2,..]` | power on/off | `PUT /state {"on":{"value":..}}` | restore last colour / send black |
| `[120,134,..]` | HSI | `PUT /state` hue, sat, brightness (`duration: 0`) in one request | HSV to RGB, queue for the UDP frame |
| `[120,135,..]` | CCT | `PUT /state` ct (value × 100, clamped 1200–6500) + brightness | Kelvin to RGB, queue |
| `[120,136,..]` | Neewer scene | ignored | ignored |
| `[120,133,0,253]` / `[120,132,0,252]` | power / channel query | answer through the notify callback from `GET /state/on`; channel stays `---` | same, from the controller |

Addresses: `NL:<id>` for the controller and `NL:<id>-P<panelId>` for a panel, where `<id>` is the device's serial number (`serialNo` from `GET /api/v1/<token>/`) with separators stripped and upper-cased. The serial is used rather than the discovery id so that pairing from discovery and pairing by IP give the same address; the discovery id is only a fallback. They work unchanged as prefs sidecar filenames, alias targets, snapshot preset keys and `--light` values. **Phase 2 task (decided):** `parseBatchString` ([NeewerLux.py:5969](NeewerLux.py#L5969)) splits on `:`, so a batch segment `NL:S12345:HSI:...` reads the light as `NL`. Teach it the `NL:` prefix (rejoin `parts[0:2]` as the light id when `parts[0]` is `NL`); the address format stays as it is. Light indexes are unaffected.

No new dependencies: HTTP with `urllib` run through `asyncio.to_thread`, discovery and streaming with `socket`.

## Phase 1: `neewerlux_nanoleaf.py` and its tests (no app changes) — DONE, not yet run on hardware

Status: implemented on branch `nanoleaf-support`, 24 tests passing, not yet committed.

Hardware check (2026-11-16, `tests/nanoleaf_hw_check.py` against "Shapes AC58", model NL42, firmware not recorded, two triangles plus controller): pairing, whole-device HSI and CCT, the power query, per-panel streaming over extControl v2, left-to-right order and restoring the previous effect all worked. Layout confirmed: Shapes triangles are shapeType 8; the controller is shapeType 12 at panelId 0 and is skipped. This set has no connector or power-connector pieces, so types 16, 19 and 20 are still unconfirmed. 21.5 fps is the script's own pacing (`asyncio.sleep(1/30)` on Windows timer granularity), not a device limit; a real ceiling still needs measuring under sound-reactive in Phase 3. `--discover` found the controller at 10.0.0.152 (whether by SSDP or the address scan was not recorded).

What was built, and where it differs from the original outline below:
- `neewerlux_nanoleaf.py` as outlined. Additions:
  - `decodeCommand()` also handles the split brightness-only (`130`) and temp-only (`131`) commands; whole-device rows send them as `/state` changes, panel rows ignore them (Nanoleaf rows are never CCT-only, so the app never splits for them).
  - Channel query answers at once with a one-byte payload, so the app shows `---` without waiting for retries to time out.
  - Whole-device `/state` writes are latest-wins: while one PUT is in flight, later bodies merge into the next one, so animations do not queue behind slow HTTP.
  - A colour sent to a panel turns that panel on (the parallel write path never sends "on" first).
  - Entering streaming sets brightness to 100 and turns the device on (stream colours are scaled by global brightness). Restore re-selects the saved effect by name; for `*Solid*`-style effects that cannot be re-selected it puts back the saved hue/sat or ct instead. Brightness and on/off are always restored.
  - Falls back to extControl v1 (port from the PUT response, v1 frame format) when the controller refuses v2.
  - Frames go out when the last in-flight panel write finishes, not on a plain `call_soon`: writes waiting for stream mode to start resume a loop turn or two later, and a plain `call_soon` split one frame into two datagrams.
  - Every frame carries every panel that has a colour, so a dropped datagram does not leave a panel stale.
  - `nanoleaf.json` entries also store `panels`, the ordered panel ids from the last layout read, so per-panel rows can be listed at startup while the device is offline. No `.gitignore` change was needed: `light_prefs/*` already covers it.
  - `setKelvinConverter(fn)` registers `convert_K_to_RGB`; a coarse built-in table is used until then.
  - Panels are ordered by x, then top to bottom (higher y first) at equal x.
  - Non-light shape types filtered: 1 (Rhythm), 12 (Shapes controller), 16 (Lines connector), 19 (controller cap), 20 (power connector), plus panel id 0. From the Open API docs; still to confirm on the Shapes set.
- Discovery: Windows Firewall (on by default) drops SSDP replies, because they come from the device's address rather than the multicast address the search went to. `discoverAll()` therefore runs SSDP and then a /24 scan (`scanSubnet` / `scanHosts`: TCP connect to 16021 plus one HTTP request, ~1–2 s, outgoing only so the firewall allows it). Scan results have no name or id until paired; the id comes from `serialNo` at pairing anyway. The Phase 2 dialog should call `discoverAll()`.
- `tests/fake_nanoleaf.py` as outlined; runnable by hand (`pair` toggles the button state, `state` prints it).
- `tests/test_nanoleaf.py` as outlined, plus tests for v1 fallback, restoring a `*Solid*` colour, a whole-device colour ending the stream and re-entering it, and the latest-wins merging.
- New `tests/nanoleaf_hw_check.py`: the hardware check from verification step 8 (discover, pair or reuse the saved token, print the raw layout with shape types, whole-device colours, panels one at a time left to right, rainbow with frame rate, restore). Saves to the repo's `light_prefs/nanoleaf.json`.

Original outline:

New file `neewerlux_nanoleaf.py`:
- `discover(timeout)`: SSDP M-SEARCH for the Nanoleaf service types, returning name, device id, ip and port from the `Location`, `nl-devicename` and `nl-deviceid` headers.
- `pair(ip, port)`: `POST /api/v1/new`; returns the token, or a clear "not in pairing mode" error on 403.
- `loadSaved()` / `saveSaved()`: `light_prefs/nanoleaf.json`, a list of `{id, name, model, ip, port, token, perPanel}`. Add this file to `.gitignore` because it holds tokens.
- `NanoleafController`: one per physical device, shared by its rows. Holds the HTTP helper, panel layout (`GET /panelLayout/layout`, skipping controller and connector shape types, ordered left to right), streaming state and the UDP socket.
- `NanoleafDevice` and `NanoleafClient` as in the table above.
- Streaming: on the first per-panel write, save the current effect and brightness, then `PUT /effects` with `extControl` v2. Panel writes mark the panel dirty; one coalesced flush per event-loop turn sends a single datagram (panel count, then id, R, G, B, W, transition per panel), so `parallelWriteToLights` produces one packet per frame. On disconnect, restore the saved effect and brightness.
- Kelvin to RGB: reuse `convert_K_to_RGB` ([NeewerLux.py:4085](NeewerLux.py#L4085)) by passing it in when the main script registers devices; HSV to RGB with `colorsys`.

New `tests/fake_nanoleaf.py`: a stdlib fake controller (pairing with a toggleable "button held" state, `/state`, `/panelLayout/layout`, `/effects`, a UDP listener that logs decoded frames). The port is configurable so it runs on 127.0.0.1.

New `tests/test_nanoleaf.py` (`unittest`): byte-string decoding for each mode, CCT clamping, UDP packet encoding, coalescing of several panel writes into one datagram, and a round trip against the fake.

## Phase 2: whole-device integration in `NeewerLux.py`

- `findDevices()` ([4757](NeewerLux.py#L4757)): after the BLE scan, add an entry for every saved Nanoleaf that is not already listed, using `getCustomLightPrefs` as the Neewer path does. Wrap the BLE scan so a machine without Bluetooth still gets its Nanoleaf rows. The "found again, clear `[1]`" branch stays BLE-only.
- `connectToLight()` ([4946](NeewerLux.py#L4946)): replace the two `BleakClient(...)` constructions with a small `makeClient(device)` that returns the Nanoleaf client for a `NanoleafDevice`. The retry loop and table updates work as they are.
- `connectToOneLight()` ([5262](NeewerLux.py#L5262)): for an `NL:` address, build the entry from the saved list in place of `BleakScanner.find_device_by_address`.
- `getLightSpecs()` ([4893](NeewerLux.py#L4893)): add a Nanoleaf entry with range 1200–6500 K, not CCT-only.
- Table label: the `"[ʀssɪ: … dBm]"` suffix is built inline in about ten places ([3087-3100](NeewerLux.py#L3087-L3100), [2200-2203](NeewerLux.py#L2200-L2203)). Move it into one helper next to `_get_light_rssi` ([4564](NeewerLux.py#L4564)) that returns `[LAN]` for Nanoleaf rows.
- Status bar strings that say "Neewer lights" become "lights".
- Pairing UI: an "Add Nanoleaf…" button beside Scan in [neewerlux_ui.py:1211](neewerlux_ui.py#L1211). The dialog lists discovered devices, has a manual `ip[:port]` field, tells the user to hold the power button for 5–7 seconds, then pairs, saves and triggers a discover. Network calls run off the GUI thread and report back through the existing `runOnGui` ([4280](NeewerLux.py#L4280)).
- Headless pairing: a `--nanoleaf_pair <ip[:port]>` CLI argument beside the others at [5596](NeewerLux.py#L5596), for `--http` and `--cli` installs.

Nothing changes in the worker thread, `writeToLight`, `parallelWriteToLights`, the animation engine, the sound engine, presets, the HTTP server or the web UI.

## Phase 3: per-panel mode

- Light Preferences tab ([neewerlux_ui.py:1561](neewerlux_ui.py#L1561), `setupLightPrefsTab` at [2111](NeewerLux.py#L2111), `checkLightPrefs` at [2174](NeewerLux.py#L2174)): add a "Show each panel as its own light" checkbox, shown only for Nanoleaf rows, and hide the CCT-only checkbox for them.
- Toggling it stops any running animation and sound-reactive session, disconnects the device, updates `perPanel` in `nanoleaf.json`, replaces that device's rows in `availableLights` (one controller row, or one row per panel named `<device> panel N`), then emits `_lightsChangedSignal` and reconnects.
- Each panel row gets its own sidecar prefs file through the existing code, so custom names and preferred IDs work per panel.
- All rows of one device share a `NanoleafController`; connecting any row connects it, and it disconnects when the last row does.

## Phase 4: docs and packaging

- [README.md](README.md): Nanoleaf section covering pairing, per-panel mode and the limits below.
- [CHANGELOG.md](CHANGELOG.md) entry; update the description and keywords in [pyproject.toml](pyproject.toml).
- [NeewerLux.spec](NeewerLux.spec): confirm the new module is bundled in the Windows build.

## Known limits (documented, not solved here)

- Neewer scene mode does nothing on Nanoleaf rows. Mapping it to Nanoleaf's own effects is a possible follow-up.
- No channel readout and no RSSI for Nanoleaf rows.
- If SSDP discovery proves unreliable on real firmware, manual IP entry still works; mDNS via an optional `zeroconf` dependency is the fallback.
- A whole-device command sent while a device is streaming per panel ends the stream; the client tracks this and re-enters streaming on the next panel write.

## Before starting

Done: work is on branch `nanoleaf-support`, made from `rust-rewrite-plan` with a clean tree.

## Verification

1. `uv run python -m unittest tests.test_nanoleaf` passes.
2. Start `tests/fake_nanoleaf.py`, run `uv run NeewerLux.py`, add `127.0.0.1:<port>` through "Add Nanoleaf…": pairing fails until the fake's button state is set, then succeeds and the row links.
3. Whole-device: CCT and HSI sliders, on/off, a preset, an animation and sound-reactive each produce the expected `/state` requests in the fake's log; the table shows `LINKED ON` / `STBY`.
4. Per-panel: enable the checkbox, confirm one row per panel, run "Rainbow Chase" and sound-reactive, and confirm the fake logs one UDP datagram per frame with distinct panel colours. Disable it and confirm the effect is restored and a single row returns.
5. Mixed: a Neewer light and the fake in one animation, with no stutter on the Neewer side.
6. Headless: `--nanoleaf_pair`, then `--http`, then drive the device through the HTTP API and the web UI.
7. Restart the app: the saved device reappears without pairing, with its custom name and preferred ID.
8. On the Shapes set: discovery, pairing, colour accuracy for HSI and CCT, per-panel left-to-right order, controller and connector pieces excluded from the rows, and frame rate during sound-reactive. Do this after Phase 1 too, with `tests/nanoleaf_hw_check.py` (`--discover`, then `<ip>`), so protocol surprises show up before the app integration.
