#!/usr/bin/env python
"""Point d'entrée des commandes Django."""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Django introuvable. Lancez les commandes via `uv run manage.py ...`."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
