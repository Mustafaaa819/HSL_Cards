# Face-up promotes into hand + visible blind reveal

## Context (read before writing any code)

Both changes are in `frontend/src/screens/GameScreen.jsx`. No backend changes
are needed for either — verified by reading `backend/app/routers/game_ws.py`
and the engine directly (see below). Do not touch backend files in this pass;
if you find yourself editing `backend/`, stop, that's a sign of scope creep.

### Change 1: face-up cards render as hand once active, not as a separate row

Current structure (~line 620 onward): three `you-row` blocks — `blind`,
`face_up`, `hand` — each independently rendering its own array
(`you.blind_count`, `youFaceUp`, `youHand`) with its own dimming logic keyed
off `you.active_layer`. The face-up row currently renders small (`size="sm"`)
cards in a plain flex row, separate from the hand's fan-row/multi-row layout
(`handRows`, built ~line 392 off `HAND_ROW_MAX`, with per-row fan rotation
math ~line 707 in the render).

`you.face_up` is the real, live, server-authoritative array — it already
shrinks as cards are played from it once `active_layer === 'face_up'`, same
as `you.hand` does. Card-id tracking already treats both namespaces as
first-class: the selection-pruning effect (~line 328) builds `validIds` from
*both* `hand-${spec}-${i}` and `faceup-${spec}-${i}`, so nothing needs to
change there.

**What to build:** once `you.active_layer === 'face_up'`, render `youFaceUp`
through the exact same rendering path currently used for `youHand` — same
`handRows`-style row-splitting (`HAND_ROW_MAX`, evened-row logic), same fan
rotation/lift math, same `size="md"`, same `Card` props shape (`dimmed`,
`selected`, `rejected`, `onClick={(e) => tapCard(id, spec, e.currentTarget)}`),
same `hand-header` controls (`Throw multiples`, `Pick up pile`). Keep the
`faceup-${spec}-${i}` id prefix (not `hand-${spec}-${i}`) so the existing
pruning effect keeps recognizing these ids without changes.

Concretely: generalize the sourcing so one row-building computation take
whichever array is active —

```
const activeLayer = you.active_layer
const activeCards = activeLayer === 'hand' ? youHand
  : activeLayer === 'face_up' ? youFaceUp
  : []
const activeIdPrefix = activeLayer === 'face_up' ? 'faceup' : 'hand'
```

— and drive the existing `handRows`-building block and the hand-section JSX
off `activeCards`/`activeIdPrefix` instead of hardcoding `youHand`/`'hand'`.
The section's caption should read `hand · {activeCards.length}` regardless of
which layer is actually feeding it — from the player's point of view during
face-up play, it just *is* their hand now.

**The old `face_up` row's fate:** once `active_layer === 'face_up'`, the
dedicated small face-up preview row is redundant (its cards moved into the
hand section above) — collapse it to nothing, or show a `cleared` placeholder
consistent with how the hand section already shows `empty` when `youHand`
is empty (~line 745, `{youHand.length === 0 && !dealing && <span
className="row-empty">empty</span>}`). Match that pattern rather than
inventing new copy.

**Scope boundary — do not touch:**
- The `blind` row/logic. Blind stays flip-only, never gets folded into hand.
- `TableSeat` (~line 853, opponent rendering). Opponents' face-up cards are
  public information regardless of whose active layer it is — they already
  render correctly as small on-table icons via `player.face_up`, and that's
  unrelated to how *you* interact with *your own* active layer. Leave it
  alone.
- The deal-animation script (`dealScript`, ~line 237) and its
  `yourRowFor = { blind: blindRowRef, face_up: faceUpRowRef, hand:
  handRowRef }` mapping — that only runs once at match start, before any
  layer promotion is possible. No interaction with this change.
- `tapCard` (~line 425) and the "never block a tap on legality" behavior
  (~line 407 comment). This is intentional, already correct, and is *why*
  the screenshot showed an "8C is not in your hand" toast — the player
  tapped a face-up card while their hand still had cards (so `active_layer`
  was still `'hand'`), the tap went through per the existing design
  philosophy, and the server correctly rejected it. That is not a bug. Do
  not add client-side tap-blocking as part of this change.

### Change 2: blind flips reveal to everyone before resolving

