"""Vues Django : écran animateur + API de polling temps réel (§2, §6).

L'API valide chaque action contre l'état courant via le ``GameManager`` :
toute action hors contexte est rejetée en 409 (§5).
"""

from __future__ import annotations

import json

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core.state_machine import GameState, InvalidAction, InvalidTransition

from .models import EnergyScenario
from .services import get_service

# Actions animateur autorisées et méthode correspondante du manager (§5).
_ACTIONS = {
    "begin_bike_check": "begin_bike_check",
    "confirm_bike_check": "confirm_bike_check",
    "start_game": "start_game",
    "confirm_spin": "confirm_spin",
    "confirm_runner": "confirm_runner",
    "next_round": "next_round",
    "to_summary": "to_pedagogical_summary",
    "reset": "reset",
}


@require_GET
def board(request: HttpRequest) -> HttpResponse:
    """Écran de pilotage de l'animateur."""
    return render(
        request,
        "game/board.html",
        {
            "game_cfg": settings.GAME,
            "scenarios": EnergyScenario.objects.filter(active=True),
        },
    )


@require_GET
def display(request: HttpRequest) -> HttpResponse:
    """Écran public (vidéoprojecteur) — même polling, affichage plein écran."""
    return render(request, "game/display.html", {})


@require_GET
def api_state(request: HttpRequest) -> JsonResponse:
    service = get_service()
    m = service.manager
    # Déclenche les transitions temporelles (fin de sélection / prépa / chrono).
    m.tick()
    service.sync()

    data = m.snapshot()
    data["config"] = {
        "team_selection_seconds": m.config.team_selection_seconds,
        "preparation_seconds": m.config.preparation_seconds,
        "cycling_seconds": m.config.cycling_seconds,
        "bike_check_revolutions": m.config.bike_check_revolutions,
        "energy_per_revolution_joules": m.energy.energy_per_revolution_joules,
        "bike_sensor": settings.GAME["BIKE_SENSOR"],
    }
    data["disclaimer"] = (
        "Estimations pédagogiques (source Ecologits) — pas une mesure réelle "
        "de datacenter. L'énergie produite au vélo est une calibration "
        "pédagogique, pas une mesure métabolique."
    )

    state = m.state
    if state == GameState.BIKE_CHECK:
        data["bike_check"] = {
            "revolutions": m.bike_check_revolutions(),
            "threshold": m.config.bike_check_revolutions,
            "passed": m.bike_check_passed(),
            "cadence_rpm": round(m.sensor.get_cadence(), 1),
        }
    elif state == GameState.INTRODUCTION:
        data["introduction"] = _introduction_payload()
    elif state == GameState.TEAM_SELECTION:
        data["team_selection"] = {
            "seconds_remaining": round(m.team_selection_remaining(), 1),
            "eligible": [
                {"id": p.id, "name": p.name} for p in m.eligible_runners()
            ],
            "selected_player_id": m.current_player_id,
            "needs_host": m.selection_needs_host,
        }
    elif state == GameState.PREPARATION:
        data["preparation"] = {
            "seconds_remaining": round(m.preparation_remaining(), 1),
        }
    elif state == GameState.CYCLING:
        data["cycling"] = m.live_progress()
    elif state == GameState.RESULT:
        data["result"] = _round_payload(m.last_round)
    elif state == GameState.FINAL_RESULTS:
        data["final_results"] = m.final_results()
        data["rounds"] = [_round_payload(r) for r in m.rounds]
    elif state == GameState.PEDAGOGICAL_SUMMARY:
        data["pedagogical_summary"] = m.pedagogical_summary()
        data["final_results"] = m.final_results()

    return JsonResponse(data)


@require_POST
def api_configure(request: HttpRequest) -> JsonResponse:
    payload = _json_body(request)
    try:
        players_per_team = int(payload["players_per_team"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "players_per_team invalide."}, status=400)

    team_a_name = (payload.get("team_a_name") or "Équipe A").strip()
    team_b_name = (payload.get("team_b_name") or "Équipe B").strip()
    names_a = _clean_names(payload.get("players_a"), players_per_team, "A")
    names_b = _clean_names(payload.get("players_b"), players_per_team, "B")

    if players_per_team < 1:
        return JsonResponse({"error": "Au moins un joueur par équipe (§4)."}, status=400)
    if len(names_a) != players_per_team or len(names_b) != players_per_team:
        return JsonResponse(
            {"error": "Effectifs égaux requis dans les deux équipes (§4)."},
            status=400,
        )

    service = get_service()
    try:
        service.configure(players_per_team, team_a_name, team_b_name, names_a, names_b)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(service.manager.snapshot())


