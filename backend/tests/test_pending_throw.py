"""Follow-up throws (RULES.md 2026-07-18): pickups demand an immediate
throw, the 2 is a bonus action, and blind 2s chain flips. All three ride the
one shared `pending_throw` primitive, so these tests also pin how the
mechanisms compose."""

import pytest

from app.engine import IllegalMoveError, Layer, Phase
from tests.helpers import c, card, make_game

# --------------------------------------------------------- pickup follow-up


def test_pickup_keeps_turn_until_the_owed_throw():
    game = make_game(
        {"a": {"hand": ["3C", "9C"]}, "b": {"hand": ["4C", "5C"]}},
        discard=["KH"],
    )
    game.pick_up_pile("a")
    assert game.current_player.player_id == "a"
    assert game.pending_action == "throw"
    result = game.play_card("a", card("9C"))
    assert not result.must_throw_again
    assert game.pending_action is None
    assert game.current_player.player_id == "b"


def test_second_pickup_rejected_while_throw_is_owed():
    game = make_game(
        {"a": {"hand": ["3C", "9C"]}, "b": {"hand": ["4C", "5C"]}},
        discard=["KH"],
    )
    game.pick_up_pile("a")
    # Explicit rejection, not the empty-pile side effect: the wording names
    # the owed throw.
    with pytest.raises(IllegalMoveError, match="throw"):
        game.pick_up_pile("a")
    assert game.current_player.player_id == "a"


def test_pickup_clears_seven_constraint_for_the_owed_throw():
    game = make_game(
        {"a": {"hand": ["9C", "KD"]}, "b": {"hand": ["4C", "5C"]}},
        discard=["5H", "7H"],
        seven_pending=True,
    )
    assert game.legal_plays("a") == []  # nothing ≤7, no power card
    game.pick_up_pile("a")
    assert not game.seven_pending
    # The follow-up throw is NOT capped at ≤7 — the king is fine.
    game.play_card("a", card("KD"))
    assert game.current_player.player_id == "b"


# ------------------------------------------------------- the 2 bonus action


def test_playing_a_two_demands_a_second_throw():
    game = make_game(
        {"a": {"hand": ["2H", "9C", "3S"]}, "b": {"hand": ["4C", "5C"]}},
        discard=["KH"],
    )
    result = game.play_card("a", card("2H"))
    assert result.must_throw_again
    assert game.current_player.player_id == "a"
    assert game.pending_action == "throw"
    # Pickup can't dodge the obligation — and here the pile is NOT empty,
    # so this isn't the empty-pile guard doing the work.
    with pytest.raises(IllegalMoveError, match="throw"):
        game.pick_up_pile("a")
    # The follow-up must be legal in the normal sense: it beats the 2.
    game.play_card("a", card("9C"))
    assert game.current_player.player_id == "b"


def test_two_twos_in_a_row_chain_the_requirement():
    game = make_game(
        {"a": {"hand": ["2H", "2S", "9C", "3S"]}, "b": {"hand": ["4C", "5C"]}},
        discard=["KH"],
    )
    assert game.play_card("a", card("2H")).must_throw_again
    # The follow-up is itself a 2: the requirement re-arms, no depth limit.
    assert game.play_card("a", card("2S")).must_throw_again
    assert game.current_player.player_id == "a"
    game.play_card("a", card("9C"))
    assert game.current_player.player_id == "b"


def test_a_group_of_twos_arms_the_follow_up_once():
    game = make_game(
        {"a": {"hand": ["2H", "2S", "9C", "3S"]}, "b": {"hand": ["4C", "5C"]}},
        discard=["KH"],
    )
    result = game.play_cards("a", c("2H", "2S"))
    assert result.must_throw_again
    # One follow-up for the whole group, exactly like the other group
    # effects: this single throw settles it.
    game.play_card("a", card("9C"))
    assert game.pending_action is None
    assert game.current_player.player_id == "b"


def test_two_satisfies_seven_constraint_and_followup_is_free_of_it():
    game = make_game(
        {"a": {"hand": ["2H", "KD", "3S"]}, "b": {"hand": ["4C", "5C"]}},
        discard=["5H", "7H"],
        seven_pending=True,
    )
    assert game.play_card("a", card("2H")).must_throw_again
    # The 2 (a power card) satisfied the 7; the follow-up plays high freely.
    assert not game.seven_pending
    game.play_card("a", card("KD"))
    assert game.current_player.player_id == "b"


def test_deck_phase_two_as_last_hand_card_waives_the_follow_up():
    # Deck-phase layer transitions are locked, and the turn-start draw
    # already happened — so a 2 that empties the hand ends the turn
    # normally instead of reaching into face-up/blind.
    game = make_game(
        {
            "a": {"hand": ["2H"], "face_up": ["AD"], "blind": ["4S"]},
            "b": {"hand": ["4C", "5C"], "face_up": ["KD"], "blind": ["6S"]},
        },
        discard=["KH"],
        draw_deck=["9C", "2H"],  # top ("2H") is a's turn-start draw
    )
    assert game.phase is Phase.DECK
    assert game.players[0].hand == c("2H", "2H")
    result = game.play_cards("a", c("2H", "2H"))  # hand now empty, deck lives
    assert not result.must_throw_again
    assert game.pending_action is None
    assert game.current_player.player_id == "b"  # turn ended normally
    assert game.players[0].face_up == c("AD")  # lower layers untouched


