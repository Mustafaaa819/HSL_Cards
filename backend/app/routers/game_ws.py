"""Live game WebSocket — /ws/{room_code}.

Thin translation layer, same philosophy as the REST router: every rule
about legality lives in the engine, every rule about identity lives in
rooms.manager, every rule about visibility lives in sync.serializer.
This file only parses messages, calls those, and reports back.

Protocol decisions (documented per the Phase 3 spec):

- AUTH: the first client message must be a JSON text frame
  {"token": "<bearer token from room create/join>"}. First-message auth
  was chosen over a query param so tokens never appear in server/proxy
  access logs. The server accepts the socket, waits up to
  AUTH_TIMEOUT_SECONDS for that frame, and closes with a 4xxx code on
  any failure — bad connections never linger.

- RECONNECT: a valid token connecting again replaces the player's
  existing socket; the old one is closed with WS_SUPERSEDED. The new
  socket immediately receives a full filtered snapshot.

- ACTIONS: {"action": "play", "card": "7H"} | {"action": "pick_up"} |
  {"action": "flip", "index": 0}. There is deliberately NO "draw"
  action: the engine draws for the current player automatically at turn
  start during the deck phase (no decision involved). The "index" on
  flip is optional and cosmetic — which physical face-down card gets
  tapped — since blind cards are unknown by definition.

- AFK (Phase 5): each turn gets TURN_TIMEOUT_SECONDS. On expiry the
  server forces a move for the current player (see _force_afk_move) and
  broadcasts it like any other. The clock is driven off the room, not a
  socket, so a player who closed their tab still times out.

- SERVER -> CLIENT: {"type": "state", "event": <event|null>, "state": {...}}
  (snapshot on connect with event=null; broadcast to every connected
  player after each legal action, each with their own filtered view) and
  {"type": "error", "message": ..., "code": ..., "card": ...} (sender
  only; nothing mutated, nothing broadcast). The error "code" is a stable
  machine-readable tag and "card" echoes the rejected card so the client
  can highlight the exact card that was refused. The event carries what
  happened publicly — notably a blind flip's revealed card, which is
  public the instant it's flipped.

- GAME END: sockets are left OPEN after game over (Phase 4 needs them
  for the results screen). The final broadcast has game_over=true and
  the full finish_order; any further action gets an error back.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.engine import Card, EngineError, FlipResult, Game, Layer, OutOfTurnError
from app.rooms import InvalidTokenError, Room, RoomNotFoundError, room_manager
from app.sync import connection_hub, filtered_state, turn_clock

router = APIRouter(tags=["game-websocket"])

AUTH_TIMEOUT_SECONDS = 10.0

# Application close codes (4000-4999 range is reserved for apps).
WS_BAD_AUTH_MESSAGE = 4000  # first frame wasn't {"token": "..."} (or never came)
WS_INVALID_TOKEN = 4001
WS_GAME_NOT_STARTED = 4002
WS_ROOM_NOT_FOUND = 4004
WS_SUPERSEDED = 4008  # replaced by a newer connection from the same player


class ProtocolError(Exception):
    """A structurally bad client message (unknown action, malformed card)."""


@router.websocket("/ws/{room_code}")
async def game_socket(websocket: WebSocket, room_code: str) -> None:
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        await websocket.close(WS_BAD_AUTH_MESSAGE, "Expected an auth message, got silence")
        return
    except WebSocketDisconnect:
        return

    token = _parse_token(raw)
    if token is None:
        await websocket.close(WS_BAD_AUTH_MESSAGE, 'First message must be {"token": "..."}')
        return

    try:
        room = room_manager.get_room(room_code)
    except RoomNotFoundError:
        await websocket.close(WS_ROOM_NOT_FOUND, f"No room with code {room_code.upper()}")
        return
    if room.game is None:
        await websocket.close(WS_GAME_NOT_STARTED, "The game has not started yet")
        return
    try:
        player = room_manager.authenticate(room, token)
    except InvalidTokenError:
        await websocket.close(WS_INVALID_TOKEN, "Token does not belong to a player in this room")
        return

    previous = connection_hub.register(room.code, player.player_id, websocket)
    if previous is not None:
        try:
            await previous.close(WS_SUPERSEDED, "Replaced by a newer connection")
        except RuntimeError:
            pass  # old socket already closed on its own — nothing to do

    # The game starts over REST, before any socket exists, so the first
    # connection is what gets the clock running. Later connections must not
    # re-arm it or the current player could refresh their way out of it.
    # Armed BEFORE the snapshot so the snapshot's turn_ends_in is real.
    turn_clock.arm_if_idle(room, _force_afk_move)

    # Snapshot goes only to the (re)connecting player; nobody else's view changed.
    await websocket.send_json(
        {"type": "state", "event": None, "state": filtered_state(room, player.player_id)}
    )

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_message(websocket, room, player.player_id, raw)
    except WebSocketDisconnect:
        pass
    finally:
        connection_hub.unregister(room.code, player.player_id, websocket)
        if not connection_hub.connections(room.code):
            # Nobody left to broadcast to. Without this an abandoned room
            # would keep forcing moves at itself until the game ended.
            turn_clock.cancel(room.code)


# ------------------------------------------------------------------ internal


def _parse_token(raw: str) -> str | None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(message, dict):
        return None
    token = message.get("token")
    return token if isinstance(token, str) and token else None


async def _handle_message(websocket: WebSocket, room: Room, player_id: str, raw: str) -> None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        await _send_error(websocket, "Messages must be JSON", "protocol")
        return
    if not isinstance(message, dict):
        await _send_error(websocket, "Messages must be JSON objects", "protocol")
        return

    try:
        event = _apply_action(room.game, player_id, message)
    except (ProtocolError, EngineError) as err:
        # Illegal, out-of-turn, or malformed: the sender alone hears about
        # it, and nothing was mutated so there is nothing to broadcast. The
        # turn didn't move, so the AFK clock keeps running — a player can't
        # buy time by spamming illegal moves.
        await _send_error(websocket, *_describe_error(room, err, message))
        return

    # Re-arm BEFORE the broadcast: arm() cancels the old turn's timer
    # synchronously, so it can't fire against the new player during the
    # broadcast's awaits.
    turn_clock.arm(room, _force_afk_move)
    await _broadcast_state(room, event)


def _display_name(room: Room, player_id: str) -> str:
    for player in room.players:
        if player.player_id == player_id:
            return player.name
    return "another player"  # unreachable: the engine only knows room players


def _describe_error(room: Room, err: Exception, message: dict) -> tuple[str, str, str | None]:
    """Turn an exception into (message, code, card) for the sender.

    The engine's own messages are already specific ("5H doesn't beat 9D",
    "No pickup in the blind phase") and are passed through verbatim — the
    point is to keep that specificity, not collapse it to "Illegal move".
    OutOfTurnError is the one exception: it can only phrase itself with
    player IDs, so it gets rebuilt here where display names are known.
    """
    if isinstance(err, OutOfTurnError):
        name = _display_name(room, err.current_player_id)
        return f"It's {name}'s turn, not yours", "out_of_turn", None

    code = "protocol" if isinstance(err, ProtocolError) else "illegal_move"
    # Echo the rejected card back so the client can highlight that exact
    # card rather than guessing which tap the error belongs to.
    card = message.get("card") if message.get("action") == "play" else None
    return str(err), code, card if isinstance(card, str) else None


def _apply_action(game: Game, player_id: str, message: dict) -> dict:
    """Translate one client action into an engine call. The engine is the
    validator — nothing is trusted from the client beyond structure."""
    action = message.get("action")

    if action == "play":
        spec = message.get("card")
        if not isinstance(spec, str):
            raise ProtocolError('The "play" action needs a "card" string like "7H"')
        try:
            card = Card.from_str(spec)
        except (ValueError, IndexError):
            raise ProtocolError(f"Unrecognized card: {spec!r}") from None
        result = game.play_card(player_id, card)
        return {
            "kind": "play",
            "player_id": player_id,
            "card": str(result.card),
            "pile_burned": result.pile_burned,
            "direction_reversed": result.direction_reversed,
            "player_finished": result.player_finished,
        }

    if action == "pick_up":
        count = game.pick_up_pile(player_id)
        return _pickup_event(player_id, count, forced=False)

    if action == "flip":
        index = message.get("index", 0)
        if not isinstance(index, int) or isinstance(index, bool):
            raise ProtocolError('"index" must be an integer')
        result = game.flip_blind(player_id, index)
        return _flip_event(player_id, result, forced=False)

    # Note there is no "skip" here, and there must not be: Game.skip_turn is
    # the AFK timer's fallback only, never something a client can ask for.
    raise ProtocolError(f"Unknown action: {action!r}")


def _pickup_event(player_id: str, count: int, *, forced: bool) -> dict:
    return {"kind": "pickup", "player_id": player_id, "count": count, "forced": forced}


def _flip_event(player_id: str, result: FlipResult, *, forced: bool) -> dict:
    # The flip event is what reveals the card to the table — state payloads
    # never carry blind values (see sync.serializer).
    return {
        "kind": "flip",
        "player_id": player_id,
        "card": str(result.card),
        "played": result.played,
        "pile_burned": result.pile_burned,
        "direction_reversed": result.direction_reversed,
        "picked_up": result.picked_up,
        "player_finished": result.player_finished,
        "forced": forced,
    }


# ---------------------------------------------------------------- afk timeout


async def _force_afk_move(room: Room) -> None:
    """The current player's 60s ran out — act for them and move play on.

    Never plays a card on their behalf: which card to play is the game's
    central strategic decision and guessing it could hand someone a loss.
    Only no-choice outcomes get forced, in order:

    1. On blind cards: flip. There's no decision to make here anyway — the
       rules say reveal one at random — so the forced move is exactly the
       move the player would have had.
    2. Pile has cards: pick it up. The normal penalty for not acting.
    3. Empty pile: skip. Pickup is illegal with nothing to pick up, so this
       is the only option left that isn't a guess. It's a self-penalty (they
       keep their cards while everyone else sheds theirs), which is also why
       it's safe to have as a fallback — there's no incentive to go AFK for it.
    """
    game = room.game
    if game is None or game.game_over:
        return

    player_id = game.current_player.player_id
    try:
        if game.active_layer(game.current_player) is Layer.BLIND:
            # blind is popped as cards are flipped, so 0 is always the next
            # still-unflipped card — earlier flips left no gap behind them.
            event = _flip_event(player_id, game.flip_blind(player_id, 0), forced=True)
        elif game.discard_pile:
            event = _pickup_event(player_id, game.pick_up_pile(player_id), forced=True)
        else:
            game.skip_turn(player_id)
            event = {"kind": "skip", "player_id": player_id, "forced": True}
    except EngineError:
        # The turn moved under us between expiry and here. Bail rather than
        # force something against the wrong player; the action that moved it
        # armed a fresh clock of its own.
        return

    turn_clock.arm(room, _force_afk_move)  # the next player may be AFK too
    await _broadcast_state(room, event)


async def _send_error(
    websocket: WebSocket, message: str, code: str = "illegal_move", card: str | None = None
) -> None:
    await websocket.send_json({"type": "error", "message": message, "code": code, "card": card})


async def _broadcast_state(room: Room, event: dict) -> None:
    """Send every connected player their own filtered view of the new state."""
    for player_id, socket in connection_hub.connections(room.code).items():
        payload = {"type": "state", "event": event, "state": filtered_state(room, player_id)}
        try:
            await socket.send_json(payload)
        except (WebSocketDisconnect, RuntimeError):
            # Socket died mid-broadcast; drop it and let the player's next
            # reconnect restore them. Everyone else still gets their state.
            connection_hub.unregister(room.code, player_id, socket)
