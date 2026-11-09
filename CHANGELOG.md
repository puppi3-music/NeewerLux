# NeewerLux changelog

Changes relative to upstream [NeewerLite-Python v0.12d](https://github.com/taburineagle/NeewerLite-Python).

## Unreleased

### Added
- **Sound reactive mode.** A new Sound tab colours the lights from an audio input in five modes: spectrum colour, beat colour jump, bass pulse, frequency bands, and rainbow drift. It has bass/mid/high meters, beat detection and automatic gain. With a loopback device (BlackHole, Stereo Mix, a PulseAudio monitor) it follows whatever the computer is playing. Needs `sounddevice` and `numpy`, which `uv sync` now installs.
- **Colour palettes for sound mode.** The Sound tab's Colours row sets which colours every sound mode uses: Auto (the built-in colours), nine presets, or your own palette of up to 8 colours chosen with a colour wheel, swatches or the system picker. This replaces the Bass pulse hue setting.
- **Beats from MIDI clock.** The Sound tab can take its beats from a MIDI clock input such as Traktor Virtual Output instead of detecting them in the sound, so beat effects land on every beat. Adds a clock lead (to cover Bluetooth delay), colour changes every N beats (on bar lines with a clock), and falls back to the sound when the clock stops. Clock beats only flash while kicks are heard, since Traktor keeps clocking when the decks stop ("Clock beats only while kicks play", on by default). With a clock, a kick only counts if it lands within about 60 ms of a beat, so an off-beat bassline doesn't keep the beats going. Needs `python-rtmidi`, which `uv sync` now installs.
- **Better beat detection from the sound.** Every block of sound is analysed (about 94 times a second, not 15), so no kick falls between frames. Kicks are found as sudden jumps in the bass, instead of loud bass, so long 808s and rolling basslines don't hide them and soft kicks in quiet passages still count. Without kicks, Beat colour jump and Bass pulse fall to a faint glow instead of holding bright on the bass. After about 4 s the tempo (70-180 BPM) is found in the sound and beats fire on time, early by the beat lead (formerly clock lead), instead of 45-65 ms after each kick; the status line shows it. "Predict beats from the tempo" (on by default) turns this off. On synthetic house, hip-hop, drum'n'bass and quiet passages, predicted beats land within 5 ms of the beat, against 45-65 ms late with some missed and extra beats before.
- **Drum rolls show in the lights.** Fast, even snare hits above the bass, as in the build before a drop, show in the lights in Beat colour jump, Bass pulse and Rainbow drift. Choose **Strobe** (the default), a deep flash on each beat with a shallow ripple on the hits between, **Swell**, a smooth climb to Max bright with no pulsing, or **Strobe + Swell**, the same pulses on a climbing brightness. Colour keeps changing on the beat, and when a roll ends the lights fade down over about a second. Needs a MIDI clock or a tempo found in the sound. After a roll the kicks of the drop pick up straight away, at the full depth of the groove: the first kick out of the roll no longer hides the next ones, and the brightness range is measured from the drop, not the roll.
- **Limit flashing caps each light at 3 flashes a second.** It works on the final brightness in every Sound mode, kicks included, following the WCAG flash thresholds, so flashes can be deep at normal tempos instead of shallow. It can be turned off after a warning and comes back on at each start.
- **Loud sounds with no kicks hold the lights up.** A synth as loud as the music was with kicks now keeps Beat colour jump and Bass pulse lit, flashing on each beat when a MIDI clock or detected tempo gives one and changing colour each bar, and a quieter pad or bassline still leaves them dim. On a detected tempo, an irregular rise off the beat during such a sound no longer counts as a kick, so a sustained synth stops causing stray flashes.
- **Sound support for Linux and Windows (still needs testing on real computers).** On Linux the Sound tab now lists a "Monitor of ..." entry for each output, so it can follow what the computer plays without any routing. On Windows each device is listed once, with its full name, through WASAPI. Devices that only open at their full channel count now work, and beat timing on Windows no longer rounds to 15.6 ms.
- **Tighter sound timing.** Audio now arrives every 11 ms or so instead of in 85 ms bursts, so if you tuned Beat lead by ear for tempo-predicted beats, tune it again. Devices at 88.2 kHz and up are brought down to about 48 kHz, which removes a 10-18 ms beat offset at 96 and 192 kHz. Sound frames no longer wait for Bluetooth or get dropped, because the worker always writes the newest colours, and light status reads pause while sound runs. MIDI clock ticks are filtered, about halving beat jitter. Opening kicks are missed less often. Brightness and Spectrum colour now weigh frequencies closer to how they are heard, so they no longer just follow the bass.
- **Sound brightness uses the full range.** Automatic gain measures each level against its own last 3 seconds, so the quietest moments of the music reach your minimum brightness instead of sitting near half, and compressed drops keep pulsing instead of holding near full. Beat colour jump takes its brightness from the bass, so it dips between kicks.
- **Spectrum colour and Bass pulse use the whole palette.** Spectrum colour spreads over the range of pitch the music actually covers, so the first and last colours show up, not only the middle ones. Bass pulse colours by how hard the bass hits, from the first palette colour for soft bass toward the last for hard kicks and each beat (MIDI clock beats included), instead of staying on the first colour. The colour glides between palette colours rather than jumping with each flash, rising quickly on a kick and easing back. Beat colour jump glides to each new colour too, over part of the time until the next change. A new Colour fade setting (default 75%) sets how smooth both are, separately from Smoothing, so brightness stays punchy: 75% glides for three quarters of the gap, 95% fades continuously, 0 cuts hard.
- **Sound presets.** The Preset row at the top of the Sound tab saves the current Sound settings under a name and loads them back with one pick: mode, sliders, palette, beat options and the all-lights choice. The input device and beat source stay as they are. Presets are kept in `light_prefs/sound_presets.json`.
- **Easier colour picking in HSI mode.** A colour wheel, 15 one-click swatches and a button for the system colour picker sit under the HSI sliders.
- **Adjustable text size.** A− / A+ toolbar buttons and Ctrl/Cmd +, − and 0 scale all interface text from 80% to 250%. The setting is remembered, and the default on macOS is 130%.

## v1.3.0 - 2026-10-02

### Added
- **More Neewer models are detected.** Lights advertising as `NW-`, `NWR` or `SL` are now picked up alongside `NEEWER`, and the TL60 RGB has its colour range built in. Contributed by @Lain2077.
- **Heartbeat logging is optional.** The "Background Thread Running" line logged every 30 seconds is now a Logging preference, off by default.

### Changed
- **Upgrading keeps your presets.** The shipped presets are now a template, `light_prefs/customLights.prefs.default`, copied into place on first run and never over an existing file. Release zips no longer contain a preset file, so extracting a new release over an install leaves your presets alone. Resetting every preset is no longer undone on the next launch, and a read-only install folder falls back to reading the template. Contributed by @lugoues.
- **Reproducible builds.** Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`, and the release build fails if the two disagree. PySide6 is optional, so the headless modes install without Qt. Python 3.11 or newer is required. Contributed by @lugoues.
- The repository no longer tracks per-machine files (Visual Studio state, window position, personal presets). Contributed by @lugoues.
- Licensed MIT, matching upstream, with a LICENSE file in the repository.
- Em-dashes and arrows removed from interface and log text, and several comments that described the wrong line or a removed feature corrected.

### Fixed
- The README's source install instructions pointed at a `requirements.txt` that didn't exist.
- `NeewerLux-HTTP.bat` now says 8080 is only the default port.

## v1.2.0 - 2026-07-24

### Restored
v1.0.4 was packaged from an older copy of the code and silently dropped the following v1.0.3 features. They are back.
- **Mode-aware hotkeys.** Brightness and slider shortcuts act on each selected light according to its own mode, instead of only driving the sliders on the visible tab. One brightness nudge reaches CCT, HSI and Scene lights together; adjustments that don't apply to a light's mode are skipped. Respects Live Preview.
- **Configurable HTTP port** in Global Preferences (1024 to 65535, default 8080). Restart the server to apply.
- **Hotkey fields** no longer show Qt's built-in clear button as an empty square.

### Changed
- Both themes are generated from one stylesheet template and a set of colour tokens, replacing two hand-maintained copies. The palette went from 71 colours to 45, and corner radii follow a consistent scale on the desktop and the dashboard.
- The log and the JSON editor share one monospace font, with fallbacks for macOS and Linux.
- The Info tab is rewritten in plain sentences. The dashboard's About section, which duplicated it, now points to it instead.
- Decorative emoji removed from dashboard headings and buttons that already had text labels.

### Fixed
- The log had no focus outline, and the horizontal scrollbar had no hover state.
- Code cleanup: redundant guard clauses, an unused function, and a stale version comment that contradicted the real version.

## v1.1.0 - 2026-07-11

### Fixed
- **Idle CPU creep.** Left running for hours, CPU use climbed from near zero to 2-3% and reset on restart. The Log tab kept every line ever written, and each new line cost more as it grew. It now keeps the last 2,000 lines.

## v1.0.9 - 2026-06-11

### Fixed
- **Chained animations now revert.** Starting an animation while another was playing could leave the lights on the last frame instead of returning to how they were before the first animation. A timing race between the old and new animation threads, missed by the v1.0.4 and v1.0.6 attempts, is fixed.

## v1.0.8 - 2026-04-30

### Added
- **WebUI button** in the toolbar and tray menu, enabled while the HTTP server is running.

## v1.0.7 - 2026-04-30

### Changed
- The version number is defined once and used everywhere: title bar, Info tab, tray tooltip, dashboard, and console banner. It had been written out separately in 13 places.
- Global Preferences are grouped into sections: Startup and Connection, Control and Presets, Light Behaviour, HTTP Server, Window and Display, Logging, Filtering, and Keyboard Shortcuts.

## v1.0.6 - 2026-04-19

### Fixed
- Second attempt at the chained-animation revert. Incomplete; see v1.0.9.

## v1.0.5 - 2026-04-13

Version number correction for v1.0.4; no code changes.

## v1.0.4 - 2026-04-13

### Fixed
- First attempt at making a chain of animations revert to the state before the first one. Incomplete; see v1.0.9.

### Regressed
- This release was built from a copy of the code that predated v1.0.3, so mode-aware hotkeys and the configurable HTTP port were lost until v1.2.0.

## v1.0.3 - 2026-03-27

### Added
- Mode-aware hotkeys and a configurable HTTP port. Both were lost in v1.0.4 and restored in v1.2.0.

## v1.0.2 - 2026-03-22

### Added
- **Loop control over HTTP GET.** The `animate` value accepts `Name|speed|rate|brightness|loop|maxLoops|revert`, all optional after the name, so `?animate=Halloween|1.0|10|50|true|2|true` plays twice at half brightness and then reverts. Loop and revert were previously POST-only, which a Stream Deck can't send.

## v1.0.1 - 2026-03-22

Tagged on the same commit as v1.0.0, so both include these fixes.

### Fixed
- Animation names in HTTP requests are matched without regard to case. The request parser lowercases everything, so names with capitals never matched.
- The Windows executable's first connection attempt fails while Bluetooth initialises. A silent warm-up attempt now absorbs that failure, so the first thing you see is a successful connection rather than an error.

## v1.0.0 - 2026-03-22

First public release, with a Windows executable.

### Presets
- **Preset Editor.** Edit a preset as a table of entries, each targeting all lights or one light, with its own mode and values. Copy and paste settings between entries.
- Duplicate presets from the right-click menu.
- Eight presets ship by default: Warm Studio, Daylight, Cool White, Candlelight, Red Alert, Blue Mood, Purple Haze and Green Screen.

### Animations
- 101 built-in animations, up from 22, grouped by category in the list: emergency, performance, holidays, studio, multi-light utility and ambient.
- **Identify Lights** blinks each light a number of times matching its ID, to tell them apart.
- **Animation editor:** a "Show light" filter for multi-light animations, gradient sliders in place of number boxes, copy and paste between keyframes, and a named scene picker instead of scene numbers.

### Colour temperature
- **Global CCT range** in Global Preferences (2700K to 8500K, default 3200K to 5600K), used by the CCT tab and both editors. Per-light ranges in Light Preferences take precedence.
- Every write to a light is checked against its range. Depending on the "incompatible command" setting, out-of-range values are clamped to the nearest limit or the command is skipped.
- Colour animations on CCT-only lights map hue across the configured range rather than a fixed one.

### Interface
- Gradient sliders shared by the main window and both editors.
- Number boxes with separate plus and minus buttons, fixing overlapping arrows at 150% display scaling and above.
- A visible Select All button on the light table, and dropdown arrows that render in both themes.
- **Update checker** in the Info tab and the dashboard, using GitHub Releases.
- Info tab links open in the browser.
- Log tab with clear and save, written to file in batches, scrolling only when you're already at the bottom.
- Updates from the background thread reach the window through Qt signals, fixing occasional missed updates.

### Build and distribution
- Windows executable built with PyInstaller by GitHub Actions on each version tag, published as a draft release.
- The executable runs without a console window. The `.bat` launchers remain for running from source.
- `light_prefs` ships beside the executable and stays editable.

### Naming and compatibility
- Renamed from NeewerLite-Python to NeewerLux throughout.
- PySide6 and PySide2 both supported.
- Fixed crashes on some PySide6 versions, and output errors when launched with `pythonw.exe`.

---

## v0.12d-PJ5 - 2026-03-04

- **Dark and light themes,** switched from the toolbar.
- **System tray.** Closing the window minimises to the tray; the tray menu shows the window, toggles the HTTP server and console, and quits.
- **HTTP server toggle** in the toolbar, no restart needed.
- **Web dashboard** at `http://localhost:8080/` with the light table, sliders, animations, a command log, and an API reference.
- **`list_json`** returns light status, animations and playback state as JSON.
- **Visual animation editor** with a keyframe table, live colour preview, and a synced JSON tab.

## v0.12d-PJ4 - 2026-03-04

- **Light names and preferred IDs** in Light Preferences. The table orders lights by ID, and names work in animations and HTTP commands.
- **Parallel writes** update every light at once during animations.
- Live animation values shown in the light table.
- Six ambient animations: Campfire, Candlelight, Ocean Waves, Thunderstorm, Northern Lights, Lava Lamp.

## v0.12d-PJ3 - 2026-03-03

- Smoother animation playback: no double waiting, throttled table updates, and dropped frames are logged.
- Brightness scaling for animation playback (5 to 100%).
- Nine animations: Concert Sweep, Bass Drop, Neon Nights, Stage Wash, Fire Flicker, Sunset Fade, DJ Pulse, Blackout Flash, Retrowave.
- Fixed the HTTP GET animate syntax and a Bleak deprecation.

## v0.12d-PJ2 - 2026-03-02

- **Animation engine:** keyframes with hold and fade times, short-way hue fades, seamless looping, and adjustable update rate.
- Seven animations, six templates, a JSON editor, and HTTP control.

## v0.12d-PJ1 - 2026-03-01

- Paged presets with your own names.
- PySide6, with PySide2 as a fallback.
- Lights relink after the computer wakes, HTTP batch commands, and cleanup of a stale instance lock.
