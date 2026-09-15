"""Implémentation GPIO réelle de BikeSensor (§7, §13 priorité 8).

PROTOTYPE — le matériel exact reste à confirmer (§12). Import de ``RPi.GPIO``
paresseux : ce module n'est jamais importé hors Raspberry Pi.

Points durs traités (§11) :
- debounce matériel + logiciel,
- protection contre le double comptage d'une même impulsion,
- nettoyage GPIO à l'arrêt,
- pas de crash si le signal disparaît (le comptage se fige, sans exception).
"""

from __future__ import annotations

import threading
import time


class GpioBikeSensor:
    def __init__(self, pin: int, debounce_ms: int = 40) -> None:
        self._pin = pin
        self._debounce_s = debounce_ms / 1000.0
        self._lock = threading.Lock()
        self._revolutions = 0
        self._running = False
        self._last_edge_at = 0.0
        self._pulses: list[float] = []
        self._gpio = None  # module RPi.GPIO, chargé dans start()

    def start(self) -> None:
        import RPi.GPIO as GPIO  # import paresseux — dépendance optionnelle

        self._gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # bouncetime = debounce matériel ; on double avec un filtre logiciel.
        GPIO.add_event_detect(
            self._pin,
            GPIO.FALLING,
            callback=self._on_edge,
            bouncetime=max(1, int(self._debounce_s * 1000)),
        )
        with self._lock:
            self._running = True

    def stop(self) -> None:
        with self._lock:
            self._running = False
        if self._gpio is not None:
            try:
                self._gpio.remove_event_detect(self._pin)
                self._gpio.cleanup(self._pin)
            except Exception:  # noqa: BLE001 — nettoyage best effort
                pass

    def reset(self) -> None:
        with self._lock:
            self._revolutions = 0
            self._last_edge_at = 0.0
            self._pulses.clear()

    def get_revolutions(self) -> int:
        with self._lock:
            return self._revolutions

    def get_cadence(self) -> float:
        now = time.monotonic()
        with self._lock:
            self._pulses = [t for t in self._pulses if now - t <= 5.0]
            if len(self._pulses) < 2:
                return 0.0
            span = self._pulses[-1] - self._pulses[0]
            return (len(self._pulses) - 1) / span * 60.0 if span > 0 else 0.0

    def _on_edge(self, _channel: int) -> None:
        now = time.monotonic()
        with self._lock:
            if not self._running:
                return
            # Protection double comptage : on ignore toute impulsion trop
            # rapprochée de la précédente (§11).
            if now - self._last_edge_at < self._debounce_s:
                return
            self._last_edge_at = now
            self._revolutions += 1
            self._pulses.append(now)
            self._pulses = self._pulses[-50:]
