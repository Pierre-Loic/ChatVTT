"""Couche de service : câble le ``GameManager`` (core) à Django.

- fabrique les dépendances (capteur, LLM, calculateur) selon ``settings.GAME`` ;
- maintient un ``GameManager`` unique en mémoire du process (un seul vélo,
  un seul animateur — §4) ;
- persiste chaque ``Round`` en base AVANT la manche suivante (§11), via le
  ``round_sink`` injecté dans le manager ;
- reflète l'état du jeu dans les modèles ``Game`` / ``Team`` / ``Player``
  pour survivre à un redémarrage (§11).
"""

from __future__ import annotations

import threading

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.bike_sensor import SimulatedBikeSensor
from core.energy import EnergyCalculator, ScoringConfig
from core.game_manager import GameConfig, GameManager, PlayerState, RoundRecord, TeamState
from core.llm_provider import AnthropicLLMProvider, SimulatedLLMProvider
from core.state_machine import GameState

from .models import EnergyScenario, Game, Player, Round, Team
from .repository import DjangoScenarioRepository

_LOCK = threading.RLock()
_SERVICE: "GameService | None" = None


def _build_energy_calculator() -> EnergyCalculator:
    cfg = settings.GAME
    scoring = ScoringConfig(points_per_tier=dict(cfg["POINTS_PER_TIER"]))
    return EnergyCalculator(cfg["ENERGY_PER_REVOLUTION_JOULES"], scoring=scoring)


def _build_bike_sensor():
    cfg = settings.GAME
    if cfg["BIKE_SENSOR"] == "gpio":
        # Import paresseux : RPi.GPIO n'existe pas hors Raspberry Pi (§7).
        from .gpio_bike_sensor import GpioBikeSensor

        return GpioBikeSensor(pin=cfg["GPIO_PIN"], debounce_ms=cfg["GPIO_DEBOUNCE_MS"])
    return SimulatedBikeSensor(auto_rpm=cfg["SIMULATED_AUTO_RPM"])


def _build_llm_provider():
    cfg = settings.GAME
    if cfg["LLM_PROVIDER"] == "anthropic":
        return AnthropicLLMProvider(model=cfg["LLM_MODEL"])
    return SimulatedLLMProvider()


def _build_game_config() -> GameConfig:
    cfg = settings.GAME
    return GameConfig(
        bike_check_revolutions=cfg["BIKE_CHECK_REVOLUTIONS"],
        team_selection_seconds=cfg["TEAM_SELECTION_SECONDS"],
        preparation_seconds=cfg["PREPARATION_SECONDS"],
        cycling_seconds=cfg["CYCLING_SECONDS"],
        team_selection_on_timeout=cfg["TEAM_SELECTION_ON_TIMEOUT"],
        signal_loss_timeout_seconds=cfg["SIGNAL_LOSS_TIMEOUT_SECONDS"],
    )


