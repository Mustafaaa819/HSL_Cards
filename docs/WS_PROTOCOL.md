# Game WebSocket protocol (Phase 3, + Phase 5 AFK/errors, + 2026-07-18 follow-up throws)

Endpoint: `ws(s)://<host>/ws/{room_code}` — live game sync only. The lobby
(create/join/ready/start) stays on the REST endpoints; connect the socket
once the room has started.

## Connecting

1. Open the socket. The server accepts it unconditionally.
2. Send **one JSON text frame** within 10 seconds: `{"token": "<your bearer token>"}`
   (the token returned by room create/join). First-message auth was chosen
   over a query param so tokens never land in server/proxy access logs.
3. On success the server replies with a state snapshot (see below). On
   failure it closes the socket:

| Close code | Meaning |
|---|---|
| 4000 | First frame missing/late or not `{"token": ...}` |
| 4001 | Token doesn't belong to a player in this room |
| 4002 | Room exists but the game hasn't started |
| 4004 | No room with that code |
| 4008 | This socket was replaced by a newer connection from the same player |

**Reconnect:** connecting again with the same token replaces the old socket
(closed with 4008) and the new socket immediately receives the current
filtered snapshot. Other players see nothing.

## Client → server actions

One JSON object per frame. There is **no "draw" action** — the engine draws
for the current player automatically at turn start during the deck phase.

- `{"action": "play", "card": "7H"}` — card format is `<rank><suit>`, ranks
  `2`–`10`, `J`, `Q`, `K`, `A`; suits `C D H S`.
