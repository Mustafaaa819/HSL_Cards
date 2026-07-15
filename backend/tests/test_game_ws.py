"""Phase 3 WebSocket sync tests.

Rooms are set up through the real REST lobby flow, then (for determinism)
the started room's Game is swapped for a rigged one via helpers.make_game —
the server code path from socket to engine stays fully real; only the
shuffle is removed.

TestClient websockets are synchronous, so "concurrent" clients are nested
context-managed sessions driven turn by turn.
"""

import json
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.rooms import room_manager
from app.routers.game_ws import (
    WS_BAD_AUTH_MESSAGE,
    WS_GAME_NOT_STARTED,
    WS_INVALID_TOKEN,
    WS_ROOM_NOT_FOUND,
    WS_SUPERSEDED,
)
from tests.helpers import make_game

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_rooms():
    room_manager.reset()
    yield
    room_manager.reset()


# ------------------------------------------------------------------ helpers


def make_started_room(num_players: int) -> tuple[str, list[dict]]:
    """Create + ready + start a room via the REST lobby. Returns
    (code, member payloads with player_id/token, host first)."""
    response = client.post("/rooms", json={"name": "P0"})
    assert response.status_code == 201, response.text
    host = response.json()
    code = host["room_code"]
    members = [host]
    for i in range(1, num_players):
        response = client.post(f"/rooms/{code}/join", json={"name": f"P{i}"})
        assert response.status_code == 200, response.text
        members.append(response.json())
    for member in members:
        response = client.put(
            f"/rooms/{code}/ready", json={"ready": True}, headers={"X-Player-Token": member["token"]}
        )
        assert response.status_code == 200, response.text
    response = client.post(f"/rooms/{code}/start", headers={"X-Player-Token": members[0]["token"]})
    assert response.status_code == 200, response.text
    return code, members


def rig_game(code: str, hands: dict, **kwargs) -> None:
    """Replace a started room's game with a deterministic one."""
    room_manager.get_room(code).game = make_game(hands, **kwargs)


def connect(stack: ExitStack, code: str, token: str) -> tuple:
    """Open an authenticated socket; returns (session, snapshot state dict)."""
    ws = stack.enter_context(client.websocket_connect(f"/ws/{code}"))
    ws.send_json({"token": token})
    message = ws.receive_json()
    assert message["type"] == "state"
    assert message["event"] is None
    return ws, message["state"]


def expect_close(code: str, first_message, expected_close_code: int) -> None:
    with client.websocket_connect(f"/ws/{code}") as ws:
        if isinstance(first_message, str):
            ws.send_text(first_message)
        else:
            ws.send_json(first_message)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == expected_close_code


def player_entry(state: dict, player_id: str) -> dict:
    return next(p for p in state["players"] if p["player_id"] == player_id)


# ------------------------------------------------------- connection + auth


def test_bad_token_is_rejected_with_close_code():
    code, _members = make_started_room(2)
    expect_close(code, {"token": "definitely-not-a-token"}, WS_INVALID_TOKEN)


def test_missing_or_malformed_auth_message_is_rejected():
    code, _members = make_started_room(2)
    expect_close(code, "this is not json", WS_BAD_AUTH_MESSAGE)
    expect_close(code, {"not_a_token": "x"}, WS_BAD_AUTH_MESSAGE)


def test_unknown_room_is_rejected():
    expect_close("ZZZZZ", {"token": "whatever"}, WS_ROOM_NOT_FOUND)


def test_room_still_in_lobby_is_rejected():
    response = client.post("/rooms", json={"name": "Early"})
    host = response.json()
    expect_close(host["room_code"], {"token": host["token"]}, WS_GAME_NOT_STARTED)


def test_second_start_does_not_replace_the_game_instance():
    code, members = make_started_room(2)
    game = room_manager.get_room(code).game
    response = client.post(f"/rooms/{code}/start", headers={"X-Player-Token": members[0]["token"]})
    assert response.status_code == 409
    assert room_manager.get_room(code).game is game


