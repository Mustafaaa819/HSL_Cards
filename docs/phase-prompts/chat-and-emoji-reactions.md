# In-game text chat + emoji reactions (no voice)

## Scope decision, already made — do not build voice

Voice chat was considered and explicitly cut for this pass: it needs WebRTC
signaling plus almost certainly a TURN relay (players are on separate phone
networks, not a LAN — STUN-only frequently fails against mobile carrier
NAT), which is real infrastructure and/or ongoing cost, not a checkbox.
Recommendation given to and accepted by the project owner: players use an
existing call app (Discord, phone) alongside the game instead. If voice ever
gets built, it's its own separate phase — nothing in this prompt should lay
groundwork for it (no placeholder mic UI, no WebRTC dependencies).

## Context (read before writing any code)

Every player already holds exactly one open WebSocket per game — see
`docs/WS_PROTOCOL.md` and `backend/app/routers/game_ws.py`. Chat rides that
same connection as a new action/message type; no new connection, no new
endpoint.

**Backend, read these exact spots:**

- `backend/app/routers/game_ws.py`, `_handle_message()` (~line 155): parses
  the raw frame, then calls `_apply_action()` which always ends in
  `turn_clock.arm(room, _force_afk_move)` + `_broadcast_state(room, event)`
  (~line 175-179). Chat must NOT go through this path — it isn't a game
  action, must not touch the AFK clock, and must not trigger a filtered
  state re-broadcast (wasteful and semantically wrong: chat is public to
  everyone identically, game state is not). Branch on
  `message.get("action") == "chat"` at the top of `_handle_message`, before
  the existing `_apply_action` call, and handle it in a separate function
  that never calls `turn_clock` or `_broadcast_state`.
- `backend/app/sync/hub.py`, `ConnectionHub.connections(room_code)` (~line
  39): returns `{player_id: websocket}` for the room. `_broadcast_state`
  (~line 373 in `game_ws.py`) shows the iterate-and-send pattern to copy —
  chat's broadcast is simpler since there's no per-player filtering, every
  socket gets the identical payload.
- `backend/app/rooms/models.py`: `Room` is a plain `@dataclass` (~line 36,
  fields `code`, `players`, `status`, `game`, `created_at`). Add
  `chat_log: list[dict] = field(default_factory=list)`, capped at the last
  50 entries (drop oldest on append past that), so a reconnecting or
  late-arriving socket isn't dropped into a silent room. `secrets` (already
  imported and used in `rooms/manager.py` for `player_id`/`token`
  generation — `secrets.token_hex(4)`, `secrets.token_urlsafe(16)`) is the
  existing convention for generating IDs in this codebase; use
  `secrets.token_hex(4)` for each chat message's id too, not `uuid`.
- `backend/app/routers/game_ws.py`, inside `game_socket()` (~line 122-125):
  the connect snapshot is sent once, right after auth succeeds. Send the
  room's `chat_log` alongside it — either as a second frame
  (`{"type": "chat_history", "messages": [...]}`) sent immediately after the
  state snapshot, or folded into the same connect payload. A second frame is
  simpler and doesn't touch the existing, carefully-documented `state`
  payload shape — prefer that.

**Frontend, read these exact spots:**

- `frontend/src/hooks/useGameSocket.js`, `socket.onmessage` (~line 33-54):
  dispatches on `message.type`. Add `else if (message.type === 'chat')` →
  call a new `handlersRef.current?.onChat?.(message.message)`, and `else if
  (message.type === 'chat_history')` → `handlersRef.current?.onChatHistory
  ?.(message.messages)`. `sendAction` (~line 94) already sends any action
  object over the socket — `sendAction({ action: 'chat', text })` needs no
  new plumbing.
- `frontend/src/screens/GameScreen.jsx`: every existing transient visual
  effect in this file (`flights`, `burn`, `forcedFlash`, `powerFx`,
  `blindReveal`) follows the same shape — a `useState` holding the current
  effect(s), a `useRef` timer, cleared via `setTimeout`, cleaned up in the
  unmount effect (~line 225-234ish, the `clearTimeout`/`clearInterval`
  block). Match this exactly for chat bubbles rather than inventing a
  different pattern.
- `seatRefs.current[player_id]` (opponents, set ~line 632's
  `seatRef={(el) => (seatRefs.current[player.player_id] = el)}`) and
  `youAreaRef` (yourself) are the existing anchor points already used by
  `resolveMotion`'s flight-origin math — reuse them for bubble placement
  rather than adding new refs.
- The header (~line 545, `.game-header`) already holds a row of `.chip`
  elements (room code, phase, direction). Add the chat toggle here, styled
  as another chip-like button, not a new UI region.

## What to build

### Backend

1. `Room.chat_log: list[dict]` field, capped at 50 (append then slice/pop
   from the front past that length).
2. A `_handle_chat(websocket, room, player_id, message)` function, called
   from `_handle_message` before the existing action dispatch, that:
   - Reads `message.get("text")`. Must be a non-empty string after
     `.strip()`. Reject (send the existing `_send_error` shape, code
     `"protocol"`) if missing, not a string, empty after stripping, or over
     **240 characters**.
   - Builds `{"id": secrets.token_hex(4), "player_id": player_id, "text":
     stripped_text, "ts": time.time()}`, appends to `room.chat_log` (cap at
     50), and broadcasts `{"type": "chat", "message": entry}` to every
     socket in `connection_hub.connections(room.code)` — same
     try/except-on-send-failure-and-unregister pattern `_broadcast_state`
     already uses, just without the per-player `filtered_state` call.
   - Does not call `turn_clock.arm`/`turn_clock.arm_if_idle`. Does not
     require it to be the sender's turn — chat works regardless of whose
     turn it is or what phase the game is in, as long as the socket is
     connected.
   - Basic spam guard: track the sender's last chat timestamp (a small
     `dict[str, float]` is fine — either on `Room` or module-level in
     `game_ws.py` keyed by `(room_code, player_id)`) and silently drop (no
     error, just no broadcast) messages sent less than 300ms after that
     player's previous one, so someone tapping a reaction emoji rapidly
     doesn't flood the room. Do not build anything more elaborate
     (profanity filtering, per-message moderation) — this is a small
     friend-group prototype, not a public chat product.
