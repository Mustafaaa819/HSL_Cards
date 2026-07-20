# Power card play animations + real fire for the 10-nuke

## Context (read before writing any code)

All motion for played/flipped cards funnels through one function:
`runMotion(event, state)` in `frontend/src/screens/GameScreen.jsx` (currently
starts around line 108). It's called from the `onEvent` callback of
`useGameSocket` every time a server event lands. Right now it has exactly two
branches:

1. `event.pile_burned` (the 10-nuke) → `setBurn({ id, spec, rect })`, cleared
   after `BURN_CLEANUP_MS` (750ms, top of file). Rendered as `.burn-ghost`
   (`App.css` ~line 861), which fakes fire with CSS filters
   (`sepia`/`hue-rotate`/`brightness`) on a scaling, fading card ghost — see
   `@keyframes burn-away`. A companion `.discard-stack--burning::after` ring
   flashes on the pile slot itself (`@keyframes burn-ring`).
2. Every other play/flip → a `flights` entry, a card that visually flies
   from its origin (hand, seat, blind row) to the discard pile
   (`.flight` class, straightforward translate+scale).

2, 7, and J currently get **no special treatment** — they use the same plain
flight as a normal numbered card. Their only permanent visual distinction is
the gold border/glow already applied to power cards generally (see
`Card.jsx`, `parseCard(spec).power`).

Card rank/power lookup already exists in `frontend/src/cards.js`:
`parseCard(spec)` returns `{ rank, symbol, red, power }`. `power` is true for
ranks `2`, `7`, `10`, `J` (`POWER_RANKS` set at the top of that file). Use
`parseCard(event.card).rank` to branch — do not re-derive rank parsing.

The direction indicator already exists: a chip in `.game-header`
(`{gameState.direction === 1 ? '⟳' : '⟲'}`) and a `DirectionRing` component
(~line 824) that draws tick marks around the table keyed by `direction`. J
already reverses `gameState.direction` server-side and the ring re-renders on
that change — what's missing is a *momentary* animated beat at the instant J
lands, not the direction state itself.

A Lottie fire animation has been placed at
`frontend/src/assets/animations/fire.json` (30fps, 500×500, orange-red,
Lottie JSON format, ~56KB). No Lottie-capable package is in
`frontend/package.json` yet — `lottie-web` needs to be added
(`npm install lottie-web` from `frontend/`). Use its plain imperative API
(`lottie.loadAnimation({ container, animationData, loop: false, autoplay:
true })`) rather than a React wrapper library — this codebase already manages
transient animation state via `useState`/`useRef` + manual cleanup timers
(see `burnTimer`, `flashTimer` patterns), so a React-idiomatic Lottie wrapper
would be an inconsistent second pattern for the same job. Match the existing
style.

## Decisions already made (do not re-litigate these)

