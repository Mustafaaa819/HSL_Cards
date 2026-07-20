# Premium glass table: compact the seats, apply gold glassmorphism

## The actual complaint, precisely

Live on a phone right now: a 2-player game shows two large boxed seat
cards (avatar, full name, 3-column stack, hand count) stacked vertically
with the deck/pile awkwardly sandwiched between them, tall enough that the
page scrolls. It reads as two profile cards with a deck stuck in the
middle, not a table. The name/avatar header on each seat is the single
biggest visual weight on the seat and it shouldn't be — the cards are what
matter.

## Reference material — read this file first

`docs/phase-prompts/design-refs/table-options-1a-1b-1c.html` — open it
directly (plain HTML, no build step, view in a browser or read the
source). It has three real, fully-coded mockups: `#1a` "Tabletop Arc",
`#1b` "Compact List", `#1c` "Glass Premium". Read the actual CSS values in
there (avatar sizing ~42-44px, name text ~10-10.5px and visually
secondary, the felt-strip opponent row, the glassmorphism recipe on `#1c`
— `backdrop-filter: blur()`, translucent panel background, soft border,
layered glow — the fanned/rotated hand-card treatment in every option's
"You" panel).

**Critical translation, don't skip this:** all three mockups are light-
themed (cream/ivory/blue). This app is dark-themed throughout
(`frontend/src/index.css` tokens: `--bg: #14181a`, `--gold: #c9a15a`,
etc. — this is deliberate, documented in `CLAUDE.md`, and everything else
in the app already matches it) and the real card art
(`frontend/src/assets/cards/`) is white/red ink meant to sit on a DARK
card face — it will be illegible on a light background. So: take the
LAYOUT, SPACING, SIZING, and the GLASSMORPHISM TECHNIQUE from the
reference file, but rebuild every color using the existing dark token
system (`--bg`, `--surface`, `--surface-raised`, `--gold`, `--text`,
`--muted`, and `color-mix()` against them for translucency) — never the
literal hex values in the reference HTML. A frosted dark-glass gold panel,
not a frosted white one.

## Scope decision already made, don't re-litigate

Keep the true circular table and the direction ring built last session
(`.round-table`, `TableSeat`, `DirectionRing` in `GameScreen.jsx`) — none
of the three mockups use a circle, but the circular arrangement was
specifically requested to make play direction and J's reverse legible at a
glance, and that reasoning still holds. This pass is about making each
seat dramatically smaller and quieter, not about flattening the table into
a row.

## Task 1 — shrink and quiet every seat

Match the reference's scale, not the current implementation's: avatar
down to roughly the reference's ~40-44px (currently larger), name text
small and visually secondary (~10-10.5px, lower-contrast color — it should
read as a label, not a headline), and cut whatever padding/gap is making
the current seat card feel like a bounded "profile box" rather than a
lightweight marker on the table. The compact stack (blind-peeking-under-
face-up) and hand-count badge stay, just tightened to match. Do this for
every seat including your own — the whole point is the table stops eating
vertical space so it can actually fit without scrolling on a 2-3 player
game.

## Task 2 — glassmorphism, on the dark palette

Apply the frosted-glass treatment (from `#1c` in the reference) to: the
round-table's seat cards (or the table surface itself, use judgment on
which reads better), the center hub (deck + discard), and the bottom
`you-area` interactive panel. Recipe, adapted to dark: a translucent dark
panel (`color-mix()` of `--surface`/`--surface-raised` at partial alpha,
NOT the reference's white-based translucency), `backdrop-filter: blur()`,
a thin light-catching border (low-alpha white or `--gold` at low opacity),
and — for the current-turn / your-turn panel specifically — the heavier
gold glow treatment `#1c` uses (layered box-shadow, richer than what's
there now). Test that `backdrop-filter` actually renders correctly in the
target mobile browsers (Chrome Android at minimum, since that's what's
being played on) — it's not universally supported the same way everywhere,
confirm rather than assume.

## Task 3 — fanned hand cards

Every reference option's "You" panel fans the hand — each card rotated a
few degrees more than the last, overlapping, with the topmost/active one
raised and given its own shadow — instead of the current flat
non-overlapping row. Bring this to the real hand row (`you-row--hand` in
`GameScreen.jsx`). This is not just decorative: it has to stay fully
functional —
- Every card still needs its own reliable tap target despite the overlap
  (stacking order / hit-testing needs to actually work, not just look
  right — test tapping a card that's mostly covered by its neighbor).
- Multi-select mode (`Throw multiples`) still needs `selected`,
  `dimmed` (rank mismatch), and `rejected` states to read clearly on a
  fanned, overlapping card — these are load-bearing signals, don't let the
  fan visually bury them.
- The existing fly-in/flight-ghost animation source position
  (`pendingTapRef`) still needs to originate from the correct fanned
  position of whichever card was actually tapped, not a stale flat-layout
  assumption.

## Optional, only if it's easy — don't chase this if it's a fight

The reference shows a compact rank-constraint pill in the header ("Beat ≥
9" / "Play ≤ 7" / "Play Anything") — a nicer, more glanceable version of
the current plain-text `seven-warning` banner. If it's a clean fit, do it;
if it means restructuring how that state is surfaced, skip it and leave
the current banner alone. Say which you did.

## Preserve, do not touch

Game logic, WS protocol, the dealing-animation script/logic
(`dealScript`, `DEAL_STEP_MS`, etc.) — it reads seat positions live via
`seatRefs`/`deckRef`/`handRowRef` DOM rects, so shrinking seats should
just work automatically, but VERIFY the deal still visually lands in the
right place at the new smaller scale rather than assuming it composes.
Also preserve: `seatRefs` registration, `discardRef` wiring, the
`prefers-reduced-motion` block (extend it for anything new you add, don't
remove from it), and every class name JS reads for state
(`card--selected`/`card--rejected`/`card--dimmed`/`seat--current`/
`seat--forced`, etc.).

## Before you're done

1. `npm run build` clean.
2. Screenshots at 390px width for 2, 3, 4, and 5 simulated players —
   confirm the table no longer forces a scroll on a 2-player game, and
   confirm it still holds together at 5.
3. Confirm real card art is still clearly legible against every new glass
   panel — this was the whole reason the light reference colors couldn't
   be used literally, verify it actually held.
4. Confirm the dealing animation still lands correctly at the new seat
   scale (rig a fresh-start game, watch it, don't just assume).
5. Confirm multi-select (`Throw multiples`) still works correctly on the
   fanned hand: select a card that's partially covered by its neighbor,
   confirm the right one gets selected, confirm `selected`/`dimmed` still
   read clearly.
6. Toggle `prefers-reduced-motion`, confirm everything (existing + new)
   correctly goes static.
7. Report back what you built, which optional pieces you skipped and why,
   and screenshots if you can capture them.

## After this lands

Same deploy step as every other session: `npm run build` in `frontend`,
copy `dist/*` into `backend/static`, restart `uvicorn`. Nothing changes
about that.
