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
| 2. Whole-device integration | Done, committed as `3c7bbcb` (CI: `e839dd0`), plus whole-device streaming and slow-light flashes. App checks 2, 3, 6 and 7 by hand still to do |
| 3. Per-panel mode | Done, committed (latest `27f432f`), checked in the app on the Shapes set (sound reactive per panel looks right) |
| 4. Docs and packaging | Done |

## Approach: Nanoleaf objects that stand in for Bleak objects

Every send path in [Puppi3Lux.py](Puppi3Lux.py) calls `availableLights[i][1].write_gatt_char(...)` directly (about 15 sites), and 58 places read `availableLights[i][0].name` / `.address`. Rather than refactor all of them, [puppi3lux_nanoleaf.py](puppi3lux_nanoleaf.py) provides two classes with the same surface as the Bleak objects, so an `availableLights` entry for a Nanoleaf has the usual ten fields and the rest of the app does not need to know.

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

## Phase 1: `puppi3lux_nanoleaf.py` and its tests — DONE

What exists, for Phase 2 to build on:
- `discoverAll(timeout)`: SSDP search, then a scan of this machine's /24 for port 16021 (`scanSubnet` / `scanHosts`, about 2 s). The scan is needed because Windows Firewall drops SSDP replies: they come from the device's address, not the multicast address the search went to. Scan results have an empty `id` and the name "Nanoleaf" until paired. `discover()` is SSDP alone.
- `pairAndDescribe(ip, port)`: pairs (`NanoleafError` with `PAIRING_HINT` on 403), reads name, model and serial, and returns a saved-device entry. `pair()` returns only the token.
- `loadSaved(path)`, `saveSaved(devices, path)`, `addSaved(entry, path)`: `light_prefs/nanoleaf.json`, a list of `{id, name, model, ip, port, token, perPanel, panels}`. `addSaved` merges by id and keeps `perPanel`. `panels` caches the ordered panel ids so per-panel rows can be listed while the device is offline. Already ignored by `light_prefs/*` in `.gitignore`. The default path follows `sys.argv[0]`, the same as the app's other prefs.
- `NanoleafController(entry, savedPath)`: one per physical device, shared by its rows. `devices()` returns the rows' `NanoleafDevice`s: one for the whole device, or one per panel (`<name> panel N`) when `perPanel` is set and the layout is known. `open()` / `close()` reference-count the clients; the first `open` reads the layout, which also checks the device is reachable and the token is good (`NanoleafError` otherwise). Closing the last client ends streaming and restores the previous effect.
- `setKelvinConverter(fn)`: register `convert_K_to_RGB` ([Puppi3Lux.py:4085](Puppi3Lux.py#L4085)). A coarse built-in table is used until then.
- Behaviour: whole-device `/state` writes are latest-wins (bodies sent while a PUT is in flight merge into the next one). Streaming turns the device on at brightness 100, uses extControl v2 with a v1 fallback, and sends one datagram per frame carrying every coloured panel; the frame goes out when the last in-flight panel write finishes. A whole-device colour ends the stream; the next panel write re-enters it. Restore re-selects the saved effect, or for `*Solid*`-style effects puts back the saved hue/sat or ct, then brightness and on/off.
- Panel order: by x, then top to bottom (higher y first) at equal x. Filtered out: panel id 0 and shape types 1 (Rhythm), 12 (Shapes controller), 16 (Lines connector), 19 (controller cap), 20 (power connector).
- [tests/fake_nanoleaf.py](tests/fake_nanoleaf.py): stdlib fake controller, runnable by hand (`pair` toggles the button state, `state` prints it, every request and frame is printed).
- [tests/test_nanoleaf.py](tests/test_nanoleaf.py): 24 tests: decoding, clamping, frame encoding, panel order, SSDP parsing, address scan, the saved file, and round trips against the fake (pairing, whole device, latest-wins, per-panel coalescing, restore, stream re-entry, v1 fallback).
- [tests/nanoleaf_hw_check.py](tests/nanoleaf_hw_check.py): hardware check. `--discover`, then `<ip>`: pair or reuse the saved token, print the raw layout, whole-device colours, panels one at a time, rainbow with frame rate, restore.

Hardware check, 2026-11-16, on the Shapes set: discovery found it, and pairing, whole-device HSI and CCT, the power query, extControl v2 streaming, left-to-right order and restore all worked. Triangles are shape type 8; the controller is type 12 at panel id 0 and was skipped. Still unconfirmed: types 16, 19 and 20 (the set has no connectors), and the real frame-rate ceiling (the script's 21.5 fps is its own `asyncio.sleep(1/30)` pacing on Windows timers).

## Phase 2: whole-device integration in `Puppi3Lux.py` — DONE

What exists, for Phase 3 to build on:
- Module-level `nanoleafControllers` (id to `NanoleafController`). `syncNanoleafControllers()` reads `nanoleaf.json` on every scan, creates missing controllers and refreshes idle ones (`controller.update(entry)`) after a re-pair or IP fix. The Kelvin converter is registered right after `convert_K_to_RGB`.
- `findDevices()`: the BLE scan is wrapped (a machine without Bluetooth logs it and carries on), then `addNanoleafLights()` appends `nanoleafLightEntry(device)` for each `controller.devices()` address not already listed. Entries use `getCustomLightPrefs`, `[5] = False` and `[9] = "LAN"`. Phase 3 can rebuild a device's rows by removing them and calling `addNanoleafLights()`.
- `makeClient(device)` in `connectToLight()`; `findNanoleafDevice(address)` in `connectToOneLight()` for `--light NL:...` (the CLI lower-cases arguments, so lookups ignore case). Link errors now include the exception text in the log.
- IP changes are handled in the module, not the app: `_request` raises `NanoleafUnreachable` for network errors. `NanoleafController.open()` then calls `relocate()`, which runs `findMovedDevice(entry, hosts)` (scan, `GET /api/v1/<token>/`, match `serialNo`) and writes the new `ip`/`port` with `updateSaved()`. One search per 60 s (`relocateInterval`); rows connecting at once share it, and a row that failed while another row moved the device just retries. `relocateHosts` narrows the scan for tests. On the Shapes set, a wrong saved IP connected in 4.6 s.
- `getLightSpecs`: `["Nanoleaf", 1200, 6500, False]`. `getCustomLightPrefs` looks specs up by kind for `NL:` addresses, since the device name is the user's own.
- `parseBatchString`: `NL:<id>:MODE:..` and `NL:<id>-P<n>:MODE:..`; the id is upper-cased, and a bare `NL:MODE` is skipped as malformed.
- `_light_table_label(entry)` builds every Name-column string (`[LAN]` for Nanoleaf); `_light_signal_text(entry)` gives "LAN" or "-60 dBm" for the HTTP page and `--list`. Status bar, `--list` and HTTP-page strings say "lights".
- "Add Nanoleaf…" (`NanoleafPairDialog` in `puppi3lux_ui.py`): it does no networking. `MainWindow.openNanoleafPairDialog` runs `discoverAll()` / `pairAndDescribe()` + `addSaved()` on threads and reports back through `runOnGui`. Devices already in `nanoleaf.json` are marked "already added". After pairing it queues `discover` if the worker is idle, else the status bar asks for a Re-scan.
- `--nanoleaf_pair <ip[:port]>` (space or `=`): retries for 60 s while the controller is not in pairing mode, saves, prints the `NL:` address, and exits. It leaves the lock file alone when another instance is running.
- The worker thread's power poll works unchanged; the status reads `LINKED ON / ᴄʜ. ---` (no channel on Nanoleaf).
- Tests: `tests/test_nanoleaf.py` now has 32 (moved device, IP recovery, search throttle, address helpers, `updateSaved`, batch strings). New `tests/test_app_nanoleaf.py` (6) drives `Puppi3Lux.py` against the fake: a scan with Bluetooth failing, connect/HSI/CCT/off/power readback, IP recovery, CLI lookup, `--nanoleaf_pair` parsing, and the pairing dialog offscreen. `.github/workflows/tests.yml` runs `unittest discover` on Windows for pull requests and pushes to `main`.
- Checked on the Shapes set (2026-11-16, app code run headless): recovery from a wrong saved IP, HSI, CCT 2700 K, off with the `STBY` readback, and `NL:` batch resolution.

Follow-up after `3c7bbcb` (sound reactive on a whole device):
- Whole-device colours that come quickly (sound reactive, animations, a dragged slider) go over the UDP stream instead of one `PUT /state` each (70–600 ms on the Shapes set). `setWhole(body, rgb)`: a colour within `STREAM_AFTER` (0.5 s) of the last one enters the stream with every panel set to that colour; after `STREAM_IDLE` (5 s) with no colour, or on close or a power change, the stream ends and the last colour is PUT. If the device refuses to stream, it PUTs for `STREAM_RETRY` (30 s) before asking again. A whole-device colour while panels already stream joins the stream.
- PUTs run on a sender thread of their own (latest-wins, newest body only), so a write never holds the other lights in the same frame. A failed PUT is raised from the next write. `settle()` waits for pending PUTs; `getPower()` and `close()` call it.
- `updateInterval` on the controller and `NanoleafClient`: the stream's transition time while streaming, else a running average of PUT time (`putTime`).
- Sound engine ([puppi3lux_audio.py](puppi3lux_audio.py)): `SoundEngine.lightInterval` (set to `soundLightInterval` in `getSoundEngine()`) gives each light's seconds per update. A light slower than `SLOW_LIGHT` (60 ms) flashes on every beat only if three updates fit between beats, else every 2nd, 4th… beat (counted the same on every light so they stay in step); during rolls it strobes on every Nth hit on the quick lights' accents. Its bass is smoothed over a flash.
- Table: while sound reactive runs, the worker's skipped power poll still emits `LINKED`, which corrects a stale `NOT LINKED`. In `setTheTable`, a plain `LINKED` no longer overwrites `LINKED\nON / ch. N`.
- Tests: `test_nanoleaf.py` now 35 (a slow device doesn't hold the write, quick colours stream, a refused PUT raises on the next write, a whole-device colour joins a panel stream). New `tests/test_slow_lights.py` (9). The fake gained `stateDelay` and `refuseState`. 50 tests in all.

Not done here:
- `release.yml`'s source zip lists files by name and was missing `puppi3lux_nanoleaf.py` (and the existing `puppi3lux_audio.py` / `puppi3lux_midi.py`). Fixed in Phase 4.

## Phase 3: per-panel mode — DONE

What exists:
- "Show each panel as its own light" in Light Preferences, Nanoleaf rows only. Toggling it queues `requestNanoleafPerPanel()`; the worker runs `setNanoleafPerPanel()` as described below. A device never linked has its panels read first; an unreachable one is left alone with a status message.
- The table groups panel rows under their device (below), and the web UI does the same.
- Chase roll style (sound mode): each deep flash of a drum roll moves to the next panel; the flash limit counts a device's panels as one area. `tests/test_roll_chase.py`.
- Frame rate, 2026-11-16 on the Shapes set (two panels): the app's write path sends 60 fps with 0.07 ms per write (per panel) or 0.27 ms (whole device), so it is never the limit; entering the stream takes about 300 ms. Red/blue swaps watched by eye were clean at 10, 15 and 30 a second; with the old 100 ms fade, 30 a second looked barely uneven. So streamed frames now use transition 0 (no fade), and a streaming device reports `STREAM_INTERVAL` (1/30 s) as its `updateInterval`, below `SLOW_LIGHT`: sound reactive flashes a streaming Nanoleaf on every beat. It used to report the fade (0.1 s) and was treated as a slow light.
- Tests: `test_app_nanoleaf.py` 15 (per-panel rows and one datagram per frame, turning it off restores the effect, unlinked and unreachable devices, per-panel prefs, grouping, select and collapse); `test_nanoleaf.py` 39.

As planned:
- Light Preferences tab ([puppi3lux_ui.py:1561](puppi3lux_ui.py#L1561), `setupLightPrefsTab` at [2111](Puppi3Lux.py#L2111), `checkLightPrefs` at [2174](Puppi3Lux.py#L2174)): add a "Show each panel as its own light" checkbox, shown only for Nanoleaf rows, and hide the CCT-only checkbox for them.
- Toggling it stops any running animation and sound-reactive session, disconnects the device, updates `perPanel` in `nanoleaf.json`, replaces that device's rows in `availableLights` with `controller.devices()`, then emits `_lightsChangedSignal` and reconnects.
- Each panel row gets its own sidecar prefs file through the existing code, so custom names and preferred IDs work per panel.
- Panel rows are listed under a group row for their device, like a directory tree (`_light_groups()` in [Puppi3Lux.py](Puppi3Lux.py)). Table rows no longer equal `availableLights` indexes: `MainWindow._tableRows` / `_lightRow` map between them, and `setTheTable`, `returnTableInfo`, `selectRows` and `selectedLights` all take and return light indexes. Double-clicking the group row (or clicking its ▾/▸ row number) collapses it; selecting it selects every panel; its Linked column counts linked panels. Collapsed state lasts for the session. The web UI does the same (`group` / `groupName` in `list_json`, collapsed state in the browser's `localStorage`) and puts the panels in an `<optgroup>` in the light picker.
- Measure the real frame rate under sound-reactive on the Shapes set. (Done, see above.)

## Phase 4: docs and packaging — DONE

- [README.md](README.md): Nanoleaf section covering Wi-Fi setup (not Thread-only), pairing, per-panel mode and the limits below.
- [CHANGELOG.md](CHANGELOG.md) entry; update the description and keywords in [pyproject.toml](pyproject.toml).
- [Puppi3Lux.spec](Puppi3Lux.spec): add `puppi3lux_nanoleaf` to `hiddenimports` and confirm it is bundled in the Windows build.
- [release.yml](.github/workflows/release.yml): add `puppi3lux_nanoleaf.py` (and the missing `puppi3lux_audio.py`, `puppi3lux_midi.py`) to the source zip.

## Known limits (documented, not solved here)

- Neewer scene mode does nothing on Nanoleaf rows. Mapping it to Nanoleaf's own effects is a possible follow-up.
- No channel readout and no RSSI for Nanoleaf rows.
- The address scan covers only this machine's /24. A device on another subnet needs its IP typed in.
- A whole-device command sent while a device is streaming per panel ends the stream; the client re-enters streaming on the next panel write.
- If the app is killed while streaming, the panels keep their last colours at full brightness until an effect is chosen in the Nanoleaf app.

## Verification

Run tests with `uv run --no-sync python ...` or the activated `.venv`'s `python`: a plain `uv run` syncs the `audio` group, and `python-rtmidi` fails to build on this machine (no C++ compiler).

1. `python -m unittest discover -s tests -p "test_*.py"` passes (89 tests on 2026-11-16; CI runs the same).
2. Start `tests/fake_nanoleaf.py`, run `Puppi3Lux.py`, add `127.0.0.1:<port>` through "Add Nanoleaf…": pairing fails until the fake's button state is set, then succeeds and the row links.
3. Whole-device: CCT and HSI sliders, on/off, a preset, an animation and sound-reactive each produce the expected `/state` requests in the fake's log; the table shows `LINKED ON` / `STBY`.
4. Per-panel: enable the checkbox, confirm one row per panel, run "Rainbow Chase" and sound-reactive, and confirm the fake logs one UDP datagram per frame with distinct panel colours. Disable it and confirm the effect is restored and a single row returns.
5. Mixed: a Neewer light and the fake in one animation, with no stutter on the Neewer side.
6. Headless: `--nanoleaf_pair`, then `--http`, then drive the device through the HTTP API (including a batch string by `NL:` address) and the web UI.
7. Restart the app: the saved device reappears without pairing, with its custom name and preferred ID. On the real device, edit the saved `ip` in `nanoleaf.json` to a wrong address and confirm the app finds it again and corrects the file.
8. On the Shapes set: repeat 3, 4 and 7 on the real device, plus colour accuracy and frame rate during sound-reactive. (Done for the Phase 1 module, see above.)
