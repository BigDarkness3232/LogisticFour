from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()  # Cargar las variables de entorno desde el archivo .env

BASE_DIR = Path(__file__).resolve().parent.parent

# ==========================
# ⚙️ CONFIGURACIÓN GENERAL
# ==========================
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-^)nb02+@4w5s$i7-vu^alov)=^ky58(sg+xuc(-q&z%*gt0z&)')  # Deberías definirla en tu archivo .env
DEBUG = True

SITE_ID = 1
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "192.168.1.9", ".ngrok.io", ".ngrok-free.app", ".ngrok-free.dev"]


CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://192.168.1.9:8000",
    "https://*.ngrok.io",
    "https://*.ngrok-free.app",
    "https://*.ngrok-free.dev",
]

SITE_URL = "http://127.0.0.1:8000"  # usado en los correos

# ==========================
# 📦 APLICACIONES
# ==========================
INSTALLED_APPS = [
    'whitenoise.runserver_nostatic',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'django.contrib.sites',
    'widget_tweaks',
]

SITE_ID = 1

# ==========================
# 🌐 MIDDLEWARE
# ==========================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'bodega.urls'

# ==========================
# 🧱 TEMPLATES
# ==========================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],  # <-- importante
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'bodega.wsgi.application'

# ==========================
# 🗄️ BASE DE DATOS
# ==========================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ==========================
# 🔐 VALIDACIÓN DE CONTRASEÑAS
# ==========================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ==========================
# 🌎 LOCALIZACIÓN
# ==========================
LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

# ==========================
# 🖼️ ARCHIVOS ESTÁTICOS
# ==========================
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "Static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==========================
# 🔐 LOGIN / LOGOUT
# ==========================
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# ==========================
# 📧 CONFIGURACIÓN DE EMAIL (Gmail App Password)
# ==========================
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
EMAIL_TIMEOUT = 20

# Obtener credenciales desde el archivo .env para mayor seguridad
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'capstonelogisticfour@gmail.com')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', 'dukb qtba ujnd gbzz')  # Clave de aplicación de Gmail en el archivo .env

DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
SERVER_EMAIL = EMAIL_HOST_USER  # para errores del sistema
ADMINS = [("MAKLF", "capstonelogisticfour@gmail.com")]

TICKETS_NOTIFY_EMAILS = [
    "antonio.amc46@gmail.com",
    "an.martinezc@duocuc.cl",
]

# ==========================
# 📝 LOGGING
# ==========================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'DEBUG',  # Puedes usar 'INFO' o 'ERROR' dependiendo de lo que quieras capturar
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs/django.log',  # Guarda los logs en la carpeta 'logs' dentro del proyecto
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'DEBUG',  # Puedes usar 'INFO' o 'ERROR' dependiendo de lo que quieras capturar
            'propagate': True,
        },
        'core': {  # Asegúrate de que 'core' sea el nombre de tu aplicación
            'handlers': ['file'],
            'level': 'DEBUG',  # Aquí registramos eventos de la aplicación específica
            'propagate': True,
        },
    },
}

