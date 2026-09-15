"""Import de scénarios énergétiques depuis un CSV vers ``EnergyScenario`` (§9, §12).

Format CSV attendu (en-tête obligatoire, séparateur virgule, UTF-8) :

    provider,model_name,output_description,output_tokens,energy_mwh[,model_family,model_size_category,source,prompt_template,active]

Colonnes minimales : provider, model_name, output_description, output_tokens,
energy_mwh. Les autres sont optionnelles.

    uv run manage.py import_scenarios data/scenarios.csv
    uv run manage.py import_scenarios data/scenarios.csv --replace

``energy_mwh`` est repris tel quel depuis le fichier (données Ecologits) —
jamais recalculé (§9).
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from game.models import EnergyScenario

REQUIRED = ["provider", "model_name", "output_description", "output_tokens", "energy_mwh"]


class Command(BaseCommand):
    help = "Importe des EnergyScenario depuis un fichier CSV (données Ecologits)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("csv_path", type=str, help="Chemin du fichier CSV.")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Vide la table EnergyScenario avant l'import.",
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            help="Passe active=False pour les scénarios absents du CSV.",
        )

    def handle(self, *args, **options) -> None:
        path = Path(options["csv_path"])
        if not path.exists():
            raise CommandError(f"Fichier introuvable : {path}")

        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
            if missing:
                raise CommandError(
                    f"Colonnes manquantes dans le CSV : {', '.join(missing)}"
                )
            rows = list(reader)

        created = updated = 0
        seen: list[tuple[str, str, str]] = []
        with transaction.atomic():
            if options["replace"]:
                EnergyScenario.objects.all().delete()

            for i, row in enumerate(rows, start=2):  # ligne 1 = en-tête
                try:
                    defaults = {
                        "output_tokens": int(row["output_tokens"]),
                        "energy_mwh": float(row["energy_mwh"]),
                        "model_family": (row.get("model_family") or "").strip() or None,
                        "model_size_category": (row.get("model_size_category") or "").strip()
                        or None,
                        "source": (row.get("source") or "").strip() or "Ecologits",
                        "prompt_template": (row.get("prompt_template") or "").strip() or None,
                        "active": _parse_bool(row.get("active"), default=True),
                    }
                except (TypeError, ValueError) as exc:
                    raise CommandError(f"Ligne {i} invalide : {exc}") from exc

                key = {
                    "provider": row["provider"].strip(),
                    "model_name": row["model_name"].strip(),
                    "output_description": row["output_description"].strip(),
                }
                obj, was_created = EnergyScenario.objects.update_or_create(
                    **key, defaults=defaults
                )
                seen.append((key["provider"], key["model_name"], key["output_description"]))
                created += was_created
                updated += not was_created

            if options["deactivate_missing"]:
                ids = [
                    o.pk
                    for o in EnergyScenario.objects.all()
                    if (o.provider, o.model_name, o.output_description) not in seen
                ]
                EnergyScenario.objects.filter(pk__in=ids).update(active=False)
                self.stdout.write(f"Désactivés (absents du CSV) : {len(ids)}")

        self.stdout.write(
            self.style.SUCCESS(f"Import terminé : {created} créés, {updated} mis à jour.")
        )


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "vrai", "oui", "yes", "y"}
