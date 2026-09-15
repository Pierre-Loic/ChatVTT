# SPEC.md — Vélo & IA Générative

Application pédagogique ludique. Deux équipes s'affrontent : chaque participant pédale une fois pour tenter de produire, avec ses jambes, l'énergie estimée d'une génération d'IA (modèle + sortie tirés au sort). Objectif : rendre perceptible le coût énergétique de l'IA générative, à partir de données Ecologits (estimations pédagogiques, pas une mesure réelle de datacenter).

Ce document est la spécification de référence pour le développement avec Claude Code. Il traduit le cahier des charges initial en règles, modèles et tâches actionnables. Les points encore ouverts sont listés en §12 — Claude Code doit poser la question ou choisir une valeur par défaut raisonnable et la documenter en commentaire, plutôt que bloquer.

## 1. Stack technique

- Python, gestion des dépendances avec `uv`
- Django (backend + UI serveur)
- SQLite en dev, schéma compatible PostgreSQL (pas de types spécifiques SQLite)
- Raspberry Pi + `RPi.GPIO` pour le capteur vélo (prototype fourni non définitif)
- HTML/CSS/JavaScript pour l'interface (écrans temps réel : chrono, jauge, roues)
- Le projet doit tourner **intégralement sans Raspberry Pi et sans LLM réel** (modes simulation, voir §7)

## 2. Architecture logique (modules découplés)

Découpler strictement pour permettre les tests sans matériel/API :

| Module | Rôle | Dépendances |
|---|---|---|
| `GameManager` | État de la partie : manches, joueurs, équipes, score, machine à états | aucune dépendance Django directe si possible (logique testable en isolation) |
| `BikeSensor` | Abstraction du capteur (réel ou simulé) | indépendant de Django |
| `EnergyCalculator` | Conversions d'unités, calcul de performance/paliers | pure logique, sans I/O |
| `ScenarioRepository` | Accès aux `EnergyScenario` (DB), tirage aléatoire pondéré/filtré sur `active=True` | Django ORM |
| `LLMProvider` | Abstraction optionnelle pour génération réelle vs simulée | interface commune, implémentations interchangeables |
| `UI Django` | Vues, templates, endpoints de polling/websocket pour l'affichage temps réel | consomme les modules ci-dessus |

Règle de conception : `GameManager`, `EnergyCalculator` et `BikeSensor` doivent être testables unitairement sans lancer Django ni brancher de matériel.

## 3. Modèle de données (Django)

```python
class Team(models.Model):
    name = models.CharField(max_length=100)
    score = models.IntegerField(default=0)

class Player(models.Model):
    name = models.CharField(max_length=100)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="players")
    has_played = models.BooleanField(default=False)  # dérivable via Round mais utile en champ direct

class EnergyScenario(models.Model):
    provider = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    model_family = models.CharField(max_length=100, blank=True, null=True)
    model_size_category = models.CharField(max_length=50, blank=True, null=True)  # pédagogique
    output_description = models.CharField(max_length=255)
    output_tokens = models.PositiveIntegerField()
    energy_mwh = models.FloatField()
    source = models.CharField(max_length=100, default="Ecologits")
    prompt_template = models.TextField(blank=True, null=True)  # §9 — séparé de output_description
    active = models.BooleanField(default=True)

class Game(models.Model):
    status = models.CharField(max_length=30, choices=GameState.choices)  # voir §5
    current_team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    current_player = models.ForeignKey(Player, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    current_round_number = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

class Round(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="rounds")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    scenario = models.ForeignKey(EnergyScenario, on_delete=models.PROTECT)
    revolutions = models.IntegerField(default=0)
    human_energy_joules = models.FloatField(default=0)
    target_energy_mwh = models.FloatField()
    performance_percent = models.FloatField(default=0)
    tier_reached = models.IntegerField(default=0)  # 0/25/50/75/100
    score = models.IntegerField(default=0)
    duration_seconds = models.IntegerField(default=60)
    created_at = models.DateTimeField(auto_now_add=True)
```

Contrainte d'intégrité applicative : un `Round` doit être enregistré (transaction validée) avant de démarrer la manche suivante (§11 robustesse).

## 4. Règles du jeu

