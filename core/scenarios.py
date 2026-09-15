"""Scénarios énergétiques : structure de données + accès (§2, §9 SPEC.md).

``ScenarioData`` est un objet transport découplé de l'ORM. ``ScenarioRepository``
est le contrat d'accès : l'implémentation Django vit dans
``game.repository.DjangoScenarioRepository`` ; les tests utilisent
``InMemoryScenarioRepository``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ScenarioData:
    """Un scénario tiré : modèle + sortie + énergie cible (Ecologits).

    ``energy_mwh`` est TOUJOURS lue depuis les données préparées, jamais
    recalculée par une formule théorique (§9).
    """

    id: int
    provider: str
    model_name: str
    output_description: str  # affiché aux joueurs (§9)
    output_tokens: int
    energy_mwh: float
    source: str = "Ecologits"
    model_family: str | None = None
    model_size_category: str | None = None
    prompt_template: str | None = None  # envoyé au LLM réel uniquement (§9)


class ScenarioRepository(Protocol):
    def list_active(self) -> list[ScenarioData]: ...

    def draw_random(self, rng: random.Random | None = None) -> ScenarioData: ...


class InMemoryScenarioRepository:
    """Repository de test — ne tire que des scénarios ``active=True`` (§14)."""

    def __init__(self, scenarios: list[ScenarioData]) -> None:
        self._scenarios = list(scenarios)

    def list_active(self) -> list[ScenarioData]:
        return list(self._scenarios)

    def draw_random(self, rng: random.Random | None = None) -> ScenarioData:
        pool = self.list_active()
        if not pool:
            raise LookupError("Aucun scénario actif disponible pour le tirage.")
        return (rng or random).choice(pool)