class GameService:
    """Enveloppe process-wide autour d'un ``GameManager``."""

    def __init__(self) -> None:
        self.manager = GameManager(
            scenario_repository=DjangoScenarioRepository(),
            energy_calculator=_build_energy_calculator(),
            bike_sensor=_build_bike_sensor(),
            llm_provider=_build_llm_provider(),
            config=_build_game_config(),
            round_sink=self._persist_round,
        )
        self.game_id: int | None = None
        self._last_sync_key: tuple | None = None

    # -- Persistance --------------------------------------------------------

    def _persist_round(self, record: RoundRecord) -> None:
        """round_sink : appelé dans ``_finish_cycling`` AVANT la transition
        RESULT. Toute exception ici bloque la progression (§11)."""
        with transaction.atomic():
            game = Game.objects.select_for_update().get(pk=self.game_id)
            scenario = EnergyScenario.objects.get(pk=record.scenario.id)
            o = record.outcome
            Round.objects.create(
                game=game,
                team_id=record.team_id,
                player_id=record.player_id,
                scenario=scenario,
                revolutions=o.revolutions,
                human_energy_joules=o.human_energy_joules,
                target_energy_mwh=o.target_energy_mwh,
                performance_percent=o.performance_percent,
                tier_reached=o.tier_reached,
                score=o.score,
                duration_seconds=record.duration_seconds,
                generation_text=(record.generation.text if record.generation else ""),
                generation_simulated=(
                    record.generation.simulated if record.generation else True
                ),
                generation_error=(
                    (record.generation.error or "")[:255] if record.generation else ""
                ),
            )
            Team.objects.filter(pk=record.team_id).update(
                score=self.manager.teams[record.team_id].score + o.score
            )
            Player.objects.filter(pk=record.player_id).update(has_played=True)

    def sync(self) -> None:
        """Reflète l'état mémoire du manager dans le modèle ``Game`` (§11)."""
        if self.game_id is None:
            return
        m = self.manager
        key = (
            str(m.state),
            m.current_round_number,
            m.current_team_id,
            m.current_player_id,
            tuple(sorted((t.id, t.score) for t in m.teams.values())),
        )
        if key == self._last_sync_key:
            return
        self._last_sync_key = key
        fields = {
            "status": str(m.state),
            "current_round_number": m.current_round_number,
            "current_team_id": m.current_team_id,
            "current_player_id": m.current_player_id,
            "players_per_team": m.players_per_team,
            "total_rounds": m.total_rounds,
        }
        if m.state in (GameState.FINAL_RESULTS, GameState.PEDAGOGICAL_SUMMARY):
            if not Game.objects.get(pk=self.game_id).finished_at:
                fields["finished_at"] = timezone.now()
        Game.objects.filter(pk=self.game_id).update(**fields)
        for t in m.teams.values():
            Team.objects.filter(pk=t.id).update(score=t.score)

    # -- Configuration d'une nouvelle partie ------------------------------

    def configure(self, players_per_team: int, team_a_name: str,
                  team_b_name: str, names_a: list[str], names_b: list[str]) -> None:
        with transaction.atomic():
            # Une seule partie active : on repart d'une base propre (§4, §11).
            Round.objects.all().delete()
            Player.objects.all().delete()
            Team.objects.all().delete()
            Game.objects.all().delete()

            team_a = Team.objects.create(name=team_a_name)
            team_b = Team.objects.create(name=team_b_name)
            players: list[PlayerState] = []
            for name in names_a:
                p = Player.objects.create(name=name, team=team_a)
                players.append(PlayerState(id=p.pk, name=p.name, team_id=team_a.pk))
            for name in names_b:
                p = Player.objects.create(name=name, team=team_b)
                players.append(PlayerState(id=p.pk, name=p.name, team_id=team_b.pk))
            game = Game.objects.create(status=GameState.CONFIGURATION)
            self.game_id = game.pk

        self._last_sync_key = None
        self.manager.reset()
        self.manager.configure(
            teams=[
                TeamState(id=team_a.pk, name=team_a.name),
                TeamState(id=team_b.pk, name=team_b.name),
            ],
            players=players,
        )
        self.sync()

    def reset(self) -> None:
        """Bouton reset animateur (§11) — retour à CONFIGURATION."""
        self._last_sync_key = None
        self.manager.reset()
        self.sync()


def get_service() -> GameService:
    global _SERVICE
    with _LOCK:
        if _SERVICE is None:
            _SERVICE = GameService()
            _restore_from_db(_SERVICE)
        return _SERVICE


def _restore_from_db(service: GameService) -> None:
    """Reprise après redémarrage : on récupère au moins l'id de partie et les
    scores (§11). L'état transitoire (chrono en cours) n'est pas restauré —
    une manche interrompue par un crash est à rejouer via le reset animateur."""
    game = Game.objects.order_by("-created_at").first()
    if game is None:
        return
    service.game_id = game.pk
    teams = list(Team.objects.all())
    players = list(Player.objects.all())
    if len(teams) != 2 or not players:
        return
    try:
        service.manager.configure(
            teams=[TeamState(id=t.pk, name=t.name) for t in teams],
            players=[
                PlayerState(id=p.pk, name=p.name, team_id=p.team_id) for p in players
            ],
        )
    except ValueError:
        return
    # Ré-applique les scores et le "déjà joué" persistés (configure les remet à 0).
    for t in teams:
        service.manager.teams[t.pk].score = t.score
    for p in players:
        service.manager.players[p.pk].has_played = p.has_played
