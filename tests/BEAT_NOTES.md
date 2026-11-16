# Beat tracking: working notes

Notes for anyone (person or coding assistant) changing the tempo and beat tracking in `neewerlux_audio.py`
(`_TempoTracker`, `_KickDetector`, the roll finder). CHANGELOG.md says what changed; this file says how it was
checked, what is still wrong, and **what was tried and didn't work**, so the same dead ends aren't walked again.
Add to it when you try something, whether it is kept or dropped.

## How changes are checked

1. Synthetic suite: `uv run python tests/beat_harness.py` (every case, line / mic / digital input). True beat
   times are exact. Tune on these, but they are cleaner than real masters.
2. Real tracks against DJ-checked Traktor beatgrids:
   `uv run --with soundfile python tests/beat_harness.py --file "<track>" --nml "<Traktor collection.nml>"`
   (add `--variant mic` for a laptop-mic simulation, `--rolls <file>` to score drum rolls).
   The set used so far is 18 tracks (house, techno, garage/breaks, a 164 BPM breakbeat, a track that switches
   136→174). Compare every change against a baseline run of the unchanged module on all of them.
3. Keep a change only if synthetic results stay the same (or better), no real track drops by more than about a
   point of on-beat %, and Strobe (Victor Ruiz Remix) with `--variant mic` holds. One commit per fix.

Columns used below: **on** = % of the track the predicted grid is on the beat; **g50 / g90** = median / 90th
percentile grid error in ms; **extra** = flashes with no beat.

## Open problems (as of 2026-11-16)

- **Love is Gonna Save Us (Benny Benassi, ARTBAT) 150-190 s.** A long fill: hits at ±117 / ±234 ms from the beat,
  few on it. The tempo window reads 4/3 (171 BPM) there and the 3/4-4/3 guard holds it off, but 102.5 (4/5) and
  then 171 still get through around 157 s. On 89.2→90.8 after the 2026-11-16 fixes; 150-190 s is still mostly off.
