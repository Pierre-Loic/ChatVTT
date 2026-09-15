from django.contrib import admin

from .models import EnergyScenario, Game, Player, Round, Team


@admin.register(EnergyScenario)
class EnergyScenarioAdmin(admin.ModelAdmin):
    list_display = (
        "model_name",
        "output_description",
        "output_tokens",
        "energy_mwh",
        "source",
        "active",
    )
    list_filter = ("active", "provider", "model_family", "model_size_category")
    search_fields = ("model_name", "output_description", "provider")
    list_editable = ("active",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "score")


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "has_played")
    list_filter = ("team", "has_played")


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "current_round_number", "total_rounds", "created_at")
    list_filter = ("status",)


@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "game",
        "team",
        "player",
        "scenario",
        "revolutions",
        "performance_percent",
        "tier_reached",
        "score",
    )
    list_filter = ("game", "team", "tier_reached")