@require_POST
def api_action(request: HttpRequest, name: str) -> JsonResponse:
    if name not in _ACTIONS:
        return JsonResponse({"error": f"Action inconnue : {name}."}, status=404)
    service = get_service()
    m = service.manager
    method = getattr(m, _ACTIONS[name])
    try:
        method()
    except (InvalidAction, InvalidTransition, LookupError) as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    service.sync()
    return JsonResponse(m.snapshot())


@require_POST
def api_select_runner(request: HttpRequest) -> JsonResponse:
    """Sélection du coureur par l'équipe active (§6.5)."""
    payload = _json_body(request)
    try:
        player_id = int(payload["player_id"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "player_id invalide."}, status=400)
    service = get_service()
    try:
        service.manager.select_runner(player_id)
    except (InvalidAction, InvalidTransition) as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    service.sync()
    return JsonResponse(service.manager.snapshot())


@require_POST
def api_pedal(request: HttpRequest) -> JsonResponse:
    """Impulsions du capteur simulé (+1 / +10 / +100) — CYCLING et BIKE_CHECK."""
    payload = _json_body(request)
    try:
        count = int(payload.get("count", 1))
    except (TypeError, ValueError):
        return JsonResponse({"error": "count invalide."}, status=400)

    service = get_service()
    m = service.manager
    add = getattr(m.sensor, "add_revolutions", None)
    if add is None:
        return JsonResponse(
            {"error": "Capteur non simulé : impulsions manuelles indisponibles."},
            status=409,
        )
    if m.state not in (GameState.CYCLING, GameState.BIKE_CHECK):
        return JsonResponse(
            {"error": "Impulsions valides seulement en BIKE_CHECK ou CYCLING (§5)."},
            status=409,
        )
    return JsonResponse({"revolutions": add(count)})


def _introduction_payload() -> dict:
    scenarios = EnergyScenario.objects.filter(active=True)
    return {
        "models": sorted({s.model_name for s in scenarios}),
        "outputs": sorted({s.output_description for s in scenarios}),
        "token_range": [
            min((s.output_tokens for s in scenarios), default=0),
            max((s.output_tokens for s in scenarios), default=0),
        ],
        "note": (
            "Deux facteurs déterminent l'énergie d'une génération : le modèle "
            "choisi et la quantité de sortie produite (tokens). Les valeurs "
            "affichées sont des ESTIMATIONS pédagogiques issues d'Ecologits."
        ),
    }


def _round_payload(record) -> dict | None:
    if record is None:
        return None
    o = record.outcome
    g = record.generation
    return {
        "round_number": record.round_number,
        "team_id": record.team_id,
        "player_id": record.player_id,
        "scenario": {
            "provider": record.scenario.provider,
            "model_name": record.scenario.model_name,
            "output_description": record.scenario.output_description,
            "output_tokens": record.scenario.output_tokens,
            "energy_mwh": record.scenario.energy_mwh,
            "source": record.scenario.source,
        },
        "revolutions": o.revolutions,
        "human_energy_joules": round(o.human_energy_joules, 2),
        "target_energy_joules": round(o.target_energy_joules, 2),
        "target_energy_mwh": o.target_energy_mwh,
        "performance_percent": round(o.performance_percent, 1),
        "tier_reached": o.tier_reached,
        "score": o.score,
        "generation": None
        if g is None
        else {"text": g.text, "simulated": g.simulated, "error": g.error},
    }


def _json_body(request: HttpRequest) -> dict:
    if not request.body:
        return {}
    try:
        return json.loads(request.body)
    except json.JSONDecodeError:
        return {}


def _clean_names(raw, expected: int, suffix: str) -> list[str]:
    names: list[str] = []
    if isinstance(raw, list):
        names = [str(n).strip() for n in raw if str(n).strip()]
    # Complète avec des noms génériques si l'animateur en a saisi trop peu.
    while len(names) < expected:
        names.append(f"Joueur {suffix}{len(names) + 1}")
    return names[:expected]
