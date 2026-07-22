# Four changes: face-up power cap, reconnect-proof chat, seat reclaim, 25s turns

## 1. Max one power card in Layer 2 (face-up) at deal time

Read `backend/app/engine/game.py`, `Game.__init__` (~line 76-93) and
`backend/app/engine/cards.py` (`build_deck`, `Card.is_power`, `POWER_RANKS`)
before touching anything.

Current dealing loop, per player in `player_ids` order:

```python
self.players.append(
    Player(
        player_id=pid,
        blind=[deck.pop() for _ in range(LAYER_SIZE)],
        face_up=[deck.pop() for _ in range(LAYER_SIZE)],
        hand=[deck.pop() for _ in range(LAYER_SIZE)],
    )
)
```

`deck` is already fully shuffled (`build_deck` shuffles once via `self.rng`)
and cards are drawn off the end via `.pop()`, so popping in sequence is
already equivalent to drawing randomly — this matters for how the fix stays
fair (see below).

**Rule, confirmed scope:** only Layer 2 (`face_up`) is capped at one power
card per player. Layer 1 (`blind`) and Layer 3 (`hand`) are untouched —
don't generalize this to them. If you think a case implies otherwise, stop
and ask rather than guessing; this was deliberately scoped to face-up only.

**Mechanism:** while dealing a player's 3 face-up cards, if the card just
popped `.is_power` and this player already has a power card among the
face-up cards already dealt to them this round, that card must NOT be kept:

1. Put it back into `deck` at a **random** index (`deck.insert(self.rng
   .randrange(len(deck) + 1), card)`) — not the top or bottom. The deck was
   randomly ordered to begin with; reinserting at a fixed position would
   make that card's future draw position predictable, which a fair-dealing
   feature shouldn't introduce.
2. Draw a replacement from a **random non-power card** in the deck — not
   just the first one found by index, which would bias replacements toward
   whichever end of the (currently ordered-by-shuffle) list you scan from.
   Collect the indices of every non-power card left in `deck`, `rng.choice`
   one, and `deck.pop(that_index)`.
3. This replacement is guaranteed non-power, so no loop/recursion is
   needed — one swap resolves it, always.

Write this as a small helper (e.g. `_deal_face_up(deck, rng) -> list[Card]`)
rather than inlining it into the constructor — it's independently testable
and keeps `__init__` readable. Guard the pathological case where `deck` has
zero non-power cards left when a replacement is needed (essentially
impossible this early — a single deck has 16 power cards out of 52, two
decks 32 of 104 — but raise a clear `InvalidSetupError` rather than let a
`StopIteration`/`IndexError` leak out if it somehow happens).

**Tests to add** (`backend/tests/test_engine.py` or wherever `Game`
construction is already tested — check first): run `Game.__init__` with a
seeded `rng` many times across 2, 3, and 5 players and assert no player's
`face_up` ever contains more than one card where `.is_power` is true. Also
assert total power-card count across the whole deal is conserved (nothing
vanishes — a swapped-out power card must still exist somewhere, either in
another player's non-face-up layers, the draw deck, or is untouched if it
was never drawn at all).

## 2. Chat drawer must not exit the page on the phone's back button

Read `frontend/src/screens/GameScreen.jsx`'s `ChatDrawer` component (~line
1362) and the `chatOpen` state (~line 144) before changing anything.

**Root cause, confirmed by reading the code, not guessed:** `ChatDrawer`
already has a working in-app Close button (`onClick={onClose}`, a plain
`setChatOpen(false)`) — that part is fine. The actual bug: opening the
drawer never calls `history.pushState`, so it adds no entry to the browser's
history stack. A phone's back gesture/button has nothing to "consume" at the
drawer level and falls straight through to real page navigation — on a
single-history-entry tab (which is exactly what a freshly opened game link
is), that navigation has nowhere else to go, so the browser exits the page
entirely, tearing down the WebSocket and all in-memory React state. This is
what "closing chat closes the whole game" actually is.

