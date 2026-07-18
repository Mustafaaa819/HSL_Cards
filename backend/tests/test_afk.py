"""Phase 5 AFK turn clock over the real socket path.

Each test drives one legal action first: that re-arms the clock at the
shrunken test timeout (the connect-time arm still holds the real 60s), so
the timeout lands on a known player with both sockets already up. No
sleeping in the test — receive_json() blocks until the forced broadcast
arrives, which is the thing being tested.
"""

from contextlib import ExitStack

import pytest

from app.rooms import room_manager
from app.sync import turn_clock
from tests.test_game_ws import client, connect, make_started_room, player_entry, rig_game

TEST_TIMEOUT = 0.05


@pytest.fixture(autouse=True)
def clean_rooms_and_clock():
    room_manager.reset()
    original = turn_clock._timeout
    yield
    turn_clock._timeout = original
    for room_code in list(turn_clock._tasks):
        turn_clock.cancel(room_code)
    room_manager.reset()


def go_afk() -> None:
    """Shrink the clock. Takes effect on the next arm — i.e. the next turn."""
    turn_clock._timeout = TEST_TIMEOUT


def test_afk_forces_a_pickup_when_the_pile_has_cards():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {
            p0: {"hand": ["9C", "KD"], "blind": ["4H"]},
            p1: {"hand": ["3D", "QS"], "blind": ["8D"]},
        },
        discard=["8S"],
        current=p0,
    )

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        go_afk()
        ws0.send_json({"action": "play", "card": "9C"})
        ws0.receive_json()
        ws1.receive_json()

        # P1 never acts. Both sockets get the forced pickup, flagged as
        # forced so the UI can say "timed out" rather than "picked up".
        event = ws0.receive_json()["event"]
        assert event == {
            "kind": "pickup",
            "player_id": p1,
            "count": 2,
            "forced": True,
            "must_throw_again": True,
        }

        state = ws1.receive_json()["state"]
        assert state["you"]["hand"] == ["3D", "QS", "8S", "9C"]
        assert state["discard_pile"] == []
        # The pickup arms the mandatory throw: P1 is STILL on the clock.
        assert state["current_player_id"] == p1
        assert state["pending_action"] == "throw"

        # The owed throw is a real choice the server won't make, so the next
        # expiry resolves it with the empty-pile skip — only now does play
        # move on past the AFK player.
        message = ws0.receive_json()
        ws1.receive_json()
        assert message["event"] == {"kind": "skip", "player_id": p1, "forced": True}
        assert message["state"]["current_player_id"] == p0
        assert message["state"]["pending_action"] is None


def test_afk_on_blind_cards_forces_a_flip():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {
            p0: {"hand": ["9C", "KD"], "blind": ["4H"]},
            p1: {"hand": [], "face_up": [], "blind": ["8D", "2S"]},
        },
        discard=["8S"],
        current=p0,
    )

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        go_afk()
        ws0.send_json({"action": "play", "card": "9C"})
        ws0.receive_json()
        state = ws1.receive_json()["state"]
        assert state["you"]["active_layer"] == "blind"

        # Blind players get a flip forced, not a pickup: flipping carries no
        # decision anyway, so it's exactly the move they would have made.
        message = ws0.receive_json()
        event = message["event"]
        assert event["kind"] == "flip"
        assert event["forced"] is True
        assert event["card"] == "8D"  # the first still-unflipped blind card
        assert event["played"] is False  # 8D can't beat the 9C on top
        assert event["picked_up"] == 3  # 8S + 9C + the failed flip
        assert event["must_throw_again"] is True  # the pickup's owed throw
        assert player_entry(message["state"], p1)["blind_count"] == 1
        assert message["state"]["current_player_id"] == p1
        assert message["state"]["pending_action"] == "throw"


def test_afk_on_an_empty_pile_forces_a_skip():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {
            p0: {"hand": ["10C", "KD"], "blind": ["4H"]},
            p1: {"hand": ["3D", "QS"], "blind": ["8D"]},
        },
        discard=["8S"],
        current=p0,
    )

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        go_afk()
        ws0.send_json({"action": "play", "card": "10C"})  # nuke — pile is now empty
        assert ws0.receive_json()["state"]["discard_pile"] == []
        ws1.receive_json()

        # Nothing to pick up and the server won't choose a card to play, so
        # the turn just passes. P1 keeps their hand — a self-penalty, which
        # is why this is safe to have as a fallback.
        message = ws0.receive_json()
        assert message["event"] == {"kind": "skip", "player_id": p1, "forced": True}
        assert player_entry(message["state"], p1)["hand_count"] == 2
        assert message["state"]["current_player_id"] == p0


