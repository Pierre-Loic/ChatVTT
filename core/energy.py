"""EnergyCalculator — conversions d'unités et paliers de performance (§8 SPEC.md).

Pure logique, aucune I/O, aucun import Django.

Distinction pédagogique non négociable (§16) :
- « énergie IA » = estimation Ecologits (mWh) — jamais une mesure datacenter.
- « énergie cycliste » = tours × constante de calibration PÉDAGOGIQUE —
  jamais une mesure métabolique.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 1 mWh = 3,6 J (§8). Constante physique, non configurable.
JOULES_PER_MWH: float = 3.6

# Paliers de performance (§8). Ordre croissant.
PERFORMANCE_TIERS: tuple[int, ...] = (25, 50, 75, 100)


@dataclass(frozen=True)
class ScoringConfig:
    """Barème de points par palier (§8, §12).

    Défaut : 0 / 25 / 50 / 75 points, et le palier 100 % est nettement
    survalorisé (bonus). Configurable via settings Django (voir
    ``config.settings.GAME`` et ``CONFIG_NOTES.md``).
    """

    points_per_tier: dict[int, int] = field(
        default_factory=lambda: {0: 0, 25: 25, 50: 50, 75: 75, 100: 150}
    )

    def points_for_tier(self, tier: int) -> int:
        return self.points_per_tier.get(tier, 0)


@dataclass(frozen=True)
class RoundOutcome:
    """Résultat calculé d'une manche."""

    revolutions: int
    human_energy_joules: float
    target_energy_mwh: float
    target_energy_joules: float
    performance_percent: float
    tier_reached: int
    score: int


class EnergyCalculator:
    """Calculs énergétiques du jeu.

    :param energy_per_revolution_joules: calibration PÉDAGOGIQUE tours -> joules
        (§8, §12). Valeur provisoire par défaut, à recalibrer avec de vrais
        participants (§13 priorité 9). Définie dans ``config.settings.GAME``.
    :param scoring: barème de points par palier.
    """

    def __init__(
        self,
        energy_per_revolution_joules: float,
        scoring: ScoringConfig | None = None,
    ) -> None:
        if energy_per_revolution_joules <= 0:
            raise ValueError("energy_per_revolution_joules doit être > 0")
        self.energy_per_revolution_joules = energy_per_revolution_joules
        self.scoring = scoring or ScoringConfig()

    # -- Conversions -----------------------------------------------------------

    @staticmethod
    def mwh_to_joules(mwh: float) -> float:
        """Énergie IA (Ecologits) : mWh -> joules. 1 mWh = 3,6 J (§8)."""
        return mwh * JOULES_PER_MWH

    @staticmethod
    def joules_to_mwh(joules: float) -> float:
        return joules / JOULES_PER_MWH

    def revolutions_to_joules(self, revolutions: int) -> float:
        """Énergie cycliste (calibration pédagogique, pas une mesure)."""
        return revolutions * self.energy_per_revolution_joules

    # -- Performance ---------------------------------------------------------

    @staticmethod
    def performance_percent(produced_joules: float, target_joules: float) -> float:
        """pourcentage = énergie_produite / énergie_cible × 100 (§6.7)."""
        if target_joules <= 0:
            return 0.0
        return produced_joules / target_joules * 100.0

    @staticmethod
    def tier_reached(performance_percent: float) -> int:
        """Palier atteint : 0 / 25 / 50 / 75 / 100 (§8).

        Seuils inclusifs : exactement 25,0 % => palier 25.
        """
        reached = 0
        for tier in PERFORMANCE_TIERS:
            if performance_percent + 1e-9 >= tier:
                reached = tier
        return reached

    # -- Résultat complet d'une manche -------------------------------------

    def evaluate_round(self, revolutions: int, target_energy_mwh: float) -> RoundOutcome:
        target_joules = self.mwh_to_joules(target_energy_mwh)
        produced_joules = self.revolutions_to_joules(revolutions)
        percent = self.performance_percent(produced_joules, target_joules)
        tier = self.tier_reached(percent)
        return RoundOutcome(
            revolutions=revolutions,
            human_energy_joules=produced_joules,
            target_energy_mwh=target_energy_mwh,
            target_energy_joules=target_joules,
            performance_percent=percent,
            tier_reached=tier,
            score=self.scoring.points_for_tier(tier),
        )
