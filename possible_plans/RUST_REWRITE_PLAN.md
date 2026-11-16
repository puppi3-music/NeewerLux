# NeewerLux: staged rewrite in Rust

## Context

NeewerLux is about 14,300 lines of Python (PySide6 GUI, bleak Bluetooth, numpy sound analysis, built-in HTTP server) shipped as a PyInstaller folder. The goal is to replace all of it with Rust: one small executable, no Python/Qt/WinRT packaging workarounds, and a sound thread free of the GIL.

Decisions already made:

- **GUI:** Tauri, with one web UI used both in the desktop window and as the remote dashboard.
- **Migration:** staged, side by side in this repo. Python stays the released app until Rust reaches parity, then it is removed.
- **Sound parity:** faithful port; beat harness scores must match Python within a tolerance, not frame for frame.

Constraints that shape the design:

- Existing `light_prefs/` files (presets, 101 animations, sound presets, per-light sidecars, global prefs) must be read and written in their current formats, so both apps can share one folder during migration.
- The HTTP API (`/NeewerLux/doAction?...`, `POST /NeewerLux/batch`, `POST /NeewerLux/animate`, the `/NeewerLite-Python/` alias, `list_json`) must stay compatible; Stream Deck setups depend on it.
- Licence stays AGPL-3.0-only; `LICENSE-MIT` for the upstream portions is kept.
- Rust is not installed on this machine (`cargo` not found), and tools here are managed by `.mise/config.toml`.

## Target layout

A Cargo workspace at the repo root, next to the Python files:

| Path | Contents | Replaces |
|---|---|---|
| `crates/nl-core` | Packet building and checksum, light model and spec table, CCT clamp/fallback, colour conversion, file formats, animation interpolation and templates, command parsing (CLI, URL params, batch strings). No Bluetooth, no threads. | The pure parts of `NeewerLux.py` (roughly lines 4037-4700, 5467-6180, 6518-6800, 7391-7595) |
| `crates/nl-ble` | `btleplug` transport and the **controller**: one tokio task that owns all lights. | `findDevices`, `connectToLight`, `writeToLight`, `parallelWriteToLights`, `workerThread` (`NeewerLux.py:4709-5465`) |
| `crates/nl-audio` | Analyser, tempo tracker, roll finder, harmony, light show, flash limiter as a pure library with time passed in; capture (`cpal`) and MIDI clock (`midir`) behind features. | `neewerlux_audio.py`, `neewerlux_midi.py` |
| `crates/nl-server` | `axum` server: legacy routes, new `/api` JSON + WebSocket routes, embedded UI bundle. | `NLPythonServer` (`NeewerLux.py:6804-7380`), `neewerlux_webui.py` |
| `crates/neewerlux-cli` | Headless binary: `--list`, `--cli`, `--http`, same flags as today. | `__main__` CLI paths |
| `tools/nl-trace` | Reads raw samples, runs `nl-audio` on a simulated clock, prints the log / fired beats / kicks as JSON. | The body of `run()` in `tests/beat_harness.py:436` |
| `app/src-tauri`, `app/ui` | Tauri v2 shell and the Svelte + TypeScript UI. | `neewerlux_ui.py`, `neewerlux_anim_editor.py`, `neewerlux_theme.py`, the main-window class in `NeewerLux.py:434-4026` |

### Key design points