- **Savana (Chris Lake) 203-239 s:** the kicks stop and an off-beat bass plays alone (hits at +213 ms, first every
  two beats, then every beat, plus a sound at +45..+65 ms). Its hits are taken as kicks, so no breakdown hold
  starts; at 208.5 s the off-beat flip (TEMPO_FLIP) moves the trusted grid half a beat, and it stays there until the
  kicks return at 239 s (on 90.3; 210-240 s is 0-14%). See Tried and dropped (Off-beat flips) for three attempts.
  Its steady g50 13.6 is not the tracker: the kicks timed from their own click land 13.7 ms before Traktor's beats
  all track long (±2 ms on the other tracks), and the decoder offset is right (Info frame + 529 samples, a kind of
  MP3 dj-tools checked to the sample; this file's header, written by ffmpeg, gives no encoder delay). Traktor's grid
  on this file sits late; don't tune for it.
- **Freestyler (Bomfunk MC's):** ~81% on; phase off under the off-beat bass in places.
- **I Found You (GVN, Elliot Vast):** ~41% on; kickless sections with a 16th off-beat bass.
- **Go Back (Sub Focus):** switches 136→174 at ~144 s and is scored against one 174 grid, so its on% means little.
- **Strobe g90 ~11-12 ms:** kick detection lateness moves by section (the kick's rise swells longer under the bass).

## Tried and dropped

Each entry: what was tried, on which problem, and what the numbers showed.

**Breakdowns and holds**
- Fixing the coast-agreement counter so TEMPO_COAST_AGREE (16 agreeing estimates) could end a hold: Afterparty's
  breakdown relocked at 5/4 (on 93.4→91.0) and Freestyler wasn't helped. The hold now ends only on kicks.
- Step-robust coast fit variants: taking the midpoint of the line and step fits, or a phase-only step: no better
  than the kept fit. Using TEMPO_FIT_KICKS 64 instead of 32 only flipped the sign of the slope error on the messy track.

**Tempo guards (3/4, 4/3, 2/3, 3/2 misreads)**
- Refusing an off-beat flip when the kicks disagree (for Freestyler): Freestyler 85.5, but Feels Like Us 87→77,
  Savana and DURO down.
- For I Found You: requiring more agreement before a relock; applying the kicks-fit test (`_kicksKeep`) to the
  3/4 guard; returning to the held grid after a wrong relock. Net zero across tracks.
- (Love fill) Refusing any relock while the window's kicks fit the locked grid as well as the new one: Love
  89.2→84.5, Afterparty 91.9→88.9, I Found You 40.9→33.9, messy g90 10.4→14.5.
- (Love fill) Adding 4/5 and 5/4 to the trusted 3/4-4/3 guard: the tempo held at 128 but the grid ended half a
  beat off for 150-180 s (Love 83.1), I Found You 36.6, Apex 84.4. The phase had already drifted, because stray
  fill hits were moving the period (fixed by TEMPO_KICK_SHARE, see the log). Worth retrying on top of that fix.

**Off-beat flips (Savana 203-239 s)**
- No flip at all for a trusted lock: Freestyler 80.2→90.6, Feels Like Us 87.4→92.0, Falling Up and Strobe 100,
  Love 92.8; but DURO 91.1→83.9, Age of Love 92.7→88.8, messy 82.6→76.2 and Savana 90.3→70.5. On Savana the grid
  then creeps instead: the window pull drags it ~10 ms towards the +57 ms hits, those enter the 45 ms kick gate and
  ratchet it to the off-beat, and with no flip nothing brings it back. The flip is also how grids recover.
- A trusted lock flips only towards where its kicks last landed on the grid (anchor updated while ≥ half the last
  8 kicks are on the grid), with or without also gating the kicks' phase nudge on that share: same numbers as no
  flip at all. The anchor follows the creeping grid.
- Start the hold for a trusted lock when on-grid kicks stop for max(2 s, 4 beats), even with other hits going on,
  and end it only on a kick within a quarter beat (or 25 ms) of the held grid. A first, buggy run (the hold
  restarted on each kick, so the fitted grid was held almost all the time) gave Savana, Love and Feels Like Us 100,
  Afterparty 98.5, messy 95.2, but Strobe 36.7, DURO 46.9, Age of Love 47.8. Fixed: Savana 91.8 (the +45 ms hits
  resnap the hold at 211 s), DURO 68.5, Strobe 82.6, I Found You 35.1. With 25 ms: Savana 95.1, messy 90.8, Desire
  100, but DURO 55.4, Strobe 61.9, Feels Like Us 56.2, Love 72.7. The trigger fires in ordinary sections too.
  Why the buggy run breaks Strobe, DURO and Age of Love (traced 2026-11-16): the resnap didn't set lastOnGrid, so
  from the first hold (DURO 28 s, Age of Love 30 s) the tracker never left it: period fixed from one fit, no window
  estimate, no flip, and every kick within ±0.25 beat (~115 ms) set the whole phase to itself. Fill hits walk the
  grid in one or two snaps (DURO 133-135 s: -110 then -169 ms; Strobe 98-99 s: -92 then -113 ms); from there the
  real kicks are too far to snap back, and on DURO the off-beat hits (+236 ms) then hold it on the off-beat to the
  end. Age of Love has steady own-click "kicks" a 16th early (-115 ms vs Traktor, every beat); the hold snaps to them
  and stays, where the base tracker's comb keeps the phase right.
  Then tried the buggy hold with the snap only within TEMPO_KICK_GATE 45 ms, and leaving the hold when ≥ 6 kicks in
  4 s come and none has fit for 4 s: Strobe, Love, Falling Up, Desire 100, Afterparty 98.5, Apex 90.5, Feels Like
  Us 90.8; but Age of Love 46.8 (still the 16th: it fits the gate once held), messy 75.0, GHOST DATA 71.5, light
  years 85.2, DURO 84.8 (130-180 s), Savana 90.7 (gain lost), and g90 much worse (Falling Up 9.4→29.5: whole-phase
  snaps to jittery kicks, no kick offset). Lesson: a hold snapped by kicks alone trusts the kick picker's phase,
  which is a 16th off on some tracks.
  Then (2026-11-16) the 45 ms hold with a second gate: a trusted hold resnaps on a kick only if the window comb's
  latest beat at the held tempo (update()'s estimate, less estOffset) is also within 45 ms of it. Step by step:
  (a) comb gate alone: Age of Love 93.4 (fixed: the comb ignores the 16th-early kicks), but Love 70.5, Apex 59.1:
  in a fill the window reads 4/3, no comb at the held tempo is stored, so no kick can resnap. (b) No fresh comb
  (none at the held tempo in the last 1.5 s): the kicks alone decide. Love and Desire 100, Strobe 99.9, Apex 90.2,
  but messy 75.3, GHOST DATA 70.9, DURO 86.2, light years 87.9, g90 about doubled (Punctual 9.4→21, Feels Like Us
  13.6→28). (c) Resnap by TEMPO_KICK_PHASE of the error instead of all of it: g90 partly back (Desire 3.9, Strobe
  16.3), on% the same. Subtracting kickOffset changes nothing (with click timing it is already in the phase).
  (d) Messy 40-60 s sat on the off-beat because the resnap didn't set lastOnGrid: the hold restarted on the next
  check, and each restart's line fit took in the off-beat kicks. With the resnap setting lastOnGrid, most tracks
  are back near base, but Strobe 75.5: at 181 s a flip moved the grid -134 ms, the hold's fit at 182.3 s put it
  back, then the 3/4 guard undid the flip on top (+131 ms) and no kick was in the gate again until 270 s.
  (e) = (d) + `_startCoast` clears `self.flipped` (the fit sets the phase, so there's nothing left to undo). Vs base:
  Desire 89.3→100, Apex 85.4→88.8, Love 90.8→92.8, Savana 91.6, messy 83.7, Age of Love 93.4, Strobe 99.6, DURO
  91.8; but Feels Like Us 87.4→83.7, Freestyler 80.2→77.8, light years 93.1→91.5, Punctual g90 9.4→19.1;
  synthetic the same except houseFillBreak/clean g90 5.8→15.1; **Strobe mic on 99.6→95.5, extra 25→84, g90 12.3→13.6**. Not kept.
  Feels Like Us 175-194 s: the window's 137 reading pulled the period to 134.4 just before an off-grid-trigger hold
  froze it; the kicks after the quiet are ~200 ms off the held grid, so the 45 ms gate never lets them resnap
  (base resnaps on any kick pair a whole number of beats apart, and recovers at 182 s). (f) = (e), but a hold that
  sees a real quiet (no kicks for max(2 s, 4 beats)) resnaps as base does: I Found You 43.4→36.2, messy 80.1,
  Apex 83.5, Feels Like Us only 84.2. Dropped.
  Open from (e): Strobe mic (not traced yet), Freestyler 210-230 s, light years 60-80 s, Feels Like Us' frozen
  wrong period.

**Kick timing**
- Timing kicks from the start of their rise instead of the 0.7 × peak crossing (for Strobe g90): unguarded it made
  "kicks" in swells and pulled Strobe to 133 BPM at 200-240 s. Requiring a clear start: Strobe g90 15.9→13.4 but
  house g90 +2..+6 ms (hop-quantised jitter). Interpolated, smoothed and slow-builds-only variants all traded ~2 ms
  on Strobe for losses on Apex, Love and messy. Timing each kick from its own click (kept) took most of the gain.
- Window pull while own-click kicks steer, swept 0 / 0.1 / 0.2: 0.1 kept.
- Shrinking the update() gain while kicks steer the period: dropped, kick phase/period loop was enough.
- TEMPO_COMB_REST 3 (for off-beat bass phase): more house loss than 2.
- TEMPO_COMB_DECAY 0.9 instead of 0.95: garage a little worse, driftJump only one beat better.
- Telling kicks from bass notes by sound alone, after the kick pitch-fall check failed on real recordings:
  (a) pitch of only the added energy: fixed synthetic kicks over a sub, barely helped real sets; (b) a click above
  the bass band: synthetic bass notes with hard attacks scored as high as kicks. Neither kept.

**Kick steering and gaps**
- (Love) Keeping the tempo through any quiet under 4 s: broke oddIntro136 clean/digital (sits at 4/3, on
  87.7→33.1), because resetting in the sparse intro's quiet stretches was what cleared its wrong first lock.
  Kept only for a trusted lock.
- (Love) The on-grid share rule for every lock, not just trusted ones: fine on real tracks, but it didn't cause
  the oddIntro break above (tested the gap change alone to find that).

**Other**
- Bass flatness as a "strong synth" test: rejected.
- A third fit for roll spans on Love: no better, reverted.
- Needing one more agreeing estimate before a roll starts (against flickers): no help on Love, removed.

## Log

Everything tried on a day, kept or dropped, in order. Numbers are on / g50 / g90 / extra against the run before.

**2026-11-16**
- Kept: roll finder follows 32nds (ROLL_HIT floor 0.05, lag must be a true peak, a faster peak ≥0.85 of the best
  wins, sub-step lag fit, keep depth 0.5 dB once on). houseBuild roll found 53-58→87-91%; oddIntro136 false rolls gone.
- Kept: TEMPO_DENSE_KICKS 2.5 (kicks per beat double the tempo): footwork160 on 0→100.
- Kept: TEMPO_COMB_REST 1→2: Freestyler 37.9→71.2, Feels Like Us 79.5→87.2, I Found You 29.4→41.0, house -2.5..+0.9.
  Dropped: 3.
- Kept: 2/3-3/2 guard (TEMPO_TRIPLET_RATIO 1.5%, trusted or `_kicksKeep`): Freestyler 71.2→78.0.
- Kept: hold through a breakdown ends only on kicks (coast agreement removed), Freestyler intro riff test
  (TEMPO_TRIPLET_SHARE, TEMPO_TRIPLET_HOLD): Freestyler 78.0→81.3. Dropped: kick-based flip refusal; fixing the
  coast-agreement counter; three I Found You ideas (see Tempo guards).
- Dropped: timing kicks from the rise start, all variants (see Kick timing).
- Kept: each kick timed from its own click (CLICK_OWN 20 ms), window pull 0.1 while those steer
  (TEMPO_EST_PULL_OWN; 0 and 0.2 tried): Strobe g90 15.8→11.2, 12/16 tracks tighter. GAP_BEAT_AGE 0.12→0.16
  (garage132 fire% back to 100). Own-click kicks skip the TEMPO_KICK_SOFT zone. TEMPO_ODD_RATIO 0.5%→1% (Strobe mic
  4/3 relock at 171 s): Strobe mic g90 16.2→12.1.
- Kept: coast fit with one phase step (TEMPO_FIT_STEP 4 ms, TEMPO_FIT_STEP_GAIN 0.5): messy g90 13.7→10.4.
  Dropped: midpoint and phase-only variants, TEMPO_FIT_KICKS 64.
- Love 140-190 s. Found: a 1.7 s fade to quiet at 138-140 s tripped QUIET_HOLD 1.5 s and pause() reset the tempo;
  then in the fill the few hits inside the ±45 ms gate dragged the period to the 3.5% span (132.5 BPM), the grid
  slid half a beat, and 102.5 (4/5) relocked.
  - Gap hold alone (QUIET_TEMPO_HOLD 4 s): Love 89.2→88.1 (140-150 s 14→95% but 150-160 s 59→5%), Afterparty
    91.9→91.1. Not enough on its own.
  - Dropped: refuse any relock while `_kicksKeep`; 4/5 + 5/4 in the trusted guard (see Tempo guards).
  - Kept: gap hold for a trusted lock only, plus TEMPO_KICK_SHARE 0.5 (a trusted lock's period moves on kicks only
    while ≥ half of the last 8 are on the grid). Love 89.2→90.8 (extra 87→70), I Found You 40.9→43.4 (g90
    37.2→32.4), others within 0.4 on; messy g90 10.4→11.9, Feels Like Us g90 13.1→13.6. Synthetic: oddIntro136
    unchanged, others under 1 ms. Strobe mic 99.6 / g90 12.1→12.3.

**2026-11-16 (later)**
- light years "blank row": not the harness. The scratchpad runall.sh ran each track in the background without
  `< /dev/null`, so the job read the start of the next line of the track list. Fixed there; the track scores
  93.1 / 1.8 / 22.4 / 99 at 4c253cf.
- Savana: offset traced to Traktor's grid on that file (see Open problems); the 0% section is an off-beat flip in a
  kickless off-beat-bass part. Dropped: no flip when trusted; anchor-directed flip; trusted hold on missing on-grid
  kicks (see Off-beat flips).
- Traced why the buggy "trusted hold" run (Savana/Love/Feels Like Us 100) broke Strobe, DURO, Age of Love: a
  permanent hold whose ±0.25-beat full resnaps let fill hits and a 16th-early kick walk the grid (see Off-beat
  flips). A tight-gate + exit version dropped: Age of Love 46.8, messy 75, g90 worse.
