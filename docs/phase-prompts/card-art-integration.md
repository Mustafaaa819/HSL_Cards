# Phase prompt: integrate real card art

## Context
`frontend/src/assets/cards/` now has 52 real SVG card faces (no jokers — deck
is a plain 52). They're a recolor of Chris Aguilar's LGPL-3.0 "Vector Playing
Card Library" v3.2, using his own official "Inverted" color mapping (not a
guessed palette) — details and the exact hex table are in
`frontend/src/assets/cards/NOTICE.md`. Backgrounds are transparent by design,
so they sit on whatever the card container already renders.

Filenames match the wire spec from `docs/WS_PROTOCOL.md` exactly:
`<rank><suit>.svg` — ranks `2 3 4 5 6 7 8 9 10 J Q K A`, suits `C D H S`.
E.g. `10H.svg`, `AS.svg`, `JC.svg`, `2D.svg`.

## What to change
`frontend/src/components/Card.jsx` has this comment on the component, still
true and still the scope boundary:

> A later phase swaps the placeholder face (rank + suit text) for real SVG
> card assets here, and nowhere else.

Only touch the face-rendering branch (`hidden === false`, roughly lines
52–66). Do NOT touch:
- the `hidden` branch / `BackPattern` (card backs, `cardback.js`) — untouched, unrelated to this phase
- `parseCard` / `cards.js` — the spec format is already correct
- `card--red` / `card--black` / `card--power` / `card--rejected` / `card--dimmed` classes — keep them, the new art still needs these signals layered on top (see below)

### Steps
1. Load the asset map with Vite's glob import. This project is on Vite 8, so
   use the current syntax, not the deprecated `as: 'url'` form:
   ```js
   const cardFaces = import.meta.glob('../assets/cards/*.svg', {
     eager: true,
     query: '?url',
     import: 'default',
   })
   ```
   Build a `spec -> url` lookup keyed off the filename (strip the path and
   `.svg`).
2. In the face branch, replace the `card-rank` / `card-suit` spans with the
   image, sized to fill the card:
   ```jsx
   <img src={cardFaces[spec]} alt="" className="card-face-art" draggable={false} />
   ```
   (`alt=""` because the `aria-label` on the outer `Tag` already carries
   `${rank}${symbol}` — don't double up.)
3. Add `.card-face-art { width: 100%; height: 100%; object-fit: contain; }`
   to `App.css`.
4. `.card--face` currently sets `background: var(--card-face)`. That token
   will now show through as the card's backing color behind the transparent
   SVG — check what it resolves to and whether it still looks right, or
   whether it should become `transparent` so the app's own dark background
   shows through instead. Decide by looking at it, not by guessing.
5. Leave `.card--power` (gold glow border) and `.card--rejected` (red glow
   border) alone — they're on the outer container, not the art. But
   specifically check contrast: some face-card art has light borders close to
   the card edge, and the gold/red glow needs to still read clearly against
   it, especially at `card--xs` (24×34px, opponents' minis).

## Known risk, flag it rather than silently accepting it
At `card--xs` (24×34px) the fine line art on face cards (K/Q/J portraits) may
not be legible — it might just look like noise at that size. If it's
illegible, decide whether that's acceptable (opponents only need to see
suit+color, not full detail) or whether `xs` needs a simplified rendering.
Don't ship it without actually looking at it rendered at 24×34px first.

## Testing
- Visual pass at 390px viewport (this project's standard first test width).
- Check all four sizes: xs (opponent minis), sm (own blind/face-up rows), md
  (own hand), lg (discard pile top card).
- Specifically verify: a power card (any 2/7/10/J) still shows the gold glow
  clearly, a rejected-card animation still shows the red glow clearly, a red
  suit (H/D) and black suit (C/S) are both legible against the card
  background.
- Card backs are out of scope for this phase — confirm they're visually
  unchanged (regression check only, not new work).
