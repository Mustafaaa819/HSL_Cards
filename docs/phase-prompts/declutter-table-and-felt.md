# Declutter the table: fewer boxes, richer felt, optional table texture

## The actual complaint

Live feedback, verbatim: "these Furqan and Mustafa boxes on the top and
bottom of this round table, they are creating noise... it feels so bad."
Looking at the real screenshot, the vertical stack right now is: game
header, turn banner (own bordered glow box), the opponent seat (own
bordered box), the felt ellipse (own bordered box), YOUR OWN seat in the
ring (own bordered gold-glow box), then the full `you-area` panel right
below it (own bordered gold-glow box) showing blind/face-up/hand. That's
five-plus stacked bordered/glowing containers competing for attention, and
two of them — your ring seat and your `you-area` panel — show the SAME
information (your status) twice. That redundancy is the single biggest,
most concrete thing to fix here.

## Task 1 — stop showing "you" twice

Remove your own seat from the circular ring entirely. The ring
(`.round-table` / `TableSeat` in `GameScreen.jsx`) should only render
OPPONENTS going forward — your own status lives exclusively in the
`you-area` panel below, which already shows it in full (blind/face-up/hand,
not just the compact preview). Update `seatCount`/`seatPos` math
accordingly (positions should be computed over the opponent list, not
`gameState.players`, since there's one fewer seat to place — recheck the
angle math, don't just leave a gap where your seat used to be). The
direction ring / chevrons still matter and stay — they still need to
visually indicate where you'd be in the flow even though your seat isn't
drawn, so anchor the ring's implied "your position" the same way it does
now (bottom-center), just without a seat marker occupying it.

## Task 2 — strip boxes from idle seats, keep one for whoever's acting

Right now every seat gets the same bordered/backed glass panel whether or
not anything is happening. Reference `#1a` in
`docs/phase-prompts/design-refs/table-options-1a-1b-1c.html` doesn't give
each opponent their own box at all — they're just avatar + label + mini
cards sitting inside ONE shared, calm surface (the felt), with no visible
border around each individual player. Bring that here: an idle opponent's
avatar/name/stack should read as a light marker directly on the felt — no
separate background panel, no border, no glow. Reserve the actual "boxed,
glowing" treatment for ONLY the current-turn seat (`seat--current` already
exists for this) — that's the one moment a container should visually
announce itself. Everyone else should visually recede into the table, not
compete with it.

## Task 3 — richer felt, not near-black

`--bg`/`--surface` are currently very close to pure black
(`#14181a`/`#1c2225`), and every one of those stacked boxes is a slightly
different near-black shade — that sameness is part of what reads as
"cluttered" rather than "layered." Move the table surface itself (the
`.round-table::before` felt, and consider the page `body` background too)
toward a richer, more saturated dark tone — a deep forest/emerald green
felt is the traditional card-table color and pairs naturally with gold,
or a warm dark wood-brown if that fits the table texture better (see Task
4). This is NOT a shift to a light theme — the person you're building
this for was explicit that going light breaks the card art (white/red ink
line work needs a dark card face to read at all) and would clash with
every other screen. Keep card-carrying surfaces (the cards themselves, any
panel that directly holds cards) dark enough that the existing art stays
legible — verify this by actually looking at it, the same way legibility
was checked in the last two passes, not by assuming a slightly lighter
green still works.

## Task 4 — the table texture image (conditional, has a fallback)

A wood-rimmed oval poker table image (chips and cards scattered around a
brown wood border, currently a WHITE/opaque fill in the middle, not
transparent) may or may not exist at
`frontend/src/assets/table/table-frame.png` by the time you run this —
check first. If it's there:
- Use it as a decorative frame/texture behind or around the round-table
  area — the wood-and-chips border is the useful part.
- Its white interior WILL look broken if left as-is against a dark UI —
  mask or overlay it (e.g. a dark radial-gradient scrim over the center,
  or `mix-blend-mode`/`background-blend-mode` tricks) so only the
  decorative border rim shows and the interior stays the dark felt color
  from Task 3. Don't ship a visible white oval in the middle of a dark
  game screen — check the actual rendered result, not just that the
  `<img>`/background-image tag is wired up.
- If masking it convincingly is a fight, it's fine to use it as a subtle
  low-opacity border/vignette only rather than a literal full table
  photo — use judgment, a bad attempt at this looks worse than skipping it.

If the file is NOT present, skip this task entirely and just ship Task 3's
CSS-only felt color — do not block on a missing asset, and say clearly in
your report whether the file was there or not.

## Preserve, do not touch

Everything from the last two passes that already works: `seatRefs`
registration (now scoped to opponents only per Task 1 — update it, don't
break it), `discardRef` wiring, the dealing-animation script (it targets
seat positions live via refs — recheck it still lands correctly now that
your own seat no longer exists in the ring; your own dealt cards should
fly straight into the `you-area` panel below, which they may already do
for your hand layer — verify blind/face-up dealt-to-you cards have a
sensible landing target now too, since they used to land on your ring seat
which is gone), the fanned hand, the `card--selected`/`card--rejected`/
`card--dimmed`/`seat--current`/`seat--forced` classes and everything that
reads them, and the `prefers-reduced-motion` block (extend, don't remove
from).

## Before you're done

1. `npm run build` clean.
2. Screenshots at 390px for 2, 3, 4, 5 players. Specifically check the
   2-player case, since that's the exact screenshot the complaint came
   from — confirm it no longer reads as a stack of near-identical boxes.
3. Count the actual bordered/backed containers visible on screen at once
   in a normal (nobody-acting-unusually) state and confirm it's genuinely
   fewer than before — this is the concrete thing being fixed, don't just
   eyeball it, actually count.
4. Confirm card art is still legible against the new felt color(s) and,
   if used, against the table texture.
5. Confirm the dealing animation still lands every card somewhere sensible
   with your own ring seat removed.
6. Report which fallback path you took on Task 4 (asset present or not),
   and screenshots if you can capture them.

## Deploy after

Same as every session: `npm run build` in `frontend`, copy `dist/*` into
`backend/static`, restart `uvicorn`. Do this yourself as part of finishing
the task, don't leave it for a manual step this time either — last round
you already did this correctly, keep doing it.
