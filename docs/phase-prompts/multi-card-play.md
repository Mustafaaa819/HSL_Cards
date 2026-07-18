# Phase prompt: multi-card (duplicate) plays — backend only

## What this is
`docs/RULES.md` now has a "Multi-card plays (duplicates)" section: a player
may play several cards of the same rank together as one turn action (e.g.
three 6s, or two 7s). This reverses a decision that was explicitly locked in
Phase 1 ("exactly one card per turn") — see the superseded note at the bottom
of `docs/RULES.md`. The engine currently only accepts one card per action.
This phase implements that in the backend engine + WebSocket protocol only.
**Frontend is explicitly out of scope** — see "Non-goals" below.

Read `docs/RULES.md`'s "Multi-card plays" section first; this prompt assumes
you have.

## Files you'll touch
- `backend/app/engine/game.py` — the actual rule change
- `backend/app/routers/game_ws.py` — protocol dispatch + event shape
- `docs/WS_PROTOCOL.md` — document the new wire format
- `backend/tests/test_multi_play.py` — new test file
- Possibly `backend/app/engine/__init__.py` if it re-exports symbols by name (check what it currently exports from `game.py` and keep the export list consistent)

## Engine change (`game.py`)

Add `Game.play_cards(player_id: str, cards: list[Card]) -> PlayResult`.
Refactor `play_card` to call `play_cards(player_id, [card])` internally
rather than duplicating validation logic — they must share one code path so
behavior can't drift between the two.

Validation order (matches the existing single-card method's order, so
existing error-message assertions in the current test suite keep passing
unchanged):
1. `cards` must be non-empty.
2. All cards must share the same rank. Mixed ranks (including mixed power
   ranks, e.g. a 2 and a 7 together) raise `IllegalMoveError` — RULES.md is
   explicit that this is NOT a valid single play.
3. Must be the current player's turn (`_require_turn`, as today).
4. Active layer must not be `Layer.BLIND` (message: reuse the existing
   "You are on your blind cards: flip, don't play" wording).
5. **Every** card in the group must actually be available in the player's
   current active layer (hand or face_up) — check by count, not just
   membership. Two-deck games (6+ players) can have genuine duplicate
   `(rank, suit)` cards, so build an `available` copy of the source list and
   `remove()` one match per requested card; if any requested card isn't
   found, raise `IllegalMoveError(f"{card} is not in your {layer.value}")`
   using that specific missing card. **Validate the full group before
   mutating anything** — don't half-remove cards then discover the 3rd one
   is missing. (Note: engine mutation atomicity-on-exception is already a
   flagged open question project-wide — don't make it worse here by
   partially mutating on a mid-validation failure.)
6. Legality is checked ONCE using a representative card (`cards[0]` — they're
   all the same rank so this is equivalent to checking any of them): reuse
   `is_legal_play` exactly as today, and preserve the existing error wording
   for the 7-constraint and "doesn't beat" cases.
7. On success: remove all cards from the source layer, then apply effects.

**Effects must apply once per group, not once per card** — this is the part
most likely to get quietly wrong. Specifically:
- **J (reverse):** flip `self.direction` exactly once. Two Jacks thrown
  together must NOT cancel each other out by flipping twice — the rule
  explicitly says a group "behaves like the single-card version."
- **10 (nuke):** the existing pile plus the *entire played group* burns, once.
  No bonus turn, same as today.
- **7 (under-power):** `seven_pending` is a boolean, so this is naturally
  correct — just make sure `_end_turn` gets called with a representative card
  of rank "7" so it still sets the flag for exactly the next player.
- **2, plain ranks:** no special effect, all cards just land on the discard
  pile together.

Refactor the existing `_apply_card_effects(card)` into something like
`_apply_group_effects(cards: list[Card])` that extends `self.discard_pile`
(or `self.burned`) with the whole list instead of appending one card, and
have both `play_cards` and `flip_blind` call it (`flip_blind` calls it with
a single-item list — the blind phase is untouched by this rule, see
non-goals, but it can still share the underlying effect-application code).

`PlayResult` currently has a single `card: Card` field. Add a `cards:
list[Card]` field (the full group) without breaking existing call sites —
default it to `[self.card]` if not explicitly passed (e.g. via
`__post_init__`), so every existing single-card call site and test that
constructs or reads a `PlayResult` keeps working unchanged.

