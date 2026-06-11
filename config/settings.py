"""
Django sozlamalari.
Ma'lumotlar bazasi — lokal SQLite fayl (data/db.sqlite3), loyiha yonida saqlanadi.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_int(name, default):
    """Butun son env o'zgaruvchisini xavfsiz o'qiydi (xato qiymatda default)."""
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_bool(name, default):
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


DEBUG = _env_bool("DEBUG", False)
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY .env faylida sozlanishi kerak.")
if not DEBUG and len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "Production uchun SECRET_KEY kamida 50 belgidan iborat bo'lishi kerak."
    )
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "quiz.apps.QuizConfig",
    "dashboard.apps.DashboardConfig",
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

# ---------------- Ma'lumotlar bazasi ----------------
# Agar .env'da DATABASE_URL bo'lsa — boshqariladigan PostgreSQL ishlatiladi
# (production uchun tavsiya: korruptsiya yo'q, parallel yozuvga chidamli, scale).
#   Misol: DATABASE_URL=postgres://user:parol@host:25060/dbname?sslmode=require
# Bo'lmasa — lokal SQLite (faqat ishlab chiqish/dev uchun).
#
# MUHIM (SQLite holatida): jonli baza faylini iCloud/Dropbox sinxronlanadigan
# papkada SAQLAMANG — sinxronizatsiya aktiv faylni buzadi. .env'da DB_PATH bilan
# sinxrondan tashqari joyga ko'chiring. Misol: DB_PATH=/Users/<siz>/quizbot-data/db.sqlite3
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=_env_bool("DB_SSL_REQUIRE", True),
        )
    }
else:
    # Baza fayli: data/sql/db.sqlite3 (papka avtomatik yaratiladi).
    # .env'dagi DB_PATH bilan boshqa joyga ko'chirish mumkin.
    DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "sql" / "db.sqlite3"))
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DB_PATH,
            "CONN_MAX_AGE": 60,
            "OPTIONS": {
                "timeout": 30,
                # Yozuv tranzaksiyalari boshidanoq yozuv qulfini oladi —
                # "database is locked" deadlock'larining oldini oladi.
                "transaction_mode": "IMMEDIATE",
                # WAL: o'quvchilar yozuvchini bloklamaydi (parallel ishlash
                # uchun shart). synchronous=NORMAL — WAL bilan xavfsiz va tez.
                "init_command": (
                    "PRAGMA journal_mode=WAL;"
                    "PRAGMA synchronous=NORMAL;"
                    "PRAGMA busy_timeout=30000;"
                    "PRAGMA cache_size=-32000;"
                    "PRAGMA temp_store=MEMORY;"
                ),
            },
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]

LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "data" / "static"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Yuklangan fayllar shu yerga vaqtincha saqlanadi (parse uchun)
MEDIA_ROOT = BASE_DIR / "data" / "uploads"
MEDIA_URL = "/media/"
MAX_UPLOAD_SIZE = _env_int("MAX_UPLOAD_SIZE", 20 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE + 1024 * 1024

# Bot sozlamalari (bot moduli ham shu settingsdan o'qiydi)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
QUESTIONS_PER_PART = _env_int("QUESTIONS_PER_PART", 50)

# Bot parallellik sozlamalari:
#   BOT_TASKS_CONCURRENCY — bir vaqtda qayta ishlanadigan update'lar soni
#   BOT_DB_THREADS — DB operatsiyalari uchun ishchi thread'lar soni
BOT_TASKS_CONCURRENCY = _env_int("BOT_TASKS_CONCURRENCY", 200)
BOT_DB_THREADS = _env_int("BOT_DB_THREADS", 32)

# Reverse-proxy (nginx) orqasida ishlayotganda True — X-Forwarded-* headerlar
# ishonchli hisoblanadi. Proxy'siz to'g'ridan-to'g'ri ochilganda False qiling,
# aks holda mijoz IP'ni soxtalashtirib login-lockout'ni aylanib o'tishi mumkin.
TRUST_PROXY = _env_bool("TRUST_PROXY", True)

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Dashboard login sahifasi (login_required uchun)
LOGIN_URL = "/dashboard/login/"

# Login throttling uchun lokal cache (tashqi xizmatsiz, tez)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dashboard-cache",
    }
}

if not DEBUG:
    SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = _env_int("SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_REFERRER_POLICY = "same-origin"
    if TRUST_PROXY:
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HTTPS domen orqasida POST formalar 403 bermasligi uchun
# (masalan: CSRF_TRUSTED_ORIGINS=https://panel.example.uz)
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

# ---------------- Logging ----------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} [{name}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {"level": LOG_LEVEL},
        "django.utils.autoreload": {"level": "WARNING"},
        "aiogram": {"level": LOG_LEVEL},
    },
}
