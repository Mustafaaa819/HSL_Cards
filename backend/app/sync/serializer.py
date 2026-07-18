"""The ONE place that decides what a player is allowed to see.

Every state payload sent over a game WebSocket — connect snapshot or
post-action broadcast — is built here, per viewer. Nothing else in the
app serializes game state, so hidden-information rules are auditable in
this single function.

Visibility rules (per Phase 3 spec / RULES.md):
- Viewer's hand (Layer 3): full card values.
- Viewer's face-up (Layer 2): full values (public anyway).
- Viewer's blind (Layer 1): COUNT only — never values, not even to the
  owner. A blind card only becomes visible through the flip *event*
  broadcast when it's revealed, never through passive state sync.
- Other players: hand = count only, face-up = full values, blind = count.
- Draw deck: count only — never identities or order.
- Discard pile: full contents (public by rule), plus top card and the
  pending-7 constraint so clients can render the pile's rule state.
- Turn holder, phase (deck/hand), direction, finish order: public.
"""

from __future__ import annotations

from app.engine import Card
from app.rooms import Room
from app.sync.clock import turn_clock


def _cards(cards: list[Card]) -> list[str]:
    return [str(card) for card in cards]


def filtered_state(room: Room, viewer_id: str) -> dict:
    """Serialize the room's live game exactly as `viewer_id` may see it."""
    game = room.game
    if game is None:
        raise ValueError("Room has no live game to serialize")

    names = {p.player_id: p.name for p in room.players}
    viewer = next(p for p in game.players if p.player_id == viewer_id)

    players = []
    for seat, player in enumerate(game.players):
        players.append(
            {
                "player_id": player.player_id,
                "name": names.get(player.player_id, player.player_id),
                "seat": seat,
                "hand_count": len(player.hand),
                "face_up": _cards(player.face_up),
                "blind_count": len(player.blind),
                "active_layer": game.active_layer(player).value,
                "finish_position": player.finish_position,
            }
        )

    return {
        "room_code": room.code,
        "phase": game.phase.value,
        "direction": game.direction,
        "current_player_id": None if game.game_over else game.current_player.player_id,
        "seven_pending": game.seven_pending,
        # Non-null while the current player owes a follow-up before the turn
        # can pass: "throw" (must play a card) or "flip" (must flip another
        # blind card). Without this, a client has no way to know a pickup or
        # a played 2 did NOT pass the turn.
        "pending_action": None if game.game_over else game.pending_action,
        "draw_deck_count": len(game.draw_deck),
        "discard_pile": _cards(game.discard_pile),
        "top_card": str(game.top_card) if game.top_card else None,
        "game_over": game.game_over,
        # Seconds until the AFK clock forces the current player's move, taken
        # at send time so a reconnecting client resumes mid-countdown instead
        # of restarting at the full timeout. None = no timer running.
        "turn_ends_in": turn_clock.remaining(room.code),
        "finish_order": list(game.finish_order),
        "players": players,
        "you": {
            "player_id": viewer.player_id,
            "hand": _cards(viewer.hand),
            "face_up": _cards(viewer.face_up),
            "blind_count": len(viewer.blind),
            "active_layer": game.active_layer(viewer).value,
            "finish_position": viewer.finish_position,
        },
    }