**Fix:** when `chatOpen` becomes `true`, push a history entry
(`window.history.pushState({ chatOpen: true }, '')`). Listen for `popstate`
while the drawer is open and treat it as "close the drawer" (`setChatOpen
(false)`) instead of letting the navigation proceed further. When the
drawer is closed via the in-app Close button (not the back gesture), also
call `window.history.back()` (or just avoid pushing a *second* forward
entry) so the pushed state gets cleanly consumed either way and the
history stack doesn't grow unbounded across repeated open/close cycles —
verify this specifically: open and close the drawer 5 times, confirm
`history.length` doesn't just keep climbing.

Scope this to the chat drawer only for this pass — don't generalize it to
every overlay in the file (`GameOverOverlay`, etc.) unless asked; those
weren't reported as broken and each would need its own review of whether
back-button-dismissal even makes sense there.

## 3. Reclaim a seat in an already-started game, by room code + name

**Design decision already made:** identity is proven by room code + the
exact name the player originally joined with (case-insensitive, matching
the uniqueness check `join_room` already enforces — see
`backend/app/rooms/manager.py` line 70, `NameTakenError`). No new
per-player secret code. This was a deliberate trade-off (simplicity, zero
new UI to remember) accepted knowing it means anyone who has both the room
code and a member's name could reclaim that seat — acceptable for a
trusted friend group, not something to silently harden further in this
pass.

**Backend — `backend/app/rooms/manager.py`:** add a method alongside
`join_room` (~line 64):

```python
def reclaim_player(self, code: str, name: str) -> tuple[Room, RoomPlayer]:
    """Hand a disconnected player back their own token by name match.
    Only valid once the game has started — a not-yet-started room's
    lobby already has a normal join flow for this. The player's token
    was never invalidated (nothing in this codebase ever revokes a
    token), so this doesn't mint anything new, it just looks it up."""
    room = self.get_room(code)
    if not room.started:
        raise RoomNotFoundError("This room hasn't started yet — use join instead")
    for player in room.players:
        if player.name.casefold() == name.casefold():
            return room, player
    raise InvalidTokenError(f"No player named {name!r} in this room")
```

Pick real exception types/messages consistent with the existing ones in
`backend/app/rooms/errors.py` — reuse `RoomNotFoundError`/`InvalidTokenError`
if their semantics fit closely enough (both map to error responses the
frontend already knows how to show), rather than inventing new error
classes for what's structurally the same "you don't have access" shape.

**Backend — `backend/app/routers/rooms.py`:** new endpoint, same response
shape as `join_room` (~line 77-86) so the frontend can treat the result
identically:

```python
@router.post("/{code}/reclaim")
async def reclaim_player(code: str, body: PlayerNameBody) -> dict:
    with _room_errors():
        room, player = room_manager.reclaim_player(code, body.name)
    return {
        "room_code": room.code,
        "player_id": player.player_id,
        "token": player.token,
        "room": room.public_state(),
    }
```

Add whatever new exception types to `_ERROR_STATUS` (~line 31) if you
introduce any; if you reuse `RoomNotFoundError`/`InvalidTokenError` as
suggested above, they're already mapped.

Update `docs/WS_PROTOCOL.md` (or wherever the REST lobby endpoints are
documented, if not there check for a separate lobby/REST doc) with this new
endpoint.

**Frontend — `frontend/src/api.js`:** add `reclaimPlayer: (code, name) =>
request(\`/rooms/${code}/reclaim\`, { method: 'POST', body: { name } })`
next to `joinRoom` (~line 52).

**Frontend — `frontend/src/screens/EntryScreen.jsx`:** `handleJoin`'s catch
block currently just shows `err.message` (~line 30-32). `ApiError` already
carries `.status` (see `frontend/src/api.js`, `ApiError` class) — a join
that fails specifically because the room already started comes back as
HTTP 409 (`RoomAlreadyStartedError`, mapped in `backend/app/routers/rooms.py`
line 36). When `err.status === 409`, don't just show the raw "This game has
already started" message — automatically retry via
`api.reclaimPlayer(code, name)` using the same name/code already typed
(no extra tap, no separate "rejoin" button/flow), and only fall back to
showing an error if THAT also fails (wrong name, room genuinely doesn't
exist, etc.).