# ---------------------------------------------------------- state filtering


def test_connect_snapshot_hides_exactly_the_hidden_information():
    code, members = make_started_room(3)
    p0, p1, p2 = (m["player_id"] for m in members)
    # from_state draws the top of the draw deck (list end, "6C") into the
    # current player's hand, leaving "6S" as the one remaining deck card.
    rig_game(
        code,
        {
            p0: {"hand": ["3H"], "face_up": ["KH", "KD"], "blind": ["4H", "4D", "4S"]},
            p1: {"hand": ["5C", "5D"], "face_up": ["9D"], "blind": ["8S"]},
            p2: {"hand": ["QC"], "face_up": [], "blind": ["2S"]},
        },
        discard=["6H", "JD"],
        draw_deck=["6S", "6C"],
        current=p0,
    )

    with ExitStack() as stack:
        _ws, state = connect(stack, code, members[0]["token"])

    # Own layers: hand and face-up in full, blind as a count only.
    assert state["you"]["hand"] == ["3H", "6C"]
    assert state["you"]["face_up"] == ["KH", "KD"]
    assert state["you"]["blind_count"] == 3
    assert "blind" not in state["you"]

    # Other players: hand count only, face-up in full, blind count only.
    entry1 = player_entry(state, p1)
    assert entry1 == {
        "player_id": p1,
        "name": "P1",
        "seat": 1,
        "hand_count": 2,
        "face_up": ["9D"],
        "blind_count": 1,
        "active_layer": "hand",
        "finish_position": None,
    }
    assert player_entry(state, p2)["hand_count"] == 1

    # Shared zones: deck count only, discard pile in full.
    assert state["draw_deck_count"] == 1
    assert state["discard_pile"] == ["6H", "JD"]
    assert state["top_card"] == "JD"
    assert state["phase"] == "deck"
    assert state["current_player_id"] == p0
    assert state["direction"] == 1
    assert state["seven_pending"] is False

    # The payload must not contain a single hidden card value anywhere:
    # own blind, others' hands, others' blinds, or the deck card.
    payload = json.dumps(state)
    for hidden in ["4H", "4D", "4S", "5C", "5D", "QC", "8S", "2S", "6S"]:
        assert f'"{hidden}"' not in payload, f"hidden card {hidden} leaked"


# --------------------------------------------------------------- full match


def test_full_match_over_websockets_reaches_a_finishing_order():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    # Endgame rig: empty deck (hand phase), one card per layer each.
    rig_game(
        code,
        {
            p0: {"hand": ["3H"], "face_up": ["KH"], "blind": ["4H"]},
            p1: {"hand": ["5C"], "face_up": ["9D"], "blind": ["8S"]},
        },
        current=p0,
    )

    with ExitStack() as stack:
        ws0, state = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])
        assert state["phase"] == "hand"
        assert state["current_player_id"] == p0

        def step(sender, action: dict) -> tuple[dict, dict]:
            """One action -> both clients receive their own broadcast.
            Returns (shared event, sender's new state)."""
            sender.send_json(action)
            message0 = ws0.receive_json()
            message1 = ws1.receive_json()
            assert message0["event"] == message1["event"]
            sender_message = message0 if sender is ws0 else message1
            return sender_message["event"], sender_message["state"]

        # P0 empties their hand; face-up becomes their active layer.
        event, state = step(ws0, {"action": "play", "card": "3H"})
        assert event["kind"] == "play" and event["card"] == "3H"
        assert state["you"]["hand"] == []
        assert state["you"]["active_layer"] == "face_up"
        assert state["current_player_id"] == p1

        event, state = step(ws1, {"action": "play", "card": "5C"})
        assert state["top_card"] == "5C"

        # P0 plays from face-up, clearing it — next up for them is blind.
        event, state = step(ws0, {"action": "play", "card": "KH"})
        assert state["you"]["face_up"] == []
        assert state["you"]["active_layer"] == "blind"

        # P1's 9D can't beat KH — forced pickup; the pile lands in their HAND
        # (Layer 3) even though they were on face-up cards, per RULES.md.
        event, state = step(ws1, {"action": "pick_up"})
        assert event == {"kind": "pickup", "player_id": p1, "count": 3}
        assert state["you"]["hand"] == ["3H", "5C", "KH"]
        assert state["you"]["face_up"] == ["9D"]
        assert state["top_card"] is None

        # P0's blind flip: 4H on an empty pile is legal. Last card gone —
        # P0 finishes 1st, P1 is last, game over. The flip event is what
        # reveals the card to the table.
        event, state = step(ws0, {"action": "flip"})
        assert event["kind"] == "flip"
        assert event["card"] == "4H"
        assert event["played"] is True
        assert event["player_finished"] is True
        assert state["game_over"] is True
        assert state["finish_order"] == [p0, p1]
        assert state["current_player_id"] is None

        # Sockets stay open in the game-over state; actions just error.
        ws0.send_json({"action": "flip"})
        message = ws0.receive_json()
        assert message["type"] == "error"
        assert "over" in message["message"].lower()


