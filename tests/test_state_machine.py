"""Tests des transitions de la machine à états (§5, §14)."""

import pytest

from core.state_machine import (
    TRANSITIONS,
    GameState,
    InvalidTransition,
    assert_transition,
    can_transition,
)

LEGAL_PATH = [
    (GameState.CONFIGURATION, GameState.BIKE_CHECK),
    (GameState.BIKE_CHECK, GameState.INTRODUCTION),
    (GameState.INTRODUCTION, GameState.SPINNING),
    (GameState.SPINNING, GameState.TEAM_SELECTION),
    (GameState.TEAM_SELECTION, GameState.PREPARATION),
    (GameState.PREPARATION, GameState.CYCLING),
    (GameState.CYCLING, GameState.RESULT),
    (GameState.RESULT, GameState.NEXT_TEAM),
    (GameState.NEXT_TEAM, GameState.SPINNING),
    (GameState.NEXT_TEAM, GameState.FINAL_RESULTS),
    (GameState.FINAL_RESULTS, GameState.PEDAGOGICAL_SUMMARY),
]


@pytest.mark.parametrize("src,dst", LEGAL_PATH)
def test_legal_transitions(src, dst):
    assert can_transition(src, dst)
    assert_transition(src, dst)  # ne lève pas


def test_all_states_have_an_entry():
    assert set(TRANSITIONS) == set(GameState)


def test_illegal_transitions_raise():
    with pytest.raises(InvalidTransition):
        assert_transition(GameState.CONFIGURATION, GameState.CYCLING)
    with pytest.raises(InvalidTransition):
        assert_transition(GameState.CYCLING, GameState.CYCLING)
    with pytest.raises(InvalidTransition):
        assert_transition(GameState.PEDAGOGICAL_SUMMARY, GameState.CONFIGURATION)


def test_no_skip_from_spinning_to_cycling():
    assert not can_transition(GameState.SPINNING, GameState.CYCLING)