- `{"action": "play", "cards": ["6H", "6C", "6D"]}` — multi-card play: a
  same-rank group thrown as one turn action (see RULES.md "Multi-card
  plays"). `"cards"` must be a non-empty array of card strings; a `play`
  frame must carry exactly one of `"card"` or `"cards"` — both, or neither,
  is a `protocol` error. Same-rank/availability/legality checks are the
  engine's, rejected as `illegal_move` like any single-card play. **The
  current frontend only ever sends the single-card form** — this shape
  exists on the wire but has no client using it yet.
- `{"action": "pick_up"}` — take the discard pile (voluntary or forced).
  Rejected as `illegal_move` while a follow-up throw is pending (see
  `pending_action` below) — the mandatory throw can't be dodged by picking
  up again.
- `{"action": "flip"}` — blind flip. Optional `"index": <int>` picks which
  face-down card (cosmetic — they're unknown by definition; defaults to 0).

**Follow-up throws (RULES.md "Follow-up throws", 2026-07-18):** a pickup or
a resolved 2 does NOT pass the turn. The same player must send one more
action — a `play` (or a `flip`, if their active layer is blind) — before
play advances. The server signals this via `pending_action` in every state
payload and `must_throw_again` / `must_flip_again` on events; there is no
new client action, just another `play`/`flip` from the same player.

That is the complete list. Notably there is **no "skip" action** — the
server can pass an AFK player's turn (see below), but a skip is never
offered to a client and `{"action": "skip"}` is rejected like any other
unknown action.

The server re-validates everything against the engine. An illegal,
out-of-turn, or malformed action is rejected **to the sender only**;
nothing is mutated or broadcast.

## Errors

```jsonc
{
  "type": "error",
  "message": "5H doesn't beat 9D",  // human-readable, safe to show as-is
  "code": "illegal_move",           // stable machine-readable tag
  "card": "5H"                      // the rejected card, or null
}
```

`message` is always specific enough to surface directly — the engine's own
wording is passed through rather than flattened to "Illegal move".

| `code` | Meaning |
|---|---|
| `illegal_move` | The engine refused it (didn't beat the top card, wrong layer, pile empty, game over, …) |
| `out_of_turn` | Not your turn. Rephrased server-side with display names, since the engine only knows player ids |
| `protocol` | Structurally bad frame: not JSON, unknown action, unparseable card, non-integer index |

`card` is the card string from a rejected `play`, echoed back so the client
can highlight **that exact card** instead of guessing which tap the error
belongs to. It is `null` for every other error, including `out_of_turn`.
A rejected multi-card play (`"cards"` form) also comes back with `card:
null` — echoing the offending group member is deferred until a client
actually sends that form.

## AFK / turn timeout

Each turn is allowed **60 seconds**. The clock is armed when the first
socket connects and re-armed on every legal action; it is driven by the
room, not by a socket, so a player who closed their tab still times out.
Illegal moves do not reset it.

On expiry the server acts for the current player and broadcasts the result
like any other move. It never plays a card on their behalf — only
no-choice outcomes are forced, in order:

1. **On blind cards** → flip the next unflipped blind card. A flip carries
   no decision anyway, so this is exactly the move they would have made.
   A blind 2-chain's forced flips arrive one per expiry.
2. **Pile has cards** → pick up the pile. The normal penalty for not
   acting. This is forced even for a player stuck mid-follow-up ("threw a
   2, owes a throw", where a client `pick_up` is rejected) — a
   system-level override, and the same resolution an unanswered pile
   always had. The forced pickup arms the mandatory follow-up throw, which
   remains a real choice the server won't make, so the player gets a fresh
   clock...
3. **Empty pile** → skip the turn (`{"kind": "skip", …}`). ...and on that
   expiry the skip discharges any owed follow-up throw and the turn
   passes. With nothing to pick up there is no forceable move left. The
   skipper keeps their whole hand while everyone else sheds cards, so this
   is a self-penalty, not an exploit. Net effect: a fully AFK player's
   turn can take two expiries (forced pickup, then skip) instead of one.

The clock is cancelled at game over and when the last socket in a room
disconnects (an abandoned room must not keep forcing moves at itself).

## Server → client messages

`{"type": "state", "event": <event|null>, "state": {...}}`

Sent as the connect snapshot (`event: null`) and broadcast to every
connected player after each legal action — each player gets their **own
filtered view**, never identical payloads.

`event` describes what just happened publicly:

- `{"kind": "play", "player_id", "card", "cards", "pile_burned", "direction_reversed", "player_finished", "must_throw_again"}`
  — `cards` is the full same-rank group played (a single-card play makes it
  a one-element list). `card` stays as the **first** card of the group for
  backward compatibility: the current frontend's fly-in/burn animation and
  log line only know how to show one card and aren't changing this phase.
  `must_throw_again` is `true` when the play was a 2 that armed a follow-up
  throw — the turn did NOT pass.
- `{"kind": "pickup", "player_id", "count", "forced", "must_throw_again"}`
  — `must_throw_again` is `true` whenever the pickup armed the mandatory
  follow-up throw (i.e. almost always; `false` only in the waived edge
  cases per RULES.md).
- `{"kind": "flip", "player_id", "card", "played", "pile_burned", "direction_reversed", "picked_up", "player_finished", "forced", "must_flip_again", "must_throw_again"}`
  — the flip event is the ONLY thing that ever reveals a blind card.
  `must_flip_again` is `true` when a flipped 2 chains (same player must
  call `flip` again); `must_throw_again` is `true` when a failed flip's
  pickup armed the follow-up throw. Both `true` mean the turn did not pass.
- `{"kind": "skip", "player_id", "forced"}` — AFK timeout on an empty pile.
  Also discharges any owed follow-up throw.

`forced` is `true` when the AFK timer produced the move rather than the
player, so the UI can say "timed out" instead of "picked up". There is no
`forced` on `play` (a card is never played for anyone) and it is always
`true` on `skip` (a skip only ever happens on timeout).

`state` (built by `app/sync/serializer.py`, the single visibility authority):

```jsonc
{
  "room_code": "ABCDE",
  "phase": "deck" | "hand",
  "direction": 1 | -1,
  "current_player_id": "…" | null,   // null once game_over
  "seven_pending": false,            // next player constrained to ≤7 / power
  "pending_action": null,            // "throw" | "flip" | null — non-null while the
                                     // CURRENT player owes a follow-up before the turn
                                     // can pass (pickup throw / 2 bonus throw / blind
                                     // 2-chain flip). The client MUST read this to know
                                     // a pickup or a 2 did not pass the turn.
  "draw_deck_count": 30,             // count only, never identities
  "discard_pile": ["6H", "JD"],      // full pile, bottom → top (public)
  "top_card": "JD" | null,
  "game_over": false,
  "turn_ends_in": 60.0,              // seconds until the AFK clock forces the current
                                     // player's move, measured at send time (so a
                                     // reconnect snapshot resumes mid-countdown).
                                     // null = no timer (game over / nobody connected).
                                     // Remaining seconds, NOT a timestamp — immune to
                                     // client/server clock skew.
  "finish_order": ["…"],             // fills as players finish; full 1st→last at game over
  "players": [                       // everyone, seat order
    { "player_id": "…", "name": "…", "seat": 0,
      "hand_count": 3,               // others' hands: count only
      "face_up": ["9D"],             // face-up is public in full
      "blind_count": 3,              // blind: count only — even your own
      "active_layer": "hand" | "face_up" | "blind",
      "finish_position": null | 1 }
  ],
  "you": {                           // the viewer's private view
    "player_id": "…",
    "hand": ["3H", "6C"],            // full values — only for yourself
    "face_up": ["KH"],
    "blind_count": 3,                // never values, not even to the owner
    "active_layer": "hand",
    "finish_position": null
  }
}
```

## Game end

Sockets are **left open** after game over so the Phase 4 results screen can
use them. The final broadcast carries `game_over: true` and the complete
`finish_order`; any further action returns an error message.
