"""Tests d'intégration GameManager + machine à états (§8, §14) — sans Django."""

import random

import pytest

from core.bike_sensor import SimulatedBikeSensor
from core.energy import EnergyCalculator
from core.game_manager import GameConfig, GameManager, PlayerState, TeamState
from core.scenarios import InMemoryScenarioRepository, ScenarioData
from core.state_machine import GameState, InvalidAction

from .conftest import configure_two_by_two


# --------------------------------------------------------------------------- #
#  Configuration & règles du jeu (§4)                                          #
# --------------------------------------------------------------------------- #

def test_configure_requires_equal_team_sizes(manager):
    with pytest.raises(ValueError):
        manager.configure(
            teams=[TeamState(1, "A"), TeamState(2, "B")],
            players=[
                PlayerState(10, "A1", 1),
                PlayerState(11, "A2", 1),
                PlayerState(20, "B1", 2),
            ],
        )


def test_configure_requires_exactly_two_teams(manager):
    with pytest.raises(ValueError):
        manager.configure(teams=[TeamState(1, "A")], players=[PlayerState(10, "A1", 1)])


def test_total_rounds_is_twice_players_per_team(manager):
    configure_two_by_two(manager)
    assert manager.players_per_team == 2
    assert manager.total_rounds == 4


# --------------------------------------------------------------------------- #
#  BIKE_CHECK (§6.2)                                                           #
# --------------------------------------------------------------------------- #

def test_bike_check_blocks_continue_until_threshold(manager):
    configure_two_by_two(manager)
    manager.begin_bike_check()
    assert manager.state is GameState.BIKE_CHECK
    manager.sensor.add_revolutions(2)
    assert not manager.bike_check_passed()
    with pytest.raises(InvalidAction):
        manager.confirm_bike_check()
    manager.sensor.add_revolutions(1)
    assert manager.bike_check_passed()
    manager.confirm_bike_check()
    assert manager.state is GameState.INTRODUCTION


# --------------------------------------------------------------------------- #
#  Actions hors contexte rejetées (§5)                                         #
# --------------------------------------------------------------------------- #

def test_pedal_tick_rejected_outside_cycling(manager):
    configure_two_by_two(manager)
    with pytest.raises(InvalidAction):
        manager.register_pedal(1)


def test_cannot_select_runner_outside_team_selection(manager):
    configure_two_by_two(manager)
    with pytest.raises(InvalidAction):
        manager.select_runner(10)


# --------------------------------------------------------------------------- #
#  Déroulé d'une manche complète + timers (§6.5-6.8)                           #
# --------------------------------------------------------------------------- #

def _reach_team_selection(manager):
    configure_two_by_two(manager)
    manager.begin_bike_check()
    manager.sensor.add_revolutions(3)
    manager.confirm_bike_check()
    manager.start_game()
    assert manager.state is GameState.SPINNING
    manager.confirm_spin()
    assert manager.state is GameState.TEAM_SELECTION


def test_team_selection_timeout_auto_picks_random_runner(manager, clock):
    _reach_team_selection(manager)
    assert manager.current_player_id is None
    clock.advance(31)
    manager.tick()
    assert manager.current_player_id in {10, 11}  # équipe A (manche 1)


def test_team_selection_timeout_host_mode_sets_flag():
    mgr = GameManager(
        scenario_repository=InMemoryScenarioRepository(
            [ScenarioData(1, "p", "m", "o", 10, 5.0)]
        ),
        energy_calculator=EnergyCalculator(1.0),
        bike_sensor=SimulatedBikeSensor(),
        config=GameConfig(bike_check_revolutions=1, team_selection_on_timeout="host"),
        clock=(clk := _Clock()),
        rng=random.Random(0),
    )
    mgr.configure(
        teams=[TeamState(1, "A"), TeamState(2, "B")],
        players=[PlayerState(10, "A1", 1), PlayerState(20, "B1", 2)],
    )
    mgr.begin_bike_check()
    mgr.sensor.add_revolutions(1)
    mgr.confirm_bike_check()
    mgr.start_game()
    mgr.confirm_spin()
    clk.advance(31)
    mgr.tick()
    assert mgr.current_player_id is None
    assert mgr.selection_needs_host is True


def test_preparation_then_cycling_then_result_with_timers(manager, clock):
    _reach_team_selection(manager)
    manager.select_runner(10)
    manager.confirm_runner()
    assert manager.state is GameState.PREPARATION

    clock.advance(5)
    manager.tick()
    assert manager.state is GameState.PREPARATION  # 10 s pas encore écoulées
    clock.advance(6)
    manager.tick()
    assert manager.state is GameState.CYCLING

    # 100 % atteint tôt : la manche NE se termine PAS en avance (§6.7).
    manager.register_pedal(1000)
    clock.advance(30)
    manager.tick()
    assert manager.state is GameState.CYCLING
    assert manager.live_progress()["performance_percent"] > 100

    clock.advance(31)  # total 61 s
    manager.tick()
    assert manager.state is GameState.RESULT
    assert manager.last_round is not None
    assert manager.last_round.outcome.tier_reached == 100
    assert len(manager.persisted) == 1  # round_sink appelé (§11)


