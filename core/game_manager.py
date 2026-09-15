"""GameManager — état de la partie et machine à états (§2, §5, §11 SPEC.md).

Aucune dépendance Django : toutes les I/O (tirage de scénario, persistance des
manches, capteur, LLM) sont injectées. Testable unitairement (cf.
``tests/test_game_manager.py``).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from .bike_sensor import BikeSensor
from .energy import EnergyCalculator, RoundOutcome
from .llm_provider import GenerationRequest, GenerationResult, LLMProvider, SimulatedLLMProvider
from .scenarios import ScenarioData, ScenarioRepository
from .state_machine import GameState, InvalidAction, assert_transition

Clock = Callable[[], float]


@dataclass(frozen=True)
class GameConfig:
    """Paramètres de jeu configurables (§8, §12). Valeurs par défaut =
    valeurs de ``config.settings.GAME`` ; voir ``CONFIG_NOTES.md``."""

    bike_check_revolutions: int = 5
    team_selection_seconds: int = 30
    preparation_seconds: int = 10
    cycling_seconds: int = 60
    # "random" (défaut recommandé §12) ou "host" (demande à l'animateur).
    team_selection_on_timeout: str = "random"
    # Perte de signal vélo pendant une manche (§11) : délai sans nouvelle
    # impulsion au-delà duquel on affiche une alerte (sans arrêter le chrono).
    signal_loss_timeout_seconds: float = 8.0


@dataclass
class TeamState:
    id: int
    name: str
    score: int = 0


@dataclass
class PlayerState:
    id: int
    name: str
    team_id: int
    has_played: bool = False


@dataclass(frozen=True)
class RoundRecord:
    """Données d'une manche à persister avant de passer à la suivante (§11)."""

    round_number: int
    team_id: int
    player_id: int
    scenario: ScenarioData
    outcome: RoundOutcome
    duration_seconds: int
    generation: GenerationResult | None = None


