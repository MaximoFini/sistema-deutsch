from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    "private": {  # comprobantes de la tienda mayorista: fuera de MEDIA_ROOT, sin URL pública
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": PRIVATE_MEDIA_ROOT, "base_url": None},  # noqa: F405
    },
}

# HSTS solo para el subdominio del panel: no se fuerza a todo deutsch.com.ar (la tienda TN y otros
# servicios del dominio no los controlamos), por eso no hay includeSubDomains ni preload.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