- **Controller instead of globals.** The 61 `global` statements and the `threadAction` string become one task with an `mpsc` command channel (discover, connect, send, power, preset, animation start/stop, sound start/stop). Animation and sound frames go into a newest-wins slot, as `soundLatestLights` does today, so a slow write never queues stale colours. State is published through a `watch` channel that the HTTP server and UI read.
- **Behaviours to carry over exactly:** status polling about every 3 s and skipped while an animation or sound mode runs; auto-reconnect with a 20-cycle cooldown; rescan after two all-disconnected cycles (sleep/wake); split brightness/temperature packets for CCT-only lights; writes without response.
- **One UI transport.** The UI always talks HTTP + WebSocket to `nl-server`, including inside Tauri. Tauri only adds the window, tray, global shortcuts and single-instance lock. To keep today's "HTTP off by default" posture, the desktop app binds loopback only, the new `/api` routes require a per-launch token given to the webview, and the legacy `/NeewerLux/*` routes are mounted only when the user turns the HTTP server on (same IP allow-list as now).
- **A small numpy stand-in.** `nl-audio` needs hand ports of the numpy calls the engine uses: `percentile` (linear interpolation), `median`, `convolve`, `correlate`, `searchsorted`, `hanning`, `sinc`, `add.reduceat`, `bincount`, `unique`, `polyfit`, `lstsq`, plus FFTs via `realfft`. Each gets a unit test against values dumped from numpy.

## Stages

Each stage is its own branch and PR, and ends with something that runs.

### Stage 0: toolchain and two spikes
- Add pinned `rust` and `node` to `.mise/config.toml`; add `rust-toolchain.toml`, root `Cargo.toml`, `.gitignore` entries, a CI job running `cargo fmt --check`, `clippy`, `test`.
- Check current versions of `btleplug`, `cpal`, `midir`, `realfft`, `axum`, Tauri v2 before pinning them.
- **Bluetooth spike:** scan, connect, send one HSI packet, read power/channel on a real light on Windows. Confirms whether the frozen-exe warm-up connect is still needed.
- **Audio spike:** list input devices including VB-Cable, open one, and try WASAPI loopback of the default output (which could remove the need for a virtual cable).
- Exit: both spikes work on this machine. If `btleplug` cannot hold a stable connection, stop and reassess before any porting.

### Stage 1: `nl-core`
- Port packets (`calculateByteString`, `calculateSeparateBytestrings`, `calculateChecksum`), `getLightSpecs`, CCT fallback (`hsiToCCTByteVal`, `applyCCTFallback`), `interpolateHSI`/`interpolateCCT`, the six templates, batch parsing (`parseBatchString`), preset string format, prefs loading.
- Fixtures: a throwaway Python script calls the existing functions over a grid of inputs and writes JSON; the Rust tests replay them. Fixtures are committed under `crates/nl-core/tests/fixtures`.
- Exit: every shipped animation, the default presets and `sound_presets.json.default` load and re-save byte-compatible or semantically equal; all fixture tests pass.

### Stage 2: controller, Bluetooth, CLI
- `nl-ble` controller and `neewerlux-cli` with `--list` and `--cli` (same flag names and defaults as `NeewerLux.py:5548-5577`).
- Animation engine on the controller (port of `animationEngineThread`, `NeewerLux.py:6307`).
- Exit: on real lights, `--list`, on/off, CCT, HSI, scene and playing a shipped animation all behave as the Python CLI does.

### Stage 3: HTTP server; first shippable piece
- Legacy routes with identical parameters and responses; `list_json` with the same shape (`NeewerLux.py:6880-6932`).
- Serve the existing dashboard HTML, lifted out of `neewerlux_webui.py` into a static file, so the headless binary is useful immediately.
- Contract tests: record responses from the Python server for a list of URLs, replay against Rust.
- Release workflow gains a job that attaches a headless Rust binary (Windows, Linux, optionally macOS and Raspberry Pi) to releases alongside the Python zip.
- Exit: existing dashboard and a Stream Deck URL work unchanged against the Rust binary.

