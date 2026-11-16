# Nanoleaf panel support for NeewerLux

## Context

NeewerLux only drives Neewer lights over Bluetooth. The goal is to control Nanoleaf panel sets (Shapes, Canvas, Lines, Elements, Light Panels) from the same light table, presets, animations, sound-reactive engine, HTTP API and web UI.

Decisions already made:
- Target the panel controllers' local Open API (HTTP on port 16021, UDP streaming on 60222). Essentials bulbs and strips are out of scope.
- A Nanoleaf appears as **one light** by default. A per-device preference expands it into **one row per panel**.
- The Rust rewrite plan is updated later, after this ships. It is not part of this work.
- Development hardware: a Nanoleaf Shapes set ("Shapes AC58", model NL42, two triangles plus controller, at 10.0.0.152). It must be on Wi-Fi: a set added only over Thread/Matter has no local API.
- Batch strings learn the `NL:` prefix; the address format stays as it is (see Addresses).
- Work happens on branch `nanoleaf-support`, made from `rust-rewrite-plan`.

## Status

| Phase | State |
|---|---|
| 1. Module, fake controller, tests | Done, committed as `af1ae59`, verified on the Shapes set |
| 2. Whole-device integration | Next |
| 3. Per-panel mode | Not started |
| 4. Docs and packaging | Not started |

## Approach: Nanoleaf objects that stand in for Bleak objects

Every send path in [NeewerLux.py](NeewerLux.py) calls `availableLights[i][1].write_gatt_char(...)` directly (about 15 sites), and 58 places read `availableLights[i][0].name` / `.address`. Rather than refactor all of them, [neewerlux_nanoleaf.py](neewerlux_nanoleaf.py) provides two classes with the same surface as the Bleak objects, so an `availableLights` entry for a Nanoleaf has the usual ten fields and the rest of the app does not need to know.

| Slot | Neewer | Nanoleaf stand-in |
|---|---|---|
| `[0]` | `BLEDevice` (`.name`, `.address`) | `NanoleafDevice` (`.name`, `.address`, `.ip`, `.token`, `.panelId`, `.controller`) |
| `[1]` | `BleakClient` | `NanoleafClient(device)` with `is_connected`, `connect()`, `disconnect()`, `write_gatt_char()`, `start_notify()`, `stop_notify()` |
| `[5]` | CCT-only flag | always `False` |
| `[9]` | RSSI | `"LAN"` |

`write_gatt_char` decodes the Neewer byte string it is given:

| Bytes | Meaning | Whole-device action | Per-panel action |
|---|---|---|---|
| `[120,129,1,1/2,..]` | power on/off | `PUT /state {"on":{"value":..}}` | restore last colour / send black |
| `[120,134,..]` | HSI | `PUT /state` hue, sat, brightness (`duration: 0`) in one request | HSV to RGB, into the next UDP frame; turns the panel on |
| `[120,135,..]` | CCT | `PUT /state` ct (value × 100, clamped 1200–6500) + brightness | Kelvin to RGB, into the next frame; turns the panel on |
| `[120,130,..]` / `[120,131,..]` | split brightness / temp | `PUT /state` brightness / ct | ignored (never sent: Nanoleaf rows are not CCT-only) |
| `[120,136,..]` | Neewer scene | ignored | ignored |
| `[120,133,0,253]` | power query | answer through the notify callback from `GET /state/on` | the panel's own on/off if known, else the controller's |
| `[120,132,0,252]` | channel query | one-byte answer at once, so the app shows `---` without retrying | same |

Addresses: `NL:<id>` for the controller and `NL:<id>-P<panelId>` for a panel, where `<id>` is the device's `serialNo` (from `GET /api/v1/<token>/`) with separators stripped and upper-cased, e.g. `NL:S23220H3960`. The serial is used rather than the discovery id so that pairing from discovery and pairing by IP give the same address. Addresses work unchanged as prefs sidecar filenames, alias targets, snapshot preset keys and `--light` values. `parseBatchString` needs a change (Phase 2).

No new dependencies: HTTP with `urllib` run through `asyncio.to_thread`, discovery and streaming with `socket`.

## Phase 1: `neewerlux_nanoleaf.py` and its tests — DONE

