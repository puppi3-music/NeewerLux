# Puppi3's NeewerLux

Control Neewer Bluetooth LED lights and Nanoleaf panels from your computer, with presets, keyframe animations, sound reactive mode, and an HTTP server for driving it all from a browser or a Stream Deck.

Puppi3's NeewerLux is made by [puppi3-music](https://github.com/puppi3-music). It is a fork of [NeewerLux](https://github.com/poizenjam/NeewerLux) by PoizenJam that adds sound reactive mode and Nanoleaf support. NeewerLux is itself a fork of [NeewerLite-Python](https://github.com/taburineagle/NeewerLite-Python) (v0.12d) by Zach Glenwright ([@taburineagle](https://github.com/taburineagle)), which grew out of [NeewerLite](https://github.com/keefo/NeewerLite) by Xu Lian ([@keefo](https://github.com/keefo)).

Up to version 1.3 this fork was called NeewerLux. Settings saved by those versions are picked up on first launch, and the old `/NeewerLux/` HTTP URLs still work.

Puppi3's NeewerLux is not affiliated with or endorsed by Neewer or Nanoleaf.

## Supported lights

Lights are detected by their Bluetooth name. Anything advertising as `NEEWER`, `NW-`, `NWR` or `SL` is picked up, and these models have known colour temperature ranges built in:

GL1, NL140, SNL1320, SNL1920, SNL480, SNL530, SNL660, SNL960, SRP16, SRP18, WRP18, ZRP16, BH30S, CB60, CL124, RGB C80, RGB CB60, RGB1000, RGB1200, RGB140, RGB168, RGB176, RGB176 A1, RGB512, RGB800, RGB1, RGB18, RGB190, RGB450, RGB480, RGB530, RGB530 PRO, RGB650, RGB660, RGB660 PRO, RGB960, RGB-P200, RGB-P280, SL-70, SL-80, SL-90, TL60 RGB, ZK-RY, Apollo.

A model that isn't on the list still connects; it just gets a default colour range, which you can override per light in Light Preferences.