**Frontend — `frontend/src/App.jsx`:** this is the part most likely to get
missed. `enterRoom()` (~line 40-50) currently **always** does
`setStage('lobby')` unconditionally — that was fine because until now
nothing could ever hand it a result pointing at an already-started room.
A reclaim result will have `result.room.status === 'in_progress'`. Route
on that, the same way the existing `stage === 'resolving'` effect already
does (~line 27: `room.status === 'in_progress' ? 'game' : 'lobby'`) — reuse
that exact condition, don't reinvent it. Critically: **do not set
`freshStart` to `true`** for a reclaim. `freshStart`/`dealOnEntry` must stay
`false` here (default) — it exists specifically to distinguish a genuine
fresh match start (plays the cosmetic deal animation) from every other way
of landing on the game screen (reload, reconnect, and now reclaim), and the
comment at `GameScreen.jsx` ~line 117 already documents this distinction.
Setting it wrong here would replay a full deal animation for a player who's
rejoining mid-game with their hand already dealt — visually wrong and
confusing.

**Tests:** a reclaimed player's token round-trips (same `player_id`,
matches what `authenticate()` accepts), reclaim before game start is
rejected, reclaim with a name not in the room is rejected, and — the one
that matters most for "exact same condition" — confirm a reclaimed
connection's WebSocket snapshot is byte-identical in game-relevant content
to what a live, never-disconnected player would see (their hand, face-up,
blind count, active_layer, everything) via the existing `filtered_state`
path, since no new state is being invented here, only a way back to the
existing state.

## 4. Turn timer: 60s → 25s

**Backend** — `backend/app/sync/clock.py` line 24: `TURN_TIMEOUT_SECONDS =
60.0` → `25.0`.

**Frontend** — `frontend/src/screens/GameScreen.jsx` lines 14-15:
`STALL_WARNING_SECONDS = 30` and `URGENT_SECONDS = 10`. These are NOT
independent of the total — `STALL_WARNING_SECONDS = 30` is impossible to
ever trigger once the whole clock is only 25 seconds (it fires when
`secondsLeft <= STALL_WARNING_SECONDS`, and `secondsLeft` starts at 25).
Rescale both proportionally so the same *feel* (a stall warning partway
through, urgency near the very end) survives the shorter clock:
`STALL_WARNING_SECONDS = 12` (roughly the same ~50% mark as 30/60) and
`URGENT_SECONDS = 7` (roughly the same ~17% mark as 10/60). These are
proposed values, not a hard requirement — if you land on a different pair
that preserves the same rough proportions, that's fine, just don't leave
`STALL_WARNING_SECONDS` at a value ≥ the new total.

Also check `docs/WS_PROTOCOL.md`'s AFK section (~"Each turn is allowed **60
seconds**") and update the stated number there to match — this file has
been kept accurate against the real constants throughout the project, don't
let this be the first place it drifts.

## Verification expected afterward

- Deal-cap: run the seeded-deck approach used in prior passes (or the new
  unit test from part 1) across many seeds/player counts, confirm zero
  face-up layers with 2+ power cards, confirm total power-card count in the
  full deal is unchanged from before the fix.
- Chat back-button: open the drawer, use an actual back gesture (or
  `window.history.back()` in devtools) instead of the Close button, confirm
  the drawer closes and the game is still fully alive and connected — not
  just "didn't crash," actually still receiving state updates.
- Reclaim: start a 2-player game, force-close one player's tab/session
  (clear its `sessionStorage` to simulate real loss, not just a reload),
  confirm the normal "Join" flow with that same name auto-reclaims into the
  live game with their actual hand intact, and confirm it does NOT replay
  the deal animation.
- Reclaim edge case: confirm a SECOND reclaim attempt (or the original tab,
  if it somehow reconnects on its own) gets cleanly superseded via the
  existing `WS_SUPERSEDED`/4008 mechanism rather than both sockets fighting
  — this already exists for ordinary reconnects, just confirm it still
  holds when the new connection arrived via reclaim instead of a normal
  token-remembered reconnect.
- Timer: confirm a real AFK timeout now fires at 25s, not 60s, and that
  the stall-warning/urgent UI states both still visibly trigger before it
  does.
- `backend/`: `pytest` — expect 160 passed plus new tests for the deal cap
  and the reclaim endpoint.
