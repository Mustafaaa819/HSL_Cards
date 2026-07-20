# Visual pass: real card art + make the table feel alive

## Read this first — what's actually true about the current state

Don't go in assuming the current frontend is a mess that needs rebuilding. It
isn't. `frontend/src/index.css` already implements the exact design system
from `CLAUDE.md` (tokens: `--bg: #14181a`, `--gold: #c9a15a` reserved for
power cards, `--danger: #c1443b`, `--safe: #3e8e82`, `--card-face`,
`--card-red`, `--card-black`, `--card-back`). `App.css` already has a working
motion layer: card flight animations, a 10-nuke burn effect, an AFK
forced-action flash, a turn-pulse glow, power-card glow, a rejected-card
shake, and a `prefers-reduced-motion` block that correctly disables all of
it. `GameScreen.jsx` is carefully commented and the state/animation wiring
(`runMotion`, flight ghosts, the countdown timer) is deliberate, not
accidental. Read it before changing it.

What's actually missing, and why it reads as "messy" in a screenshot despite
all that: there is no real card art (`Card.jsx` still renders plain rank +
suit text on a flat box — a card game with no card faces looks unfinished no
matter how good the motion underneath is), and the typography promised in
`CLAUDE.md` — "a condensed, high-contrast display face for card ranks... the
ranks carry the personality, the interface stays quiet" — was never actually
built. Everything renders in `system-ui`. Fix those two things and add real
depth (current cards have zero shadow/elevation, the background is a flat
single color with no texture), and most of the "flat and boring" impression
should resolve without a rewrite.

## Scope boundary — read this too

This pass is visual/cosmetic + the card art swap. It is explicitly NOT a
layout restructuring — the three-layer hand, the opponent arc, the
turn-banner logic, the `pending_action` follow-up signal, all stay exactly
where they are structurally. A separate, bigger UX pass is coming in a later
session; don't pre-empt it by redesigning the layout here. If you think the
layout genuinely needs to change to make this work, stop and say so rather
than just doing it.

Do NOT touch: `useGameSocket.js`, any WS/state logic, the `runMotion`
flight/burn/forced-flash system or its existing keyframes (`card-arrive`,
`burn-away`, `burn-ring`, `forced-flash`, `turn-pulse`, `banner-in`,
`card-rejected`), the `prefers-reduced-motion` block (extend it if you add
new motion, don't remove from it), or any class name that JS reads to apply
conditional state (`card--power`, `card--rejected`, `card--selected`,
`card--dimmed`, `turn-banner--*`, `opponent--current`, `opponent--forced`,
`row-caption--active`, etc. — renaming these breaks the JS that toggles
them). Adding new classes alongside them is fine.

## Task 1 — integrate the real card art

`frontend/src/assets/cards/` has 52 SVGs already committed (recolored dark-
theme cards, filenames match the wire spec: `10H.svg`, `AS.svg`, etc.) —
this is what I'm assuming "the black cards" refers to; if you actually meant
a different asset set, stop and flag it rather than guessing further.

Full spec for this already exists at
`docs/phase-prompts/card-art-integration.md` — follow it exactly (Vite glob
import pattern, which lines of `Card.jsx` to touch, what NOT to touch,
the `card--xs` legibility risk at 24×34px that needs an actual look before
shipping, not an assumption). Don't re-derive this from scratch, that doc
is the spec.

## Task 2 — give the ranks a real typeface

`CLAUDE.md`'s design intent: a condensed, high-contrast DISPLAY font for
card ranks specifically (the numbers/letters need to read instantly at a
glance on a small phone screen), paired with the existing plain system font
for everything else (buttons, labels, chrome — leave that alone, the intent
is deliberately "quiet interface, personality in the ranks" contrast).

Pick a real font that fits "condensed, high-contrast, reads instantly at
small sizes" — something in the Bebas Neue / Oswald / Rajdhani / Barlow
Condensed family is the right category, but use your judgment on the actual
choice and justify it briefly. Load it properly (self-hosted or a Google
Fonts `<link>` in `index.html` — this is a live mobile game over a
Cloudflare tunnel, so keep the font-weight count minimal, one or two
weights, not a whole family). Apply it to `.card-rank` only (and check
`.card-suit` still reads fine next to it — suit symbols usually want to stay
in a normal/symbol-safe font, use judgment). Verify it actually renders at
all four card sizes (`xs` 24×34 through `lg` 76×106) before calling it done.

## Task 3 — make it feel alive: depth, not new colors

Current cards and surfaces are completely flat — no shadow, no elevation, no
texture anywhere except the power/rejected/selected glow states. Add real
depth using the EXISTING token palette (shadows/gradients built from
`color-mix()` on `--bg`, `--surface`, `--gold`, etc. — the pattern already
used for the power-card glow — not new hues):

- Base elevation on cards (subtle drop shadow so they lift off the table
  instead of looking pasted flat onto the background).
- Some texture or depth in the table background itself — currently a single
  flat `--bg` fill. A subtle gradient/vignette is the kind of thing that
  makes a "table" feel like a surface instead of a solid color block. Keep
  it subtle — this is a dark, moody palette by design, not a bright one.
  Don't fight that intent.
  - Tap/press feedback on interactive elements (cards, buttons) — there's
  currently no `:active` state anywhere. Mobile-first game with no tap
  feedback feels unresponsive even when it's working correctly. Add a quick
  scale/brightness change on press.
- Consider whether the discard pile, the current-turn opponent highlight,
  and the power-card glow could be MORE visually confident than they are now
  (bigger glow radius, a touch more contrast) without turning into visual
  noise — these are the moments that should grab attention, on purpose.
- Use your own design judgment beyond this list — you have room to actually
  design here, this isn't meant to be an exhaustive checklist. Just stay
  inside the existing token palette and the "quiet chrome, loud signals"
  philosophy rather than introducing a competing color scheme.

Any new animation/transition you add must be included in the existing
`prefers-reduced-motion` block in `App.css`.

## Before you're done

1. `npm run build` clean, no errors.
2. Visual check at 390px width (this project's standard test width, per
   existing conventions) across: entry screen, lobby, and the live game
   screen with a real hand — including the opponent arc, blind/face-up/hand
   rows, the discard pile with a fanned power-card stack on top, and the
   game-over standings overlay.
3. Specifically confirm at `card--xs` (opponent minis, 24×34px): suit/rank
   are still legible with the new font, and face-card (K/Q/J) art isn't just
   noise at that size — this was flagged as an open risk in the original
   integration doc and still needs an actual look, not an assumption.
4. Confirm a power card's gold glow, a rejected card's red shake, and the
   your-turn pulse are all still clearly visible against the new art and any
   new background treatment — these are load-bearing signals, not
   decoration, and must not get visually lost.
5. Toggle `prefers-reduced-motion` and confirm everything (old animations
   AND anything new you added) correctly goes static.
6. Report back with what you actually changed and why, plus screenshots if
   you're able to capture them — I want to review the real result, not a
   description of intent.