Nanoleaf panel sets (Shapes, Canvas, Lines, Elements, Light Panels) are controlled over your network instead; see [Nanoleaf panels](#nanoleaf-panels). Nanoleaf Essentials bulbs and strips are not supported.

## Installation

### Windows

1. Download `Puppi3sNeewerLux-<version>-Windows.zip` from [Releases](https://github.com/puppi3-music/NeewerLux/releases).
2. Extract it anywhere.
3. Run `Puppi3sNeewerLux.exe`.

Your presets, animations and per-light settings live in the `light_prefs` folder next to the executable. They are plain text and safe to edit by hand or copy between installs. Release zips don't include a preset file, so extracting a newer release over an existing install keeps your presets.

### macOS (Apple Silicon)

1. Download `Puppi3sNeewerLux-<version>-macOS-AppleSilicon.zip` from [Releases](https://github.com/puppi3-music/NeewerLux/releases) and open it.
2. Drag `Puppi3sNeewerLux.app` to Applications.
3. Open it. The app isn't signed by Apple, so the first time macOS says it can't check it: open System Settings > Privacy & Security, click **Open Anyway** next to the message about Puppi3's NeewerLux, and confirm. (Or run `xattr -dr com.apple.quarantine /Applications/Puppi3sNeewerLux.app` in Terminal.)

macOS asks once for Bluetooth access, for microphone access the first time you use the Sound tab, and for local network access when you add a Nanoleaf. Settings live in `~/Library/Application Support/Puppi3sNeewerLux/light_prefs`, so replacing the app with a newer one keeps them. On an Intel Mac, run from source.

### Linux (x86_64)

1. Download `Puppi3sNeewerLux-<version>-Linux-x86_64.tar.gz` from [Releases](https://github.com/puppi3-music/NeewerLux/releases).
2. Extract it somewhere in your home folder: `tar -xzf Puppi3sNeewerLux-<version>-Linux-x86_64.tar.gz`
3. Run `Puppi3sNeewerLux/Puppi3sNeewerLux`. Started from a terminal, it also prints its log there.

Bluetooth goes through BlueZ, which desktop distributions already run. A few system libraries aren't bundled; on Debian or Ubuntu, `sudo apt install libxcb-cursor0 libportaudio2` covers the window (on X11) and the Sound tab. Settings live in the `light_prefs` folder next to the program, as on Windows.

### From source

Runs on Windows, macOS and Linux, on any CPU. Requires Python 3.11 or newer. Dependency versions are pinned in `uv.lock`.

With [uv](https://docs.astral.sh/uv/):

```
uv sync --locked
uv run Puppi3sNeewerLux.py
```

With pip:

```
pip install "PySide6>=6.7,<7" "bleak>=0.22,<4" "sounddevice>=0.5" "numpy>=1.26" "python-rtmidi>=1.5"
python Puppi3sNeewerLux.py
```

On Linux the Sound tab also needs PortAudio from your distribution (on Debian or Ubuntu: `sudo apt install libportaudio2`). Windows and macOS get it with the `sounddevice` package.

The command-line and HTTP-only modes (`--cli`, `--list`, `--http`) don't need Qt. To install without it:

```
uv sync --locked --no-default-groups
uv run --no-default-groups Puppi3sNeewerLux.py --http
```

`--no-default-groups` is needed on both commands, because `uv run` re-syncs first and would otherwise reinstall PySide6.

## Using it

### Controlling lights

Scan, connect, then use the CCT, HSI or Scene tab. In Light Preferences you can give each light a name and a fixed number. Named lights keep their place in the table, and the name works anywhere a light is targeted: animations, presets and HTTP commands. The HSI tab also has a colour wheel, 15 one-click swatches and a button for the system colour picker.

Keyboard shortcuts for brightness and the sliders act on each selected light according to its own mode, so one brightness nudge reaches CCT, HSI and Scene lights together. All shortcuts are configurable in Global Preferences.

### Colour temperature limits

Global Preferences sets the CCT range your lights should stay within (2700K to 8500K, default 3200K to 5600K), and Light Preferences can override it per light. When a command falls outside a light's range, Puppi3's NeewerLux either clamps it to the nearest value the light can reach or skips it, whichever you choose. The same setting decides what happens when an HSI or Scene command reaches a CCT-only light.

### Presets

The preset buttons sit in a grid under the light table. Right-click one to save the current setup, edit, rename, reorder, duplicate or delete it; left-click recalls it; middle-click renames. A preset can set every light the same way or give each light its own settings, and the Preset Editor lays that out as a table.

Eight presets ship by default: Warm Studio, Daylight, Cool White, Candlelight, Red Alert, Blue Mood, Purple Haze and Green Screen.

### Animations

An animation is a list of keyframes. Each keyframe holds a colour for some time, fades from the previous one over some time, and can set different lights to different colours in HSI, CCT or Scene mode. Hue fades take the short way round the colour wheel. CCT-only lights follow colour animations by mapping hue to the nearest colour temperature.

101 animations ship with the app:

| Category | Examples |
|---|---|
| Emergency | Police Flash, Ambulance, Fire Truck, Hazard |
| Performance | Guitar Solo, Drum Solo, Metal Mosh, Encore, Power Ballad, Spotlight, Rock Anthem, Concert Build |
| Holidays | Christmas, Halloween, Valentines, Easter, Hanukkah, New Years Eve, St Patricks, Fourth of July |
| Studio | Interview, Warm Studio, Focus, Reading Light, Product Photo, Film Noir, Key Fill Rim, Dawn Simulator, Magic Hour, Golden Hour |
| Multi-light | Color Chase, Ping Pong, Ripple, Alternating Flash, Gradient Sweep, Warm Cascade, Identify Lights |
| Ambient | Neon Nights, Retrowave, Stage Wash, Campfire, Candlelight, Sunset Fade, Ocean Waves, Northern Lights, Lava Lamp, Breathe, and more |

Playback settings: speed (0.25x to 4x), update rate during fades (1 to 30 per second, default 5), brightness scaling (applied at playback, the file is unchanged), looping, and whether to return the lights to their previous state when the animation ends. With parallel writes on, every light is updated at once rather than one after another, which keeps fades smooth with several lights; turn it off if your Bluetooth adapter struggles.

New animations can start from one of six templates, or be built in the animation editor, which works on keyframes as a table with a live colour preview and a JSON tab for direct editing. Animation files are JSON in `light_prefs/animations` and target lights by name, number, MAC address, or `*` for all of them.

### Sound reactive

The Sound tab drives the lights from audio. It listens to an input device several times a second (15 by default) and splits the sound into bass, mids and highs. It also picks out beats, and it adjusts to the volume automatically, so quiet and loud tracks both use the full brightness range. Modes:

- **Spectrum colour**: the colour follows the pitch of the sound. Bass goes red/orange, vocals green, hi-hats blue/violet. Brightness follows loudness.
- **Beat colour jump**: a new colour on every beat, or every few beats with **Colour every**, gliding from one to the next. **Colour fade** sets how much of the time between changes the glide takes; 0 cuts hard. Brightness follows the bass and flashes on the beat.
- **Bass pulse**: brightness pumps to the kicks and the bass under them, and the colour follows how hard it hits: soft bass on the first palette colour, hard kicks and each beat (including MIDI clock beats) toward the last. On Auto it stays blue.
- **Frequency bands**: light 1 follows the bass (red), light 2 the mids (green), light 3 the highs (blue), repeating. A single light blends all three.
- **Rainbow drift**: the colour moves round the wheel, faster when the music is louder.

The **Colours** row picks the colours the modes use. *Auto* keeps the colours described above. The other presets sit in submenus: *Moods* (Rainbow, Club, Fire, Ice, Sunset, Ocean, Forest, Red & blue, Purple haze), *Pride flags* (Trans, Bi, Pan, Lesbian, Gay men's, Nonbinary, Genderfluid, Ace, Aro, Intersex, Agender, Polyamorous, Polysexual, Aroace, Demigirl, Demiboy; Rainbow is the classic one), *Holidays* (Christmas, Halloween, Valentine's, St Patrick's, Hanukkah), *Looks* (Teal & orange, Vaporwave, Cyberpunk, Neon noir, Pastel, Aurora) and *Seasons* (Spring, Summer, Autumn, Winter). Flags lose their black, grey and brown stripes, since a palette has no brightness. Whichever you pick, each mode then uses only those colours: spectrum colour runs from the first colour (low sounds) to the last (high sounds), beat jump steps between them, bass pulse moves from the first toward the last the harder the bass hits, frequency bands use the first three, and rainbow drift fades through them all. Click a colour to change it with a colour wheel, swatches or the system picker, and use + and − to add or remove colours (up to 8). Drag a colour sideways to reorder it, or right-click it to insert, delete, copy or paste colours. Editing a preset turns it into *Custom*, which is remembered. **Save palette as…** in the Colours menu (or a chip's right-click menu) keeps it under a name in *My palettes*, stored in `light_prefs/sound_palettes.json`; the same menu deletes the one picked. Sound presets keep a saved palette's colours, so they still work after it is deleted.

**Beats from the sound.** Puppi3's NeewerLux analyses the sound about 94 times a second and spots kicks as sudden jumps in the bass, so a long 808 or a rolling bassline doesn't hide them and soft kicks in quiet passages still count. A bass note as sudden as a kick counts as one too. While no kicks play, Beat colour jump and Bass pulse drop to a faint glow instead of holding bright on the bass, unless a sound is as loud as the music was with kicks: a big synth keeps them lit and flashing on each beat of the MIDI clock or detected tempo. They flash at full depth, and the **Flash limit** keeps them, like everything else the lights do in Sound mode, to at most 4 flashes a second, or 10 at the Show level. After about 4 s of a steady beat it finds the tempo (70-180 BPM) and fires each beat on time, early by **Beat lead** to make up for Bluetooth, instead of after the kick is heard; the status line shows the tempo. In a breakdown without kicks it lets go after 4 beats and follows the sound again. Untick **Predict beats from the tempo** to flash on every kick as it is heard. A sound with no kicks that is as loud as the music was with kicks, such as a big sustained synth, holds Beat colour jump and Bass pulse up and changes colour each bar; a quieter pad or bassline leaves them dim.

**Breakdowns, synths and drops.** A detected tempo is held through a breakdown, for up to a minute, and the first kicks back set where the beats fall, so a drop lands on the beat. A new track at another tempo is picked up from its kicks. In Beat colour jump, a loud synth with no kicks sets the colour from its notes: Puppi3's NeewerLux tells notes from drums and noise by the shape of the sound, whatever the input level, and the same chord comes back in the same colour. The first loud kick after 8 beats without one fades more slowly, so a drop lands with weight.

**Stops, drops and hits.** When the music cuts out, even for a fraction of a second, the lights go dark at once, and any predicted beat that falls in the stop is held back. The first kick after a stop or a roll is treated as a drop: it hits at full brightness and fades more slowly. In the beat modes, the bass under the kicks only partly reaches the brightness while kicks play, so each kick stands out. A low thump under a vocal, far below the kicks so far, doesn't count as a kick. A sudden loud hit with no kicks playing, like a stab or a pickup, flashes straight away.

**Drum rolls.** In Beat colour jump, Bass pulse and Rainbow drift, a fast, even snare roll above the bass, as in the build before a drop, shows in the lights while the colour keeps changing on the beat. **Drum rolls** on the Sound tab picks how. **Strobe**, the default, flashes on each beat from Max all the way down to Min bright and ripples on the hits between; at the Show level a roll builds instead, starting with one full flash per beat and halving the gap every 2 seconds up to every hit, as far as the limit allows. The ripple moves 8 points, 6 in saturated red, which is too little to count as a flash. The **Flash limit** caps each light on its final brightness, in every Sound mode and for kicks too; a flash above the cap is held back until one is free. **Standard**, the default, allows 4 flashes a second, the figure in UK Health and Safety Executive advice for strobes at public events, which is guidance rather than law and also calls for a notice. Every kick still flashes up to about 200 BPM. **Show** allows 10 a second and is only for use with a flashing-lights notice: 10 is inside the range that commonly triggers seizures, and choosing it asks you to confirm a notice is posted. Each light can only flash above 4 a second for about 4 seconds, added up over any short dips. It then falls back to 4 a second until about 8 seconds below that rate have passed, so a long roll drops back to flashing on the beat partway through and can build again later. **Off** removes the limit altogether, including the burst limit, with the same confirmation, and rolls build the same way up to every hit at any tempo. Show and Off go back to Standard at each start and presets can't change the level. See the [Canadian Epilepsy Alliance](https://www.canadianepilepsyalliance.org/about-epilepsy/types-of-seizures/photosensitive-epilepsy/) or the [Epilepsy Society](https://epilepsysociety.org.uk/about-epilepsy/epileptic-seizures/seizure-triggers/photosensitive-epilepsy) for more about photosensitive epilepsy. **Swell** has no pulses: brightness climbs smoothly to Max bright over about 8 seconds. **Strobe + Swell** puts the same pulses, with the same limit, on a brightness that climbs to Max bright over about 8 seconds. **Chase** runs the roll round a Nanoleaf's panels, left to right: each deep flash goes to the next panel, and every panel keeps the ripple. It needs the Nanoleaf shown as one light per panel (Light Preferences). Every other light, such as a Neewer panel, keeps the Strobe, and two Nanoleafs each chase on their own. Panels sit side by side, so the flash limit counts a Nanoleaf's panels together as one area: the chase moves no faster than one light's Strobe would, and at Show it builds the same way. The cap counts flashes using the WCAG flash thresholds, which were written for screens, and assumes light output follows the brightness percentage. It counts brightness only, not colour changes, and lights fill far more of the view than a screen does. It lowers the risk but can't rule it out, so if your audience may include people with photosensitive epilepsy, use Swell and put up a flashing-lights notice. A roll can also start with the kick still playing under it, once its hits have been even for about a second and a half, and it stays on through the gaps of a broken build pattern. When a roll ends, the lights fade down over about a second, and a kick still shows through the fade. Rolls need a beat to line up with, so they show with a MIDI clock or once the tempo has been found.

**Beats from MIDI clock.** A MIDI clock is exact even when the music has no clear kick. DJ software can instead send MIDI clock, its exact tempo and beat position, and Puppi3's NeewerLux can follow it: pick the MIDI input under **Beats from**. On Windows, if your DJ software has no MIDI output to pick, make one with [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html). Beat effects then land on every beat, and **Colour every** (say 4 beats) changes colour on the bar lines. **Beat lead** fires each beat a little early (50 ms by default) to make up for Bluetooth delay; raise it if the lights land after the kick. If the clock stops, beats come from the sound again until it returns. Traktor keeps sending clock after the decks stop, so **Clock beats only while kicks play** (on by default) pauses the beats when no kicks are heard, such as after the decks stop. With a clock, a kick only counts if it lands within about 60 ms of a beat, so an off-beat bassline doesn't keep the beats going. The clock and the sound can arrive with different delays, so that beat position is learned from the last few kicks, up to 140 ms either way, and the beats fire on it rather than on the raw clock. The first kick back flashes as it is heard. In Traktor: Preferences > MIDI Clock > tick *Send MIDI Clock*; in Controller Manager add a Generic MIDI device with Out-Port *Traktor Virtual Output*; press the clock-send button in the Master Clock panel, then pick *Traktor Virtual Output* in NeewerLux. If the bar count drifts off the downbeat, press Sync in Traktor's Master Clock panel. Needs `python-rtmidi`, which `uv sync` installs.

Brightness sensitivity (how far quiet parts light up), kick sensitivity (how easily a rise in the bass counts as a kick), smoothing, colour fade (how smoothly Bass pulse and Beat colour jump glide between colours, separate from smoothing so brightness stays punchy), the brightness range, saturation and the update rate can all be changed while it runs. It drives every connected light, or only the selected ones. Starting an animation stops sound mode, and the other way round.

**Presets.** The **Preset** row at the top of the tab saves the current settings under a name and loads them back with one pick: mode, sliders, colours, beat options and the all-lights choice. The input device and beat source stay as they are. Presets are kept in `light_prefs/sound_presets.json`.

Seven presets ship by default: Ambient Spectrum, Band Split, Chill, Club, Drum'n'Bass, Footwork and House & Techno. The genre ones set the tempo range to suit (Drum'n'Bass 165 to 180, Footwork 150 to 170 with Flash on: Kicks, House & Techno 115 to 140 with a colour change each bar). They leave your beat lead, rate, all-lights choice and the two beat checkboxes as they are, so loading one doesn't undo tuning for your lights. Saving, updating or deleting a preset copies the whole list into `sound_presets.json`. After that, removing a shipped preset keeps it removed. To get the shipped presets back, delete that file.

To follow what your computer is playing rather than a microphone, send the output through a loopback device and pick that device in the Sound tab:

- **macOS**: install [BlackHole](https://existential.audio/blackhole/). In Audio MIDI Setup, create a Multi-Output Device containing your speakers and BlackHole, and make it the sound output. Then choose BlackHole in Puppi3's NeewerLux. The first time, macOS asks for microphone access.
- **Windows**: enable Stereo Mix in Sound settings (Recording devices, "Show Disabled Devices"), or install [VB-Cable](https://vb-audio.com/Cable/) and make it the sound output, listening through it in Windows' "Listen to this device" setting. Then choose it in Puppi3's NeewerLux. For DJ software such as Traktor, [Voicemeeter](https://vb-audio.com/Voicemeeter/) avoids the crackle of a 10 ms shared WASAPI buffer: play through its Virtual ASIO driver, send that strip to A1 (your speakers) and B1, and choose "Voicemeeter Out B1" in NeewerLux.
- **Linux**: choose the "Monitor of ..." entry for your output; nothing needs routing. These entries need `pactl` and ALSA's PulseAudio plugin, which most desktops already have (on Debian or Ubuntu: `sudo apt install pulseaudio-utils libasound2-plugins`). PipeWire works the same way through its PulseAudio layer.

**Windows and Linux still need testing.** Sound reactive mode has been developed and used on macOS. Its Windows and Linux support is written but hasn't been tested on real computers yet, so it may not work as described above.

### Text size

**A−** and **A+** in the toolbar change the size of all text, as do Ctrl/Cmd + and −. Ctrl/Cmd 0 resets it. The size is remembered. On macOS the default is 130%.

## Nanoleaf panels

Nanoleaf panel sets (Shapes, Canvas, Lines, Elements and Light Panels) sit in the light table next to your Neewer lights, and presets, animations, sound reactive mode, the HTTP server and the dashboard all drive them. Puppi3's NeewerLux talks to the controller over your local network with Nanoleaf's Open API, so no extra software is needed.

**Wi-Fi first.** The controller must be on your Wi-Fi network. A set added only over Thread or Matter (for example straight to Apple Home) has no local API: add it to Wi-Fi in the Nanoleaf app first. The computer running Puppi3's NeewerLux must be able to reach it on port 16021 (TCP) and 60222 (UDP).

**Pairing.** Click **Add Nanoleaf…** in the toolbar. Puppi3's NeewerLux searches the network and lists what it finds; pick the set, or type its IP address (shown in the Nanoleaf app's device settings), then hold the power button on the controller for 5-7 seconds until the lights flash and click **Pair** within 30 seconds. The set then appears after a scan, marked `[LAN]`, and links like any other light. Without the window, pair from the command line:

```
python Puppi3sNeewerLux.py --nanoleaf_pair 192.168.1.50
```

It waits up to a minute for the controller to enter pairing mode, saves the set and prints its address, such as `NL:S23220H3960`. That address works with `--light`, in batch strings, in animations and in the HTTP API. Paired sets are kept in `light_prefs/nanoleaf.json`, and if a set's IP address changes, Puppi3's NeewerLux finds it again on this network and updates the file.

**One light, or one per panel.** A set is one light by default: every panel shows the same colour. Select it and tick **Show each panel as its own light** in Light Preferences to give every panel a row of its own, numbered left to right. The panel rows sit under a row for the set, like folders: double-click that row (or click its ▾ / ▸) to collapse or expand it, and select it to select every panel. Each panel can have its own name and fixed number, animations and presets can set panels to different colours, and Offset and Colour spread run across them. The dashboard groups panels the same way. Per-panel colours are sent as a fast stream, so sound reactive mode and animations can update every panel many times a second. Untick the box to go back to one light; the set returns to the effect it was showing before.

**Chase drum rolls.** In sound reactive mode, set **Drum rolls** to **Chase** to run a drum roll round a set shown one light per panel: each deep flash goes to the next panel, left to right. Other lights keep the Strobe. See [Sound reactive](#sound-reactive) for the flash limit, which counts a set's panels together as one area.

**Known limits.**

- The Scene tab (Neewer's built-in effects) does nothing on a Nanoleaf.
- Nanoleaf rows have no channel readout and no signal strength; the table shows `LAN` instead.
- The search only covers this computer's own subnet (the /24 it is on). For a set on another subnet, type its IP address.
- Sending one colour to the whole set while its panels are being driven one by one stops the panel stream for a moment; it starts again with the next panel colour.
- If Puppi3's NeewerLux is killed while streaming panel colours, the panels keep their last colours at full brightness until you choose an effect in the Nanoleaf app.

## Remote control

Turn on the HTTP server from the toolbar, or have it start with the app in Global Preferences. The dashboard is at `http://localhost:8080/` (the port is configurable), and the toolbar's WebUI button opens it.

Every action is also a plain URL, which is how a Stream Deck or a script drives Puppi3's NeewerLux:

```
http://localhost:8080/Puppi3sNeewerLux/doAction?light=1&mode=CCT&temp=5600&bri=80
http://localhost:8080/Puppi3sNeewerLux/doAction?use_preset=3
http://localhost:8080/Puppi3sNeewerLux/doAction?animate=Halloween|1.0|10|50|true|2|true
http://localhost:8080/Puppi3sNeewerLux/doAction?stop_animate
```

URLs starting `/NeewerLux/`, from versions up to 1.3, still work.

The `animate` value is `Name|speed|rate|brightness|loop|maxLoops|revert|offset|spread`. Only the name is required. The example plays Halloween twice at half brightness, then puts the lights back how they were. `offset` and `spread` (0-100) stagger the lights through the loop and spread their colours round the wheel; both default to 0, every light in step.

For richer control, POST JSON to `/Puppi3sNeewerLux/batch` (several lights in one request) or `/Puppi3sNeewerLux/animate`:

```json
{ "action": "play", "name": "Concert Sweep", "speed": 1.0, "loop": true, "maxLoops": 3, "revert": true, "offset": 50, "spread": 0 }
```

The Info tab and the dashboard both carry the full command reference.

**Security:** the HTTP server has no authentication. Access is limited only by the IP allowlist in Global Preferences, which by default admits this machine and common private network ranges. Don't expose the port to the internet.

## Other details

- Closing the window minimises to the system tray by default; quit from the tray menu.
- Dark and light themes.
- Lights are relinked automatically after the computer wakes from sleep.
- Only one copy runs at a time.
- The Log tab shows activity and can save it to a file.
- The Windows executable has no console window. When running from source, Global Preferences can hide the console on launch.

## License

This fork is licensed under the GNU Affero General Public License v3.0 only (AGPL-3.0-only). See [LICENSE](LICENSE). Copyright (c) 2026 puppi3-music.

It includes code originally released under the MIT License by Zach Glenwright and PoizenJam. Their copyright and permission notice is kept in [LICENSE-MIT](LICENSE-MIT), and the original projects remain available under MIT.
