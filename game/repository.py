"""ScenarioRepository — implémentation Django (§2).

Tire uniquement parmi les ``EnergyScenario`` ``active=True`` (§6.4, §14).
"""

from __future__ import annotations

import random

from core.scenarios import ScenarioData

from .models import EnergyScenario


def _to_data(obj: EnergyScenario) -> ScenarioData:
    return ScenarioData(
        id=obj.pk,
        provider=obj.provider,
        model_name=obj.model_name,
        output_description=obj.output_description,
        output_tokens=obj.output_tokens,
        energy_mwh=obj.energy_mwh,
        source=obj.source,
        model_family=obj.model_family,
        model_size_category=obj.model_size_category,
        prompt_template=obj.prompt_template,
    )


class DjangoScenarioRepository:
    def list_active(self) -> list[ScenarioData]:
        return [_to_data(o) for o in EnergyScenario.objects.filter(active=True)]

    def draw_random(self, rng: random.Random | None = None) -> ScenarioData:
        pool = self.list_active()
        if not pool:
            raise LookupError(
                "Aucun EnergyScenario actif : importez des scénarios "
                "(`manage.py import_scenarios` ou `loaddata scenarios`)."
            )
        return (rng or random).choice(pool)
