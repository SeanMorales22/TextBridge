"""
Django settings for sms_project.

All secrets (Django secret key, SMS gateway credentials) are read from environment
variables. For local development they can be placed in a `.env` file in the
repository root (see `.env.example`). The `.env` file is git-ignored and must
never be committed.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# BASE_DIR = folder containing manage.py; REPO_DIR = repository root.
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

# Load variables from .env (repo root first, then next to manage.py).
# Real environment variables always take precedence over the file.
load_dotenv(REPO_DIR / ".env")
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# --- Core security -----------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        # Only acceptable for local development. Never used when DEBUG is off.
        SECRET_KEY = "dev-only-insecure-key-set-DJANGO_SECRET_KEY-in-your-env"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is not set. Copy .env.example to .env and fill it in."
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

# Cookie / header hardening (safe defaults for local development too).
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", default=True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", default=True)


# --- SMS provider: SMS Gateway for Android (https://sms-gate.app) ------------

# Cloud mode: https://api.sms-gate.app/3rdparty/v1
# Local mode: http://<phone-local-ip>:8080  (computer and phone on the same Wi-Fi)
SMSGATE_URL = os.getenv("SMSGATE_URL", "https://api.sms-gate.app/3rdparty/v1").strip().rstrip("/")
SMSGATE_USERNAME = os.getenv("SMSGATE_USERNAME", "").strip()
SMSGATE_PASSWORD = os.getenv("SMSGATE_PASSWORD", "").strip()
# Optional SIM slot (1-3) on dual-SIM phones; empty = phone's default SIM.
_sim = os.getenv("SMSGATE_SIM_NUMBER", "").strip()
SMSGATE_SIM_NUMBER = int(_sim) if _sim.isdigit() else None
# Seconds to wait for the gateway before treating it as a network error.
SMSGATE_TIMEOUT = int(os.getenv("SMSGATE_TIMEOUT", "15"))

# Region used to interpret local-format numbers such as 09171234567.
SMS_DEFAULT_REGION = os.getenv("SMS_DEFAULT_REGION", "PH").strip().upper()
# Maximum message length accepted by the form (about 10 SMS segments).
SMS_MAX_LENGTH = 1600


# --- Applications ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "sms_app",
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

ROOT_URLCONF = "sms_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "sms_app.context_processors.provider_status",
            ],
        },
    },
]

WSGI_APPLICATION = "sms_project.wsgi.application"


# --- Database ----------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# --- Password validation -----------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internationalization ----------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Manila")
USE_I18N = True
USE_TZ = True


# --- Static files ------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Messages framework -> CSS classes ---------------------------------------

from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {
    message_constants.DEBUG: "info",
    message_constants.INFO: "info",
    message_constants.SUCCESS: "success",
    message_constants.WARNING: "warning",
    message_constants.ERROR: "error",
}


# --- Logging (never logs credentials) ----------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "sms_app": {"handlers": ["console"], "level": os.getenv("SMS_LOG_LEVEL", "INFO")},
    },
}
