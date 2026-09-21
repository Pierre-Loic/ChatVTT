"""Implémentation GPIO réelle de BikeSensor (§7, §13 priorité 8).

PROTOTYPE — le matériel exact reste à confirmer (§12). Utilise ``lgpio`` (API
noyau ``/dev/gpiochipN``), sans détection de modèle de carte : fonctionne sur
tous les Raspberry Pi, y compris Pi 1 et Pi 5. Import paresseux : ce module
n'est jamais importé hors Raspberry Pi.

Points durs traités (§11) :
- debounce matériel (lgpio) + logiciel,
- protection contre le double comptage d'une même impulsion,
- libération des GPIO à l'arrêt,
- pas de crash si le signal disparaît (le comptage se fige, sans exception),
- erreur explicite si la puce/broche GPIO est inaccessible.

Note : ``lgpio`` crée un fichier ``.lgd-nfyN`` dans le dossier courant à
l'import ; le processus doit pouvoir écrire dans le dossier du projet.
"""

from __future__ import annotations

import threading
import time


class GpioBikeSensor:
    def __init__(self, pin: int, debounce_ms: int = 40, chip: int = 0) -> None:
        self._pin = pin
        self._chip = chip
        self._debounce_s = debounce_ms / 1000.0
        self._lock = threading.Lock()
        self._revolutions = 0
        self._running = False
        self._last_edge_at = float("-inf")
        self._pulses: list[float] = []
        self._lgpio = None  # module lgpio, chargé dans start()
        self._handle: int | None = None
        self._callback = None

    def start(self) -> None:
        if self._handle is None:
            self._open()
        with self._lock:
            self._running = True

    def stop(self) -> None:
        with self._lock:
            self._running = False
        self._close()

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

    def _open(self) -> None:
        import lgpio  # import paresseux — dépendance optionnelle

        handle = None
        try:
            handle = lgpio.gpiochip_open(self._chip)
            lgpio.gpio_claim_alert(
                handle, self._pin, lgpio.FALLING_EDGE, lgpio.SET_PULL_UP
            )
            # Debounce matériel ; on double avec un filtre logiciel dans _on_edge.
            lgpio.gpio_set_debounce_micros(
                handle, self._pin, int(self._debounce_s * 1_000_000)
            )
            callback = lgpio.callback(
                handle, self._pin, lgpio.FALLING_EDGE, self._on_edge
            )
        except Exception as exc:
            if handle is not None:
                self._release(lgpio, handle)
            raise RuntimeError(
                f"Capteur GPIO indisponible (gpiochip{self._chip}, "
                f"broche BCM {self._pin}) : {exc}"
            ) from exc
        self._lgpio = lgpio
        self._handle = handle
        self._callback = callback

    def _close(self) -> None:
        callback, handle, lgpio = self._callback, self._handle, self._lgpio
        self._callback = self._handle = None
        if callback is not None:
            try:
                callback.cancel()
            except Exception:  # noqa: BLE001 — nettoyage best effort
                pass
        if handle is not None:
            self._release(lgpio, handle)

    def _release(self, lgpio, handle: int) -> None:
        for release in (
            lambda: lgpio.gpio_free(handle, self._pin),
            lambda: lgpio.gpiochip_close(handle),
        ):
            try:
                release()
            except Exception:  # noqa: BLE001 — nettoyage best effort
                pass

    def _on_edge(self, _chip: int, _gpio: int, level: int, _tick: int) -> None:
        if level != 0:  # 0 = front descendant ; 2 = watchdog, 1 = montant
            return
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
