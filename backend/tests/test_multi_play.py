"""Multi-card (same-rank group) plays — RULES.md "Multi-card plays"."""

import pytest

from app.engine import IllegalMoveError
from tests.helpers import c, card, make_game


def test_same_rank_group_beats_pile_and_lands_together():
    game = make_game(
        {
            "a": {"hand": ["6H", "6C", "6D", "3S"]},
            "b": {"hand": ["9C", "4C"]},
        },
        discard=["5H"],
    )
    result = game.play_cards("a", c("6H", "6C", "6D"))
    assert result.cards == c("6H", "6C", "6D")
    assert result.card == card("6H")
    assert game.discard_pile == c("5H", "6H", "6C", "6D")
    assert game.top_card.rank == "6"
    assert game.players[0].hand == c("3S")
    assert game.current_player.player_id == "b"


def test_mixed_ranks_rejected():
    game = make_game(
        {"a": {"hand": ["2H", "7C", "3S"]}, "b": {"hand": ["9C", "4C"]}},
        discard=["5H"],
    )
    # Mixed power ranks are explicitly NOT a valid single play either.
    with pytest.raises(IllegalMoveError):
        game.play_cards("a", c("2H", "7C"))
    assert game.discard_pile == c("5H")
    assert game.players[0].hand == c("2H", "7C", "3S")


def test_claiming_more_copies_than_held_rejected_without_mutation():
    game = make_game(
        {"a": {"hand": ["6H", "3S"]}, "b": {"hand": ["9C", "4C"]}},
        discard=["5H"],
    )
    # One 6H in hand, two claimed: the availability check is by count.
    with pytest.raises(IllegalMoveError):
        game.play_cards("a", c("6H", "6H"))
    assert game.players[0].hand == c("6H", "3S")
    assert game.discard_pile == c("5H")
    assert game.current_player.player_id == "a"


def test_duplicate_copies_from_two_decks_are_playable_together():
    # 6+ player games shuffle two decks, so identical (rank, suit) cards
    # genuinely coexist — a group of two 6H must be legal when both are held.
    game = make_game(
        {"a": {"hand": ["6H", "6H", "3S"]}, "b": {"hand": ["9C", "4C"]}},
        discard=["5H"],
    )
    game.play_cards("a", c("6H", "6H"))
    assert game.discard_pile == c("5H", "6H", "6H")
    assert game.players[0].hand == c("3S")


def test_two_sevens_constrain_only_the_next_player_once():
    game = make_game(
        {
            "a": {"hand": ["7H", "7S", "3S"]},
            "b": {"hand": ["9C", "4D"]},
            "c": {"hand": ["KH", "5C"]},
        },
        discard=["5H"],
    )
    game.play_cards("a", c("7H", "7S"))
    assert game.seven_pending
    assert game.current_player.player_id == "b"
    with pytest.raises(IllegalMoveError):
        game.play_card("b", card("9C"))
    game.play_card("b", card("4D"))
    # Not doubled, not chained: c plays high freely.
    assert not game.seven_pending
    game.play_card("c", card("KH"))


def test_two_tens_burn_pile_and_group_with_no_bonus_turn():
    game = make_game(
        {
            "a": {"hand": ["10H", "10S", "3S"]},
            "b": {"hand": ["3C", "4C"]},
        },
        discard=["KD", "AH"],
    )
    result = game.play_cards("a", c("10H", "10S"))
    assert result.pile_burned
    assert game.discard_pile == []
    assert game.burned == c("KD", "AH", "10H", "10S")
    # No bonus turn: b is up, facing an empty pile.
    assert game.current_player.player_id == "b"
    game.play_card("b", card("3C"))
    assert game.top_card == card("3C")


def test_two_jacks_flip_direction_exactly_once():
    game = make_game(
        {
            "a": {"hand": ["JH", "JC", "3S"]},
            "b": {"hand": ["9C", "4C"]},
            "c": {"hand": ["QD", "5C"]},
        },
        discard=["4H"],
    )
    result = game.play_cards("a", c("JH", "JC"))
    assert result.direction_reversed
    # One flip for the whole group — the Jacks must not cancel out.
    assert game.direction == -1
    assert game.current_player.player_id == "c"
    assert game.discard_pile == c("4H", "JH", "JC")


def test_equal_rank_group_without_power_still_illegal():
    game = make_game(
        {"a": {"hand": ["6H", "6C", "9S"]}, "b": {"hand": ["9C", "4C"]}},
        discard=["6D"],
    )
    # Equal rank is only playable via a power card — grouping doesn't help.
    with pytest.raises(IllegalMoveError):
        game.play_cards("a", c("6H", "6C"))
    assert game.discard_pile == c("6D")


def test_group_play_rejected_in_blind_phase():
    game = make_game(
        {
            "a": {"blind": ["6H", "6C"]},
            "b": {"hand": ["9C", "4C"]},
        },
        discard=["5H"],
    )
    with pytest.raises(IllegalMoveError, match="blind"):
        game.play_cards("a", c("6H", "6C"))


def test_empty_group_rejected():
    game = make_game(
        {"a": {"hand": ["6H", "3S"]}, "b": {"hand": ["9C", "4C"]}},
        discard=["5H"],
    )
    with pytest.raises(IllegalMoveError):
        game.play_cards("a", [])


def test_single_card_group_matches_play_card_behavior():
    game = make_game(
        {"a": {"hand": ["6H", "3S"]}, "b": {"hand": ["9C", "4C"]}},
        discard=["5H"],
    )
    result = game.play_cards("a", c("6H"))
    assert result.card == card("6H")
    assert result.cards == c("6H")
    assert game.top_card == card("6H")