def test_afk_stuck_mid_two_gets_a_forced_pickup_then_a_skip():
    """A player throws a 2 (owes a follow-up throw, pickup barred) and goes
    AFK: the system's override pickup is the fallback — the same resolution
    an unanswered pile always had — then the next expiry's skip finally
    passes the turn."""
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {
            p0: {"hand": ["9C", "KD"], "blind": ["4H"]},
            p1: {"hand": ["2D", "QS", "3D"], "blind": ["8D"]},
        },
        discard=["8S"],
        current=p1,
    )

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws1, _ = connect(stack, code, members[1]["token"])

        go_afk()
        ws1.send_json({"action": "play", "card": "2D"})
        message = ws1.receive_json()
        assert message["event"]["must_throw_again"] is True
        assert message["state"]["pending_action"] == "throw"
        ws0.receive_json()

        # A client pickup is rejected mid-follow-up...
        ws1.send_json({"action": "pick_up"})
        message = ws1.receive_json()
        assert message["type"] == "error"
        assert "throw" in message["message"].lower()

        # ...but the AFK timer's system pickup goes through: the 8S + 2D pile
        # lands in P1's hand, and the throw is owed again.
        message = ws1.receive_json()
        assert message["event"] == {
            "kind": "pickup",
            "player_id": p1,
            "count": 2,
            "forced": True,
            "must_throw_again": True,
        }
        assert message["state"]["current_player_id"] == p1
        ws0.receive_json()

        # Second expiry: the skip discharges the owed throw. Play moves on.
        message = ws1.receive_json()
        assert message["event"] == {"kind": "skip", "player_id": p1, "forced": True}
        assert message["state"]["current_player_id"] == p0
        assert message["state"]["pending_action"] is None
        ws0.receive_json()


def test_skip_is_not_reachable_as_a_client_action():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {p0: {"hand": ["9C"], "blind": ["4H"]}, p1: {"hand": ["3D"], "blind": ["8D"]}},
        current=p0,
    )

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])

        # Empty pile, P0's turn — the exact state where the SERVER may skip.
        # A player asking for the same thing is still an unknown action.
        ws0.send_json({"action": "skip"})
        message = ws0.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "protocol"
        assert room_manager.get_room(code).game.current_player.player_id == p0


def test_state_payloads_carry_the_turn_countdown():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {p0: {"hand": ["9C", "KD"], "blind": ["4H"]}, p1: {"hand": ["3D"], "blind": ["8D"]}},
        discard=["8S"],
        current=p0,
    )

    with ExitStack() as stack:
        ws0, snapshot = connect(stack, code, members[0]["token"])
        # The connect snapshot is sent after the clock is armed, so even the
        # very first frame tells the client how long the turn has left.
        assert 0 < snapshot["turn_ends_in"] <= turn_clock._timeout

        ws0.send_json({"action": "play", "card": "9C"})
        state = ws0.receive_json()["state"]
        assert 0 < state["turn_ends_in"] <= turn_clock._timeout


def test_turn_countdown_is_null_once_the_game_is_over():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {
            p0: {"hand": ["9C"], "face_up": [], "blind": []},
            p1: {"hand": ["3D"], "blind": ["8D"]},
        },
        discard=["8S"],
        current=p0,
    )

    with ExitStack() as stack:
        ws0, _ = connect(stack, code, members[0]["token"])
        ws0.send_json({"action": "play", "card": "9C"})  # P0's last card — game over
        message = ws0.receive_json()
        assert message["state"]["game_over"] is True
        # No turn left to time: the client must not render a countdown over
        # the results screen.
        assert message["state"]["turn_ends_in"] is None


def test_clock_stops_when_the_last_socket_leaves():
    code, members = make_started_room(2)
    p0, p1 = (m["player_id"] for m in members)
    rig_game(
        code,
        {p0: {"hand": ["9C"], "blind": ["4H"]}, p1: {"hand": ["3D"], "blind": ["8D"]}},
        discard=["8S"],
        current=p0,
    )

    with ExitStack() as stack:
        connect(stack, code, members[0]["token"])
        assert turn_clock.is_armed(code)  # first connection starts the clock

    # Everyone's gone: nothing to broadcast to, so an abandoned room must not
    # keep forcing moves at itself.
    assert not turn_clock.is_armed(code)