What exists, for Phase 2 to build on:
- `discoverAll(timeout)`: SSDP search, then a scan of this machine's /24 for port 16021 (`scanSubnet` / `scanHosts`, about 2 s). The scan is needed because Windows Firewall drops SSDP replies: they come from the device's address, not the multicast address the search went to. Scan results have an empty `id` and the name "Nanoleaf" until paired. `discover()` is SSDP alone.
- `pairAndDescribe(ip, port)`: pairs (`NanoleafError` with `PAIRING_HINT` on 403), reads name, model and serial, and returns a saved-device entry. `pair()` returns only the token.
- `loadSaved(path)`, `saveSaved(devices, path)`, `addSaved(entry, path)`: `light_prefs/nanoleaf.json`, a list of `{id, name, model, ip, port, token, perPanel, panels}`. `addSaved` merges by id and keeps `perPanel`. `panels` caches the ordered panel ids so per-panel rows can be listed while the device is offline. Already ignored by `light_prefs/*` in `.gitignore`. The default path follows `sys.argv[0]`, the same as the app's other prefs.
- `NanoleafController(entry, savedPath)`: one per physical device, shared by its rows. `devices()` returns the rows' `NanoleafDevice`s: one for the whole device, or one per panel (`<name> panel N`) when `perPanel` is set and the layout is known. `open()` / `close()` reference-count the clients; the first `open` reads the layout, which also checks the device is reachable and the token is good (`NanoleafError` otherwise). Closing the last client ends streaming and restores the previous effect.
- `setKelvinConverter(fn)`: register `convert_K_to_RGB` ([NeewerLux.py:4085](NeewerLux.py#L4085)). A coarse built-in table is used until then.
- Behaviour: whole-device `/state` writes are latest-wins (bodies sent while a PUT is in flight merge into the next one). Streaming turns the device on at brightness 100, uses extControl v2 with a v1 fallback, and sends one datagram per frame carrying every coloured panel; the frame goes out when the last in-flight panel write finishes. A whole-device colour ends the stream; the next panel write re-enters it. Restore re-selects the saved effect, or for `*Solid*`-style effects puts back the saved hue/sat or ct, then brightness and on/off.
- Panel order: by x, then top to bottom (higher y first) at equal x. Filtered out: panel id 0 and shape types 1 (Rhythm), 12 (Shapes controller), 16 (Lines connector), 19 (controller cap), 20 (power connector).
- [tests/fake_nanoleaf.py](tests/fake_nanoleaf.py): stdlib fake controller, runnable by hand (`pair` toggles the button state, `state` prints it, every request and frame is printed).
- [tests/test_nanoleaf.py](tests/test_nanoleaf.py): 24 tests: decoding, clamping, frame encoding, panel order, SSDP parsing, address scan, the saved file, and round trips against the fake (pairing, whole device, latest-wins, per-panel coalescing, restore, stream re-entry, v1 fallback).
- [tests/nanoleaf_hw_check.py](tests/nanoleaf_hw_check.py): hardware check. `--discover`, then `<ip>`: pair or reuse the saved token, print the raw layout, whole-device colours, panels one at a time, rainbow with frame rate, restore.

Hardware check, 2026-11-16, on the Shapes set: discovery found it, and pairing, whole-device HSI and CCT, the power query, extControl v2 streaming, left-to-right order and restore all worked. Triangles are shape type 8; the controller is type 12 at panel id 0 and was skipped. Still unconfirmed: types 16, 19 and 20 (the set has no connectors), and the real frame-rate ceiling (the script's 21.5 fps is its own `asyncio.sleep(1/30)` pacing on Windows timers).

## Phase 2: whole-device integration in `NeewerLux.py` — NEXT

- Startup: `nanoleaf.setKelvinConverter(convert_K_to_RGB)`, and one `NanoleafController` per saved entry, kept in a module-level dict by id so every row and rescan reuses it.
- `findDevices()` ([4757](NeewerLux.py#L4757)): after the BLE scan, add a row for every `controller.devices()` entry whose address is not already listed, using `getCustomLightPrefs` as the Neewer path does. Wrap the BLE scan so a machine without Bluetooth still gets its Nanoleaf rows. The "found again, clear `[1]`" branch stays BLE-only.
- `connectToLight()` ([4946](NeewerLux.py#L4946)): replace the two `BleakClient(...)` constructions with a small `makeClient(device)` that returns `NanoleafClient(device)` for a `NanoleafDevice`. The retry loop and table updates work as they are.
- `connectToOneLight()` ([5262](NeewerLux.py#L5262)): for an `NL:` address, build the entry from the saved list in place of `BleakScanner.find_device_by_address`.
- IP changes: if connecting fails with an unreachable error, run `scanSubnet()`, try the saved token on each hit (`GET /api/v1/<token>/`), and when the `serialNo` matches, update `ip` in `nanoleaf.json` and retry. Without this, a new DHCP address means pairing again. Needs a small helper in the module plus a fake-controller test.
- `getLightSpecs()` ([4893](NeewerLux.py#L4893)): add a Nanoleaf entry with range 1200–6500 K, not CCT-only.
- `parseBatchString()` ([5969](NeewerLux.py#L5969)): when `parts[0]` is `NL`, rejoin `parts[0:2]` as the light id (a panel address is `NL:<id>-P<n>`, still one colon). Add a check that `NL:S1:HSI:0:100:50` and `NL:S1-P5:OFF` parse.
- Table label: the `"[ʀssɪ: … dBm]"` suffix is built inline in about ten places ([3087-3100](NeewerLux.py#L3087-L3100), [2200-2203](NeewerLux.py#L2200-L2203)). Move it into one helper next to `_get_light_rssi` ([4564](NeewerLux.py#L4564)) that returns `[LAN]` for Nanoleaf rows.
- Status bar strings that say "Neewer lights" become "lights".
- Pairing UI: an "Add Nanoleaf…" button beside Scan in [neewerlux_ui.py:1211](neewerlux_ui.py#L1211). The dialog lists `discoverAll()` results, has a manual `ip[:port]` field, shows `PAIRING_HINT`, then calls `pairAndDescribe` and `addSaved` and triggers a discover. Network calls run off the GUI thread and report back through the existing `runOnGui` ([4280](NeewerLux.py#L4280)).
- Headless pairing: a `--nanoleaf_pair <ip[:port]>` CLI argument beside the others at [5596](NeewerLux.py#L5596), for `--http` and `--cli` installs.

Nothing changes in the worker thread, `writeToLight`, `parallelWriteToLights`, the animation engine, the sound engine, presets, the HTTP server or the web UI.

## Phase 3: per-panel mode

- Light Preferences tab ([neewerlux_ui.py:1561](neewerlux_ui.py#L1561), `setupLightPrefsTab` at [2111](NeewerLux.py#L2111), `checkLightPrefs` at [2174](NeewerLux.py#L2174)): add a "Show each panel as its own light" checkbox, shown only for Nanoleaf rows, and hide the CCT-only checkbox for them.
- Toggling it stops any running animation and sound-reactive session, disconnects the device, updates `perPanel` in `nanoleaf.json`, replaces that device's rows in `availableLights` with `controller.devices()`, then emits `_lightsChangedSignal` and reconnects.
- Each panel row gets its own sidecar prefs file through the existing code, so custom names and preferred IDs work per panel.
- Measure the real frame rate under sound-reactive on the Shapes set.

## Phase 4: docs and packaging

- [README.md](README.md): Nanoleaf section covering Wi-Fi setup (not Thread-only), pairing, per-panel mode and the limits below.
- [CHANGELOG.md](CHANGELOG.md) entry; update the description and keywords in [pyproject.toml](pyproject.toml).
- [NeewerLux.spec](NeewerLux.spec): add `neewerlux_nanoleaf` to `hiddenimports` and confirm it is bundled in the Windows build.

## Known limits (documented, not solved here)

- Neewer scene mode does nothing on Nanoleaf rows. Mapping it to Nanoleaf's own effects is a possible follow-up.
- No channel readout and no RSSI for Nanoleaf rows.
- The address scan covers only this machine's /24. A device on another subnet needs its IP typed in.
- A whole-device command sent while a device is streaming per panel ends the stream; the client re-enters streaming on the next panel write.
- If the app is killed while streaming, the panels keep their last colours at full brightness until an effect is chosen in the Nanoleaf app.

## Verification

Run tests with `uv run --no-sync python ...` or the activated `.venv`'s `python`: a plain `uv run` syncs the `audio` group, and `python-rtmidi` fails to build on this machine (no C++ compiler).

1. `python -m unittest tests.test_nanoleaf` passes.
2. Start `tests/fake_nanoleaf.py`, run `NeewerLux.py`, add `127.0.0.1:<port>` through "Add Nanoleaf…": pairing fails until the fake's button state is set, then succeeds and the row links.
3. Whole-device: CCT and HSI sliders, on/off, a preset, an animation and sound-reactive each produce the expected `/state` requests in the fake's log; the table shows `LINKED ON` / `STBY`.
4. Per-panel: enable the checkbox, confirm one row per panel, run "Rainbow Chase" and sound-reactive, and confirm the fake logs one UDP datagram per frame with distinct panel colours. Disable it and confirm the effect is restored and a single row returns.
5. Mixed: a Neewer light and the fake in one animation, with no stutter on the Neewer side.
6. Headless: `--nanoleaf_pair`, then `--http`, then drive the device through the HTTP API (including a batch string by `NL:` address) and the web UI.
7. Restart the app: the saved device reappears without pairing, with its custom name and preferred ID. On the real device, edit the saved `ip` in `nanoleaf.json` to a wrong address and confirm the app finds it again and corrects the file.
8. On the Shapes set: repeat 3, 4 and 7 on the real device, plus colour accuracy and frame rate during sound-reactive. (Done for the Phase 1 module, see above.)
