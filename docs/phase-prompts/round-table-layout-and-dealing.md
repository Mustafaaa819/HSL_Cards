# Round table layout + a one-time dealing animation

## What this is, and what it deliberately is not

This is a STRUCTURE/functionality pass, not a beautification pass — that's
an explicitly separate next session, already planned. Get the layout and
the animation logic right; don't spend time on colors, glow tuning, or
polish for the new pieces you're building here. Reuse whatever's already in
`App.css`'s token system where you need color at all, but don't treat this
as the visual-quality bar.

Design brief straight from the person building this, so you have the actual
intent, not just a spec:

> I want the players sitting roundly [in a circle] like a real table, with
> the main deck in the middle. A machine deals cards to each player one at a
> time, rotating around the table, layer by layer — layer 1 (blind) dealt
> face-down to everyone first, then layer 2 (face-up), then layer 3 (hand).
> The face-up layer should sit slightly overlapping the blind layer beneath
> it, to save space and look tidy. I want a TRUE circular arrangement
> specifically (not just an arc) because it makes the direction of play —
> and the J's reverse effect — visually intuitive: you should be able to
> see which way the circle is "flowing."

Confirmed scope decisions (already settled, don't re-litigate these):
- The circular table is an ADDITIVE overview. The existing bottom panel
  (your blind/face-up/hand rows, the pickup button, multi-select — all of
  `GameScreen.jsx`'s `you-area` section) stays exactly as it is today,
  unchanged, below the new table. You still play from there.
- The compact "face-up peeking out over blind" stacked visual applies to
  EVERY seat in the circle, including your own — so your seat in the circle
  shows the same compact preview everyone else's does, even though your
  real interactive rows are separately visible below. This is intentional
  redundancy for visual consistency, not a mistake.
- Hand (layer 3) is NOT part of the compact per-seat stack visual for
  anyone. Opponents' hand stays a plain count (however it's currently shown
  — `✋{hand_count}`). Your own hand isn't shown in the table at all, only
  in your panel below.
- The dealing "machine" is a one-time COSMETIC client-side animation only.
  The server already deals everything instantly in one shot at match start
  (see `backend/app/engine/game.py`'s `Game.__init__`) and that does NOT
  change — no protocol changes, no engine changes, no new WS messages. The
  client already receives the fully-dealt state on the first snapshot; this
  animation just visually replays a plausible dealing sequence using data
  that's already fully known, then settles into showing the real state.
  Purely presentational, zero risk to the rules work from earlier sessions.
- Design and test for 2–5 players. The engine technically supports more via
  two-deck games, but that's not going to be used — don't spend effort
  making 6+ players look good in this layout.

## Current structure (read the real files, this is a summary not a spec)

`frontend/src/screens/GameScreen.jsx` currently renders, top to bottom:
header → `<section className="opponents">` (a horizontal arc of
`OpponentSeat` — name, avatar, hand/blind counts, tiny face-up cards,
current-turn gold highlight via `.opponent--current`) → turn banner →
seven-constraint / pending-follow-up banners → `<section
className="table-center">` (draw deck pile + discard pile, side by side) →
event log line → `<section className="you-area">` (your three rows,
fully interactive).

The motion system (`runMotion` in `GameScreen.jsx`, `.flight`/`.burn-ghost`
CSS in `App.css`) animates played cards flying from wherever they were
tapped (or from `seatRefs.current[player_id]` for opponents) to
`discardRef` — the discard pile's DOM rect, read live via
`getBoundingClientRect()`. This means the discard pile can visually move
anywhere on screen without breaking that system, AS LONG AS `discardRef` is
still attached to wherever it visually ends up, and `seatRefs` still
correctly maps each opponent's player_id to their new seat position in the
circle. Both are load-bearing — verify both still work after your changes,
don't just assume it composes.

## Task 1 — the circular table

Turn the opponents arc + table-center into one circular arrangement: the
draw deck and discard pile sit in the visual center, and every player
(including you) occupies a seat evenly spaced around a true circle —
compute positions with actual angle math (e.g. `cos`/`sin` of `2π ×
index/seatCount`, offset so your own seat anchors at a fixed position,
bottom-center makes sense since that's nearest the existing interactive
panel below), not a flex row with staggered offsets like the current arc
does. This needs to hold up at 2, 3, 4, and 5 total players — don't
hardcode for exactly 4 just because the reference sketch shows 4.

Each seat shows: name/avatar (as now), the compact stacked visual for
blind+face-up (three columns, each a slightly-offset overlap of a face-down
card behind a face-up one — reuse the existing `Card` component for both
layers, just position them overlapping via CSS rather than in two separate
rows), a plain hand-count indicator, and the current-turn highlight
(generalize the existing `.opponent--current` gold-glow pattern to also
apply to your own seat when it's your turn — right now that class only
ever applies to opponents).

Add a visual indicator of play direction around the circle itself — an arc,
an arrow, a highlighted path between the current seat and the next one in
turn order, whatever reads clearly — driven by `gameState.direction` (`1` =
clockwise, `-1` = reversed; the existing header chip already shows this as
a static ⟳/⟲ icon, this should be a real part of the table now, not just an
icon). This is the actual point of going circular per the design brief
above — a J's reverse should be visibly legible as "the flow just changed
direction," not just an icon flip.

Preserve, don't touch: the `seatRefs` ref-registration pattern for
opponents (flight animations depend on it locating each opponent's DOM
position correctly — if you restructure how opponent seats render, keep
registering into `seatRefs.current[player_id]`), `discardRef`/`blindRowRef`
wiring, the `.card--power`/`.card--rejected`/`.card--selected`/
`.card--dimmed` classes and what reads them, and everything in the
`you-area` section below (don't restructure it, don't move it).

## Task 2 — the one-time dealing animation

Trigger: this must play ONLY on a genuine fresh match start, never on a
reconnect or page reload mid-game. `App.jsx` already has exactly this
signal — `LobbyScreen`'s `onStarted={() => setStage('game')}` (around line
74) is the one path that means "a match just began." A reconnect or direct
load instead resolves `stage` via the room-status check earlier in
`App.jsx` (line ~23) without ever calling `onStarted`. Thread a prop through
so `GameScreen` can tell the two cases apart, and only run the animation
in the fresh-start case.

Sequence: using the already-known final dealt state from the first
snapshot (no new data needed — you already know exactly what's in
everyone's blind/face-up/hand), animate cards flying from the center deck
out to each seat, round-robin by layer then by seat: one blind card to each
seat in turn (repeat 3×, all face-down — including to your own seat, you
don't know your blind cards either), then one face-up card to each seat in
turn (repeat 3×, revealed/face-up as they land, same as they're publicly
visible for real), then one hand card to each seat in turn (repeat 3× —
face-down flights landing in opponents' hand-count area, but landing
face-up/revealed specifically in YOUR OWN hand panel below, since only you
can see your actual hand). Reuse the existing flight-ghost visual approach
(`.flight`, fixed-position, `pointer-events: none`, transform-based) as the
pattern for these ghosts, but build this as its own self-contained
component/sequence — it's a scripted one-shot animation with its own
lifecycle, not another case bolted onto the existing event-driven
`runMotion` (that system reacts to one server event at a time; this needs
to run a whole pre-known sequence up front).

Pace it so the whole thing takes a few seconds, not 30 — a 5-player game is
5 seats × 9 cards = 45 individual card landings; batch/stagger them so it
reads as a deal, not a slideshow. Handle the edge case where real game
events could start arriving over the WebSocket before the animation
finishes (an eager player could act fast) — don't let a real event get
silently lost or double-rendered; decide whether to queue incoming events
until the animation completes or make the animation fast/interruptible
enough that this is a non-issue, and say which you did and why.

## Before you're done

1. `npm run build` clean.
2. Visual check at 390px width for 2, 3, 4, and 5 simulated players —
   confirm the circle actually holds together at each count, doesn't
   overlap the header or the banners above the table-center's old
   position, and doesn't collide with the you-area panel below it.
3. Confirm the direction indicator visibly flips when direction reverses
   (rig a game state with `direction: -1` and check it, don't assume).
4. Confirm a real play still flight-animates correctly from an opponent's
   new circular seat position to the (now recentered) discard pile — this
   is the regression most likely to silently break.
5. Play through the dealing animation at least once end to end and confirm
   it settles into the exact real state afterward with no mismatch or pop.
6. Confirm a reconnect mid-game does NOT replay the dealing animation.
7. Report back what you built, any judgment calls you made on the parts
   left open above (seat-anchor angle, exact pacing, the mid-animation
   real-event handling), and screenshots if you can capture them.
