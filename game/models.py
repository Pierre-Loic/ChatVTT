"""Modèle de données (§3 SPEC.md).

Schéma compatible PostgreSQL : aucun type spécifique SQLite (§1).
Les ``choices`` de statut sont dérivées de ``core.state_machine.GameState``
(source de vérité unique, §5).
"""

from __future__ import annotations

from django.db import models

from core.state_machine import GameState


class GameStatus(models.TextChoices):
    """Miroir Django de ``core.state_machine.GameState`` (§5)."""

    CONFIGURATION = GameState.CONFIGURATION, "Configuration"
    BIKE_CHECK = GameState.BIKE_CHECK, "Vérification du vélo"
    INTRODUCTION = GameState.INTRODUCTION, "Introduction pédagogique"
    SPINNING = GameState.SPINNING, "Tirage (roues)"
    TEAM_SELECTION = GameState.TEAM_SELECTION, "Sélection du coureur"
    PREPARATION = GameState.PREPARATION, "Préparation"
    CYCLING = GameState.CYCLING, "Pédalage"
    RESULT = GameState.RESULT, "Résultat de la manche"
    NEXT_TEAM = GameState.NEXT_TEAM, "Équipe suivante"
    FINAL_RESULTS = GameState.FINAL_RESULTS, "Résultats finaux"
    PEDAGOGICAL_SUMMARY = GameState.PEDAGOGICAL_SUMMARY, "Synthèse pédagogique"


class Team(models.Model):
    name = models.CharField(max_length=100)
    score = models.IntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.name} ({self.score} pts)"


class Player(models.Model):
    name = models.CharField(max_length=100)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="players")
    # Dérivable via Round mais utile en champ direct (§3).
    has_played = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name


class EnergyScenario(models.Model):
    """Scénario énergétique préparé à partir d'Ecologits (§9).

    ``energy_mwh`` est une donnée, jamais un résultat de formule théorique.
    """

    provider = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    model_family = models.CharField(max_length=100, blank=True, null=True)
    # Catégorie pédagogique (ex. « petit / moyen / grand »).
    model_size_category = models.CharField(max_length=50, blank=True, null=True)
    # Affiché aux joueurs (§9) — distinct de prompt_template.
    output_description = models.CharField(max_length=255)
    output_tokens = models.PositiveIntegerField()
    energy_mwh = models.FloatField(help_text="Estimation Ecologits en mWh (§9).")
    source = models.CharField(max_length=100, default="Ecologits")
    # Texte réellement envoyé au LLM si génération réelle (§9) — nullable (§12).
    prompt_template = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["provider", "model_name", "output_tokens"]

    def __str__(self) -> str:
        return f"{self.model_name} — {self.output_description} ({self.energy_mwh} mWh)"


class Game(models.Model):
    status = models.CharField(
        max_length=30,
        choices=GameStatus.choices,
        default=GameStatus.CONFIGURATION,
    )
    current_team = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    current_player = models.ForeignKey(
        Player, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    current_round_number = models.IntegerField(default=0)
    players_per_team = models.IntegerField(default=0)
    total_rounds = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Partie #{self.pk} — {self.get_status_display()}"


class Round(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="rounds")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    # PROTECT : on ne supprime pas un scénario référencé par une manche jouée.
    scenario = models.ForeignKey(EnergyScenario, on_delete=models.PROTECT)
    revolutions = models.IntegerField(default=0)
    human_energy_joules = models.FloatField(default=0)
    target_energy_mwh = models.FloatField()
    performance_percent = models.FloatField(default=0)
    tier_reached = models.IntegerField(default=0)  # 0 / 25 / 50 / 75 / 100
    score = models.IntegerField(default=0)
    duration_seconds = models.IntegerField(default=60)
    # Trace de la génération LLM (optionnelle, §9). Vide en mode simulé sans texte.
    generation_text = models.TextField(blank=True, default="")
    generation_simulated = models.BooleanField(default=True)
    generation_error = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["game", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["game", "player"], name="unique_player_round_per_game"
            )
        ]

    def __str__(self) -> str:
        return f"Manche {self.pk} — {self.team.name} / {self.player.name}"
