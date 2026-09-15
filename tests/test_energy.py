"""Tests unitaires EnergyCalculator (§14) — sans Django."""

import pytest

from core.energy import JOULES_PER_MWH, EnergyCalculator, ScoringConfig


def test_mwh_to_joules():
    assert EnergyCalculator.mwh_to_joules(1) == pytest.approx(3.6)
    assert EnergyCalculator.mwh_to_joules(28.1) == pytest.approx(101.16)
    assert JOULES_PER_MWH == 3.6


def test_joules_roundtrip():
    calc = EnergyCalculator(2.0)
    assert calc.joules_to_mwh(calc.mwh_to_joules(42)) == pytest.approx(42)


def test_revolutions_to_joules_uses_calibration_constant():
    assert EnergyCalculator(1.5).revolutions_to_joules(10) == pytest.approx(15.0)


def test_energy_per_revolution_must_be_positive():
    with pytest.raises(ValueError):
        EnergyCalculator(0)
    with pytest.raises(ValueError):
        EnergyCalculator(-1)


def test_performance_percent():
    assert EnergyCalculator.performance_percent(50, 200) == pytest.approx(25.0)
    assert EnergyCalculator.performance_percent(0, 200) == 0.0
    # Cible nulle -> 0 %, pas de division par zéro.
    assert EnergyCalculator.performance_percent(10, 0) == 0.0


@pytest.mark.parametrize(
    "percent,expected",
    [
        (0, 0), (24.9, 0), (25, 25), (25.0, 25), (49.999, 25),
        (50, 50), (74.9, 50), (75, 75), (99.9, 75), (100, 100), (250, 100),
    ],
)
def test_tier_reached_thresholds(percent, expected):
    assert EnergyCalculator.tier_reached(percent) == expected


def test_scoring_100_is_most_valued():
    scoring = ScoringConfig()
    # Le saut vers le palier 100 % est nettement plus gros qu'un palier normal.
    jump_to_100 = scoring.points_for_tier(100) - scoring.points_for_tier(75)
    normal_step = scoring.points_for_tier(75) - scoring.points_for_tier(50)
    assert jump_to_100 > 2 * normal_step
    assert scoring.points_for_tier(0) == 0


def test_evaluate_round_end_to_end():
    calc = EnergyCalculator(1.0)  # 1 tour = 1 J
    # cible 28.1 mWh = 101.16 J ; 51 tours -> ~50,4 % -> palier 50
    outcome = calc.evaluate_round(revolutions=51, target_energy_mwh=28.1)
    assert outcome.target_energy_joules == pytest.approx(101.16)
    assert outcome.performance_percent == pytest.approx(50.42, abs=0.01)
    assert outcome.tier_reached == 50
    assert outcome.score == ScoringConfig().points_for_tier(50)