Verified the backend already broadcasts the true flipped card to every
connected player on every flip, played or not:
`backend/app/routers/game_ws.py`, `_flip_event()` (~line 292) always sets
`"card": str(result.card)`, with a comment confirming this is deliberate
("The flip event is what reveals the card to the table — state payloads
never carry blind values"). `_broadcast_state()` (~line 373) sends the same
unfiltered `event` dict to every socket in the room; only the `state`
snapshot is per-player filtered. **No backend change needed for this
feature** — the data is already there, this is purely about what the
frontend does with `event.card` on a `flip` event.

Current frontend gap, in `runMotion` (~line 139 in `GameScreen.jsx`): a flip
that lands on the pile (`event.played`) gets a flight animation showing the
real card — but only because it hits the same branch normal plays use
(~line 152). A flip that fails (`event.picked_up`) triggers *no visual at
all* — the log line (`describeEvent`, further down the file) is the only
place the card value currently surfaces for that case.

**What to build:** intercept `flip` events before any existing resolution
logic runs. Split the current `runMotion` body into two pieces:

1. `runMotion(event, state)` — the new entry point. If `event.kind ===
   'flip'`, show a new large centered reveal (state shape `{ card, id,
   playerId }`), then after `BLIND_REVEAL_MS` (2000, add alongside the other
   duration constants ~line 20) clear the reveal and call
   `resolveMotion(event, state)`. For every other event kind, call
   `resolveMotion(event, state)` immediately, unchanged from today.
2. `resolveMotion(event, state)` — the *existing* `runMotion` body,
   unmodified: burn/fire branch, flight branch, powerFx (2/7/J) branch,
   forced-flash branch. This still receives `flip` events exactly as before,
   just 2 seconds later than today.

Keep `setLastEvent(event)` and the toast/dealing-cancel logic in the
`onEvent` callback (~line 208) firing immediately, not delayed — the log
entry and error-clearing should not wait on the reveal.

**Reveal presentation:** large card, centered over the table (not
per-seat — the opponent arc markers are too small on a phone screen to be
legible for this). Caption it with whose flip it is (`${name} flips
blind`-style, reuse `nameById` the same way `describeEvent` already does).
`pointer-events: none` on the overlay, consistent with how every other
transient effect layer in this file is built (see the comment at ~line 96:
"nothing here ever blocks the next tap") — this can't be the only thing
running at once (game state keeps moving), so don't let it eat input.

**Chained flips (a flipped 2 auto-chains into the next blind flip per the
existing rule engine — `Game.pending_throw`/`_arm_followup` in
`backend/app/engine/game.py`, already shipped, do not touch):** a second
`flip` event can legitimately arrive while the first reveal is still
holding. Do not clobber the first reveal the way `burn`/`powerFx` clobber
each other (those use a `Date.now()` key and reset the timer, which is fine
for effects nobody's reading text off). A reveal getting silently skipped
mid-chain means a real blind card never gets shown before it hits the pile —
queue reveals FIFO instead: an array of pending `{ card, id, playerId,
event, state }` entries, show one at a time, `resolveMotion` for entry N
firing only after entry N's 2-second hold completes, then immediately
starting entry N+1's reveal if the queue isn't empty.

**Resolution after the reveal:**
- If `event.played` (the flip legally beat the pile): resolve exactly as
  `resolveMotion` already does today — reuses the existing flight-to-pile
  (or burn-fire, if it's also `pile_burned`) unchanged.
- If `event.picked_up` (failed flip, swept into the flipper's hand): there's
  currently no animation for this at all anywhere in the codebase. Add one —
  reuse the existing `flights` ghost mechanism's shape but aim it at the
  flipper's own area instead of the pile: destination `rectOf(youAreaRef.current)`
  if `event.player_id === myId`, else `rectOf(seatRefs.current[event.player_id])`
  — i.e. swap `to`/`from` relative to how a normal flight works. Same rough
  duration as `FLIGHT_CLEANUP_MS` (450ms) so it doesn't feel like a separate
  new animation language, just a flight that goes the other direction.

**Respect `prefers-reduced-motion`** the same way every other effect in this
file already does (grep the existing `@media (prefers-reduced-motion:
reduce)` block in `App.css` and extend it) — for the reveal specifically,
reduced motion should still *show* the card (the information matters,
someone flipped a real card) but skip the pop/scale entrance and hold it
statically for a shorter beat, not for the full 2000ms, since motion is what
reduced-motion users are opting out of, not information.

## Verification expected afterward

- Trigger a normal hand-phase pickup that empties a hand down to zero with
  face-up cards still present (or the seeded-deal approach used to verify
  the last animation pass — `HSL_DEAL_SEED`, add and remove the same way,
  confirmed clean removal last time via `git diff -w`). Confirm face-up
  cards render in the hand section, full size, fan rows, with working
  `Throw multiples` and `Pick up pile`, and the old face-up row shows
  `cleared`.
- Confirm a mistaken tap on a *still-inactive* face-up card (hand not yet
  empty) still produces the existing rejection toast — i.e. confirm nothing
  about the "never block on the client" behavior changed.
- Trigger a blind flip that plays legally, one that gets picked up, and (if
  feasible with the seed hook) a flipped 2 chaining into a second flip — the
  second reveal should show only after the first one's 2-second hold and
  resolution finish, never simultaneously.
- Confirm `prefers-reduced-motion: reduce` still shows the revealed card
  (not skipped entirely) but with a shorter hold and no entrance animation.
- Run `backend/`: `pytest` to confirm zero engine changes were needed (it
  should report the same 148 passed with an empty `git diff` against
  `backend/`, matching the last two passes).
