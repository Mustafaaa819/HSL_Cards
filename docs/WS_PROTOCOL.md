# Game WebSocket protocol (Phase 3)

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
filtered snapshot. Other players see nothing. No AFK/timeout logic exists
yet (Phase 5).

## Client → server actions

One JSON object per frame. There is **no "draw" action** — the engine draws
for the current player automatically at turn start during the deck phase.

- `{"action": "play", "card": "7H"}` — card format is `<rank><suit>`, ranks
  `2`–`10`, `J`, `Q`, `K`, `A`; suits `C D H S`.
- `{"action": "pick_up"}` — take the discard pile (voluntary or forced).
- `{"action": "flip"}` — blind flip. Optional `"index": <int>` picks which
  face-down card (cosmetic — they're unknown by definition; defaults to 0).

The server re-validates everything against the engine. An illegal,
out-of-turn, or malformed action gets `{"type": "error", "message": "..."}`
back **to the sender only**; nothing is mutated or broadcast.

## Server → client messages

`{"type": "state", "event": <event|null>, "state": {...}}`

Sent as the connect snapshot (`event: null`) and broadcast to every
connected player after each legal action — each player gets their **own
filtered view**, never identical payloads.

`event` describes what just happened publicly:

- `{"kind": "play", "player_id", "card", "pile_burned", "direction_reversed", "player_finished"}`
- `{"kind": "pickup", "player_id", "count"}`
- `{"kind": "flip", "player_id", "card", "played", "pile_burned", "direction_reversed", "picked_up", "player_finished"}`
  — the flip event is the ONLY thing that ever reveals a blind card.

`state` (built by `app/sync/serializer.py`, the single visibility authority):

```jsonc
{
  "room_code": "ABCDE",
  "phase": "deck" | "hand",
  "direction": 1 | -1,
  "current_player_id": "…" | null,   // null once game_over
  "seven_pending": false,            // next player constrained to ≤7 / power
  "draw_deck_count": 30,             // count only, never identities
  "discard_pile": ["6H", "JD"],      // full pile, bottom → top (public)
  "top_card": "JD" | null,
  "game_over": false,
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
