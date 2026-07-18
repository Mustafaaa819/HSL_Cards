# Rule change: pickup no longer ends the turn, and the 2 becomes a real bonus action

## Context — this is a rule CHANGE, not a bug fix

I tested the game and two things bothered me, but I checked `game.py` against our own
`docs/RULES.md` first: the current code is a correct implementation of the rules as written.
`RULES.md` line 42 says explicitly, about the 10: "the nuker does NOT get a bonus turn —
playing the [power card] counts as their full action." The 2 (line 40) is documented as
"effectively a free dump" with no follow-up. Pickup (line 16) says nothing about throwing
again. So don't go looking for a defect in `_end_turn` / `_apply_group_effects` — there isn't
one relative to the current spec. We are deliberately changing the spec. Update `RULES.md`
using the same "SUPERSEDED (date) — see X" pattern already used for the multi-card-play
change (see line 73), not a silent rewrite — I want the history of what changed and why to
stay visible in the doc, same as last time.

Both changes below require the SAME new primitive: a turn that continues with the same
player instead of advancing, gated by an explicit pending-action flag. Build one mechanism
and reuse it for both — do not write two parallel special cases, that's how this grows extra
bugs.

## Change 1 — pickup requires an immediate follow-up throw

Today: `pick_up_pile()` merges the pile into the player's hand and calls `_end_turn(None)`,
which advances to the next player. New behavior: after ANY pickup (voluntary — deck-phase
choice — or forced, including a failed blind flip's pickup), the SAME player must immediately
throw one legal card before the turn passes to anyone else. The pile is empty at that point
(they just took all of it), so in practice almost any card they hold will be legal — this
is not meant to be a hard gate, it's meant to guarantee a pickup is never a "free pass" that
skips a throw.

Rules for this:
- The `seven_pending` constraint must be cleared the moment pickup happens (not carried into
  the follow-up throw) — the player already paid the cost of failing the 7 constraint by
  picking up; don't also cap what they can throw next.
- While this follow-up is pending, `pick_up_pile()` must reject a second pickup attempt with
  a clear error — the player cannot dodge the mandatory throw by picking up again. (Note the
  existing empty-pile guard in `pick_up_pile` already blocks this by coincidence right after
  a pickup, but make the rejection explicit and correctly worded rather than relying on that
  side effect, since it needs to also apply after Change 2's forced throw, where the pile is
  NOT empty.)
- If, after the pickup, the player's active layer genuinely has zero cards to choose from,
  waive the requirement and end the turn normally (proceed to the usual finish/advance-layer
  check). This should be structurally impossible for a pure pickup (they just gained the
  entire pile into hand) but the guard needs to exist for composition with Change 2 — see the
  shared edge case below.

## Change 2 — the 2 is a bonus action: play it, then you must throw again

Today: a 2 is just always-legal (`is_legal_play` treats all power ranks as auto-legal) with
no special handling in `_apply_group_effects` — it behaves like nothing happened beyond
becoming the new top card. New behavior: whenever a 2 is played from hand or face-up (as a
single card OR as a same-rank group of 2s — a group resolves this ONCE per group, exactly
like the existing 10/J/7 group-effect precedent already documented in RULES.md's "Multi-card
plays" section, not once per individual 2), the SAME player is immediately required to throw
one more card before the turn passes. That follow-up card:
- Must still be a legal play in the normal sense (it has to beat whatever's now on top — in
  practice this is almost never a real constraint since a 2 sitting on the pile is the lowest
  possible rank per the locked rank order, so nearly anything beats it).
- Is chosen freely by the player — normal legal-play selection, not auto-picked by the server.
- If it is ALSO a 2, the requirement re-arms: same player throws again. This should fall out
  naturally from the shared pending-flag mechanism (any 2 arms the flag; resolving a play
  clears it unless the resolving card is itself a 2) — don't hardcode a two-deep limit.

Edge case — the 2 empties the player's current layer (e.g. it was their last hand card):
the follow-up throw comes from whatever their now-recomputed active layer is (face-up next,
or blind after that) EXCEPT during the deck phase, where `RULES.md` locks layer transitions
outright (hand refills every turn via the automatic draw). If a 2 happens to be a deck-phase
player's very last hand card, there's no lower layer to reach into and no draw available
mid-resolution (the turn-start draw already happened at the top of this turn, not again here).
In that specific case, waive the follow-up and end the turn normally rather than inventing a
layer-transition exception to the deck-phase lock — flag this explicitly in your PR/summary
so it's a visible decision, not a silent one, since I'm not 100% sure this is the right call
and want the chance to override it.

## Change 2b — the 2 in the blind phase is a chain, not a hand-throw

This is the one that's structurally different: in the blind phase there's no hand or face-up
to choose a follow-up from, and blind flips are explicitly "no choice, no strategy" per
`RULES.md`. So when a flipped blind card turns out to be a 2: it's automatically safe (it
already was, since power cards auto-pass `is_legal_play`), but instead of ending the turn,
the SAME player immediately flips their next remaining blind card too — forced, same as any
blind flip, no agency. If that one is ALSO a 2, flip again. This chains for as long as 2s
keep coming up. If the chain runs the player out of blind cards entirely (all layers now
empty), they finish the game right there via the normal `_check_finish` path — this is
explicitly the intended "big win" case for this rule, not an edge case to suppress.

If a flip inside the chain is NOT a 2, resolve it exactly as `flip_blind` does today: if it
beats the pile, safe, turn ends normally; if it doesn't, the existing pickup-and-return-to-
hand-style-play behavior kicks in, and Change 1 now applies on top of that pickup as normal.

Implementation note: `flip_blind(player_id, index)` currently returns one `FlipResult` per
call and lets the client choose which blind index to flip. Keep that per-call shape rather
than looping internally inside one call — add a field to `FlipResult` (e.g. `must_flip_again:
bool`) so the server tells the client "you're not done, call flip_blind again," rather than
the engine silently resolving a multi-flip chain server-side in one shot. This keeps every
engine action as one explicit call, consistent with how the rest of the file is written. If
you think auto-chaining inside one call is actually cleaner given how the WS layer is
structured, say so and explain the tradeoff rather than just picking one silently.

## The AFK-timer gap — investigate, don't guess

`skip_turn()` currently only permits a system-forced skip when the discard pile is empty,
specifically because before this change there was always a real action available otherwise
(play or pick up) and the server deliberately never chooses a card on a player's behalf.
After Change 2, a player can go AFK mid "must throw again after my 2" with a NON-empty pile
(the 2 itself is sitting on top) and pickup is now disallowed as an escape from that specific
obligation. That means there is currently no defined system fallback for an AFK player stuck
in that exact state. Read the actual AFK/timeout implementation (find it — likely under
`backend/app/sync/` or wherever the timer lives, I haven't traced it precisely) before
deciding how to handle this. Propose a fix consistent with the existing philosophy (server
doesn't pick a card on their behalf) — my instinct is the least-bad option is to let the
system force a pickup ONLY in this specific stuck-mid-2 AFK scenario, since it's the same
resolution that would've happened pre-this-change, but confirm this against however the
AFK system currently signals "this player is stuck, resolve it somehow" before implementing.
Flag your reasoning in the summary either way.

## Required for this to be done, not just "compiles"

1. `backend/app/engine/game.py` — implement the shared pending-continuation mechanism,
   both changes on top of it, all edge cases above.
2. `docs/RULES.md` — supersede the relevant sections using the existing dated-supersession
   pattern, don't silently rewrite.
3. `docs/WS_PROTOCOL.md` and `backend/app/routers/game_ws.py` — the client needs to be told
   "it's still your turn, you must throw again" / "must_flip_again" explicitly in the
   broadcast state, or the frontend has no way to know the turn didn't actually pass. This is
   a protocol addition, not cosmetic.
4. Tests — update whatever in `test_pickup.py`, `test_power_cards.py`, `test_multi_play.py`,
   `test_layers_blind.py`, and `test_afk.py` currently assumes the old behavior (pickup ends
   turn immediately; a played 2 doesn't chain), and add new tests for: pickup → mandatory
   throw → turn actually advances after; a played 2 chains into a mandatory second throw;
   a chain of two 2s in a row; the deck-phase last-hand-card-is-a-2 waived case; a blind-phase
   chain of 2s that ends in a win; a blind 2-chain where a later flip fails and pickup kicks
   in with Change 1 layered on top; the AFK-stuck-mid-2 fallback. Run the full suite after —
   I want a real pass/fail count reported, not "should be fine."
5. Minimal frontend signaling only — just enough that a live player can actually see and
   respond to "you must throw again" instead of the UI silently waiting on the wrong player.
   Do NOT do any broader UI work here — that's the next phase, explicitly out of scope for
   this change.

## Explicitly out of scope

No UI redesign or simplification (separate phase, coming next). No changes to 7 or 10 or J
behavior beyond whatever falls out naturally from sharing the new pending-flag mechanism —
if implementing this touches how those resolve, stop and flag it rather than changing their
behavior as a side effect. No four-of-a-kind auto-burn or other house rules not described
here.

## Before you write code

Give me a short summary of the state-machine design you're planning (what the pending flag
looks like, what clears/arms it, how it composes across Change 1 and Change 2 and the blind
chain) before implementing, so I can catch a wrong assumption before it's built into 66 files
of diff. Then implement, run the full backend test suite, and report the actual before/after
pass counts.
