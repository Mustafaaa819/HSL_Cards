# [Working Title] — Consolidated Ruleset v1

A Shithead/Palace-style climbing card game with custom power cards, built for 2–5 players (live synchronous multiplayer, mobile-first).

## Setup
- Standard 52-card deck. For 6+ players, use two decks shuffled together.
- Each player gets 9 cards total, arranged in 3 layers of 3:
  - **Layer 1 (bottom):** face-down, unknown to everyone including the owner. Never looked at until a player reaches this layer.
  - **Layer 2 (middle):** face-up on the table, visible to all players, belongs to the owner but can't be touched until Layer 3 is cleared.
  - **Layer 3 (top):** the player's actual hand. Only the owner can see these. This is what's played from during the deck phase and the post-deck hand phase.
- Remaining cards form the shared draw deck in the middle.

## Core mechanic
- Play proceeds clockwise. Each play must be equal to or higher than the top card of the discard pile, UNLESS it's a power card (see below).
- Equal rank is only playable via a power card. A non-power card of equal rank to the top card is not a legal play (e.g. you can't play A on A unless that A is being used as a power — it isn't, so you can't).
- If a player cannot or will not beat the top card, they pick up the entire discard pile into their hand.
  - **PARTLY SUPERSEDED (2026-07-18) — see "Follow-up throws" below.** A pickup no longer ends the turn: the picker must immediately throw one legal card before play passes.

## Deck phase (before the shared deck runs out)
1. On your turn, draw one card from the shared deck.
2. Decide: play any one legal card from your hand (not necessarily the one you just drew), or voluntarily pick up the entire pile instead — even if you have a legal play. Picking up is always allowed as a strategic choice in this phase.
3. If you can't legally play anything, you must pick up the pile.
4. Any cards picked up (voluntary or forced) merge into your Layer 3 hand and become playable normally.
5. Deck phase ends when the shared draw deck is empty. This is considered the "real start" of the game.

## Hand phase (after the shared deck is empty)
- Same as above minus the draw step: play a legal card from hand, or voluntarily pick up the pile.
- Once a player's hand is empty, they move to Layer 2 (their face-up cards) and those become their active "hand."
- Once Layer 2 is empty, they move to Layer 1 (blind cards).

## Blind phase (Layer 1)
- Player reveals ONE face-down card at a time, blind — no choice, no strategy, pure luck.
- If it legally beats the top of the pile (or is a power card), it's played and stays down; safe.
- If it doesn't beat the pile, the player picks up the entire pile — merged into a new active hand, and they go back to playing hand-style (draw-then-decide style pickup rules resume) until that hand is cleared again, at which point they return to flipping their remaining blind card(s).
- **Voluntary pickup does NOT apply in this phase.** You must flip and attempt to play before any pickup decision — no choosing to take the pile instead of flipping.
- Any of the player's still-unflipped blind cards stay on the table untouched, waiting for the player to cycle back around to them.
- **AMENDED (2026-07-18) — see "Follow-up throws" below.** A flipped 2 forces the same player to immediately flip their next blind card too (chaining), and a failed flip's pickup now demands an immediate throw from the new hand.

## Power cards (2, 7, 10, J)
Power cards can be played on top of ANY card, regardless of rank, ignoring the higher/or equal rule entirely. Power cards can also be stacked on top of each other in any combination (7 on J, J on 7, 7 on 7, etc).

- **2 — Reset:** Can be played on anything. Clears the "must beat this rank" pressure — effectively a free dump.
  - **SUPERSEDED (2026-07-18) — see "Follow-up throws" below.** The 2 is no longer a plain dump: it's a bonus action. The player who plays it must immediately throw one more card (and in the blind phase, must flip their next blind card).
- **7 — Under-power:** Can be played on anything. Forces the very next player only to play a card ranked 7 or lower (2–7). This constraint applies to that one next player only, not chained further. If that player has no card ≤7 and no power card, they must pick up the pile.
- **10 — Nuke:** Can be played on anything. Immediately clears/burns the entire discard pile out of the game. The nuker does NOT get a bonus turn — playing the 10 counts as their full action for the turn, and play passes to the next player normally, who now faces an empty pile and can throw anything.
- **J — Reverse:** Can be played on anything. Reverses turn order direction. In 2-player games this has no functional effect on who goes next (turn order is unaffected by direction with only 2 players), but is still legal to play as a power card.

## Multi-card plays (duplicates)
- A player may play multiple cards of the same rank together as a single turn action, instead of just one — e.g. three 6s regardless of suit, or two 7s. Applies to plain ranks and power ranks alike.
- Legality is checked once, using the shared rank: if a single card of that rank would be a legal play (beats the pile top, or is a power card), the whole group is legal. All cards in the group must share the same rank — mixed-rank groups (including mixed power ranks, e.g. a 2 and a 7 together) are NOT a valid single play. Power-card stacking across different ranks still happens one card at a time, as separate plays (see Power cards above).
- All cards in the group must come from the player's single currently-active layer (hand, face-up, or a merged pickup hand). A player cannot combine cards from two different layers into one throw.
- The group counts as ONE turn action. After it resolves, the discard pile top is the played rank, and play passes to the next player exactly as it would after a single-card play of that rank — same power-card effects apply once (a group of 7s still constrains only the immediate next player; a group of 10s still burns the pile with no bonus turn; a group of 2s or Js behaves like their single-card versions).
- Does NOT apply in the blind phase (Layer 1). Blind reveals are strictly one card at a time, forced, with no player choice — there's nothing to group together.
- **Explicitly NOT included:** no bonus/auto-burn for playing all four of a rank (a common house-rule variant in this genre). Not implied by this rule, not added. If you want it, say so — it needs its own decision.

## Follow-up throws — pickups and the 2 as a bonus action (added 2026-07-18)

Both rules below share ONE mechanism in the engine: a pending-follow-up flag that keeps the turn with the same player until they take one more card-shedding action. While the flag is armed, picking up the pile is rejected — the follow-up cannot be dodged by taking the pile (again).

**Pickup requires an immediate follow-up throw.** After ANY pickup — voluntary, forced, or the pickup from a failed blind flip — the same player must immediately throw one legal card before the turn passes. The pile is empty at that moment, so in practice almost anything they hold is legal; the point is that a pickup is never a free pass that skips a throw. A live 7 constraint is cleared the moment the pickup happens (the player already paid the 7's price by picking up — it does not cap the follow-up throw).

**The 2 is a bonus action.** Whenever a 2 resolves from hand or face-up — as a single card or as a same-rank group of 2s, which arms this ONCE per group, exactly like the other group effects — the same player must throw one more card before the turn passes. The follow-up is chosen freely and must be legal in the normal sense (it must beat the 2 now on top — rarely a real constraint, since 2 is the lowest rank). If the follow-up is itself a 2, the requirement re-arms and chains as deep as the 2s last.

**The 2 in the blind phase chains flips.** A flipped blind 2 is automatically safe (power card), but instead of ending the turn, the same player immediately flips their next blind card — forced, no agency, like every blind flip. Another 2 chains again. If the chain clears the last blind card, the player finishes on the spot via the normal finish path — that "big win" is the intended payoff of this rule. A non-2 flip inside the chain resolves exactly as any flip: beats the pile → safe, turn ends; fails → the usual pickup, with the pickup-throw rule above layered on top.

**Edge cases (deliberate decisions, revisit if playtesting disagrees):**
- If a 2 empties the player's current layer, the follow-up comes from their newly active layer (face-up next, or blind — where it becomes a forced flip).
- EXCEPT in the deck phase, where layer transitions are locked (see engine decisions below): a 2 that was a deck-phase player's very last hand card waives the follow-up and the turn ends normally. No mid-turn draw happens — the turn-start draw already did. **Tentative:** waiving was chosen over inventing a deck-phase layer-transition exception; flagged for review.
- If a follow-up is owed but the active layer has zero cards (structurally impossible for a pure pickup; guard exists for composition with the 2), the requirement is waived and the turn ends via the normal finish/advance checks.
- A 2 that is the player's very last card overall finishes them normally — no follow-up is owed by a finished player.

**AFK interaction.** The server still never plays a card on anyone's behalf. An AFK player stuck mid-follow-up with a non-empty pile (their 2 on top, pickup barred) gets a system-forced pickup — the same resolution an unanswered pile always had — which re-arms the follow-up throw; if that clock also expires, the empty-pile skip discharges the owed throw and play moves on. A fully AFK turn can therefore take two timeout cycles instead of one.

## Win/loss condition
- The game does NOT end when the first player empties all three layers. Play continues until only one player remains holding cards. Full finishing order is tracked and shown: 1st place, 2nd, 3rd, etc., with the last player holding cards ranked last. Not binary win/loss — every player's finish position matters.

## Player count
- 2–5 players per single deck.
- 6+ players: two decks shuffled together.
- Max 11 players (two decks = 104 cards; 12 players × 9 cards = 108 doesn't fit).
- Confirmed: 1v1 vs AI is a stated long-term goal but is OUT OF SCOPE for the friend-group prototype build.

## Engine implementation decisions (locked in Phase 1)

These weren't explicitly stated in earlier rules discussion but were required to make the engine unambiguous. Treat these as final rules, not implementation trivia:

- **Rank order: 2 (low) < 3 < 4 < 5 < 6 < 7 < 8 < 9 < 10 < J < Q < K < A (high).** Ace is the highest non-power card, only beatable by a power card.
- **The 7 constraint REPLACES the beat-the-top rule for the very next player only** — it does not stack with it. A 3 is legal on top of a 7 even though 3 is lower than 7, because the active rule at that moment is "≤7," not "beat the top card."
- **Power cards keep their natural rank once they're sitting on the discard pile.** A J played as a power must then be beaten by Q, K, A, or another power card — its "beat me" value reverts to normal once it's no longer the card being played.
- **The 10 fully leaves the game when it nukes the pile** — it does not remain as the new top card of an empty pile. After a nuke, the next player can play anything at all.
- **A failed blind-flip reveal joins the player's new picked-up hand.** It cannot return face-down, since it's already been seen by the table.
- **All pickups — from the deck phase, hand phase, or a failed blind flip — land in the player's private hand (Layer 3), even if the player was actively playing from their face-up Layer 2 at the time.** The player clears that hand before resuming whatever face-up cards they had left.
- **Layer transitions (hand → face-up → blind) cannot happen during the deck phase.** The turn-start draw keeps refilling the hand, so face-up and blind stay locked until the shared deck is empty.
- **SUPERSEDED (2026-07-16) — see "Multi-card plays" above.** Originally locked as exactly one card per turn, no same-rank grouping. That's reversed: multi-card plays of the same rank are now in scope. The engine's validate→mutate path currently only handles one card per action and needs updating — this is not just a doc change.
- **First player is seat 0, in join order.** Arbitrary and easily changed later (e.g. randomized, or loser-of-last-game starts).
- **A follow-up throw is one shared engine primitive (2026-07-18).** Pickups and 2s both arm the same pending flag; the required action follows the player's active layer ("throw" from hand/face-up, "flip" on blind). The turn-start deck-phase draw belongs to the turn, not the action — it never re-runs for a follow-up.
- **Voluntary pickup requires a non-empty pile.** It cannot be used as a pass/skip action.