class GameManager:
    def __init__(
        self,
        *,
        scenario_repository: ScenarioRepository,
        energy_calculator: EnergyCalculator,
        bike_sensor: BikeSensor,
        llm_provider: LLMProvider | None = None,
        config: GameConfig | None = None,
        clock: Clock = time.monotonic,
        rng: random.Random | None = None,
        round_sink: Callable[[RoundRecord], None] | None = None,
    ) -> None:
        self.scenario_repository = scenario_repository
        self.energy = energy_calculator
        self.sensor = bike_sensor
        self.llm = llm_provider or SimulatedLLMProvider()
        self.config = config or GameConfig()
        self._clock = clock
        self._rng = rng or random.Random()
        self._round_sink = round_sink
        self.reset()

    # ------------------------------------------------------------------ #
    #  Cycle de vie / reset (§11)                                        #
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        """Retour à CONFIGURATION — bouton reset animateur (§11)."""
        try:
            self.sensor.stop()
        except Exception:  # noqa: BLE001 — le reset ne doit jamais planter
            pass
        self.state: GameState = GameState.CONFIGURATION
        self.teams: dict[int, TeamState] = {}
        self.players: dict[int, PlayerState] = {}
        self._team_order: list[int] = []
        self.players_per_team: int = 0
        self.total_rounds: int = 0
        self.current_round_number: int = 0
        self.current_team_id: int | None = None
        self.current_player_id: int | None = None
        self.current_scenario: ScenarioData | None = None
        self.last_round: RoundRecord | None = None
        self.rounds: list[RoundRecord] = []
        self._phase_started_at: float | None = None
        self._chrono_active: bool = False
        self._round_persisted: bool = True
        self._timeout_needs_host: bool = False
        self._last_rev_count: int = 0
        self._last_rev_change_at: float | None = None

    # ------------------------------------------------------------------ #
    #  CONFIGURATION (§6.1)                                              #
    # ------------------------------------------------------------------ #

    def configure(
        self, teams: list[TeamState], players: list[PlayerState]
    ) -> None:
        self._require_state(GameState.CONFIGURATION)
        if len(teams) != 2:
            raise ValueError("Deux équipes exactement sont requises (§4).")
        by_team: dict[int, int] = {t.id: 0 for t in teams}
        for p in players:
            if p.team_id not in by_team:
                raise ValueError(f"Joueur {p.name!r} rattaché à une équipe inconnue.")
            by_team[p.team_id] += 1
        counts = set(by_team.values())
        if counts == {0} or 0 in counts:
            raise ValueError("Chaque équipe doit avoir au moins un joueur (§4).")
        if len(counts) != 1:
            raise ValueError("Les deux équipes doivent avoir le même effectif (§4).")
        self.teams = {t.id: replace(t, score=0) for t in teams}
        self.players = {p.id: replace(p, has_played=False) for p in players}
        self._team_order = [teams[0].id, teams[1].id]
        self.players_per_team = counts.pop()
        self.total_rounds = 2 * self.players_per_team

    # ------------------------------------------------------------------ #
    #  BIKE_CHECK (§6.2)                                                 #
    # ------------------------------------------------------------------ #

    def begin_bike_check(self) -> None:
        self._transition(GameState.BIKE_CHECK)
        self.sensor.reset()
        self.sensor.start()
        self._mark_phase_start()

    def bike_check_revolutions(self) -> int:
        self._require_state(GameState.BIKE_CHECK)
        return self.sensor.get_revolutions()

    def bike_check_passed(self) -> bool:
        return self.bike_check_revolutions() >= self.config.bike_check_revolutions

    def confirm_bike_check(self) -> None:
        self._require_state(GameState.BIKE_CHECK)
        if not self.bike_check_passed():
            raise InvalidAction(
                "Vélo non validé : seuil de tours non atteint (§6.2)."
            )
        self.sensor.stop()
        self._transition(GameState.INTRODUCTION)

    # ------------------------------------------------------------------ #
    #  INTRODUCTION -> SPINNING (§6.3, §6.4)                             #
    # ------------------------------------------------------------------ #

    def start_game(self) -> ScenarioData:
        self._require_state(GameState.INTRODUCTION)
        self.current_round_number = 0
        self._transition(GameState.SPINNING)
        return self._begin_round()

    def _begin_round(self) -> ScenarioData:
        """Prépare une nouvelle manche : incrémente le numéro, désigne
        l'équipe active (alternance stricte §4) et tire un scénario (§6.4)."""
        self.current_round_number += 1
        # Alternance stricte A, B, A, B... (manche 1 -> équipe d'index 0).
        self.current_team_id = self._team_order[(self.current_round_number - 1) % 2]
        self.current_player_id = None
        self._timeout_needs_host = False
        self._round_persisted = False
        self.current_scenario = self.scenario_repository.draw_random(self._rng)
        self._mark_phase_start()
        return self.current_scenario

    def confirm_spin(self) -> None:
        self._require_state(GameState.SPINNING)
        if self.current_scenario is None:
            raise InvalidAction("Aucun scénario tiré (§6.4).")
        self._transition(GameState.TEAM_SELECTION)
        self._mark_phase_start()

    # ------------------------------------------------------------------ #
    #  TEAM_SELECTION (§6.5, §12)                                        #
    # ------------------------------------------------------------------ #

    def eligible_runners(self) -> list[PlayerState]:
        return [
            p
            for p in self.players.values()
            if p.team_id == self.current_team_id and not p.has_played
        ]

    def select_runner(self, player_id: int) -> None:
        self._require_state(GameState.TEAM_SELECTION)
        player = self.players.get(player_id)
        if player is None or player.team_id != self.current_team_id:
            raise InvalidAction("Ce joueur n'appartient pas à l'équipe active (§4).")
        if player.has_played:
            raise InvalidAction("Ce joueur a déjà pédalé (§4).")
        self.current_player_id = player_id
        self._timeout_needs_host = False

    def team_selection_remaining(self) -> float:
        self._require_state(GameState.TEAM_SELECTION)
        return self._phase_remaining(self.config.team_selection_seconds)

    @property
    def selection_needs_host(self) -> bool:
        """True si le délai a expiré et la politique est "host" (§12)."""
        return self._timeout_needs_host

    def confirm_runner(self) -> None:
        self._require_state(GameState.TEAM_SELECTION)
        if self.current_player_id is None:
            raise InvalidAction("Aucun coureur sélectionné (§6.5).")
        self._transition(GameState.PREPARATION)
        self._mark_phase_start()

    # ------------------------------------------------------------------ #
    #  PREPARATION (§6.6)                                                #
    # ------------------------------------------------------------------ #

    def preparation_remaining(self) -> float:
        self._require_state(GameState.PREPARATION)
        return self._phase_remaining(self.config.preparation_seconds)

    def _start_cycling(self) -> None:
        # Verrou : interdiction de deux chronomètres en parallèle (§5, §11).
        if self._chrono_active:
            raise InvalidAction("Un chronomètre est déjà actif (§11).")
        self._transition(GameState.CYCLING)
        self.sensor.reset()
        self.sensor.start()
        self._chrono_active = True
        self._last_rev_count = 0
        self._last_rev_change_at = self._clock()
        self._mark_phase_start()

    # ------------------------------------------------------------------ #
    #  CYCLING (§6.7)                                                    #
    # ------------------------------------------------------------------ #

    def register_pedal(self, count: int = 1) -> int:
        """Enregistre des tours — valide UNIQUEMENT en CYCLING (§5)."""
        if self.state is not GameState.CYCLING:
            raise InvalidAction("Tick de pédalage hors de l'état CYCLING (§5).")
        add = getattr(self.sensor, "add_revolutions", None)
        if add is None:
            raise InvalidAction("Le capteur courant n'accepte pas d'impulsions simulées.")
        return add(count)

    def cycling_remaining(self) -> float:
        self._require_state(GameState.CYCLING)
        return self._phase_remaining(self.config.cycling_seconds)

    def cycling_elapsed(self) -> float:
        self._require_state(GameState.CYCLING)
        return self._phase_elapsed()

    @property
    def signal_lost(self) -> bool:
        """Alerte perte de signal vélo (§11) — n'arrête pas le chrono."""
        if self.state is not GameState.CYCLING or self._last_rev_change_at is None:
            return False
        return (self._clock() - self._last_rev_change_at) >= self.config.signal_loss_timeout_seconds

    def live_progress(self) -> dict:
        """Données d'affichage temps réel pendant CYCLING (§6.7)."""
        self._require_state(GameState.CYCLING)
        assert self.current_scenario is not None
        revolutions = self.sensor.get_revolutions()
        produced_j = self.energy.revolutions_to_joules(revolutions)
        target_j = self.energy.mwh_to_joules(self.current_scenario.energy_mwh)
        percent = self.energy.performance_percent(produced_j, target_j)
        return {
            "revolutions": revolutions,
            "cadence_rpm": round(self.sensor.get_cadence(), 1),
            "human_energy_joules": round(produced_j, 2),
            "target_energy_joules": round(target_j, 2),
            "performance_percent": round(percent, 1),
            "tier_reached": self.energy.tier_reached(percent),
            "seconds_remaining": round(self.cycling_remaining(), 1),
            "signal_lost": self.signal_lost,
        }

    def _finish_cycling(self) -> None:
        """Fin des 60 s : arrêt du comptage, calcul, persistance, score (§6.8)."""
        assert self.current_scenario is not None
        assert self.current_team_id is not None and self.current_player_id is not None
        revolutions = self.sensor.get_revolutions()
        self.sensor.stop()
        self._chrono_active = False

        outcome = self.energy.evaluate_round(revolutions, self.current_scenario.energy_mwh)
        generation = self._safe_generate()
        record = RoundRecord(
            round_number=self.current_round_number,
            team_id=self.current_team_id,
            player_id=self.current_player_id,
            scenario=self.current_scenario,
            outcome=outcome,
            duration_seconds=self.config.cycling_seconds,
            generation=generation,
        )
        # Persistance AVANT toute suite (§11). Si le sink échoue, on reste en
        # CYCLING-terminé : la transition RESULT n'a pas lieu.
        if self._round_sink is not None:
            self._round_sink(record)
        self._round_persisted = True

        self.teams[self.current_team_id].score += outcome.score
        self.players[self.current_player_id].has_played = True
        self.last_round = record
        self.rounds.append(record)
        self._transition(GameState.RESULT)

    def _safe_generate(self) -> GenerationResult | None:
        """Génération LLM optionnelle — ne bloque jamais le jeu (§9, §11)."""
        if self.current_scenario is None:
            return None
        try:
            return self.llm.generate(
                GenerationRequest(
                    provider=self.current_scenario.provider,
                    model_name=self.current_scenario.model_name,
                    output_description=self.current_scenario.output_description,
                    output_tokens=self.current_scenario.output_tokens,
                    prompt_template=self.current_scenario.prompt_template,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(text="", simulated=True, error=str(exc))

    # ------------------------------------------------------------------ #
    #  RESULT -> NEXT_TEAM -> boucle (§6.8, §6.9)                        #
    # ------------------------------------------------------------------ #

    def next_round(self) -> GameState:
        self._require_state(GameState.RESULT)
        if not self._round_persisted:
            raise InvalidAction("La manche doit être persistée avant la suivante (§11).")
        self._transition(GameState.NEXT_TEAM)
        if self.current_round_number < self.total_rounds:
            self._transition(GameState.SPINNING)
            self._begin_round()
        else:
            self._transition(GameState.FINAL_RESULTS)
        return self.state

    # ------------------------------------------------------------------ #
    #  FINAL_RESULTS / PEDAGOGICAL_SUMMARY (§6.10, §6.11)                #
    # ------------------------------------------------------------------ #

    def to_pedagogical_summary(self) -> None:
        self._transition(GameState.PEDAGOGICAL_SUMMARY)

    def final_results(self) -> dict:
        winner = None
        scores = {tid: t.score for tid, t in self.teams.items()}
        if scores:
            best = max(scores.values())
            leaders = [tid for tid, s in scores.items() if s == best]
            winner = leaders[0] if len(leaders) == 1 else None  # None = égalité
        return {
            "team_scores": scores,
            "winner_team_id": winner,
            "is_draw": winner is None and bool(scores),
            "total_revolutions": sum(r.outcome.revolutions for r in self.rounds),
            "total_human_energy_joules": round(
                sum(r.outcome.human_energy_joules for r in self.rounds), 2
            ),
            "total_target_energy_mwh": round(
                sum(r.scenario.energy_mwh for r in self.rounds), 3
            ),
            "scenario_breakdown": self._scenario_breakdown(),
        }

    def _scenario_breakdown(self) -> list[dict]:
        agg: dict[tuple[str, str], dict] = {}
        for r in self.rounds:
            key = (r.scenario.model_name, r.scenario.output_description)
            entry = agg.setdefault(
                key,
                {
                    "model_name": r.scenario.model_name,
                    "output_description": r.scenario.output_description,
                    "count": 0,
                    "total_energy_mwh": 0.0,
                },
            )
            entry["count"] += 1
            entry["total_energy_mwh"] = round(
                entry["total_energy_mwh"] + r.scenario.energy_mwh, 3
            )
        return sorted(agg.values(), key=lambda e: e["count"], reverse=True)

    def pedagogical_summary(self) -> dict:
        """Synthèse reliant résultats et choix modèle/longueur (§6.11, §16).

        Contre-factuel : « et si le modèle le plus léger / la sortie la plus
        courte de la base avaient été utilisés ? ».
        """
        active = self.scenario_repository.list_active()
        lightest = min(active, key=lambda s: s.energy_mwh, default=None)
        shortest = min(active, key=lambda s: s.output_tokens, default=None)
        actual_total = sum(r.scenario.energy_mwh for r in self.rounds)
        n = len(self.rounds)
        return {
            "rounds": [
                {
                    "round_number": r.round_number,
                    "model_name": r.scenario.model_name,
                    "output_description": r.scenario.output_description,
                    "output_tokens": r.scenario.output_tokens,
                    "energy_mwh": r.scenario.energy_mwh,
                    "performance_percent": round(r.outcome.performance_percent, 1),
                    "tier_reached": r.outcome.tier_reached,
                }
                for r in self.rounds
            ],
            "actual_total_energy_mwh": round(actual_total, 3),
            "counterfactual_lightest_model": lightest.model_name if lightest else None,
            "counterfactual_lightest_total_mwh": (
                round(lightest.energy_mwh * n, 3) if lightest else None
            ),
            "counterfactual_shortest_output": shortest.output_description if shortest else None,
            "counterfactual_shortest_total_mwh": (
                round(shortest.energy_mwh * n, 3) if shortest else None
            ),
            "disclaimer": (
                "Estimations pédagogiques issues d'Ecologits — pas une mesure "
                "réelle de datacenter. L'énergie « produite » au vélo est une "
                "calibration pédagogique, pas une mesure métabolique."
            ),
        }

    # ------------------------------------------------------------------ #
    #  Boucle temps : transitions automatiques (§6.5, §6.6, §6.7)        #
    # ------------------------------------------------------------------ #

    def tick(self) -> None:
        """À appeler périodiquement (polling). Déclenche les transitions
        qui dépendent du temps. Idempotent."""
        if self.state is GameState.TEAM_SELECTION:
            if self._phase_remaining(self.config.team_selection_seconds) <= 0:
                self._handle_selection_timeout()
        elif self.state is GameState.PREPARATION:
            if self._phase_remaining(self.config.preparation_seconds) <= 0:
                self._start_cycling()
        elif self.state is GameState.CYCLING:
            self._update_signal_watch()
            if self._phase_remaining(self.config.cycling_seconds) <= 0:
                self._finish_cycling()

    def _handle_selection_timeout(self) -> None:
        if self.current_player_id is not None:
            return
        if self.config.team_selection_on_timeout == "random":
            pool = self.eligible_runners()
            if pool:
                self.current_player_id = self._rng.choice(pool).id
        else:  # "host" — on attend une action animateur (§12)
            self._timeout_needs_host = True

    def _update_signal_watch(self) -> None:
        current = self.sensor.get_revolutions()
        if current != self._last_rev_count:
            self._last_rev_count = current
            self._last_rev_change_at = self._clock()

    # ------------------------------------------------------------------ #
    #  Introspection pour la couche Django                              #
    # ------------------------------------------------------------------ #

    def snapshot(self) -> dict:
        return {
            "state": str(self.state),
            "round_number": self.current_round_number,
            "total_rounds": self.total_rounds,
            "players_per_team": self.players_per_team,
            "current_team_id": self.current_team_id,
            "current_player_id": self.current_player_id,
            "teams": [
                {"id": t.id, "name": t.name, "score": t.score}
                for t in self.teams.values()
            ],
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "team_id": p.team_id,
                    "has_played": p.has_played,
                }
                for p in self.players.values()
            ],
            "scenario": _scenario_dict(self.current_scenario),
            "chrono_active": self._chrono_active,
            "round_persisted": self._round_persisted,
            "selection_needs_host": self._timeout_needs_host,
        }

    # ------------------------------------------------------------------ #
    #  Helpers internes                                                  #
    # ------------------------------------------------------------------ #

    def _transition(self, dst: GameState) -> None:
        assert_transition(self.state, dst)
        self.state = dst

    def _require_state(self, *allowed: GameState) -> None:
        if self.state not in allowed:
            raise InvalidAction(
                f"Action invalide dans l'état {self.state} (attendu : "
                f"{', '.join(str(s) for s in allowed)}) (§5)."
            )

    def _mark_phase_start(self) -> None:
        self._phase_started_at = self._clock()

    def _phase_elapsed(self) -> float:
        if self._phase_started_at is None:
            return 0.0
        return self._clock() - self._phase_started_at

    def _phase_remaining(self, total_seconds: float) -> float:
        return max(0.0, total_seconds - self._phase_elapsed())


def _scenario_dict(s: ScenarioData | None) -> dict | None:
    if s is None:
        return None
    return {
        "id": s.id,
        "provider": s.provider,
        "model_name": s.model_name,
        "model_family": s.model_family,
        "model_size_category": s.model_size_category,
        "output_description": s.output_description,
        "output_tokens": s.output_tokens,
        "energy_mwh": s.energy_mwh,
        "source": s.source,
    }
