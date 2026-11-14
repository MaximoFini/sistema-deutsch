"""Settings base. Todo lo sensible o dependiente del entorno se lee de variables de entorno."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "axes",
    "django_htmx",
    "django_tailwind_cli",
    "procrastinate.contrib.django",
    # Apps propias (orden = dependencias)
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.alerts",
    "apps.catalog",
    "apps.inventory",
    "apps.pricing",
    "apps.customers",
    "apps.sales",
    "apps.integrations",
    "apps.conversations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
                "apps.core.context_processors.panel",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "apps.accounts.backends.PanelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"
PASSWORD_RESET_TIMEOUT = 2 * 60 * 60  # 2 h

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.5  # horas
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_USERNAME_FORM_FIELD = "username"

LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "media")

TAILWIND_CLI_SRC_CSS = "assets/css/source.css"
TAILWIND_CLI_DIST_CSS = "css/panel.css"

EMAIL_CONFIG = env.email_url("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Sistema Deutsch <no-reply@deutsch.com.ar>")

FIELD_ENCRYPTION_KEYS = env.list("FIELD_ENCRYPTION_KEY")
ALLOW_CHANNEL_WRITES = env.bool("ALLOW_CHANNEL_WRITES", default=False)

# ── Tiendanube (M1) ──
TN_APP_ID = env("TN_APP_ID", default="")
TN_CLIENT_SECRET = env("TN_CLIENT_SECRET", default="")
TN_USER_AGENT = env("TN_USER_AGENT", default="Sistema Deutsch")
TN_API_VERSION = env("TN_API_VERSION", default="2025-03")
TN_WEBHOOKS_BASE_URL = env("TN_WEBHOOKS_BASE_URL", default="")  # vacío en local: sin webhooks
TN_ORDERS_RECONCILE_MINUTES = env.int("TN_ORDERS_RECONCILE_MINUTES", default=5)
TN_INITIAL_ORDER_DAYS = env.int("TN_INITIAL_ORDER_DAYS", default=30)
# Canal que alimenta el stock del sistema hasta la integración directa con Contabilium (M8).
STOCK_FEED_CHANNEL = env("STOCK_FEED_CHANNEL", default="tiendanube")

# ── Mercado Libre (M2) ──
ML_APP_ID = env("ML_APP_ID", default="")
ML_CLIENT_SECRET = env("ML_CLIENT_SECRET", default="")
ML_REDIRECT_URI = env("ML_REDIRECT_URI", default="")
ML_SITE = env("ML_SITE", default="MLA")
ML_POLL_MINUTES = env.int("ML_POLL_MINUTES", default=5)
ML_LABEL_FORMAT = env("ML_LABEL_FORMAT", default="pdf")  # pdf | zpl2 (impresora a confirmar)
ML_INITIAL_ORDER_DAYS = env.int("ML_INITIAL_ORDER_DAYS", default=30)

# ── Catálogo maestro (M3) ──
CATALOG_SUSPICIOUS_PRICE_MIN = env.int("CATALOG_SUSPICIOUS_PRICE_MIN", default=1000)
CATALOG_PRICE_DIFF_PCT = env.int("CATALOG_PRICE_DIFF_PCT", default=30)
CONTABILIUM_WHOLESALE_INCLUDES_VAT = env.bool("CONTABILIUM_WHOLESALE_INCLUDES_VAT", default=False)
CONTABILIUM_MAX_FILE_MB = 5

SENTRY_DSN = env("SENTRY_DSN", default="")
ENVIRONMENT_NAME = env("ENVIRONMENT_NAME", default="local")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"mask_secrets": {"()": "apps.core.logging.MaskSecretsFilter"}},
    "formatters": {"simple": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple", "filters": ["mask_secrets"]},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "procrastinate": {"level": "WARNING"},
        "axes": {"level": "WARNING"},
    },
}

from apps.core.sentry import init as _init_sentry  # noqa: E402

_init_sentry(SENTRY_DSN, ENVIRONMENT_NAME)
