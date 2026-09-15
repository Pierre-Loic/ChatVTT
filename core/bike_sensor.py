"""BikeSensor — abstraction du capteur vélo (§7 SPEC.md).

Interface commune + implémentation simulée (obligatoire, sans RPi.GPIO).
L'implémentation GPIO réelle vit dans ``game.gpio_bike_sensor`` (import
paresseux de ``RPi.GPIO``) pour que ce module reste importable partout.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class BikeSensor(Protocol):
    """Contrat commun capteur réel / simulé (§7)."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def reset(self) -> None: ...
    def get_revolutions(self) -> int: ...
    def get_cadence(self) -> float: ...


class SimulatedBikeSensor:
    """Capteur simulé (§7, §10) — aucune dépendance à RPi.GPIO.

    Les tours sont ajoutés explicitement via :meth:`add_revolutions` (boutons
    +1 / +10 / +100 de l'UI) ou par un pédalage automatique optionnel
    (:paramref:`auto_rpm`) utile pour les tests de bout en bout.

    Thread-safe : le compteur peut être incrémenté depuis des requêtes HTTP
    concurrentes pendant que le chrono tourne.
    """

    def __init__(self, auto_rpm: float = 0.0) -> None:
        self._lock = threading.Lock()
        self._revolutions = 0
        self._running = False
        self._auto_rpm = auto_rpm
        self._auto_thread: threading.Thread | None = None
        self._last_pulse_at: float | None = None
        self._recent_pulses: list[float] = []

    # -- Contrôle du cycle de vie -----------------------------------------

    def start(self) -> None:
        with self._lock:
            self._running = True
        if self._auto_rpm > 0 and (
            self._auto_thread is None or not self._auto_thread.is_alive()
        ):
            self._auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
            self._auto_thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def reset(self) -> None:
        with self._lock:
            self._revolutions = 0
            self._last_pulse_at = None
            self._recent_pulses.clear()

    # -- Lecture ----------------------------------------------------------

    def get_revolutions(self) -> int:
        with self._lock:
            return self._revolutions

    def get_cadence(self) -> float:
        """Cadence estimée en tours/minute sur les ~5 dernières secondes."""
        now = time.monotonic()
        with self._lock:
            self._recent_pulses = [t for t in self._recent_pulses if now - t <= 5.0]
            if len(self._recent_pulses) < 2:
                return 0.0
            span = self._recent_pulses[-1] - self._recent_pulses[0]
            if span <= 0:
                return 0.0
            return (len(self._recent_pulses) - 1) / span * 60.0

    @property
    def last_pulse_at(self) -> float | None:
        with self._lock:
            return self._last_pulse_at

    # -- Simulation -----------------------------------------------------

    def add_revolutions(self, count: int = 1) -> int:
        """Ajoute ``count`` tours (ignoré si le capteur n'est pas démarré)."""
        if count <= 0:
            return self.get_revolutions()
        now = time.monotonic()
        with self._lock:
            if not self._running:
                return self._revolutions
            self._revolutions += count
            self._last_pulse_at = now
            # On garde un historique borné pour l'estimation de cadence.
            self._recent_pulses.extend([now] * min(count, 10))
            self._recent_pulses = self._recent_pulses[-50:]
            return self._revolutions

    def _auto_loop(self) -> None:
        interval = 60.0 / self._auto_rpm
        while True:
            with self._lock:
                if not self._running:
                    return
            self.add_revolutions(1)
            time.sleep(interval)
