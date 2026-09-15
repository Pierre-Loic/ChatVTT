# CONFIG_NOTES.md — décisions et valeurs provisoires

Ce fichier répond au §12 de `SPEC.md` : pour chaque point ouvert, une valeur
par défaut raisonnable a été choisie, rendue configurable, et documentée ici.
Tous les paramètres de jeu vivent dans `config/settings.py` → `GAME` et sont
surchargeables par variables d'environnement.

| Point (§12) | Décision par défaut | Où / comment changer |
|---|---|---|
| Format des données Ecologits | CSV (en-tête obligatoire). Colonnes min. : `provider, model_name, output_description, output_tokens, energy_mwh`. Exemple : `data/scenarios.sample.csv`. | `uv run manage.py import_scenarios <fichier.csv> [--replace] [--deactivate-missing]` |
| Liste des modèles / scénarios | Fixture `game/fixtures/scenarios.json` : le cas fourni (Claude Haiku 4.5 / email / 250 tk / 28.1 mWh) + 4 scénarios factices de démo (marqués « valeur factice de démo » dans `source`). | Éditer la fixture, l'admin Django, ou importer un CSV réel. |
| `energy_per_revolution` (calibration vélo) | **1,5 J / tour** — valeur arbitraire PROVISOIRE. Choisie pour qu'avec ~90 tours en 60 s on approche l'objectif du scénario email (101 J). À recalibrer avec de vrais participants (§13 priorité 9). | `GAME["ENERGY_PER_REVOLUTION_JOULES"]` / env `GAME_ENERGY_PER_REVOLUTION_JOULES` |
| Barème de points par palier | `0 / 25 / 50 / 75 / 150`. Le palier 100 % est volontairement survalorisé (bonus net). | `GAME["POINTS_PER_TIER"]` |
| Expiration des 30 s de sélection du coureur | `random` : tirage automatique parmi les joueurs restants de l'équipe active. | `GAME["TEAM_SELECTION_ON_TIMEOUT"]` = `"random"` \| `"host"` |
| LLM réel pendant l'atelier | Non par défaut : provider **simulé** (aucun appel réseau). Provider réel Anthropic optionnel. | `GAME["LLM_PROVIDER"]` = `"simulated"` \| `"anthropic"` ; `pip`/`uv` extra `llm` ; `ANTHROPIC_API_KEY` |
| `prompt_template` par scénario | Laissé `NULL`. Le provider réel retombe alors sur `output_description`. | Champ `EnergyScenario.prompt_template` (admin / CSV) |
| Capteur exact sur le Raspberry Pi | Développé entièrement contre l'interface `core.bike_sensor.BikeSensor`. Impl. simulée par défaut. Impl. GPIO = prototype (pin BCM 17, debounce 40 ms). | `GAME["BIKE_SENSOR"]` = `"simulated"` \| `"gpio"` ; `GAME["GPIO_PIN"]`, `GAME["GPIO_DEBOUNCE_MS"]` ; extra `rpi` |
| Design / résolution d'écran | Templates simples et responsives (thème sombre). Écran animateur `/` + écran public `/display/`. | `game/templates/`, `static/game/` |
| Seuil de validation du vélo (BIKE_CHECK) | 5 tours. | `GAME["BIKE_CHECK_REVOLUTIONS"]` |
| Durées des phases | sélection 30 s / préparation 10 s / pédalage 60 s. | `GAME["TEAM_SELECTION_SECONDS"]`, `GAME["PREPARATION_SECONDS"]`, `GAME["CYCLING_SECONDS"]` |
| Perte de signal vélo (§11) | Alerte visuelle après 8 s sans nouvelle impulsion pendant `CYCLING` ; le chrono **n'est pas** arrêté. | `GAME["SIGNAL_LOSS_TIMEOUT_SECONDS"]` |

## Notes d'implémentation

- **Un seul vélo, un seul animateur** : le `GameManager` est un singleton en
  mémoire du process (`game.services.get_service()`). Ne pas lancer plusieurs
  workers Gunicorn/Uvicorn sans revoir ce point.
- **Redémarrage** (§11) : `Game` / `Team` / `Player` / `Round` sont persistés.
  Au redémarrage on restaure l'id de partie, les scores et les « déjà joué ».
  L'état transitoire (chrono en cours) n'est pas restauré : une manche coupée
  par un crash se rejoue via le bouton **Reset** de l'animateur.
- **Temps réel** : polling HTTP (`GET /api/state`, ~700 ms) — pas de WebSocket
  pour rester simple et sans dépendance ASGI supplémentaire. `config/asgi.py`
  est fourni si un passage à Channels devient nécessaire.