### Stage 4: sound engine
- Port in dependency order: envelopes/gain/gate, `_Decimator`, `_Analyser`, `_KickPicker`, `_TempoTracker`, `_RollFinder`, `_Harmony`, `_FlashLimiter`, `_LightShow`, then `SoundEngine` capture and `MidiClock`/`BeatTracker`. Keep the constants block (`neewerlux_audio.py:69-242`) one to one, with the comments.
- `tools/nl-trace`, and a `--engine rust` option on `tests/beat_harness.py` that swaps `run()` for a call to it. Synthetic cases and scoring stay in Python for now, so both engines are scored by the same code. This is the only Python file edited before cutover.
- Compare in two layers: per-hop band levels and kick times (catches port bugs early), then the harness tables.
- Tolerance for "same scores": same `ratio` and `sits` on every case; `on%`, `fire%`, `kick%` within 2 points; `grid50`, `fire50` within 2 ms; `lock` within 0.5 s. Any case outside it is investigated, not waved through.
- Capture: WASAPI first with the DirectSound/MME fallback, PulseAudio monitor sources on Linux (`_linuxMonitors`), the device-stopped watchdog.
- New `/api/sound/*` routes and a WebSocket stream of live state (levels, BPM, beat).
- Exit: harness within tolerance on all synthetic cases in all three input variants and on the real tracks listed in `tests/BEAT_NOTES.md`; sound mode drives real lights from the headless binary.

### Stage 5: Tauri desktop app
- Build `app/ui` screen by screen against `/api`: light table; CCT / HSI (wheel, swatches) / Scene; preset grid and per-light preset editor; animation list, keyframe editor and templates; Sound tab (device, mode, palette editor, sound presets, MIDI port, live meters); Light Preferences; Global Preferences including shortcut editing and CCT limits; Log tab; themes and text size.
- Shell: tray and minimise-to-tray, global shortcuts, single-instance lock, update check, window state.
- The same bundle is embedded in `nl-server`, replacing the old dashboard HTML.
- Ship as a clearly labelled beta next to the Python release for at least one release cycle.
- Exit: a written parity checklist built from the README's "Using it" section is fully ticked on Windows, with a smoke pass on Linux.

### Stage 6: cutover
- Release as 2.0 with the same portable zip layout (`light_prefs` next to the exe, no preset file in the zip, so extracting over an install keeps presets).
- Remove the Python sources, `NeewerLux.spec`, `pyproject.toml`, `uv.lock`, the `.bat` launchers; update `README.md`, `CHANGELOG.md`, `.desktop` file and `release.yml`.
- Port the harness's synthetic cases and scoring to a Rust dev tool so `tests/BEAT_NOTES.md` stays reproducible; freeze the last Python numbers in the notes as the baseline.

## Rules while both versions exist

- Once a module's stage is merged, any behaviour change to that Python module needs the matching Rust change in the same PR.
- Beat tracking experiments keep going into `tests/BEAT_NOTES.md`, noting which engine the numbers came from.

## Main risks

| Risk | Mitigation |
|---|---|
| `btleplug` behaves differently from bleak on Windows with these lights | Stage 0 spike is a go/no-go gate before any porting |
| Small numeric differences shift the tuned tracker | Per-hop layer comparison first, then the agreed harness tolerance |
| Desktop UI grows without end | Parity checklist fixed up front from the README; no new features until cutover |
| Webview dependency (WebView2 on Windows 10, webkit2gtk on Linux) | Document it; headless binary plus browser remains a fallback |
| Loopback server widens the attack surface | Token on `/api`, legacy routes off unless enabled, IP allow-list kept |

## Verification

- `cargo test --workspace`: packet/interpolation/file-format fixtures, numpy stand-in tests, HTTP contract tests.
- `uv run python tests/beat_harness.py` and the same with `--engine rust`, plus `--flash`; compare tables against the tolerance above. Repeat with `--file` on the real tracks from `tests/BEAT_NOTES.md`.
- On real lights, per stage: `--list`; CCT/HSI/scene/on/off by CLI and by `doAction` URL; a `batch` POST; play and stop a shipped animation; sound mode from a loopback device for several minutes, including unplugging the device; sleep/wake auto-reconnect.
- Point the Rust and Python apps at the same `light_prefs` folder in turn and confirm each reads what the other saved.
- Desktop: run through the parity checklist in the packaged build, not only `tauri dev`.
