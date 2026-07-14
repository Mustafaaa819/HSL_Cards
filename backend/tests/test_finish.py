"""Finishing order, game end, and turn rotation around finished players."""

import pytest

from app.engine import Game, IllegalMoveError, Player
from tests.helpers import c, card, make_game


def test_full_finishing_order_is_tracked():
    game = make_game(
        {
            "a": {"hand": ["9H"]},
            "b": {"hand": ["2C"]},
            "c": {"hand": ["3C", "4C"]},
        },
        discard=["5H"],
    )
    result = game.play_card("a", card("9H"))
    assert result.player_finished
    assert game.players[0].finish_position == 1
    assert not game.game_over  # first finisher does NOT end the game
    assert game.current_player.player_id == "b"

    result = game.play_card("b", card("2C"))
    assert result.player_finished and result.game_over
    # c never emptied their cards: ranked last automatically.
    assert game.players[1].finish_position == 2
    assert game.players[2].finish_position == 3
    assert game.finish_order == ["a", "b", "c"]
    assert game.game_over


def test_no_actions_after_game_over():
    game = make_game(
        {"a": {"hand": ["9H"]}, "b": {"hand": ["3C", "4C"]}},
        discard=["5H"],
    )
    game.play_card("a", card("9H"))
    assert game.game_over
    with pytest.raises(IllegalMoveError):
        game.play_card("b", card("3C"))


def test_turn_rotation_skips_finished_players():
    players = [
        Player(player_id="a", finish_position=1),
        Player(player_id="b", hand=c("9C", "4D")),
        Player(player_id="c", hand=c("KH", "5D")),
    ]
    game = Game.from_state(players, discard_pile=c("5H"), current_index=1)
    game.play_card("b", card("9C"))
    assert game.current_player.player_id == "c"  # a was skipped
    game.play_card("c", card("KH"))
    assert game.current_player.player_id == "b"  # wrapped past a again


def test_finish_by_successful_blind_flip():
    game = make_game(
        {"a": {"blind": ["AS"]}, "b": {"hand": ["3C", "4D"]}},
        discard=["3H"],
    )
    result = game.flip_blind("a")
    assert result.played and result.player_finished
    assert game.players[0].finish_position == 1
    assert game.players[1].finish_position == 2  # last player holding cards
    assert game.game_over


def test_cannot_finish_while_draw_deck_alive():
    game = make_game(
        {"a": {}, "b": {"hand": ["3C", "4C"]}},
        draw_deck=["9C", "8C"],
    )
    player_a = game.players[0]
    # a's whole holding is the 8C drawn at turn start; playing it leaves a
    # with zero cards, but the deck still has the 9C so a is not done.
    game.play_card("a", card("8C"))
    assert not player_a.finished

    # b draws the last card (9C) and plays it; when the turn comes back to
    # a — zero cards, empty deck — a finishes on the spot.
    game.play_card("b", card("9C"))
    assert player_a.finish_position == 1
    assert game.players[1].finish_position == 2
    assert game.game_over
