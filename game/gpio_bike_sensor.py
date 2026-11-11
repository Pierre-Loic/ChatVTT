"""Implémentation GPIO réelle de BikeSensor (§7, §13 priorité 8).

PROTOTYPE — le matériel exact reste à confirmer (§12). Import de ``RPi.GPIO``
paresseux : ce module n'est jamais importé hors Raspberry Pi.

Le niveau de la broche est lu en boucle (polling, ~1 ms) plutôt que par
``add_event_detect``, qui échoue sur certains Pi (« Failed to add edge
detection »). Capteur câblé entre la broche et la masse, pull-up interne :
un tour = un front descendant (contact qui se ferme).

Points durs traités (§11) :
- debounce logiciel,
- protection contre le double comptage d'une même impulsion,
- nettoyage GPIO à l'arrêt,
- pas de crash si le signal disparaît (le comptage se fige, sans exception).
"""

from __future__ import annotations

import logging
import os
import struct
import threading
import time

POLL_INTERVAL_S = 0.001

logger = logging.getLogger(__name__)

DEVICE_TREE_REVISION = "/proc/device-tree/system/linux,revision"

# Codes de révision « ancien format » (Pi 1 / CM1) → équivalent « nouveau
# format » (bit 23 à 1 : mémoire, fabricant, type de carte, révision).
# rpi-lgpio refuse les anciens codes ; on lui fournit l'équivalent via la
# variable d'environnement RPI_LGPIO_REVISION, qu'il lit en priorité.
_OLD_TO_NEW_REVISION = {
    0x0002: 0x800010, 0x0003: 0x800010,                     # B 1.0, 256 Mo
    0x0004: 0x800012, 0x0005: 0x800012, 0x0006: 0x800012,   # B 2.0, 256 Mo
    0x0007: 0x800002, 0x0008: 0x800002, 0x0009: 0x800002,   # A 2.0, 256 Mo
    0x000D: 0x900012, 0x000E: 0x900012, 0x000F: 0x900012,   # B 2.0, 512 Mo
    0x0010: 0x900032, 0x0013: 0x900032,                     # B+ 1.2, 512 Mo
    0x0011: 0x900061, 0x0014: 0x900061,                     # CM1, 512 Mo
    0x0012: 0x800021, 0x0015: 0x900021,                     # A+ 1.1
}
_DEFAULT_NEW_REVISION = 0x900032  # B+ : connecteur 40 broches, BCM2835


def _ensure_lgpio_revision(path: str = DEVICE_TREE_REVISION) -> None:
    """Pour rpi-lgpio sur un Pi à code de révision ancien format : fixe
    ``RPI_LGPIO_REVISION`` à l'équivalent nouveau format. Sans effet sinon."""
    if "RPI_LGPIO_REVISION" in os.environ:
        return
    try:
        with open(path, "rb") as f:
            revision = struct.unpack(">I", f.read(4))[0]
    except (OSError, struct.error):
        return  # pas un Pi, ou device-tree illisible : on laisse le module décider
    if revision == 0 or revision >> 23 & 1:
        return  # nouveau format : rien à faire
    # Bits 24-25 : garantie annulée / surtension — sans incidence ici.
    new = _OLD_TO_NEW_REVISION.get(revision & 0xFFFF, _DEFAULT_NEW_REVISION)
    os.environ["RPI_LGPIO_REVISION"] = f"{new:x}"
    logger.info(
        "Code de révision ancien format 0x%x : RPI_LGPIO_REVISION=%x", revision, new
    )


class GpioBikeSensor:
    def __init__(self, pin: int, debounce_ms: int = 40) -> None:
        self._pin = pin
        self._debounce_s = debounce_ms / 1000.0
        self._lock = threading.Lock()
        self._revolutions = 0
        self._running = False
        self._last_edge_at = float("-inf")
        self._pulses: list[float] = []
        self._gpio = None  # module RPi.GPIO, chargé dans start()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._prev_level = 1

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            with self._lock:
                self._running = True
            return

        _ensure_lgpio_revision()
        try:
            import RPi.GPIO as GPIO  # import paresseux — dépendance optionnelle
        except ImportError as exc:
            raise RuntimeError(
                "Module RPi.GPIO introuvable dans cet environnement Python "
                "(voir README, section « Matériel réel »)."
            ) from exc
        except Exception as exc:  # ex. rpi-lgpio : « old-style revision codes »
            raise RuntimeError(
                f"Module RPi.GPIO inutilisable sur ce Raspberry Pi : {exc} "
                "(voir README, section « Matériel réel »)."
            ) from exc

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._prev_level = GPIO.input(self._pin)
        except Exception as exc:
            self._cleanup(GPIO)
            raise RuntimeError(
                f"Capteur GPIO indisponible (broche BCM {self._pin}) : {exc}"
            ) from exc
        logger.info(
            "Capteur GPIO démarré (broche BCM %s, niveau initial %s, module %s)",
            self._pin, self._prev_level, getattr(GPIO, "__file__", "?"),
        )

        self._gpio = GPIO
        self._stop_event.clear()
        with self._lock:
            self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._cleanup(self._gpio)

    def reset(self) -> None:
        with self._lock:
            self._revolutions = 0
            self._last_edge_at = float("-inf")
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

    def _cleanup(self, gpio) -> None:
        if gpio is None:
            return
        try:
            gpio.cleanup(self._pin)
        except Exception:  # noqa: BLE001 — nettoyage best effort
            pass

    def _poll_loop(self) -> None:
        failing = False
        while not self._stop_event.is_set():
            try:
                self._poll_once()
                if failing:
                    logger.warning("Lecture GPIO broche %s rétablie", self._pin)
                    failing = False
            except Exception:  # noqa: BLE001 — signal perdu : on fige, sans crash
                # Journalisé une seule fois par panne, pour ne pas inonder les logs.
                if not failing:
                    logger.exception("Échec de lecture GPIO broche %s", self._pin)
                    failing = True
            self._stop_event.wait(POLL_INTERVAL_S)

    def _poll_once(self) -> None:
        level = self._gpio.input(self._pin)
        previous, self._prev_level = self._prev_level, level
        if previous == 1 and level == 0:  # front descendant
            self._on_pulse()

    def _on_pulse(self) -> None:
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
