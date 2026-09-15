"""Tests du capteur simulé (§7, §10, §14)."""

from core.bike_sensor import BikeSensor, SimulatedBikeSensor


def test_conforms_to_protocol():
    assert isinstance(SimulatedBikeSensor(), BikeSensor)


def test_counts_only_when_running():
    s = SimulatedBikeSensor()
    assert s.add_revolutions(5) == 0  # pas démarré -> ignoré
    s.start()
    assert s.add_revolutions(5) == 5
    assert s.add_revolutions(10) == 15
    s.stop()
    assert s.add_revolutions(3) == 15  # arrêté -> ignoré


def test_reset_clears_count():
    s = SimulatedBikeSensor()
    s.start()
    s.add_revolutions(42)
    s.reset()
    assert s.get_revolutions() == 0


def test_negative_or_zero_increment_is_noop():
    s = SimulatedBikeSensor()
    s.start()
    s.add_revolutions(0)
    s.add_revolutions(-5)
    assert s.get_revolutions() == 0