def test_hand_phase_two_empties_hand_and_follow_up_comes_from_face_up():
    game = make_game(
        {
            "a": {"hand": ["2H"], "face_up": ["AD"], "blind": ["4S"]},
            "b": {"hand": ["4C", "5C"]},
        },
        discard=["KH"],
    )
    result = game.play_card("a", card("2H"))  # last hand card
    assert result.must_throw_again
    assert game.active_layer(game.players[0]) is Layer.FACE_UP
    game.play_card("a", card("AD"))  # the owed throw, from face-up
    assert game.current_player.player_id == "b"


def test_two_from_face_up_empties_it_and_follow_up_becomes_a_forced_flip():
    # One layer deeper than the hand->face-up case above: a 2 played from
    # face-up (hand already empty) that empties face-up too hands the
    # follow-up down into blind, where there's no free choice left — the
    # "throw" becomes a forced flip, same as any blind-phase action.
    game = make_game(
        {
            "a": {"hand": [], "face_up": ["2H"], "blind": ["4S", "5S"]},
            "b": {"hand": ["4C", "5C"], "blind": ["6S"]},
        },
        discard=["KH"],
    )
    assert game.active_layer(game.players[0]) is Layer.FACE_UP
    result = game.play_card("a", card("2H"))
    assert result.must_throw_again
    assert game.pending_action == "flip"  # not "throw" — the next layer is blind
    assert game.active_layer(game.players[0]) is Layer.BLIND
    assert game.current_player.player_id == "a"
    # Playing a card is not an option here; only a flip satisfies the debt.
    with pytest.raises(IllegalMoveError):
        game.play_card("a", card("4S"))
    flip_result = game.flip_blind("a")
    assert flip_result.played
    assert game.current_player.player_id == "b"


def test_two_as_very_last_card_finishes_without_owing_a_throw():
    game = make_game(
        {
            "a": {"hand": ["2H"], "face_up": [], "blind": []},
            "b": {"hand": ["4C", "5C"], "blind": ["6S"]},
        },
        discard=["KH"],
    )
    result = game.play_card("a", card("2H"))
    assert result.player_finished
    assert not result.must_throw_again
    assert game.game_over  # two players: the game ends right here
    assert game.finish_order == ["a", "b"]


# ------------------------------------------------------------ blind 2-chain


def test_blind_chain_of_twos_ends_in_a_win():
    game = make_game(
        {
            "a": {"blind": ["2S", "2C"]},
            "b": {"hand": ["4C", "5C"], "blind": ["6S"]},
        },
        discard=["KH"],
    )
    result = game.flip_blind("a")
    assert result.played and result.must_flip_again
    assert game.pending_action == "flip"
    # No pickup escape mid-chain either (and blind bars it anyway).
    with pytest.raises(IllegalMoveError):
        game.pick_up_pile("a")
    # The chained flip is the last blind card: the intended "big win".
    result = game.flip_blind("a")
    assert result.played and result.player_finished
    assert not result.must_flip_again
    assert game.game_over
    assert game.finish_order == ["a", "b"]


def test_blind_chain_then_later_flip_failure_layers_the_pickup_throw():
    # Note: the flip directly after a chained 2 can never fail — the 2 is
    # the lowest rank, so any non-power card beats it and any power card
    # auto-plays. A blind-phase failure therefore happens on a LATER cycle,
    # once opponents have raised the pile again; that's the composition this
    # test pins: 2-chain → safe flip → pile rises → failed flip → pickup
    # with the owed throw (Change 1) on top.
    game = make_game(
        {
            "a": {"blind": ["2S", "4C", "6S"]},
            "b": {"hand": ["QD", "5C"], "blind": ["6C"]},
        },
        discard=["KH", "9H"],
    )
    result = game.flip_blind("a")  # the 2 plays, chain arms
    assert result.card == card("2S") and result.must_flip_again
    result = game.flip_blind("a")  # chained flip: 4C beats the 2, chain ends
    assert result.card == card("4C") and result.played
    assert not result.must_flip_again
    assert game.current_player.player_id == "b"

    game.play_card("b", card("QD"))  # the pile climbs out of reach
    result = game.flip_blind("a")  # 6S can't beat the queen
    assert not result.played and result.must_throw_again
    assert game.pending_action == "throw"
    assert game.current_player.player_id == "a"
    picked = game.players[0].hand
    assert card("6S") in picked and card("QD") in picked
    assert game.players[0].blind == []
    game.play_card("a", card("QD"))  # the owed throw settles it
    assert game.current_player.player_id == "b"
