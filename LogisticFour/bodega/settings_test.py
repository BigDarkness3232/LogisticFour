"""Settings de test: heredan de bodega.settings y sobrescriben la BD para usar SQLite en memoria.

Este archivo facilita ejecutar la suite de tests localmente sin depender de Postgres/Supabase.
"""
from .settings import *  # noqa: F401,F403

# Usar SQLite en memoria para tests rápidos y aislados
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Usar un hasher rápido para acelerar creación de usuarios en tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Email en memoria (no envía nada fuera)
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Reduce logging o ajustes adicionales aquí si los necesitas
