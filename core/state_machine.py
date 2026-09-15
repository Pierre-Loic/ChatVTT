"""Machine à états de la partie (§5 SPEC.md).

Source de vérité unique des états et transitions. ``game.models`` construit
ses ``choices`` Django à partir de ``GameState`` — ne pas dupliquer la liste.
"""

from __future__ import annotations

from enum import StrEnum


class GameState(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    BIKE_CHECK = "BIKE_CHECK"
    INTRODUCTION = "INTRODUCTION"
    SPINNING = "SPINNING"
    TEAM_SELECTION = "TEAM_SELECTION"
    PREPARATION = "PREPARATION"
    CYCLING = "CYCLING"
    RESULT = "RESULT"
    NEXT_TEAM = "NEXT_TEAM"
    FINAL_RESULTS = "FINAL_RESULTS"
    PEDAGOGICAL_SUMMARY = "PEDAGOGICAL_SUMMARY"


# Transitions autorisées (§5). Le reset animateur (-> CONFIGURATION) est
# permis depuis n'importe quel état et géré à part (§11).
TRANSITIONS: dict[GameState, tuple[GameState, ...]] = {
    GameState.CONFIGURATION: (GameState.BIKE_CHECK,),
    GameState.BIKE_CHECK: (GameState.INTRODUCTION,),
    GameState.INTRODUCTION: (GameState.SPINNING,),
    GameState.SPINNING: (GameState.TEAM_SELECTION,),
    GameState.TEAM_SELECTION: (GameState.PREPARATION,),
    GameState.PREPARATION: (GameState.CYCLING,),
    GameState.CYCLING: (GameState.RESULT,),
    GameState.RESULT: (GameState.NEXT_TEAM,),
    GameState.NEXT_TEAM: (GameState.SPINNING, GameState.FINAL_RESULTS),
    GameState.FINAL_RESULTS: (GameState.PEDAGOGICAL_SUMMARY,),
    GameState.PEDAGOGICAL_SUMMARY: (),
}


class InvalidTransition(RuntimeError):
    """Transition d'état non autorisée (§5)."""


class InvalidAction(RuntimeError):
    """Action appelée dans un état où elle n'a pas de sens (§5).

    Ex. : un tick de pédalage hors de l'état ``CYCLING``.
    """


def can_transition(src: GameState, dst: GameState) -> bool:
    return dst in TRANSITIONS.get(src, ())


def assert_transition(src: GameState, dst: GameState) -> None:
    if not can_transition(src, dst):
        raise InvalidTransition(f"{src} -> {dst} interdit (§5)")
