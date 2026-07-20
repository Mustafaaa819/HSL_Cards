# Two small tweaks: lighten the background a bit, wrap the hand to a second row

Both are minor, targeted changes on top of the table declutter pass that
just shipped — don't restructure anything else while you're in here.

## Tweak 1 — background a little lighter

Current tokens (`frontend/src/index.css`): `--bg: #14181a`, `--surface:
#1c2225`, `--surface-raised: #232b2e`, plus the `body` background gradient
that fades the emerald `--felt` tint out to near-black at the edges (lines
~43-54). The person playing this wants it a LITTLE lighter/richer overall
— not a light theme, just less near-black. Nudge `--bg`/`--surface`/
`--surface-raised` up somewhat (a modest lightness increase, not doubling
them) and/or let the felt-green tint carry further out into the gradient
before fading to `--bg`, so the room reads a bit brighter without becoming
a different theme.

Standing constraint, same as every pass before this one: card-carrying
surfaces (`--card-face` and anything the real SVG card art sits on) must
stay dark enough that the white/red ink art stays legible. Check this by
looking at the actual rendered cards against the new background, don't
assume a small token nudge is automatically safe.

## Tweak 2 — wrap the hand to a second row instead of horizontal scroll

The hand is currently one continuous fan (`.hand-fan` / `.fan-card` in
`App.css`, rendered from `youHand.map(...)` around line 601 in
`GameScreen.jsx`) — each card rotated and overlapped via negative margin,
scrolling horizontally (`.row-cards--hand { overflow-x: auto }`) once it
outgrows the row. With a big hand (a picked-up pile can easily put 6-9+
cards in hand), that scroll is exactly the clutter being complained about
— the ask is a second row instead, so the whole hand is visible at once.

This isn't a simple `flex-wrap` — a continuous rotate+negative-margin fan
doesn't reflow cleanly across a wrap the way normal block content does.
The straightforward approach: figure out how many cards comfortably fit in
one row at the current card width/overlap (`card--md` width minus the
per-card negative margin already in `.fan-card + .fan-card`), then chunk
`youHand` into groups of that size and render each chunk as its OWN
independent, self-contained fan row (each row centered on its own, same
rotation/overlap logic reset per row — reads as two neat rows of cards,
not one fan awkwardly broken mid-arc). Stack the rows with a small gap.
Use your judgment on the exact per-row count and whether it should be a
fixed number or computed from actual available width — a fixed sensible
number (e.g. whatever comfortably fits at 390px) is fine if computing it
live is overkill.

This must not regress anything already working in the hand:
- Every card keeps its own reliable tap target, in either row.
- Multi-select (`Throw multiples`): `selected`/`dimmed`/`rejected` states
  must keep reading clearly regardless of which row a card lands in, and
  selecting/deselecting must work identically across both rows.
- The flight-ghost animation's tap-position lookup (`pendingTapRef`) must
  still resolve the correct on-screen position of whichever card was
  actually tapped, in either row — verify this specifically, it's the
  easiest thing to silently break when a single row becomes two.
- `prefers-reduced-motion` handling stays intact for anything already
  covered.

## Before you're done

1. `npm run build` clean.
2. Rig a hand with 7-9+ cards, confirm it visibly splits into two rows
   instead of requiring horizontal scroll, at 390px width.
3. Confirm tapping a card in the second row plays it correctly, and that
   multi-select still works with selections spanning both rows.
4. Confirm the background change reads as "a bit lighter," not a different
   theme, and that card art is still clearly legible everywhere.
5. Screenshot both changes if you can.

## Deploy after

Same as every session: `npm run build`, copy `dist/*` into `backend/static`,
restart `uvicorn` — do this yourself, don't leave it as a manual step.
