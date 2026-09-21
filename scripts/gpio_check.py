"""Diagnostic du capteur vélo, sans Django : affiche chaque front détecté.

    uv run python scripts/gpio_check.py [--pin 17] [--chip 0]

Actionne le capteur (aimant devant le contact / tour de pédalier) : chaque
changement de niveau s'affiche avec la durée passée dans l'état précédent.
Ctrl+C pour quitter. Aucun debounce : on voit le signal brut.
"""

from __future__ import annotations

import argparse
import time

import lgpio


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", type=int, default=17, help="broche BCM (défaut 17)")
    ap.add_argument("--chip", type=int, default=0, help="gpiochip (défaut 0)")
    args = ap.parse_args()

    handle = lgpio.gpiochip_open(args.chip)
    lgpio.gpio_claim_alert(handle, args.pin, lgpio.BOTH_EDGES, lgpio.SET_PULL_UP)
    last = [time.monotonic()]
    count = [0]

    def on_edge(_chip: int, _gpio: int, level: int, _tick: int) -> None:
        now = time.monotonic()
        name = {0: "BAS  (front descendant)", 1: "HAUT (front montant)"}.get(level, "watchdog")
        if level == 0:
            count[0] += 1
        print(f"  {name} après {(now - last[0]) * 1000:7.1f} ms   [descendants : {count[0]}]")
        last[0] = now

    cb = lgpio.callback(handle, args.pin, lgpio.BOTH_EDGES, on_edge)
    print(f"gpiochip{args.chip}, broche BCM {args.pin}, pull-up activé. Ctrl+C pour quitter.")
    try:
        while True:
            level = lgpio.gpio_read(handle, args.pin)
            print(f"niveau actuel : {level} ({'HAUT = contact ouvert' if level else 'BAS = contact fermé'})")
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        cb.cancel()
        lgpio.gpio_free(handle, args.pin)
        lgpio.gpiochip_close(handle)


if __name__ == "__main__":
    main()