def test_round_persisted_before_next_round(manager, clock):
    _play_full_round(manager, clock, runner_id=10, revolutions=10)
    assert manager._round_persisted is True
    manager.next_round()
    assert manager.state is GameState.SPINNING


def test_next_round_blocked_if_sink_failed(manager, clock):
    def boom(_record):
        raise RuntimeError("DB indisponible")

    manager._round_sink = boom
    _reach_team_selection(manager)
    manager.select_runner(10)
    manager.confirm_runner()
    clock.advance(11)
    manager.tick()  # -> CYCLING
    manager.register_pedal(5)
    clock.advance(61)
    with pytest.raises(RuntimeError):
        manager.tick()  # _finish_cycling lève, pas de transition
    assert manager.state is GameState.CYCLING
    assert manager._round_persisted is False


# --------------------------------------------------------------------------- #
#  Partie complète (§14)                                                       #
# --------------------------------------------------------------------------- #

def test_full_game_alternation_and_single_play(manager, clock):
    configure_two_by_two(manager)
    manager.begin_bike_check()
    manager.sensor.add_revolutions(3)
    manager.confirm_bike_check()
    manager.start_game()

    teams_seen = []
    players_seen = []
    for _ in range(manager.total_rounds):
        assert manager.state is GameState.SPINNING
        manager.confirm_spin()
        teams_seen.append(manager.current_team_id)
        # sélection auto par timeout
        clock.advance(31)
        manager.tick()
        players_seen.append(manager.current_player_id)
        manager.confirm_runner()
        clock.advance(11)
        manager.tick()  # -> CYCLING
        manager.register_pedal(20)
        clock.advance(61)
        manager.tick()  # -> RESULT
        manager.next_round()

    assert manager.state is GameState.FINAL_RESULTS
    # Alternance stricte A,B,A,B (§4)
    assert teams_seen == [1, 2, 1, 2]
    # Chaque joueur exactement une fois (§4)
    assert sorted(players_seen) == [10, 11, 20, 21]
    assert all(p.has_played for p in manager.players.values())
    assert len(manager.persisted) == 4


def test_cannot_select_same_player_twice(manager, clock):
    _play_full_round(manager, clock, runner_id=10, revolutions=10)
    manager.next_round()  # manche 2 -> équipe B
    manager.confirm_spin()
    with pytest.raises(InvalidAction):
        manager.select_runner(10)  # équipe A, déjà joué + mauvaise équipe


def test_reset_returns_to_configuration(manager, clock):
    _reach_team_selection(manager)
    manager.reset()
    assert manager.state is GameState.CONFIGURATION
    assert manager.teams == {}


def test_final_results_and_pedagogical_summary(manager, clock):
    configure_two_by_two(manager)
    manager.begin_bike_check()
    manager.sensor.add_revolutions(3)
    manager.confirm_bike_check()
    manager.start_game()
    for i in range(manager.total_rounds):
        manager.confirm_spin()
        clock.advance(31)
        manager.tick()
        manager.confirm_runner()
        clock.advance(11)
        manager.tick()
        manager.register_pedal(50 if i == 0 else 5)
        clock.advance(61)
        manager.tick()
        manager.next_round()

    results = manager.final_results()
    assert set(results["team_scores"]) == {1, 2}
    assert results["total_revolutions"] == 50 + 5 + 5 + 5
    assert results["scenario_breakdown"]

    manager.to_pedagogical_summary()
    summary = manager.pedagogical_summary()
    assert len(summary["rounds"]) == 4
    assert summary["counterfactual_lightest_total_mwh"] is not None
    assert "pédagogique" in summary["disclaimer"].lower()


# --------------------------------------------------------------------------- #
#  Scénarios désactivés (§14)                                                  #
# --------------------------------------------------------------------------- #

def test_only_active_scenarios_are_drawn():
    active = [ScenarioData(i, "p", f"m{i}", "o", 10, 5.0) for i in range(1, 6)]
    repo = InMemoryScenarioRepository(active)
    rng = random.Random(0)
    drawn = {repo.draw_random(rng).id for _ in range(200)}
    assert drawn <= {1, 2, 3, 4, 5}


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


def _play_full_round(manager, clock, *, runner_id, revolutions):
    _reach_team_selection(manager)
    manager.select_runner(runner_id)
    manager.confirm_runner()
    clock.advance(11)
    manager.tick()  # -> CYCLING
    manager.register_pedal(revolutions)
    clock.advance(61)
    manager.tick()  # -> RESULT
