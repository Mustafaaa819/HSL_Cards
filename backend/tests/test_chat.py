"""In-game chat over the existing game socket.

Chat is the one client message that is deliberately NOT a game action: it
skips the engine, the AFK clock, and the filtered state broadcast. Most of
what's worth testing here is that it stays out of those three things, not
that text arrives.

Room setup reuses the REST-lobby helpers from test_game_ws.
"""

import time

import pytest
from contextlib import ExitStack

from fastapi.testclient import TestClient

from app.main import app
from app.rooms import room_manager
from app.routers.game_ws import CHAT_LOG_LIMIT, CHAT_MAX_LENGTH, _last_chat_at
from app.sync import turn_clock
from tests.test_game_ws import connect, connect_with_chat, make_started_room, rig_game

client = TestClient(app)

# Comfortably past CHAT_MIN_INTERVAL_SECONDS — the cooldown is real wall
# time, so tests that need two accepted messages have to actually wait.
COOLDOWN_GAP = 0.35


@pytest.fixture(autouse=True)
def clean_rooms():
    room_manager.reset()
    _last_chat_at.clear()
    yield
    room_manager.reset()
    _last_chat_at.clear()


def two_player_room() -> tuple[str, list[dict]]:
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {
            p0: {"hand": ["3H", "9C"], "blind": ["4H"]},
            p1: {"hand": ["5C"], "blind": ["8D"]},
        },
        discard=["8S"],
        current=p0,
    )
    return code, members


# ------------------------------------------------------------- broadcasting


def test_chat_reaches_every_socket_including_the_sender():
    code, members = two_player_room()
    p0 = members[0]["player_id"]

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        ws0.send_json({"action": "chat", "text": "  good luck  "})
        for ws in (ws0, ws1):
            message = ws.receive_json()
            assert message["type"] == "chat"
            entry = message["message"]
            assert entry["player_id"] == p0
            assert entry["text"] == "good luck"  # stripped
            assert isinstance(entry["id"], str) and entry["id"]
            assert isinstance(entry["ts"], float)


def test_chat_works_out_of_turn_and_after_game_over():
    """No turn check anywhere in the chat path — that's the point of it not
    going through _apply_action."""
    code, members = two_player_room()
    p1 = members[1]["player_id"]

    with ExitStack() as stack:
        ws0, state = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])
        assert state["current_player_id"] != p1  # P1 is emphatically not up

        ws1.send_json({"action": "chat", "text": "not my turn but still talking"})
        assert ws0.receive_json()["type"] == "chat"
        assert ws1.receive_json()["type"] == "chat"

        room_manager.get_room(code).game.game_over = True
        time.sleep(COOLDOWN_GAP)
        ws1.send_json({"action": "chat", "text": "gg"})
        assert ws1.receive_json()["message"]["text"] == "gg"


def test_chat_does_not_rearm_the_afk_clock_or_broadcast_state():
    """The regression this whole design exists to prevent: chat routed
    through the action path would reset the current player's 25 seconds and
    hand every client a fresh state payload."""
    code, members = two_player_room()

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        before = turn_clock.remaining(code)
        assert before is not None
        time.sleep(0.05)

        ws0.send_json({"action": "chat", "text": "stalling for time"})
        assert ws0.receive_json()["type"] == "chat"
        assert ws1.receive_json()["type"] == "chat"

        after = turn_clock.remaining(code)
        assert after < before  # kept counting down; was not re-armed to 25

        # Nothing else was queued behind the chat frame: the next message
        # each socket sees is the broadcast from a real move, proving no
        # state payload was emitted for the chat.
        time.sleep(COOLDOWN_GAP)
        ws0.send_json({"action": "play", "card": "9C"})
        assert ws0.receive_json()["type"] == "state"
        assert ws1.receive_json()["type"] == "state"


# --------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "bad",
    [
        {"action": "chat"},  # no text at all
        {"action": "chat", "text": 42},  # not a string
        {"action": "chat", "text": "   "},  # empty once stripped
        {"action": "chat", "text": "x" * (CHAT_MAX_LENGTH + 1)},
    ],
)
def test_malformed_chat_is_rejected_to_the_sender_only(bad):
    code, members = two_player_room()

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        ws0.send_json(bad)
        message = ws0.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "protocol"
        assert room_manager.get_room(code).chat_log == []

        # ws1 heard nothing about it — its next frame is a legal message.
        ws0.send_json({"action": "chat", "text": "ok"})
        assert ws1.receive_json()["message"]["text"] == "ok"


def test_message_of_exactly_the_limit_is_accepted():
    code, members = two_player_room()
    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws0.send_json({"action": "chat", "text": "x" * CHAT_MAX_LENGTH})
        assert len(ws0.receive_json()["message"]["text"]) == CHAT_MAX_LENGTH


def test_rapid_messages_are_dropped_silently():
    """Emoji-mash guard. Dropped, not rejected: an error toast per tap
    would be a worse experience than the flood it prevents."""
    code, members = two_player_room()

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])

        for text in ["🔥", "🔥", "🔥"]:
            ws0.send_json({"action": "chat", "text": text})
        time.sleep(COOLDOWN_GAP)
        ws0.send_json({"action": "chat", "text": "after the cooldown"})

        # Exactly two landed: the first of the burst, and the one that
        # waited. No error frame for the two that were dropped.
        first = ws0.receive_json()
        assert first["type"] == "chat" and first["message"]["text"] == "🔥"
        second = ws0.receive_json()
        assert second["type"] == "chat" and second["message"]["text"] == "after the cooldown"
        assert len(room_manager.get_room(code).chat_log) == 2


def test_cooldown_is_per_player_not_per_room():
    code, members = two_player_room()

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        ws0.send_json({"action": "chat", "text": "from P0"})
        ws1.send_json({"action": "chat", "text": "from P1"})
        # Both land back-to-back — one player talking must not mute another.
        assert [ws0.receive_json()["message"]["text"] for _ in range(2)] == ["from P0", "from P1"]


# ------------------------------------------------------------------ history


def test_connect_sends_the_backlog_and_reconnect_gets_it_again():
    code, members = two_player_room()

    with ExitStack() as stack:
        ws0, _, history = connect_with_chat(stack, code, members[0]["token"])
        assert history == []  # always sent, even empty

        ws0.send_json({"action": "chat", "text": "first"})
        ws0.receive_json()

        # A player joining the socket late sees what they missed...
        _ws1, _state, history1 = connect_with_chat(stack, code, members[1]["token"])
        assert [m["text"] for m in history1] == ["first"]

        # ...and so does the same player reconnecting on a new socket.
        _ws0b, _state, history0b = connect_with_chat(stack, code, members[0]["token"])
        assert [m["text"] for m in history0b] == ["first"]


def test_chat_log_keeps_only_the_newest_entries():
    code, members = two_player_room()
    room = room_manager.get_room(code)
    # Prefill past the cap rather than sending 50+ frames through the
    # cooldown — the trimming is what's under test, not the transport.
    room.chat_log.extend({"id": str(i), "player_id": "x", "text": str(i), "ts": 0.0} for i in range(CHAT_LOG_LIMIT))

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws0.send_json({"action": "chat", "text": "newest"})
        ws0.receive_json()

    assert len(room.chat_log) == CHAT_LOG_LIMIT
    assert room.chat_log[-1]["text"] == "newest"
    assert room.chat_log[0]["text"] == "1"  # the oldest entry fell off
