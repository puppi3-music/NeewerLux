# Puppi3Lux changelog

Changes relative to upstream [NeewerLite-Python v0.12d](https://github.com/taburineagle/NeewerLite-Python).

## v1.5.0 - 2026-11-16

### Renamed
- **Puppi3's NeewerLux is now Puppi3Lux**, since it drives more than Neewer lights. The app is `Puppi3Lux.py` (`Puppi3Lux.exe` in releases), the HTTP API lives at `/Puppi3Lux/`, and the repository moved to [puppi3-music/Puppi3Lux](https://github.com/puppi3-music/Puppi3Lux), where update checks and Releases links now point (the old address redirects). Old `/Puppi3sNeewerLux/` and `/NeewerLux/` URLs still work, and on first launch `Puppi3sNeewerLux.prefs`, `.geometry` and `.log` in `light_prefs` (or the older `NeewerLux.*` files) are renamed to `Puppi3Lux.*`.

### Added
- **Animation Smoothing.** A new **Smoothing** setting in the Animations tab spends at least that share of each keyframe gliding from the colour before it, taken from its hold so the timing stays the same. 0% plays the fades as set; 100% never holds and always moves smoothly on to the next colour. On the web dashboard too, and in the HTTP API (`animate=Name|...|pattern|smoothing`, or `"smoothing"` in the POST body).
- **Random pattern.** Pattern has a new **Random** choice that gives every light, Nanoleaf panel or not, its own place at random. The lights are dealt new places each time an animation or sound session starts.
- **Loop forever.** The Animations tab's Loop setting is now a **Forever** tick box, on by default: the animation goes round until Stop. Untick it to play a number of **Times**.
- **Panels added while in use.** A linked Nanoleaf shown one light per panel is checked every 5 seconds for panels added or taken off. New panels get their own rows, are linked and join a running animation straight away; removed panels' rows are dropped. A running sound reactive session carries on, with its lights following their rows. **Scan** checks every per-panel Nanoleaf the same way, linked or not.
- **Unpair a Nanoleaf.** Light Preferences has an **Unpair this Nanoleaf…** button. It takes the device out of the light table and `light_prefs/nanoleaf.json` and asks the controller to forget the app's token. Its per-light prefs are kept, so pairing it again brings back names and IDs.
- **Pattern: effects that follow a Nanoleaf's layout.** Animations and the Sound tab have a new **Pattern** setting beside Offset and Colour spread. **Light order**, the default, works as before. **Left to right**, **Right to left**, **Top to bottom**, **Bottom to top**, **Centre out**, **Edges in** and **Around** place each panel of a Nanoleaf shown one light per panel by where it sits on the wall, with the canvas rotation from the Nanoleaf app applied. Panels level with each other move together, so with some Offset a breathe or flash sweeps across the set as a straight edge, spreads out from the middle in rings, or turns like a clock hand. Colour spread lays a rainbow across the set the same way. In sound mode the Pattern also sets the order for Rainbow drift and the Chase drum roll. In Frequency bands, the set splits into thirds along the pattern, so Bottom to top shows the bass at the bottom and the highs at the top. Other lights keep their place in light order. Panel positions are cached in `light_prefs/nanoleaf.json`. Saved with the window and in sound presets, on the web dashboard, and in the HTTP API (`animate=Name|...|offset|spread|pattern`, such as `centre-out`, or `"pattern"` in the POST body).
- **Suggested settings per animation.** An animation file can now carry `"suggest": {"offset": 50, "spread": 0, "pattern": "Centre out"}`. Picking that animation, in the app or on the dashboard, sets Offset, Colour spread and Pattern to those values, and you can still change them before playing. HTTP requests that leave those values out use them too. Animations without one leave the controls as they are. 18 built-in animations that set every light at once now suggest settings: for example, Breathe pulses out in rings, Color Cycle turns round the set, Matrix falls from the top, and the fires rise from the bottom. Animations that name lights 1–4, and strobes and sirens, have no suggestion and stay in step. The visual editor keeps a file's suggestion when you save it.

### Fixed
- **The HTTP server's accepted IP list matched too much.** An entry matched anywhere in the address, so the default `10.` let in any address containing "10." (such as 8.8.10.1), and an empty line in the list let in everyone. Entries now match whole parts from the start: `192.168.` and `10.` are ranges, and a full address matches only itself.
- **POST /animate with no name** answered with an error page instead of `{"success": false, ...}`.
- **A tap on the panels no longer leaves a Nanoleaf unresponsive.** Tapping or swiping the panels (or picking an effect in the Nanoleaf app) takes the device out of the stream mode the app drives it with, and every colour sent after that went nowhere. The app now notices within about 5 seconds. During an animation or sound session it takes the panels straight back; otherwise the next colour you send restarts the stream.

## v1.4.0 - 2026-11-16

### Licence
- **This fork is now AGPL-3.0-only**, made by puppi3-music. Code inherited from NeewerLite-Python and NeewerLux keeps its MIT notice in `LICENSE-MIT`. puppi3-music is credited in the About text, and source links point to this fork.

### Added
- **Nanoleaf panels.** Nanoleaf panel sets (Shapes, Canvas, Lines, Elements, Light Panels) on your Wi-Fi network now sit in the light table beside Neewer lights, and presets, animations, sound reactive mode, the HTTP API and the dashboard drive them. **Add Nanoleaf…** in the toolbar finds sets on this computer's subnet and pairs one (or type its IP address); `--nanoleaf_pair <ip>` does the same from the command line. Paired sets are saved in `light_prefs/nanoleaf.json`, appear with every scan without pairing again, and are found again if their IP address changes. A set is one light by default; **Show each panel as its own light** in Light Preferences gives each panel its own row, grouped under the set (collapse it, or select it to select every panel), with its own name and number, on the desktop and the dashboard. Panel colours, and quick changes to a whole set, go over Nanoleaf's UDP stream, so sound reactive mode flashes a Nanoleaf on every beat. Addresses look like `NL:S23220H3960` (`NL:<id>-P<panel id>` for one panel) and work with `--light`, in batch strings and in animation files. A set added only over Thread or Matter has no local API and must be put on Wi-Fi first. Known limits: the Scene tab does nothing on a Nanoleaf, there is no channel readout or signal strength, the search covers only this computer's /24, and a set left streaming when the app is killed keeps its last colours until an effect is chosen in the Nanoleaf app. A computer without Bluetooth now scans for Nanoleafs instead of failing.
- **Lights out of step: Offset and Colour spread.** Animations and the Sound tab each have two new settings, both 0% by default (every light in step, as before). **Offset** staggers the lights in light order: in an animation, 100% spreads them evenly over the whole loop, so Breathe or Color Wash chases from light to light; in sound mode, each light shows the music a little later than the one before, up to nearly a beat behind at 100%, so flashes ripple across the room. **Colour spread** gives each light its own colour, turned further round the colour wheel (or, in sound mode with a palette, along the palette), evenly over the whole wheel at 100%; white (CCT) keyframes are left alone, and in sound mode it applies to Spectrum colour, Beat colour jump and Bass pulse. Saved with the window and in sound presets, on the web dashboard, and in the HTTP API (`animate=Name|...|offset|spread`, or `"offset"` and `"spread"` in the POST body). Animations now play from the clock instead of sleeping between keyframes, so they no longer drift slower over long loops, and a light only gets a write when its colour changes.
- **Sound reactive mode.** A new Sound tab colours the lights from an audio input in five modes: spectrum colour, beat colour jump, bass pulse, frequency bands, and rainbow drift. It has bass/mid/high meters, beat detection and automatic gain. With a loopback device (BlackHole, Stereo Mix, a PulseAudio monitor) it follows whatever the computer is playing. Needs `sounddevice` and `numpy`, which `uv sync` now installs.
- **Colour palettes for sound mode.** The Sound tab's Colours row sets which colours every sound mode uses: Auto (the built-in colours), 40 presets in Moods, Pride flags (16 flags), Holidays, Looks and Seasons submenus, or your own palette of up to 8 colours chosen with a colour wheel, swatches or the system picker, which you can save by name to a My palettes submenu. This replaces the Bass pulse hue setting.
- **Beats from MIDI clock.** The Sound tab can take its beats from a MIDI clock input such as Traktor Virtual Output instead of detecting them in the sound, so beat effects land on every beat. Adds a clock lead (to cover Bluetooth delay), colour changes every N beats (8 by default, and in every preset, since a new colour on every beat is disorienting at higher tempos; on bar lines with a clock), and falls back to the sound when the clock stops. Clock beats only flash while kicks are heard, since Traktor keeps clocking when the decks stop ("Clock beats only while kicks play", on by default). With a clock, a kick only counts if it lands within about 60 ms of a beat, so an off-beat bassline doesn't keep the beats going. The clock and the sound can arrive with different delays, so that beat position is learned from the last few kicks, up to 140 ms either way. Needs `python-rtmidi`, which `uv sync` now installs. Kicks still count when the clock sits any distance from the sound or shifts mid-track: the offset is learned from where kicks land.
- **Better beat detection from the sound.** Every block of sound is analysed (about 94 times a second, not 15), so no kick falls between frames. Kicks are found as sudden jumps in the bass, instead of loud bass, so long 808s and rolling basslines don't hide them and soft kicks in quiet passages still count. Without kicks, Beat colour jump and Bass pulse fall to a faint glow instead of holding bright on the bass. After about 4 s the tempo (70-180 BPM) is found in the sound and beats fire on time, early by the beat lead (formerly clock lead), instead of 45-65 ms after each kick; the status line shows it. "Predict beats from the tempo" (on by default) turns this off. On synthetic house, hip-hop, drum'n'bass and quiet passages, predicted beats land within 5 ms of the beat, against 45-65 ms late with some missed and extra beats before. Footwork at 160 BPM, whose 3-3-2 kicks repeat only every two beats, no longer locks at half speed (80) in the default range: kicks coming several to a beat double the tempo. Where the bass plays the off-beat 8ths as hard as the beat (Bomfunk MC's Freestyler), the snare and hats now set where the beat falls, so the grid no longer sits on the off-beat: on beats rose from 38% to 71% on that track and from 80% to 87% on a garage track, with house and synthetic results unchanged to within 2.5 points. A riff of dotted quarters against the beat (also Freestyler) no longer pulls the tempo to 2/3 (110 instead of 164 BPM), in the riff-only intro or mid-track: on beats there rose to 81%, with every other track unchanged to within 0.2 points.
- **Drum rolls show in the lights.** Fast, even snare hits above the bass, as in the build before a drop, show in the lights in Beat colour jump, Bass pulse and Rainbow drift. Choose **Strobe** (the default), a deep flash on each beat with a shallow ripple on the hits between, **Swell**, a smooth climb to Max bright with no pulsing, **Strobe + Swell**, the same pulses on a climbing brightness, or **Chase**, where each deep flash goes to the next panel of a Nanoleaf shown one light per panel, so the roll runs across it while other lights keep the Strobe. The flash limit counts a Nanoleaf's panels as one area, so the chase moves no faster than one light's strobe would. Colour keeps changing on the beat, and when a roll's hits stop the lights fade down over about a second, through any gap before the drop, and the first kick lands from there. Needs a MIDI clock or a tempo found in the sound. A roll can start with the kick still under it, and stays on through the gaps of a broken build pattern. A roll that speeds up to 32nds stays on to the drop, and its ripple follows the faster hits. After a roll the kicks of the drop pick up straight away, at the full depth of the groove: the first kick out of the roll no longer hides the next ones, and the brightness range is measured from the drop, not the roll.
- **Harder contrast in sound mode.** The lights go dark as soon as the music stops, drops after a stop or roll hit at full brightness on the first kick, kicks pump deeper because the bass under them no longer holds the lights up, and sudden hits with no kicks flash at once. A flash now reaches full brightness on its first frame, thumps far below the kicks no longer count as kicks, and the flash limit no longer counts flashes from before a dark rest against the next flash.
- **Tempo held through breakdowns, synth notes and drop hits.** The tempo found in the sound is now kept through a breakdown, and the first kicks back set the beat, so drops land on the grid. Against DJ-checked Traktor beatgrids on 11 tracks, the correct tempo during kickless sections rose from 33% to 78% of the time, and recovery after a breakdown fell from 1.8 s to 0.9 s. A new detector follows the notes of tonal sounds, and in Beat colour jump a synth with no kicks now takes its colour from its notes. A drop's first kick fades more slowly. Fixed a crash when sound stopped in the middle of a drum roll. Long breakdowns now keep the grid on the beat as well: when the kicks stop, the tempo is measured from the last 32 kicks instead of carried over (a step in those kicks, as when a new part makes the kick sound a few ms later, no longer tilts that measurement: on one track 9 beats in 10 landed within 10 ms of Traktor's grid instead of 14), and sparse hits a whole number of beats apart (a sub note every two bars) no longer end the hold. A short quiet in the middle of a track (under 4 s, as a fade before a fill) no longer throws away a tempo the kicks have confirmed, and the stray hits of a fill no longer drag the tempo off: on Love is Gonna Save Us beats on time rose from 89% to 91%, and on I Found You from 41% to 43%. Once the kicks have confirmed the tempo, a breakdown with other hits still going on now holds the grid too, and kicks only move the held grid where the tempo window agrees they are on the beat, so off-beat bass notes and fills no longer flip it half a beat: on 18 tracks checked against Traktor, beats on time rose on HUMAN404's Desire from 89% to 100%, on Apex from 85% to 89%, on Feels Like Us from 87% to 91% and on Love is Gonna Save Us from 91% to 93%, with one track (light years) down from 93% to 92%. On a synthetic 8-bar breakdown the grid comes back within 4.4 ms instead of 19.5 ms, and through a 32-bar breakdown beats on time rose from 67-87% to 100%.
- **"Flash on: Kicks".** Beside "Predict beats from the tempo", "Flash on" chooses what the beat flash follows with a MIDI clock or a predicted tempo: **Beats** (the default, unchanged) flashes each beat of the grid ahead by the beat lead; **Kicks** flashes each kick as it is heard, so broken and syncopated patterns (footwork, 2-step garage) show as played, while the grid still counts the bar, so colours change on the beat and rolls stay on the grid. Kick flashes come without the beat lead, about 20-30 ms after the kick plus the sound card and Bluetooth delay, and the flash limit still applies: on a synthetic 3-3-2 footwork pattern at 160 BPM, Standard shows about 60% of the kicks and Show about 70%. Saved in presets.
- **Tempo changes followed from each kick.** While the tempo found in the sound is locked, each kick close to a beat of the grid moves the grid and the tempo a little towards it, so a DJ nudging the pitch or a track jumping a few BPM is followed within a few beats instead of after several seconds while the 8 s window catches up. On a synthetic jump from 120 to 124 BPM, beats on time rose from 92% to 98-100%, with 0-2 beats out of place instead of 8-9; on a slow ramp from 120 to 126 the worst grid error fell from 13.5 to 11.5 ms. Kicks off the grid (syncopation, strays) don't steer it, and the usual delay of a kick behind the beat is learned first, so steady tracks are unchanged.
- **Flash limit caps how often each light flashes.** Standard, the default, allows 4 flashes a second. Show allows 10 in bursts of about 4 seconds, then falls back to 4 a second until about 8 seconds below that rate have passed; drum rolls at Show build from one flash per beat up to every hit. Off removes the limit. Show and Off ask you to confirm a flashing-lights notice is posted, then go back to Standard at each start. The limit works on the final brightness in every Sound mode, kicks included, counting flashes by the WCAG thresholds, and roll accents use the whole range from Max to Min bright.
- **Loud sounds with no kicks hold the lights up.** A synth as loud as the music was with kicks now keeps Beat colour jump and Bass pulse lit, flashing on each beat when a MIDI clock or detected tempo gives one and changing colour each bar, and a quieter pad or bassline still leaves them dim. On a detected tempo, an irregular rise off the beat during such a sound no longer counts as a kick, so a sustained synth stops causing stray flashes.
- **Sound support for Linux and Windows (still needs testing on real computers).** On Linux the Sound tab now lists a "Monitor of ..." entry for each output, so it can follow what the computer plays without any routing. On Windows each device is listed once, with its full name, through WASAPI. Devices that only open at their full channel count now work, and beat timing on Windows no longer rounds to 15.6 ms.
- **Tighter sound timing.** Audio now arrives every 11 ms or so instead of in 85 ms bursts, so if you tuned Beat lead by ear for tempo-predicted beats, tune it again. Devices at 88.2 kHz and up are brought down to about 48 kHz, which removes a 10-18 ms beat offset at 96 and 192 kHz. Predicted beats no longer land late on real kicks whose body comes some milliseconds after their click: the delay from each kick's click is learned, and on three house tracks checked against Traktor's beatgrid, and on three more held out from tuning, the beats now land within 7 ms of it instead of 8-21 ms late. Sound frames no longer wait for Bluetooth or get dropped, because the worker always writes the newest colours, and light status reads pause while sound runs. MIDI clock ticks are filtered, about halving beat jitter. Opening kicks are missed less often. Brightness and Spectrum colour now weigh frequencies closer to how they are heard, so they no longer just follow the bass. The predicted beats no longer lock onto the off-beat when the kick's body swells in over 30-60 ms under an off-beat bassline as loud as the kick: on deadmau5's Strobe (Victor Ruiz Remix), beats on Traktor's grid rose from 24% to 99%, landing 1 ms after it instead of 14 ms, with about a fifth as many extra flashes. Once kick clicks are heard, the kicks set where the beat sits, rather than the bass's biggest rise 20-30 ms into each kick, and a dotted-eighth bassline (three notes to two beats) no longer reads as a new tempo or moves the beat onto the off-beat. Each kick is now timed from its own click, so the beat no longer slips a few milliseconds where a kick swells in under the bass (deadmau5 Strobe: 90% of beats within 11 ms of Traktor's grid instead of 16). In 2-step garage the bar's first beat no longer fires late on its kick: the short dip in the sound before it isn't taken as the music stopping. Six other house tracks checked against Traktor are unchanged within about a point. That guard waits until kicks have landed on the grid, so a track whose quiet intro gives a wrong first tempo still finds the right one: Sub Focus's Go Back now reads its 136 BPM from 20 s instead of sitting at 181 for 90 s.
- **Sound brightness uses the full range.** Automatic gain measures each level against its own last 3 seconds, so the quietest moments of the music reach your minimum brightness instead of sitting near half, and compressed drops keep pulsing instead of holding near full. Beat colour jump takes its brightness from the bass, so it dips between kicks.
- **Spectrum colour and Bass pulse use the whole palette.** Spectrum colour spreads over the range of pitch the music actually covers, so the first and last colours show up, not only the middle ones. Bass pulse colours by how hard the bass hits, from the first palette colour for soft bass toward the last for hard kicks and each beat (MIDI clock beats included), instead of staying on the first colour. The colour glides between palette colours rather than jumping with each flash, rising quickly on a kick and easing back. Beat colour jump glides to each new colour too, over part of the time until the next change. A new Colour fade setting (default 75%) sets how smooth both are, separately from Smoothing, so brightness stays punchy: 75% glides for three quarters of the gap, 95% fades continuously, 0 cuts hard.
- **Sound presets.** The Preset row at the top of the Sound tab saves the current Sound settings under a name and loads them back with one pick: mode, sliders, palette, beat options and the all-lights choice. The input device and beat source stay as they are. Presets are kept in `light_prefs/sound_presets.json`. Seven presets ship by default (Ambient Spectrum, Band Split, Chill, Club, Drum'n'Bass, Footwork, House & Techno), read from `sound_presets.json.default` until you save, update or delete one. They leave the beat lead, rate and all-lights choice alone.
- **Separate brightness and kick sensitivity.** The Sound tab's Sensitivity control is now two: Bright sens sets how far quiet parts light up, and Kick sens sets how easily a rise in the bass counts as a kick. Presets saved with the single control set both to its value.
- **No second flash from a beat lead.** A kick heard just after the flash that led it no longer fires another flash as the first kick back. This matters most at long beat leads, and every beat keeps its flash.
- **More soft kicks picked up.** Where the MIDI clock or detected tempo expects a kick, a smaller rise in the bass now counts, as soft kicks and off-beat bass rise about as much as each other and only their timing tells them apart. With a clock this applies only while recent kicks agree on where the clock sits against the sound. On 13 tracks, about 15 more kicks in every 100 were caught (63% to 78% with no clock, 64% to 79% with one), with no track losing kicks; off-grid kicks rose 7-12% with no clock or a clock on time, and up to about 22% with a clock that is off or shifts. Not yet tried with live MIDI.
- **Easier colour picking in HSI mode.** A colour wheel, 15 one-click swatches and a button for the system colour picker sit under the HSI sliders.
- **Adjustable text size.** A− / A+ toolbar buttons and Ctrl/Cmd +, − and 0 scale all interface text from 80% to 250%. The setting is remembered, and the default on macOS is 130%.

### Changed
- **Renamed to Puppi3's NeewerLux.** The window, About text, web dashboard, HTTP pages and command-line output use the new name, and the credits name puppi3-music, then NeewerLux by PoizenJam, NeewerLite-Python and NeewerLite as before. Files, modules and URLs use `Puppi3sNeewerLux`, since an apostrophe causes trouble there: `Puppi3sNeewerLux.py` (and `puppi3s_neewerlux_*.py`), `Puppi3sNeewerLux.exe` in a `Puppi3sNeewerLux` folder, release zips named `Puppi3sNeewerLux-<version>-Windows.zip` and `-Source.zip`, and the package name `puppi3s-neewerlux`. Upgrading keeps your settings: on first launch, `NeewerLux.prefs`, `NeewerLux.geometry` and `NeewerLux.log` in `light_prefs` are renamed to `Puppi3sNeewerLux.*`, and presets, animations and per-light files keep their names. The HTTP API moves to `/Puppi3sNeewerLux/doAction`, `/batch` and `/animate`; the old `/NeewerLux/` (and `/NeewerLite-Python/`) URLs still work, so Stream Deck buttons don't need changing. A version up to 1.3 that is still running isn't detected as another instance, so close it before starting this one.
- **Update checks and Releases links point to this fork** (github.com/puppi3-music/NeewerLux). They pointed at PoizenJam's NeewerLux, so the update banner compared this fork against upstream's releases.

### Fixed
- A crash on macOS after scanning for or linking to lights. The background thread was rebuilding the light table itself; the main window now does that.
- Possible crashes while an animation plays or the web interface changes presets or animations. Those background threads were changing the window directly; the main window now does that.
- Clearing the light selection no longer throws you off the Animations or Global Preferences tab, and it now leaves Light Preferences, which needs a selected light.
- A MIDI Start no longer makes Sound mode forget where the clock sits against the music, which left flashes off the kicks until enough kicks had been heard again.
- Launching no longer opens a greyed-out Light Preferences tab when the app was last closed on it.
- The number fields with − / + buttons (Sound tab, and loop count, rate and brightness on the Animations tab) were blank on Windows 11 with Qt 6.12, which shrank their text to 1 px wide. They show their values again.
- On Windows, a Sound input that WASAPI refuses ("Invalid device", seen with VB-Cable) now opens through DirectSound, or MME, instead of failing. Those deliver audio in bursts, so the lights can react a little later than through WASAPI.

### Development
- **Beat-tracking harness** (`tests/beat_harness.py`, not part of the app). It feeds synthetic house, builds, fills and breakdowns, UK garage, footwork, 200 BPM and tempo drift through the real analyser and light show in simulated time, as a line feed and as a laptop mic. It scores lock time, tempo misreads, grid error, fired beats and kick detection, and can try other tempo windows (`--sweep`) or score a real track (`--file`).

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
