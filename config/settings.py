"""Configuration Django — Vélo & IA Générative.

Schéma DB compatible PostgreSQL : SQLite en dev, aucun type spécifique SQLite
(§1). Voir ``CONFIG_NOTES.md`` pour les valeurs de jeu provisoires (§12).
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-insecure-key-change-me-in-production"
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "game",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# SQLite en dev ; passer à PostgreSQL via DATABASE_URL en prod (§1).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------- #
#  Paramètres de jeu (§8, §12) — PROVISOIRES, à recalibrer (§13 priorités 9). #
#  Surchargeables par variables d'environnement pour l'atelier.               #
# --------------------------------------------------------------------------- #
GAME = {
    # Calibration PÉDAGOGIQUE tours de roue -> joules (§8, §12).
    # Valeur arbitraire provisoire : ~1 tour ≈ 1,5 J. À ajuster avec de vrais
    # participants pour que le palier 100 % reste difficile mais atteignable.
    "ENERGY_PER_REVOLUTION_JOULES": float(
        os.environ.get("GAME_ENERGY_PER_REVOLUTION_JOULES", "1.5")
    ),
    # Seuil de tours pour valider le vélo au BIKE_CHECK (§6.2).
    "BIKE_CHECK_REVOLUTIONS": int(os.environ.get("GAME_BIKE_CHECK_REVOLUTIONS", "5")),
    # Durées des phases (secondes) — §6.5 / §6.6 / §6.7.
    "TEAM_SELECTION_SECONDS": int(os.environ.get("GAME_TEAM_SELECTION_SECONDS", "30")),
    "PREPARATION_SECONDS": int(os.environ.get("GAME_PREPARATION_SECONDS", "10")),
    "CYCLING_SECONDS": int(os.environ.get("GAME_CYCLING_SECONDS", "60")),
    # Comportement si le délai de sélection du coureur expire (§12) :
    # "random" (défaut recommandé) ou "host".
    "TEAM_SELECTION_ON_TIMEOUT": os.environ.get(
        "GAME_TEAM_SELECTION_ON_TIMEOUT", "random"
    ),
    # Alerte perte de signal vélo pendant une manche (§11).
    "SIGNAL_LOSS_TIMEOUT_SECONDS": float(
        os.environ.get("GAME_SIGNAL_LOSS_TIMEOUT_SECONDS", "8")
    ),
    # Barème de points par palier (§8, §12). Le palier 100 % est survalorisé.
    "POINTS_PER_TIER": {0: 0, 25: 25, 50: 50, 75: 75, 100: 150},
    # Capteur vélo : "simulated" (défaut, §7/§10) ou "gpio" (Raspberry Pi).
    "BIKE_SENSOR": os.environ.get("GAME_BIKE_SENSOR", "simulated"),
    # Pédalage automatique du capteur simulé (tr/min) — 0 = manuel (boutons UI).
    # >0 pratique pour dérouler une partie complète en test.
    "SIMULATED_AUTO_RPM": float(os.environ.get("GAME_SIMULATED_AUTO_RPM", "0")),
    # Provider LLM : "simulated" (défaut, §9/§10) ou "anthropic" (réel, §12).
    "LLM_PROVIDER": os.environ.get("GAME_LLM_PROVIDER", "simulated"),
    "LLM_MODEL": os.environ.get("GAME_LLM_MODEL", "claude-haiku-4-5-20251001"),
    # Pin GPIO du capteur vélo réel (BCM) — prototype, à confirmer (§12).
    "GPIO_PIN": int(os.environ.get("GAME_GPIO_PIN", "17")),
    "GPIO_DEBOUNCE_MS": int(os.environ.get("GAME_GPIO_DEBOUNCE_MS", "40")),
}
