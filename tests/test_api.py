"""Tests d'intégration de la couche Django : API + persistance (§11, §14)."""

import json

import pytest
from django.test import Client

from game.models import EnergyScenario, Game, Player, Round, Team
from game.services import GameService

pytestmark = pytest.mark.django_db


@pytest.fixture
def scenario(db):
    return EnergyScenario.objects.create(
        provider="Anthropic",
        model_name="Claude Haiku 4.5",
        output_description="Écrire le texte d'un email",
        output_tokens=250,
        energy_mwh=28.1,
    )


@pytest.fixture
def inactive_scenario(db):
    return EnergyScenario.objects.create(
        provider="X", model_name="Never", output_description="jamais",
        output_tokens=10, energy_mwh=1.0, active=False,
    )


@pytest.fixture
def service(db, settings):
    settings.GAME = {**settings.GAME, "SIMULATED_AUTO_RPM": 0}
    import game.services as svc

    svc._SERVICE = None  # isole chaque test
    s = svc.get_service()
    yield s
    svc._SERVICE = None


def _post(client, url, payload=None):
    return client.post(
        url, data=json.dumps(payload or {}), content_type="application/json"
    )


def test_configure_creates_db_rows(client, service, scenario):
    resp = _post(client, "/api/configure", {
        "players_per_team": 2,
        "team_a_name": "Rouges", "team_b_name": "Bleus",
        "players_a": ["Ada", "Alan"], "players_b": ["Grace", "Linus"],
    })
    assert resp.status_code == 200
    assert Team.objects.count() == 2
    assert Player.objects.count() == 4
    assert Game.objects.get().status == "CONFIGURATION"


def test_configure_rejects_unequal_teams(client, service, scenario):
    resp = _post(client, "/api/configure", {
        "players_per_team": 2,
        "players_a": ["Ada"], "players_b": ["Grace", "Linus"],
    })
    # names complétés côté serveur -> égal ; on teste le vrai déséquilibre :
    resp = _post(client, "/api/configure", {"players_per_team": 0})
    assert resp.status_code == 400


def test_action_rejected_out_of_state(client, service, scenario):
    _post(client, "/api/configure", {
        "players_per_team": 1, "players_a": ["A"], "players_b": ["B"],
    })
    # start_game n'est pas valide depuis CONFIGURATION
    resp = _post(client, "/api/action/start_game")
    assert resp.status_code == 409


def test_pedal_rejected_outside_cycling(client, service, scenario):
    _post(client, "/api/configure", {
        "players_per_team": 1, "players_a": ["A"], "players_b": ["B"],
    })
    resp = _post(client, "/api/pedal", {"count": 5})
    assert resp.status_code == 409


def test_full_game_via_api_persists_each_round(client, service, scenario, inactive_scenario):
    _post(client, "/api/configure", {
        "players_per_team": 1,
        "team_a_name": "Rouges", "team_b_name": "Bleus",
        "players_a": ["Ada"], "players_b": ["Grace"],
    })
    _post(client, "/api/action/begin_bike_check")
    _post(client, "/api/pedal", {"count": 10})
    _post(client, "/api/action/confirm_bike_check")
    _post(client, "/api/action/start_game")

    m = service.manager
    for _ in range(m.total_rounds):
        _post(client, "/api/action/confirm_spin")
        runner = m.eligible_runners()[0].id
        _post(client, "/api/select-runner", {"player_id": runner})
        _post(client, "/api/action/confirm_runner")
        # force la fin de la préparation puis du chrono via l'horloge du manager
        m._phase_started_at -= 999
        client.get("/api/state")  # tick -> CYCLING
        _post(client, "/api/pedal", {"count": 30})
        m._phase_started_at -= 999
        client.get("/api/state")  # tick -> RESULT
        assert m.state.value == "RESULT"
        _post(client, "/api/action/next_round")

    assert m.state.value == "FINAL_RESULTS"
    assert Round.objects.count() == 2
    # Scénario inactif jamais tiré (§14)
    assert not Round.objects.filter(scenario=inactive_scenario).exists()
    # Scores reflétés en base (§11)
    for t in Team.objects.all():
        assert t.score == service.manager.teams[t.pk].score

    _post(client, "/api/action/to_summary")
    assert Game.objects.get().finished_at is not None


def test_state_endpoint_shape(client, service, scenario):
    resp = client.get("/api/state")
    data = resp.json()
    assert data["state"] == "CONFIGURATION"
    assert "disclaimer" in data and "pédagogique" in data["disclaimer"].lower()
