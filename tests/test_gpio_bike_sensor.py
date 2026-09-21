"""Tests de GpioBikeSensor avec un faux module ``lgpio`` (pas de matériel requis)."""

import sys
import types

import pytest

from core.bike_sensor import BikeSensor
from game import gpio_bike_sensor
from game.gpio_bike_sensor import GpioBikeSensor


class FakeLgpio(types.ModuleType):
    FALLING_EDGE = 2
    SET_PULL_UP = 32

    def __init__(self, fail_claim: bool = False) -> None:
        super().__init__("lgpio")
        self.fail_claim = fail_claim
        self.calls: list[str] = []
        self.func = None

    def gpiochip_open(self, chip):
        self.calls.append("open")
        return 7

    def gpio_claim_alert(self, handle, pin, edge, flags):
        self.calls.append("claim")
        if self.fail_claim:
            raise RuntimeError("GPIO busy")

    def gpio_set_debounce_micros(self, handle, pin, micros):
        self.calls.append(f"debounce:{micros}")

    def callback(self, handle, pin, edge, func):
        self.calls.append("callback")
        self.func = func
        return types.SimpleNamespace(cancel=lambda: self.calls.append("cancel"))

    def gpio_free(self, handle, pin):
        self.calls.append("free")

    def gpiochip_close(self, handle):
        self.calls.append("close")


@pytest.fixture
def fake(monkeypatch):
    module = FakeLgpio()
    monkeypatch.setitem(sys.modules, "lgpio", module)
    return module


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(gpio_bike_sensor.time, "monotonic", lambda: now[0])
    return now


def test_conforms_to_protocol():
    assert isinstance(GpioBikeSensor(pin=17), BikeSensor)


def test_counts_falling_edges_only_when_running(fake, clock):
    s = GpioBikeSensor(pin=17, debounce_ms=40)
    s.start()
    assert "debounce:40000" in fake.calls

    fake.func(0, 17, 0, 0)
    clock[0] += 0.5
    fake.func(0, 17, 1, 0)  # front montant : ignoré
    fake.func(0, 17, 2, 0)  # watchdog : ignoré
    assert s.get_revolutions() == 1

    s.stop()
    fake.func(0, 17, 0, 0)  # arrêté : ignoré
    assert s.get_revolutions() == 1


def test_software_debounce_ignores_double_pulse(fake, clock):
    s = GpioBikeSensor(pin=17, debounce_ms=40)
    s.start()
    fake.func(0, 17, 0, 0)
    clock[0] += 0.010
    fake.func(0, 17, 0, 0)  # rebond < 40 ms
    assert s.get_revolutions() == 1
    clock[0] += 0.050
    fake.func(0, 17, 0, 0)
    assert s.get_revolutions() == 2


def test_cadence_from_recent_pulses(fake, clock):
    s = GpioBikeSensor(pin=17)
    s.start()
    for _ in range(4):
        fake.func(0, 17, 0, 0)
        clock[0] += 1.0  # 1 tour/s = 60 tr/min
    assert s.get_cadence() == pytest.approx(60.0)


def test_start_is_idempotent_and_stop_releases(fake):
    s = GpioBikeSensor(pin=17)
    s.start()
    s.start()
    assert fake.calls.count("open") == 1

    s.stop()
    assert fake.calls[-3:] == ["cancel", "free", "close"]

    s.start()  # redémarrage possible après stop
    assert fake.calls.count("open") == 2


def test_start_failure_raises_clear_error_and_closes_chip(monkeypatch):
    module = FakeLgpio(fail_claim=True)
    monkeypatch.setitem(sys.modules, "lgpio", module)
    s = GpioBikeSensor(pin=17)
    with pytest.raises(RuntimeError, match="broche BCM 17"):
        s.start()
    assert module.calls[-2:] == ["free", "close"]
