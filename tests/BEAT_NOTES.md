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
- **Savana (Chris Lake):** g50 13.6 ≈ g90 16.0, which points to a steady offset (onset delay or kick offset), not jitter.
- **light years (Inez, John Summit):** the harness prints no score row; probably a harness or parse problem.
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