3. Send `{"type": "chat_history", "messages": room.chat_log}` once, right
   after the existing connect snapshot send in `game_socket()`.
4. Update `docs/WS_PROTOCOL.md` with a new `## Chat` section: the
   `{"action": "chat", "text": "..."}` client action, the 240-char limit,
   the `{"type": "chat", "message": {...}}` broadcast shape, and the
   `{"type": "chat_history", "messages": [...]}` connect-time payload —
   same documentation rigor as every other section in that file.

### Frontend

1. `useGameSocket.js`: the two new `onmessage` branches described above.
2. `GameScreen.jsx` state, alongside the existing transient-effect state
   block (~line 94-105):
   - `chatLog` (array, cap at ~100 client-side, seeded from
     `onChatHistory` then appended to by `onChat`).
   - `chatOpen` (bool, drawer visibility).
   - `bubbles` (array of `{ id, playerId, text }`), each auto-removed via
     `setTimeout` after `CHAT_BUBBLE_MS` (new constant, 2500, alongside the
     other duration constants at the top of the file, e.g. next to
     `BLIND_REVEAL_MS`).
   - Unread badge count while `chatOpen` is false (increment on `onChat`,
     zero it when the drawer opens).
3. `onChat` handler: append to `chatLog`, push a new `bubbles` entry.
4. Bubble rendering: fixed-position overlay anchored to
   `rectOf(seatRefs.current[playerId])` for opponents or
   `rectOf(youAreaRef.current)` for yourself (same `rectOf` helper already
   used everywhere else in this file), `pointer-events: none`, pop in and
   fade out. Respect `prefers-reduced-motion` the same way every other
   effect in this file does — skip the pop entrance, keep it legible for a
   shorter, non-animated hold.
5. Chat toggle: a new chip-style button in `.game-header` next to the
   existing chips, showing an unread badge when `chatOpen` is false and
   `chatLog` has grown since it was last opened.
6. Chat drawer (open state only — take zero layout space while closed): a
   bottom-sheet panel, styled consistent with the existing glass/overlay
   visual language already established in `App.css` (reuse existing color
   tokens — no new palette), containing:
   - A scrollable message list (`chatLog`), each entry showing sender name
     (via the existing `nameById` lookup already built elsewhere in this
     file) and text. Render `{entry.text}` as plain text content — never
     `dangerouslySetInnerHTML` — React's default text rendering is already
     injection-safe, don't add a sanitization library, just don't bypass
     the default.
   - A text input (`maxLength={240}` matching the server limit) plus a send
     button, wired to `sendAction({ action: 'chat', text: trimmedValue })`.
     No-op client-side on empty/whitespace-only input, mirroring (not
     replacing) the server-side validation.
   - A row of 8 quick-tap preset emoji above or beside the input:
     😂 🔥 😱 👏 😤 💀 🤔 🤝 — tapping one sends it immediately as a chat
     message whose text is just that glyph (no new action type — a
     one-character emoji message IS a reaction, the frontend can style it
     larger/differently in the bubble/log purely by checking `text.length`
     against a short emoji check, no protocol change needed).
7. New CSS in `App.css`: `.chat-bubble`, `.chat-toggle` (+ unread badge),
   `.chat-drawer`, quick-emoji row. Extend the existing
   `@media (prefers-reduced-motion: reduce)` block to cover the new bubble
   entrance animation, same pattern as every other effect already listed
   there.

## Explicitly out of scope for this pass

- Lobby chat. The lobby (`LobbyScreen.jsx`) runs over REST, not the game
  WebSocket (per `WS_PROTOCOL.md`'s own opening line: "the lobby... stays on
  the REST endpoints; connect the socket once the room has started"). Adding
  chat there would mean a second delivery mechanism entirely — don't start
  it as a side effect of this work.
- Any voice/mic UI, even as a disabled placeholder.
- Profanity filtering or message moderation beyond the length cap and
  300ms rate-guard described above.
- Persisting chat beyond the in-memory 50-message cap (this project keeps
  nothing in a database anywhere yet — matching that, not introducing the
  project's first persistence layer for chat specifically).

## Verification expected afterward

- Two-plus browser tabs/players: confirm a sent message appears in every
  tab's bubble + log, confirm it does NOT reset anyone's AFK turn timer
  (send chat mid-turn-countdown, confirm `turn_ends_in` keeps counting down
  normally in the state payloads — this is the one that would be easy to
  get wrong if chat accidentally routes through the existing action path).
- Confirm a reconnect (kill and reopen a tab with the same token) receives
  `chat_history` and the log isn't empty if messages were sent before the
  reconnect.
- Confirm the 240-char limit and the 300ms rate-guard both actually reject/
  drop as designed (rapid-tap a reaction emoji several times, confirm not
  all of them land).
- Confirm `prefers-reduced-motion: reduce` still shows bubbles (information)
  without the pop animation, same standard as every other effect in this
  file.
- Run `backend/`: `pytest` — expect 148 passed plus whatever new tests get
  added for the chat handler itself (a genuinely new server-side code path
  deserves real test coverage, unlike the last two passes which were pure
  frontend and left the suite count unchanged).
