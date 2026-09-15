# Vélo & IA Générative

Application pédagogique ludique. Deux équipes s'affrontent : chaque participant
pédale une fois pour tenter de produire, avec ses jambes, l'énergie **estimée**
d'une génération d'IA (modèle + sortie tirés au sort). Objectif : rendre
perceptible le coût énergétique de l'IA générative, à partir de données
Ecologits — **estimations pédagogiques, pas une mesure réelle de datacenter**.

Spécification de référence : [`SPEC.md`](SPEC.md). Décisions sur les points
ouverts : [`CONFIG_NOTES.md`](CONFIG_NOTES.md).

## Démarrage rapide

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py loaddata scenarios      # 1 scénario du CDC + 4 de démo
uv run python manage.py createsuperuser         # optionnel, pour /admin
uv run python manage.py runserver
```

- Écran **animateur** (pilotage) : http://localhost:8000/
- Écran **public** (vidéoprojecteur, affichage seul) : http://localhost:8000/display/
- **Admin** (scénarios, parties) : http://localhost:8000/admin/

Aucun Raspberry Pi ni LLM réel n'est nécessaire : le vélo et le LLM sont
simulés par défaut (§7, §9, §10 de la spec). En mode simulé, les boutons
`+1 / +10 / +100` de l'écran animateur remplacent le pédalage.

## Tests

```bash
uv run pytest
```

La logique métier pure (`core/`) est testée **sans Django ni matériel**
(machine à états, calculs énergétiques, capteur simulé, déroulé complet d'une
partie). `tests/test_api.py` couvre la couche Django (API, persistance).

## Architecture (§2 de la spec)

```
core/                 logique métier, AUCUN import Django, testable en isolation
  state_machine.py    GameState + transitions autorisées (§5)
  game_manager.py     GameManager : état de partie, machine à états, verrous
  energy.py           EnergyCalculator : mWh<->J, %, paliers, barème
  bike_sensor.py      BikeSensor (Protocol) + SimulatedBikeSensor
  llm_provider.py     LLMProvider : SimulatedLLMProvider (défaut) + Anthropic
  scenarios.py        ScenarioData + ScenarioRepository (Protocol)

game/                 application Django
  models.py           Team, Player, EnergyScenario, Game, Round (§3)
  repository.py       DjangoScenarioRepository (tire parmi active=True)
  gpio_bike_sensor.py implémentation GPIO réelle (prototype, §13 priorité 8)
  services.py         câble le GameManager à Django + persiste chaque Round
  views.py / urls.py  écran animateur + API de polling temps réel
  management/commands/import_scenarios.py   import CSV -> EnergyScenario

config/               projet Django (settings.GAME = tous les réglages de jeu)
```

Règle de conception : `GameManager`, `EnergyCalculator` et `BikeSensor` ne
dépendent pas de Django et sont testables unitairement.

## Déroulé d'une partie (§5, §6)

`CONFIGURATION → BIKE_CHECK → INTRODUCTION → SPINNING → TEAM_SELECTION →
PREPARATION → CYCLING → RESULT → NEXT_TEAM → (boucle) → FINAL_RESULTS →
PEDAGOGICAL_SUMMARY`

Chaque action de l'API est validée contre l'état courant : toute action hors
contexte est rejetée (HTTP 409). Chaque `Round` est écrit en base **avant** de
passer à la manche suivante (§11).

## Importer de vraies données Ecologits

```bash
uv run python manage.py import_scenarios data/scenarios.sample.csv --replace
```

Format CSV documenté dans `CONFIG_NOTES.md` et en tête de la commande.
`energy_mwh` est repris tel quel du fichier, jamais recalculé (§9).

## Matériel réel (Raspberry Pi)

```bash
uv sync --extra rpi
GAME_BIKE_SENSOR=gpio GAME_GPIO_PIN=17 uv run python manage.py runserver 0.0.0.0:8000
```

## LLM réel (optionnel)

```bash
uv sync --extra llm
GAME_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-... uv run python manage.py runserver
```

Toute erreur du provider est capturée : le jeu ne dépend jamais du LLM réel.

## Principes pédagogiques (§16, non négociables)

- L'énergie **estimée de l'IA** (Ecologits, mWh) et l'énergie **produite par le
  cycliste** (calibration pédagogique, tours × constante) sont toujours
  distinguées explicitement dans l'UI.
- Les valeurs Ecologits ne sont jamais présentées comme une mesure exacte d'un
  datacenter ; la `source` est conservée sur chaque scénario.
- Les deux facteurs de l'énergie — modèle et quantité de sortie — sont toujours
  visibles.
- Le débriefing final compare le résultat à un scénario « modèle plus léger /
  sortie plus courte ».