- Deux équipes obligatoires, **même effectif** dans chaque équipe.
- Chaque participant pédale **exactement une fois**.
- `nombre_total_manches = 2 × nombre_participants_par_équipe`.
- Alternance stricte : équipe A, équipe B, équipe A, ... Un joueur déjà passé est exclu de la sélection.
- Fin de partie automatique quand tous les joueurs des deux équipes ont participé.

## 5. Machine à états (`GameManager`)

```
CONFIGURATION → BIKE_CHECK → INTRODUCTION → SPINNING → TEAM_SELECTION
→ PREPARATION → CYCLING → RESULT → NEXT_TEAM → (retour à SPINNING si manches restantes)
→ ... → FINAL_RESULTS → PEDAGOGICAL_SUMMARY
```

Contraintes :
- Transitions explicites, chacune couverte par un test (voir §8).
- Interdiction stricte de démarrer deux chronomètres ou deux manches en parallèle (verrou d'état).
- Chaque état correspond à un écran ; documenter dans le code quelles actions/API sont valides dans quel état, et rejeter toute action hors contexte (ex: pas de tick de pédalage hors `CYCLING`).

## 6. Détail des écrans / étapes

1. **CONFIGURATION** — L'animateur saisit le nombre de participants par équipe (identique des deux côtés). Le système calcule le nombre total de manches.
2. **BIKE_CHECK** — Le participant pédale quelques secondes ; affichage des impulsions détectées ; vélo validé après un seuil configurable de tours ; le bouton "Continuer" ne s'active qu'après validation. Afficher optionnellement la dernière impulsion et la cadence à l'animateur.
3. **INTRODUCTION** — Écran pédagogique : modèles disponibles, types/longueurs de sortie, rôle des tokens, principe du jeu, mention explicite qu'il s'agit d'une **estimation pédagogique**.
4. **SPINNING** — Deux roues façon machine à sous : Roue 1 = modèle, Roue 2 = sortie/longueur. Le tirage se fait d'abord sur les scénarios `active=True` en base ; les roues n'en sont que la représentation visuelle (ne pas générer un couple modèle/sortie qui n'existe pas en base). Animation de rotation puis arrêt. Récupération de `energy_mwh` cible.
5. **TEAM_SELECTION** — 30 secondes pour que l'équipe active choisisse son coureur parmi les joueurs n'ayant pas encore joué. Comportement en cas d'expiration : **configurable** (choix automatique aléatoire vs. demande à l'animateur) — voir §12.
6. **PREPARATION** — Décompte 10 secondes, puis affichage plein écran "PÉDALEZ !" et démarrage du chrono de 60 secondes.
7. **CYCLING** — Pendant 60 secondes, mesure en continu des tours de roue. Affichage temps réel : équipe active, modèle, sortie, chrono restant, nombre de tours, énergie produite, % de l'objectif, jauge de progression.
   - `pourcentage = énergie_produite / énergie_cible × 100`
   - Le chrono reste fixé à 60 s : atteindre 100 % **ne termine pas** la manche en avance.
8. **RESULT** — À la fin des 60 s : arrêt du comptage, calcul énergie produite et pourcentage, détermination du palier atteint (25/50/75/100 %), attribution des points, affichage du score d'équipe.
9. **NEXT_TEAM / boucle** — Retour à `SPINNING` si des manches restent, sinon passage à `FINAL_RESULTS`.
10. **FINAL_RESULTS** — Score final par équipe, équipe gagnante, total des tours, énergie totale produite, répartition des scénarios tirés, modèles/sorties utilisés.
11. **PEDAGOGICAL_SUMMARY** — Synthèse pédagogique reliant les résultats aux choix de modèle/longueur de réponse. Idéalement une comparaison type « et si un modèle plus léger / une sortie plus courte avait été utilisée ? ».

## 7. Capteur vélo (`BikeSensor`)

Interface commune, deux implémentations :

```python
class BikeSensor(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def reset(self) -> None: ...
    def get_revolutions(self) -> int: ...
    def get_cadence(self) -> float: ...
```

- **Implémentation réelle** : détection d'impulsions GPIO, debounce, nettoyage GPIO à l'arrêt, gestion des erreurs matérielles, protection contre le double comptage d'une même impulsion.
- **Implémentation simulée** (obligatoire, utilisée en dev/tests) : boutons/API +1, +10, +100 tours, simulation de cadence, sans dépendance à `RPi.GPIO`.
- Le code GPIO initial fourni est un prototype : ne pas le considérer comme l'implémentation finale, l'encapsuler derrière l'interface ci-dessus dès le départ.

## 8. Calcul énergétique (`EnergyCalculator`)

- Conversion Ecologits (mWh) → joules pour les calculs internes : **1 mWh = 3,6 J**.
- Énergie produite par le cycliste (calibration pédagogique, pas une mesure physiologique) :
  `énergie_produite = nombre_de_tours × energy_per_revolution` (constante configurable, valeur à définir — §12).
  - **Toujours documenter/afficher que cette constante est une calibration pédagogique**, jamais présentée comme une mesure métabolique exacte.
- Paliers de performance :

  | Performance | Palier |
  |---|---|
  | < 25 % | aucun |
  | ≥ 25 % | 25 % |
  | ≥ 50 % | 50 % |
  | ≥ 75 % | 75 % |
  | ≥ 100 % | 100 % |

- Barème de points par palier : valeur exacte à définir/configurer (§12). Le palier 100 % doit être nettement le plus valorisé.

## 9. Scénarios énergétiques et LLM

- Ne jamais recalculer l'énergie via une formule théorique : toujours lire `energy_mwh` depuis les données préparées à partir d'Ecologits (fichier ou base).
- Structure de données conçue pour ajouter facilement de nouveaux modèles/sorties/valeurs sans toucher au code métier (import via fixture/CSV → `EnergyScenario`).
- Séparer strictement `output_description` (affiché aux joueurs, ex. « Écrire le texte d'un email ») et `prompt_template` (texte réellement envoyé au LLM si génération réelle activée).
- `LLMProvider` abstrait avec au moins deux implémentations : provider simulé (par défaut, aucun appel réseau) et provider réel optionnel.

Exemple de scénario fourni dans le cahier des charges :
`provider=Anthropic, model_name=Claude Haiku 4.5, output_description="Écrire le texte d'un email", output_tokens=250, energy_mwh=28.1, source=Ecologits`

## 10. Mode simulation (obligatoire, transverse)

Le jeu doit être développable et testable de bout en bout sans aucun matériel :
- Vélo simulé (§7).
- Provider LLM simulé (§9) — aucune dépendance à une API externe pour jouer une partie complète.
- Ce mode doit permettre de dérouler l'intégralité de la machine à états (§5) en tests automatisés.

## 11. Robustesse

- Ne jamais compter deux fois la même impulsion GPIO (debounce + protection double-comptage).
- Empêcher deux manches ou deux chronomètres simultanés (verrou au niveau `GameManager`).
- Gérer la perte du signal vélo pendant une manche (timeout / message d'erreur, ne pas planter le chrono).
- Gérer l'arrêt/redémarrage de l'application sans corrompre l'état de la partie en cours.
- Prévoir un bouton de reset explicite pour l'animateur (retour à `CONFIGURATION`).
- Gérer les erreurs du provider LLM sans bloquer le déroulement du jeu (le jeu ne dépend jamais du LLM réel pour fonctionner).
- Chaque `Round` doit être persisté en base avant la transition vers la manche suivante.

## 12. Points à clarifier avant/pendant l'implémentation

Ne pas bloquer le développement sur ces points : choisir une valeur par défaut raisonnable, la rendre configurable (settings Django / modèle de config), et la signaler clairement en commentaire ou dans un fichier `CONFIG_NOTES.md`.

- Format et emplacement exact des données Ecologits sources (CSV, Excel, JSON, DB) → prévoir une commande de management Django `import_scenarios` qui accepte un format simple (CSV recommandé par défaut) et documenter le format attendu.
- Liste exacte des modèles et scénarios à proposer → un seul exemple est fourni dans le cahier des charges ; prévoir des fixtures avec ce cas + 2-3 scénarios factices pour pouvoir développer/tester tout de suite.
- Valeur de `energy_per_revolution` (calibration vélo) → mettre une valeur par défaut arbitraire en `settings.py`, clairement commentée comme provisoire.
- Barème de points par palier → valeur par défaut simple (ex. 0/25/50/75/100 points, palier 100 % bonus supplémentaire), configurable.
- Comportement si les 30 secondes de sélection du coureur expirent → défaut recommandé : sélection automatique aléatoire parmi les joueurs restants de l'équipe, avec flag de config pour basculer vers "demande à l'animateur".
- Utilisation ou non d'un LLM réel pendant l'atelier → développer d'abord avec le provider simulé ; l'intégration réelle reste optionnelle et activable par config.
- Prompt exact par scénario → laisser `prompt_template` vide/nullable tant que non défini.
- Matériel/capteur exact sur le Raspberry Pi → développer entièrement contre l'interface `BikeSensor`, l'implémentation GPIO réelle vient en dernier (§13, priorité 8).
- Design graphique final / résolution d'écran → construire des templates simples et responsives d'abord, style à affiner ensuite.

## 13. Ordre de développement recommandé

1. Machine à états + logique de jeu (`GameManager`), sans matériel ni LLM réel.
2. Import des scénarios énergétiques depuis un fichier/fixture vers `EnergyScenario`.
3. Interface Django (écrans) + animation des deux roues.
4. Mode simulation du vélo (`BikeSensor` simulé).
5. Calcul énergétique (`EnergyCalculator`) et paliers.
6. Provider LLM simulé.
7. Provider LLM réel (optionnel).
8. Intégration Raspberry Pi + capteur GPIO réel.
9. Calibration réelle du modèle tours → énergie pédagogique.
10. Test de l'expérience avec de vrais participants, ajustement du game design.

## 14. Plan de tests

Tests unitaires (sans Django si possible pour la logique pure) :
- Conversion mWh → joules.
- Calcul tours → énergie humaine.
- Calcul du pourcentage de performance.
- Détection du palier atteint pour chaque seuil (0/25/50/75/100 %).
- Attribution des points selon le barème configuré.
- Sélection aléatoire d'un scénario, garantie qu'il est `active=True`.
- Alternance correcte des équipes sur toute une partie.
- Impossibilité de sélectionner deux fois le même joueur.

Tests d'intégration / machine à états :
- Décompte de sélection du coureur (30 s) et comportement à expiration.
- Décompte de préparation (10 s).
- Chronomètre de pédalage (60 s), y compris le cas où 100 % est atteint avant la fin.
- Déroulement complet d'une partie en mode vélo simulé + LLM simulé.
- Fin de partie correcte quand tous les joueurs ont participé.
- Gestion des scénarios désactivés (`active=False` jamais tiré).
- Gestion des erreurs du provider LLM (ne bloque pas le jeu).

## 15. Critères d'acceptation

- [ ] L'animateur configure le nombre de participants par équipe (effectifs égaux).
- [ ] Le système vérifie le fonctionnement du vélo avant la partie.
- [ ] L'écran de présentation pédagogique s'affiche avec la mention "estimation".
- [ ] Les deux roues animées tirent un scénario réellement présent en base.
- [ ] Le scénario affiché contient au minimum modèle, sortie, tokens, énergie.
- [ ] L'équipe dispose de 30 secondes pour choisir son coureur.
- [ ] Décompte de préparation de 10 secondes avant "PÉDALEZ !".
- [ ] Mesure des tours pendant exactement 60 secondes, sans arrêt anticipé à 100 %.
- [ ] Affichage temps réel de la progression (tours, énergie, %, jauge).
- [ ] Paliers 25/50/75/100 % correctement calculés.
- [ ] Points attribués selon le barème configuré.
- [ ] Un joueur déjà passé ne peut plus être sélectionné.
- [ ] Les équipes alternent strictement.
- [ ] Chaque participant passe exactement une fois.
- [ ] Fin de partie automatique quand tous ont participé.
- [ ] Le mode simulation permet de jouer sans Raspberry Pi.
- [ ] Chaque manche est persistée en base avant la suivante.
- [ ] L'écran final présente scores, énergie totale, répartition des scénarios et synthèse pédagogique.

## 16. Principes pédagogiques (contraintes transverses, non négociables)

- Toujours distinguer explicitement énergie estimée de l'IA vs. énergie produite par le cycliste.
- Ne jamais présenter les valeurs Ecologits comme une mesure exacte de la consommation réelle d'un datacenter.
- Conserver la traçabilité de la source des données (`source` sur chaque `EnergyScenario`).
- Toujours rendre visibles les deux facteurs qui déterminent l'énergie : modèle et quantité de sortie.
- Le vélo est un support de compréhension, pas une mesure scientifique de dépense métabolique — le dire explicitement dans l'UI.
- Prévoir un débriefing final reliant les résultats du jeu aux choix d'usage de l'IA.
