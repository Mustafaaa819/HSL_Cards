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
  socket immediately receives a full filtered snapshot. No AFK/timeout
  logic here — that's Phase 5.

- ACTIONS: {"action": "play", "card": "7H"} | {"action": "pick_up"} |
  {"action": "flip", "index": 0}. There is deliberately NO "draw"
  action: the engine draws for the current player automatically at turn
  start during the deck phase (no decision involved). The "index" on
  flip is optional and cosmetic — which physical face-down card gets
  tapped — since blind cards are unknown by definition.

- SERVER -> CLIENT: {"type": "state", "event": <event|null>, "state": {...}}
  (snapshot on connect with event=null; broadcast to every connected
  player after each legal action, each with their own filtered view) and
  {"type": "error", "message": "..."} (sender only; nothing mutated,
  nothing broadcast). The event carries what happened publicly — notably
  a blind flip's revealed card, which is public the instant it's flipped.

- GAME END: sockets are left OPEN after game over (Phase 4 needs them
  for the results screen). The final broadcast has game_over=true and
  the full finish_order; any further action gets an error back.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.engine import Card, EngineError, Game
from app.rooms import InvalidTokenError, Room, RoomNotFoundError, room_manager
from app.sync import connection_hub, filtered_state

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
        await _send_error(websocket, "Messages must be JSON")
        return
    if not isinstance(message, dict):
        await _send_error(websocket, "Messages must be JSON objects")
        return

    try:
        event = _apply_action(room.game, player_id, message)
    except (ProtocolError, EngineError) as err:
        # Illegal, out-of-turn, or malformed: the sender alone hears about
        # it, and nothing was mutated so there is nothing to broadcast.
        await _send_error(websocket, str(err))
        return

    await _broadcast_state(room, event)


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
        return {"kind": "pickup", "player_id": player_id, "count": count}

    if action == "flip":
        index = message.get("index", 0)
        if not isinstance(index, int) or isinstance(index, bool):
            raise ProtocolError('"index" must be an integer')
        result = game.flip_blind(player_id, index)
        return {
            # The flip event is what reveals the card to the table — state
            # payloads never carry blind values (see sync.serializer).
            "kind": "flip",
            "player_id": player_id,
            "card": str(result.card),
            "played": result.played,
            "pile_burned": result.pile_burned,
            "direction_reversed": result.direction_reversed,
            "picked_up": result.picked_up,
            "player_finished": result.player_finished,
        }

    raise ProtocolError(f"Unknown action: {action!r}")


async def _send_error(websocket: WebSocket, message: str) -> None:
    await websocket.send_json({"type": "error", "message": message})


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
