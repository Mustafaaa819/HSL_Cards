#  Card Game

## What this is

A real-time multiplayer card game built for a friend group to play together remotely during summer vacation, everyone on their own phone, live at the same time. It's a custom variant in the Shithead/Palace family of climbing card games — get rid of all your cards before anyone else, with a set of power cards that break the normal rules and a hidden-information mechanic (a face-down layer of your own cards that even you can't see) that adds bluffing and memory play on top of the base climbing mechanic.

Prototype goal: fully playable by the friend group this summer. Play Store packaging and a single-player AI opponent mode are explicitly OUT OF SCOPE for this build — deferred to a later phase once the prototype is proven and fun.

## Players

2–5 players per single 52-card deck. 6 or more players: use two decks shuffled together.

## Setup

Each player is dealt 9 cards, arranged in three layers of three:

- **Layer 1 (bottom):** face-down, unknown to everyone — including the owner. Never revealed until a player reaches this layer near the end of the game.
- **Layer 2 (middle):** face-up on the table, visible to all players. Can't be touched or played until the player's Layer 3 is fully cleared.
- **Layer 3 (top):** the player's actual hand. Only the owner can see these cards. This is what's played from during the deck phase and the hand phase.

The remaining cards form a shared draw deck in the middle of the table.

## Core mechanic

Play proceeds clockwise (direction can reverse — see the J power card). Each card played must be equal to or higher in rank than the top card of the discard pile, UNLESS it's a power card.

Equal rank is only playable via a power card. A plain (non-power) card of the same rank as the top card is not a legal play.

If a player cannot or chooses not to beat the top card, they pick up the entire discard pile into their hand.

## Deck phase (while the shared draw deck still has cards)

1. On your turn, draw one card from the shared deck.
2. Decide: play any one legal card from your hand — not necessarily the card you just drew — or voluntarily pick up the entire discard pile instead, even if you have a legal play available. Voluntary pickup is always allowed here as a strategic choice (e.g. avoiding a pile loaded with cards you'll need later).
3. If you have no legal play, you must pick up the pile.
4. Any picked-up cards (voluntary or forced) merge into your Layer 3 hand and become part of your active playable hand.
5. The deck phase ends once the shared draw deck is empty. This is considered the real start of the game — the phase before this is largely a setup/positioning period.

## Hand phase (after the shared deck is empty)

Same as the deck phase, minus the draw step: play a legal card from hand, or voluntarily pick up the pile.

Once a player's hand (Layer 3) is empty, they move to playing from Layer 2 (their face-up cards), which becomes their active "hand." Once Layer 2 is empty, they move to Layer 1, the blind phase.

## Blind phase (Layer 1)

- The player reveals ONE face-down card at a time, blind — no choice, no strategy, pure chance.
- If it legally beats the top of the pile (or is a power card), it's played and the player is safe.
- If it doesn't beat the pile, the player picks up the entire discard pile — merged into a new active hand — and goes back to playing hand-style (including the ability to voluntarily pick up again) until that hand is cleared, at which point they resume flipping their remaining blind card(s).
- **Voluntary pickup does NOT apply in this phase.** A player must flip and attempt to play before any pickup decision — there is no option to skip flipping and take the pile instead.
- Any still-unflipped blind cards stay on the table untouched, waiting for the player to cycle back to them.

## Power cards (2, 7, 10, J)

Power cards can be played on top of ANY card regardless of rank, completely ignoring the higher-or-equal rule. Power cards can also be stacked on each other in any combination (7 on J, J on 7, 7 on 7, etc).

- **2 — Reset:** Playable on anything. Acts as a free dump, clearing whatever rank pressure was on the pile.
- **7 — Under-power:** Playable on anything. Forces the very next player only to play a card ranked 7 or lower (2 through 7), or another power card. This constraint applies to that one next player only — it does not chain further down the line. If that player has no card ≤7 and no power card, they must pick up the pile.
- **10 — Nuke:** Playable on anything. Immediately burns/clears the entire discard pile out of the game. The nuker does NOT get a bonus turn — the nuke counts as their full action for the turn, and play passes to the next player normally, who now faces a completely empty pile and can play anything.
- **J — Reverse:** Playable on anything. Reverses the direction of play. In a 2-player game this has no functional effect on turn order (reversing direction doesn't change who's next when there are only two players), but it's still a legal play.

## Win / loss condition

The game does NOT end when the first player clears all three layers. Play continues until only one player is left holding cards. Full finishing order is tracked — 1st place, 2nd, 3rd, and so on — with the last player still holding cards ranked last. This is not a binary win/loss game; every player's finish position counts.

## Tech stack

- **Backend:** FastAPI (Python), WebSockets for real-time state sync. Server is the sole authority on all hidden game state (deck contents, opponents' hands, blind cards) — clients only ever receive a filtered view of state relevant to them.
- **Frontend:** React + Vite, mobile-first responsive design (built and tested at phone viewport widths first, not shrunk down from desktop).
- **Deployment:** targeting Hugging Face Spaces (Docker SDK), consistent with prior projects — pending confirmation in Phase 0 that HF Spaces reliably sustains a live WebSocket connection for a full game session. Render or Fly.io are the fallback if it doesn't.
- **Card art:** public-domain/CC0 SVG playing card assets (not the Kenney pack — went with a more traditional/realistic card look instead). Card faces are static assets; card backs for the blind Layer 1 pile are custom-generated per-card patterns rather than a single static back image, to visually reinforce that even the owner doesn't know what's underneath.

## Design system

- **Palette:** deep ink-green-black background (`#14181A`), burnt-gold accent reserved specifically for power cards (`#C9A15A`) so they read as visually distinct the instant they hit the pile, muted red for danger/forced-pickup states (`#C1443B`), dim teal for safe/legal-play states (`#3E8E82`), warm off-white for text (`#EDE7DC`).
- **Type:** a condensed, high-contrast display face for card ranks (numbers need to read instantly at a glance on a small phone screen), paired with a plain, unobtrusive UI font for chrome/buttons/menus — the ranks carry the personality, the interface stays quiet.
- **Layout:** opponents shown in a small arc at the top of the table with avatar + face-down card count only (never actual card values). Large center zone for the discard pile with the top card prominent and power cards visually distinct (border/glow). The player's own three layers stack at the bottom of the screen — blind row small and dimmed, face-up row visible, hand row largest and the only directly tappable row. Draw deck shown off to one side with a visible remaining count. Whose turn it is gets an unambiguous, unmissable visual indicator.

## Build phases (high level)

0. Scaffolding — backend/frontend skeleton, WebSocket echo test, deployment sanity check.
1. Core game engine (server-side, no UI) — deck, dealing, full rule/move validation, tested in isolation.
2. Lobby/room system — create/join by code, ready-up, host starts match.
3. Real-time sync — filtered state broadcast per player, turn actions over WebSocket, reconnect handling.
4. Frontend game UI — the actual table, cards, layers, pile, deck, turn indicator, touch interaction.
5. Rules edge cases and polish — ranking, AFK/timeout handling, invalid-move feedback.
6. Visual/UX polish pass using the design system above.
7. Real playtesting with the friend group, bug fixes from actual sessions.
8. Deferred: Play Store packaging, AI 1v1 mode. Not part of this build.