## Protocol change (`game_ws.py` + `WS_PROTOCOL.md`)

Keep the existing `{"action": "play", "card": "7H"}` shape working
byte-for-byte identically — the current frontend sends this and must not
need to change. Add a new, alternative shape for the group case:

```jsonc
{"action": "play", "cards": ["6H", "6C", "6D"]}
```

Reject a message that has both `"card"` and `"cards"`, or neither, with a
`ProtocolError` (same family as the existing malformed-card errors).
`"cards"` must be a non-empty JSON array of strings; validate that the same
way `"card"` is validated today (unrecognized card spec → `ProtocolError`,
not an engine error).

The `play` event payload gains a `"cards"` field (list of card strings) in
addition to the existing `"card"` field, which stays as the *first* card of
the group for backward compatibility with the current frontend's fly-in/burn
animation and log line — it only knows how to animate one card and isn't
being touched this phase. Document this explicitly in `WS_PROTOCOL.md` next
to the event shape.

Update `WS_PROTOCOL.md`'s "Client → server actions" and "Server → client
messages" sections to describe both the single-card and multi-card `play`
shapes, and add a short note that the current frontend only ever sends the
single-card form — the multi-card form exists on the wire but has no client
using it yet.

One gap to leave as-is, don't try to fix it this phase: `_describe_error`'s
card-echo-on-rejection (the `"card"` field in error responses) only reads
`message.get("card")`, so a rejected multi-card play won't echo back which
card(s) were the problem — it'll just come back `null`. That's a frontend
highlighting concern for whenever the multi-select UI actually exists; note
it in a code comment so it isn't mistaken for an oversight.

## Non-goals — do not touch these
- **Frontend.** No changes to `frontend/`. The existing single-card play flow
  must keep working exactly as it does today, unverified-by-you only in the
  sense that you should run the existing frontend build/lint if easy, but
  there's no new frontend work here.
- **Blind phase (Layer 1).** RULES.md is explicit that multi-card plays don't
  apply there — `flip_blind` stays exactly as it is today, one card, forced,
  no player choice. Don't add any grouping there.
- **Four-of-a-kind auto-burn bonus.** Not part of this rule. Don't add it.
- **AFK forced-move logic (`_force_afk_move` in `game_ws.py`).** It never
  guesses which card to play on a player's behalf today, and multi-card
  plays are even more of a strategic decision than single ones — leave it
  untouched. It should keep forcing single-card-equivalent fallbacks only
  (flip / pick up / skip), never a multi-card play.

## Tests
Add `backend/tests/test_multi_play.py` using the existing `helpers.py`
conventions (`make_game`, `c(...)`, `card(...)`). At minimum cover:
- A basic same-rank group (e.g. three 6s) legally beats the pile; pile grows
  by all three; top card is that rank.
- Mixed ranks in one group → rejected.
- Claiming more copies than the player actually holds (e.g. two 6H when they
  have one) → rejected, nothing mutated.
- Two 7s played together: `seven_pending` ends up `True`, and constrains only
  the *next* player once (not doubled, not carried further).
- Two 10s played together: pile + both 10s all burn, next player faces an
  empty pile, no bonus turn for the player who played them.
- **Two Jacks played together: direction ends up flipped exactly once**, not
  back to its original value. This is the test most likely to catch a wrong
  implementation.
- A same-rank group equal to the current pile-top rank, where that rank is
  NOT a power card → still illegal (equal rank without power stays blocked,
  group or not).
- Attempting a group play while in the blind phase → rejected the same way a
  single blind-phase `play_card` attempt is today.
- Existing single-card tests (`test_validation.py`, `test_power_cards.py`,
  `test_pickup.py`, etc.) must still pass unmodified — the refactor of
  `play_card` into `play_cards` must not change single-card behavior or
  error wording. Run the full suite (`pytest`) and confirm zero regressions
  before calling this done; report the pass count.

## Definition of done
- `pytest` passes in full, including the new `test_multi_play.py`.
- `docs/WS_PROTOCOL.md` documents the new `"cards"` action/event shape and
  the "frontend doesn't send this yet" caveat.
- No file under `frontend/` was touched.
