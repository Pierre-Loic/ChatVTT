"""Fixtures partagées. La logique pure (core) est testée SANS Django (§14)."""

from __future__ import annotations

import random

import pytest

from core.bike_sensor import SimulatedBikeSensor
from core.energy import EnergyCalculator, ScoringConfig
from core.game_manager import GameConfig, GameManager, PlayerState, TeamState
from core.scenarios import InMemoryScenarioRepository, ScenarioData


@pytest.fixture
def scenarios() -> list[ScenarioData]:
    return [
        ScenarioData(1, "Anthropic", "Claude Haiku 4.5", "Écrire un email", 250, 28.1),
        ScenarioData(2, "Anthropic", "Claude Sonnet 4.5", "Article de blog", 900, 168.0),
        ScenarioData(3, "Mistral", "Mistral Small", "Réponse courte", 40, 5.2),
    ]


@pytest.fixture
def calculator() -> EnergyCalculator:
    # 1 tour = 1,0 J pour des calculs simples et prévisibles dans les tests.
    return EnergyCalculator(1.0, scoring=ScoringConfig({0: 0, 25: 25, 50: 50, 75: 75, 100: 150}))


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def manager(scenarios, calculator, clock):
    persisted: list = []
    mgr = GameManager(
        scenario_repository=InMemoryScenarioRepository(scenarios),
        energy_calculator=calculator,
        bike_sensor=SimulatedBikeSensor(),
        config=GameConfig(bike_check_revolutions=3),
        clock=clock,
        rng=random.Random(1234),
        round_sink=persisted.append,
    )
    mgr.persisted = persisted  # type: ignore[attr-defined]
    return mgr


def configure_two_by_two(manager) -> None:
    manager.configure(
        teams=[TeamState(id=1, name="A"), TeamState(id=2, name="B")],
        players=[
            PlayerState(id=10, name="A1", team_id=1),
            PlayerState(id=11, name="A2", team_id=1),
            PlayerState(id=20, name="B1", team_id=2),
            PlayerState(id=21, name="B2", team_id=2),
        ],
    )
