"""Tests de GpioBikeSensor avec un faux module ``RPi.GPIO`` (pas de matériel requis)."""

import sys
import types

import pytest

from core.bike_sensor import BikeSensor
from game import gpio_bike_sensor
from game.gpio_bike_sensor import GpioBikeSensor


class FakeGPIO(types.ModuleType):
    BCM = 11
    IN = 1
    PUD_UP = 22

    def __init__(self, fail_setup: bool = False) -> None:
        super().__init__("RPi.GPIO")
        self.fail_setup = fail_setup
        self.level = 1
        self.calls: list[str] = []

    def setmode(self, mode):
        self.calls.append("setmode")

    def setup(self, pin, mode, pull_up_down=None):
        self.calls.append(f"setup:{pin}")
        if self.fail_setup:
            raise RuntimeError("GPIO busy")

    def input(self, pin):
        return self.level

    def cleanup(self, pin):
        self.calls.append(f"cleanup:{pin}")


def install(monkeypatch, gpio: FakeGPIO) -> None:
    rpi = types.ModuleType("RPi")
    rpi.GPIO = gpio
    monkeypatch.setitem(sys.modules, "RPi", rpi)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", gpio)


@pytest.fixture
def fake(monkeypatch):
    gpio = FakeGPIO()
    install(monkeypatch, gpio)
    return gpio


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(gpio_bike_sensor.time, "monotonic", lambda: now[0])
    return now


def running_sensor(fake: FakeGPIO, debounce_ms: int = 40) -> GpioBikeSensor:
    """Capteur prêt à être interrogé à la main via ``_poll_once`` (sans thread)."""
    s = GpioBikeSensor(pin=27, debounce_ms=debounce_ms)
    s._gpio = fake
    s._running = True
    return s


def poll(s: GpioBikeSensor, fake: FakeGPIO, level: int) -> None:
    fake.level = level
    s._poll_once()


def test_conforms_to_protocol():
    assert isinstance(GpioBikeSensor(pin=27), BikeSensor)


def test_counts_falling_edges_only(fake, clock):
    s = running_sensor(fake)
    poll(s, fake, 1)
    poll(s, fake, 0)  # front descendant : +1
    poll(s, fake, 0)  # contact maintenu : rien
    clock[0] += 0.5
    poll(s, fake, 1)  # front montant : rien
    assert s.get_revolutions() == 1
    poll(s, fake, 0)
    assert s.get_revolutions() == 2


def test_software_debounce_ignores_double_pulse(fake, clock):
    s = running_sensor(fake, debounce_ms=40)
    poll(s, fake, 0)
    poll(s, fake, 1)
    clock[0] += 0.010
    poll(s, fake, 0)  # rebond < 40 ms
    assert s.get_revolutions() == 1
    poll(s, fake, 1)
    clock[0] += 0.050
    poll(s, fake, 0)
    assert s.get_revolutions() == 2


def test_no_count_when_stopped(fake, clock):
    s = running_sensor(fake)
    s._running = False
    poll(s, fake, 0)
    assert s.get_revolutions() == 0


def test_cadence_from_recent_pulses(fake, clock):
    s = running_sensor(fake)
    for _ in range(4):
        poll(s, fake, 0)
        poll(s, fake, 1)
        clock[0] += 1.0  # 1 tour/s = 60 tr/min
    assert s.get_cadence() == pytest.approx(60.0)


def test_start_stop_lifecycle_with_real_thread(fake):
    s = GpioBikeSensor(pin=27)
    s.start()
    thread = s._thread
    assert thread is not None and thread.is_alive()
    s.start()  # idempotent : pas de second thread
    assert s._thread is thread

    s.stop()
    assert not thread.is_alive()
    assert fake.calls[-1] == "cleanup:27"

    s.start()  # redémarrage possible après stop
    assert s._thread is not thread and s._thread.is_alive()
    s.stop()


def test_contact_already_closed_at_start_is_not_counted(fake):
    fake.level = 0
    s = GpioBikeSensor(pin=27)
    s.start()
    s._poll_once()
    s.stop()
    assert s.get_revolutions() == 0


def test_start_failure_raises_clear_error(monkeypatch):
    gpio = FakeGPIO(fail_setup=True)
    install(monkeypatch, gpio)
    s = GpioBikeSensor(pin=27)
    with pytest.raises(RuntimeError, match="broche BCM 27"):
        s.start()
    assert gpio.calls[-1] == "cleanup:27"