# ------------------------------------------------------------ illegal moves


def test_illegal_and_out_of_turn_moves_error_privately_and_change_nothing():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {
            p0: {"hand": ["3H", "9C"], "blind": ["4H"]},
            p1: {"hand": ["5C", "QD"], "blind": ["8D"]},
        },
        discard=["8S"],
        current=p0,
    )

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        # Out of turn: rejected, sender only.
        ws1.send_json({"action": "play", "card": "QD"})
        message = ws1.receive_json()
        assert message["type"] == "error"
        assert "turn" in message["message"].lower()

        # On turn but illegal: 3H does not beat the 8S on the pile.
        ws0.send_json({"action": "play", "card": "3H"})
        message = ws0.receive_json()
        assert message["type"] == "error"
        assert "beat" in message["message"].lower()

        # Card the client doesn't hold, malformed card, unknown action.
        for bad in [
            {"action": "play", "card": "AH"},
            {"action": "play", "card": "banana"},
            {"action": "dance"},
        ]:
            ws0.send_json(bad)
            assert ws0.receive_json()["type"] == "error"

        # Now a legal play. The VERY NEXT message each client sees is this
        # broadcast — proving none of the rejects were broadcast — and the
        # pile still shows the untouched 8S underneath.
        ws0.send_json({"action": "play", "card": "9C"})
        message0 = ws0.receive_json()
        message1 = ws1.receive_json()
        assert message0["event"]["kind"] == "play"
        assert message0["event"]["card"] == "9C"
        assert message1["state"]["discard_pile"] == ["8S", "9C"]
        assert message1["state"]["current_player_id"] == p1


# --------------------------------------------------------------- reconnect


def test_reconnect_replaces_socket_and_restores_filtered_state():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {
            p0: {"hand": ["3H", "9C"], "blind": ["4H"]},
            p1: {"hand": ["5C"], "blind": ["8D"]},
        },
        current=p0,
    )

    with ExitStack() as stack:
        ws0_old, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        # Same player, new socket: the old one is closed as superseded and
        # the new one immediately gets the current filtered state back.
        ws0_new, snapshot = connect(stack, code, members[0]["token"])
        assert snapshot["you"]["hand"] == ["3H", "9C"]
        assert snapshot["current_player_id"] == p0
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws0_old.receive_json()
        assert exc_info.value.code == WS_SUPERSEDED

        # The replaced player acts on the NEW socket; both live sockets get
        # the broadcast. ws1 saw nothing from the reconnect itself — its
        # next message is this play, so other players were unaffected.
        ws0_new.send_json({"action": "play", "card": "3H"})
        message_new = ws0_new.receive_json()
        message1 = ws1.receive_json()
        assert message_new["event"]["kind"] == "play"
        assert message1["event"]["card"] == "3H"
        assert message1["state"]["current_player_id"] == p1
        assert player_entry(message1["state"], p0)["hand_count"] == 1