- **10-nuke: full replace, not layered.** The current CSS `burn-away`
  scale/fade/filter effect is being replaced outright by the real Lottie fire
  animation, not layered on top of it. Remove the `sepia`/`hue-rotate`
  filter trickery from `@keyframes burn-away` — the point of the real asset
  is to stop faking fire with color filters. The played card should still
  render (so players see what actually burned), the Lottie fire animation
  plays over/around it, and the card finishes with a distinct "pop" —
  a quick scale-up + fade-out (roughly 120–180ms, ease-out) — timed to land
  as the fire animation completes, not before or independently of it. Total
  effect duration should replace `BURN_CLEANUP_MS` (750ms) with whatever
  duration correctly fits `fire.json`'s actual frame count/fps (30fps, `op:
  30` in the JSON → 1 second at native speed; measure against the real file,
  don't assume) plus the pop tail.
- **2/7/J: use this exact scheme**, color-coded, motion-only (no palette
  changes, everything themes off existing CSS custom properties):
  - **2 (reset):** a blue pulse ring on the discard pile slot, similar
    mechanism to the existing `.discard-stack--burning::after` ring but blue
    (`--safe` is teal, not blue — introduce a one-off blue via
    `color-mix`/a scoped variable, don't repurpose `--safe` or `--gold`).
    Since a 2 is often immediately followed by a forced bonus throw
    (`Game.pending_throw` on the backend — see project CLAUDE.md), the pulse
    should read as "the pile just cleared, you're not done yet," not as a
    completion beat.
  - **7 (under-power):** a green ripple on the pile plus a small temporary
    badge/chip near the discard pile reading "≤7" that appears with the
    ripple and fades after a few seconds (this doubles as the "current rule"
    surfacing that's currently missing from the UI entirely — reuse this
    same badge for the general rule-indicator gap if you also implement that
    from the earlier phase-prompt list; if not doing that in this pass, this
    badge only needs to appear for the 7's own effect window, not
    persistently).
  - **J (reverse):** an animated arrow flash plus a stronger, momentary pulse
    on the existing `DirectionRing` (not a new ring — animate the existing
    one, e.g. a brightness/scale keyframe pass across its tick marks) timed
    to the direction actually changing.
  - **10 (nuke):** the Lottie fire, per above. No separate treatment needed
    beyond that.

## What to build

1. `npm install lottie-web` in `frontend/`.
2. Import `fire.json` in `GameScreen.jsx`
   (`import fireAnimation from '../assets/animations/fire.json'`) and wire a
   `lottie-web` instance that plays once into a `ref`-attached container
   positioned over the discard pile (`discardRef`/`rectOf(discardRef.current)`
   — same rect math already used for `burn`). Load/destroy the animation
   instance per play (don't leak instances — call `.destroy()` in cleanup,
   mirroring the existing `clearTimeout(burnTimer.current)` pattern).
3. Rewrite the `event.pile_burned` branch in `runMotion` to drive the new
   fire+pop effect instead of the old CSS-filter ghost. Update/remove
   `@keyframes burn-away`'s color-filter steps in `App.css` accordingly —
   keep only the pop scale/opacity, or replace with the new pop keyframes
   described above.
4. Add a new branch (or extend the existing non-burn branch) in `runMotion`
   that checks `parseCard(event.card).rank` for `'2'`, `'7'`, `'J'` on any
   `event.kind === 'play'` and triggers the corresponding effect state (new
   `useState` per effect or one shared `powerFx` state shaped like
   `{ rank, id, rect }`, cleared on its own timer the same way `burn` and
   `forcedFlash` already are). These effects run *in addition to* the normal
   card flight for that card — the card still visibly travels to the pile,
   the pile/ring/badge reacts alongside it.
5. Respect the existing `prefers-reduced-motion` handling — grep `App.css`
   for the current reduced-motion block (it already disables `.burn-ghost`,
   `.discard-stack--burning::after`, and flights) and extend it to cover the
   new fire/pop/pulse/badge effects the same way.
6. Keep effect colors on existing CSS custom properties (`--danger`,
   `--gold`, `--safe`, `--felt`, etc.) wherever plausible; the one exception
   is the 2's blue, which is a new token since nothing existing is blue —
   name it clearly (e.g. `--reset-blue`) and add it to the `:root` block in
   `index.css` next to the other tokens, with a one-line comment explaining
   what it's for (matching this codebase's existing token-commenting style).

## Verification expected afterward

- Play each of 2, 7, 10, J (deck phase is easiest — draw into a hand with
  power cards, or briefly stack the test deck) and confirm each fires its
  distinct effect, not just the generic flight.
- Confirm the fire animation actually plays at the discard pile's real
  screen position at various card counts/table sizes (2 vs 5 players), not
  just at one fixed layout.
- Confirm `lottie-web` instances are destroyed after each play — no
  detached DOM nodes or growing memory after firing several nukes in a row
  (open devtools, play several 10s back to back, check node count doesn't
  climb).
- Confirm `prefers-reduced-motion: reduce` suppresses all of the new effects
  the same way it already suppresses the flight/old burn effects.
- Run the existing test suite (`backend/`: `pytest`) to confirm nothing here
  touched engine logic — this should be a pure frontend/visual change, no
  `game.py` edits expected. If any get touched, that's a signal scope crept
  beyond what was asked.
