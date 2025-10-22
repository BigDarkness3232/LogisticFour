"""
Django settings for bodega project (dev-optimized).
"""

from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# -------------------------
# Paths
# -------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# -------------------------
# Core
# -------------------------
SECRET_KEY = os.environ.get("SECRET_KEY")
DEBUG = True

ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "192.168.1.9",
    ".ngrok.io",
    ".ngrok-free.app",
    ".ngrok-free.dev",
]

CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://192.168.1.9:8000",
    "https://*.ngrok.io",
    "https://*.ngrok-free.app",
    "https://*.ngrok-free.dev",
]

SITE_URL = "http://localhost:8000"

# -------------------------
# Apps
# -------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

# -------------------------
# Middleware
# -------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.TimingMiddleware",  # añade Server-Timing y log SLOW
]

ROOT_URLCONF = "bodega.urls"

# -------------------------
# Templates
# -------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "bodega.wsgi.application"

# -------------------------
# Database (Supabase)
# -------------------------
SUPABASE_DBNAME = os.environ.get("SUPABASE_DBNAME", "postgres")
SUPABASE_USER = os.environ.get("SUPABASE_USER")
SUPABASE_PASSWORD = os.environ.get("SUPABASE_PASSWORD")

# Pooler (uso normal de la app)
SUPABASE_HOST = os.environ.get("SUPABASE_HOST")            # ej: aws-1-us-east-2.pooler.supabase.com
SUPABASE_PORT = os.environ.get("SUPABASE_PORT", "6543")

# Directo (migraciones/admin)
SUPABASE_DIRECT_HOST = os.environ.get("SUPABASE_DIRECT_HOST")  # ej: aws-1-us-east-2.supabase.com
SUPABASE_DIRECT_PORT = os.environ.get("SUPABASE_DIRECT_PORT", "5432")

DB_COMMON_OPTS = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": SUPABASE_DBNAME,
    "USER": SUPABASE_USER,
    "PASSWORD": SUPABASE_PASSWORD,
    "OPTIONS": {
        "sslmode": "require",
        "connect_timeout": 5,
        # Mantén viva la conexión (evita handshakes por request)
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    },
    # Conexión persistente (reduce latencia por request)
    "CONN_MAX_AGE": 120,          # segundos; usa None si quieres sin límite
    "CONN_HEALTH_CHECKS": True,   # reabre si el pool cerró la conexión
}

DATABASES = {
    "default": {
        **DB_COMMON_OPTS,
        "HOST": SUPABASE_HOST,        # pooler
        "PORT": SUPABASE_PORT,
    },
    "direct": {
        **DB_COMMON_OPTS,
        "HOST": SUPABASE_DIRECT_HOST, # directo (migraciones puntuales)
        "PORT": SUPABASE_DIRECT_PORT,
    },
}

# -------------------------
# Passwords (más rápido en DEBUG para login)
# -------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

if DEBUG:
    # ⚠️ Solo dev: acelera el hash de password para que el login no tarde ~4s
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    # Alternativa si quieres seguir con PBKDF2 pero más rápido:
    # PBKDF2_PASSWORD_ITERATIONS = 6000

# -------------------------
# I18N / TZ
# -------------------------
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

# -------------------------
# Static
# -------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "Static"]  # crea la carpeta si no existe para evitar warnings

# -------------------------
# Defaults
# -------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# -------------------------
# Cache (local memory para poder usar fragment caching en dev)
# -------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "bodega-dev-cache",
    }
}

# -------------------------
# Logging
# -------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        # Sube a INFO durante 5 min si quieres ver todas las queries de una vista
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",      # cambia a "INFO" para diagnóstico de N+1
        },
        "perf": {
            "handlers": ["console"],
            "level": "WARNING",      # "SLOW GET /ruta 1234.5ms" desde TimingMiddleware
            "propagate": False,
        },
    },
}
