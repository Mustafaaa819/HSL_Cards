"""Lobby/room system tests — hit the REST endpoints via FastAPI's TestClient.

Gameplay itself is out of scope (Phase 3); these tests stop at "a started
room holds a correctly-constructed Phase 1 Game object".
"""

import pytest
from fastapi.testclient import TestClient

from app.engine import Game, Phase
from app.main import app
from app.rooms import CODE_ALPHABET, CODE_LENGTH, MAX_PLAYERS, room_manager

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_rooms():
    room_manager.reset()
    yield
    room_manager.reset()


def create_room(name: str = "Host") -> dict:
    response = client.post("/rooms", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def join_room(code: str, name: str) -> dict:
    response = client.post(f"/rooms/{code}/join", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def set_ready(code: str, token: str, ready: bool = True):
    return client.put(
        f"/rooms/{code}/ready", json={"ready": ready}, headers={"X-Player-Token": token}
    )


def start(code: str, token: str):
    return client.post(f"/rooms/{code}/start", headers={"X-Player-Token": token})


def make_ready_room(num_players: int) -> tuple[str, list[dict]]:
    """Create a room with num_players members, everyone ready. Returns
    (code, list of create/join payloads, host first)."""
    host = create_room("P0")
    code = host["room_code"]
    members = [host] + [join_room(code, f"P{i}") for i in range(1, num_players)]
    for member in members:
        response = set_ready(code, member["token"])
        assert response.status_code == 200, response.text
    return code, members


# ---------------------------------------------------------------- creation


def test_create_room_returns_code_and_host_credentials():
    data = create_room("Mustafa")
    assert len(data["room_code"]) == CODE_LENGTH
    assert all(ch in CODE_ALPHABET for ch in data["room_code"])
    assert data["player_id"]
    assert data["token"]

    room = data["room"]
    assert room["status"] == "lobby"
    assert room["max_players"] == MAX_PLAYERS
    assert len(room["players"]) == 1
    host = room["players"][0]
    assert host == {
        "player_id": data["player_id"],
        "name": "Mustafa",
        "ready": False,
        "is_host": True,
    }


def test_create_room_rejects_blank_name():
    response = client.post("/rooms", json={"name": "   "})
    assert response.status_code == 422


# ----------------------------------------------------------------- joining


def test_join_valid_room():
    host = create_room()
    data = join_room(host["room_code"], "Friend")
    assert data["token"] != host["token"]
    players = data["room"]["players"]
    assert [p["name"] for p in players] == ["Host", "Friend"]
    assert [p["is_host"] for p in players] == [True, False]


def test_join_is_case_insensitive_on_room_code():
    host = create_room()
    response = client.post(f"/rooms/{host['room_code'].lower()}/join", json={"name": "F"})
    assert response.status_code == 200


def test_join_nonexistent_room_is_404():
    response = client.post("/rooms/ZZZZZ/join", json={"name": "Ghost"})
    assert response.status_code == 404


def test_join_full_room_is_rejected():
    host = create_room("P0")
    code = host["room_code"]
    for i in range(1, MAX_PLAYERS):
        join_room(code, f"P{i}")
    response = client.post(f"/rooms/{code}/join", json={"name": "TooMany"})
    assert response.status_code == 409
    assert "full" in response.json()["detail"].lower()


def test_join_started_room_is_rejected():
    code, members = make_ready_room(2)
    assert start(code, members[0]["token"]).status_code == 200
    response = client.post(f"/rooms/{code}/join", json={"name": "Late"})
    assert response.status_code == 409
    assert "started" in response.json()["detail"].lower()


def test_duplicate_name_in_room_is_rejected():
    host = create_room("Sam")
    response = client.post(f"/rooms/{host['room_code']}/join", json={"name": "sam"})
    assert response.status_code == 409


# ---------------------------------------------------------------- ready-up


def test_ready_toggling():
    host = create_room()
    code, token = host["room_code"], host["token"]

    response = set_ready(code, token, True)
    assert response.status_code == 200
    assert response.json()["players"][0]["ready"] is True

    response = set_ready(code, token, False)
    assert response.status_code == 200
    assert response.json()["players"][0]["ready"] is False


def test_ready_with_bad_token_is_401():
    host = create_room()
    response = set_ready(host["room_code"], "not-a-real-token")
    assert response.status_code == 401


# ------------------------------------------------------------------- start


def test_start_requires_all_players_ready():
    host = create_room("P0")
    code = host["room_code"]
    join_room(code, "P1")  # never readies up
    set_ready(code, host["token"])

    response = start(code, host["token"])
    assert response.status_code == 409
    assert "P1" in response.json()["detail"]


def test_start_requires_host():
    code, members = make_ready_room(3)
    response = start(code, members[1]["token"])
    assert response.status_code == 403


def test_start_requires_two_players():
    host = create_room()
    set_ready(host["room_code"], host["token"])
    response = start(host["room_code"], host["token"])
    assert response.status_code == 409


def test_start_twice_is_rejected():
    code, members = make_ready_room(2)
    assert start(code, members[0]["token"]).status_code == 200
    response = start(code, members[0]["token"])
    assert response.status_code == 409


def test_start_instantiates_engine_game_with_players_in_join_order():
    code, members = make_ready_room(4)
    response = start(code, members[0]["token"])
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"

    room = room_manager.get_room(code)
    game = room.game
    assert isinstance(game, Game)
    # Seats follow join order, so seat 0 = host and the engine's "seat 0
    # starts" rule puts the host on turn.
    expected_ids = [m["player_id"] for m in members]
    assert [p.player_id for p in game.players] == expected_ids
    assert game.current_player.player_id == members[0]["player_id"]
    # A fresh 4-player game: one deck, everyone dealt 3+3+3 (+1 turn-start
    # draw for the current player), deck phase underway.
    assert game.phase is Phase.DECK
    assert all(len(p.blind) == 3 and len(p.face_up) == 3 for p in game.players)
    assert len(game.current_player.hand) == 4


def test_room_at_engine_max_can_start():
    code, members = make_ready_room(MAX_PLAYERS)
    response = start(code, members[0]["token"])
    assert response.status_code == 200
    game = room_manager.get_room(code).game
    assert len(game.players) == MAX_PLAYERS


# ---------------------------------------------------------------- room state


def test_get_room_state_requires_membership_token():
    host = create_room()
    code = host["room_code"]

    response = client.get(f"/rooms/{code}", headers={"X-Player-Token": host["token"]})
    assert response.status_code == 200
    assert response.json()["code"] == code

    response = client.get(f"/rooms/{code}", headers={"X-Player-Token": "wrong"})
    assert response.status_code == 401


def test_room_state_never_leaks_tokens():
    host = create_room()
    join_room(host["room_code"], "Friend")
    response = client.get(
        f"/rooms/{host['room_code']}", headers={"X-Player-Token": host["token"]}
    )
    body = response.text
    assert host["token"] not in body
    for player in response.json()["players"]:
        assert "token" not in player


# ----------------------------------------------------------------- leaving


def test_leave_before_start_removes_player():
    host = create_room()
    code = host["room_code"]
    friend = join_room(code, "Friend")

    response = client.post(f"/rooms/{code}/leave", headers={"X-Player-Token": friend["token"]})
    assert response.status_code == 200
    names = [p["name"] for p in response.json()["room"]["players"]]
    assert names == ["Host"]


def test_host_leaving_promotes_next_player():
    host = create_room()
    code = host["room_code"]
    join_room(code, "Friend")

    response = client.post(f"/rooms/{code}/leave", headers={"X-Player-Token": host["token"]})
    assert response.status_code == 200
    players = response.json()["room"]["players"]
    assert players[0]["name"] == "Friend"
    assert players[0]["is_host"] is True


def test_last_player_leaving_deletes_room():
    host = create_room()
    code = host["room_code"]
    response = client.post(f"/rooms/{code}/leave", headers={"X-Player-Token": host["token"]})
    assert response.status_code == 200
    assert response.json()["room"] is None

    response = client.post(f"/rooms/{code}/join", json={"name": "Anyone"})
    assert response.status_code == 404


def test_leave_after_start_is_rejected():
    code, members = make_ready_room(2)
    assert start(code, members[0]["token"]).status_code == 200
    response = client.post(f"/rooms/{code}/leave", headers={"X-Player-Token": members[1]["token"]})
    assert response.status_code == 409
