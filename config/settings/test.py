import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault(
    "FIELD_ENCRYPTION_KEY", "rlGP-My9nsDbI22vOAtLwL-Q0OE10qVPl3PcsKv6xiA="
)  # clave solo para tests

from .base import *  # noqa: E402,F403

DEBUG = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
AXES_ENABLED = False
ALLOW_CHANNEL_WRITES = False
SENTRY_DSN = ""
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
TN_APP_ID = "1234"
TN_CLIENT_SECRET = "secreto-de-test"
TN_USER_AGENT = "Sistema Deutsch Tests (test@example.com)"
TN_WEBHOOKS_BASE_URL = ""
ML_APP_ID = "5555"
ML_CLIENT_SECRET = "ml-secreto-de-test"
ML_REDIRECT_URI = "https://example.com/ml-callback"
