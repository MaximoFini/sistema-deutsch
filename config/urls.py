from django.contrib import admin
from django.urls import include, path

from apps.core.views import health
from apps.integrations.urls import webhook_urlpatterns

admin.site.site_header = "Sistema Deutsch · soporte técnico"

urlpatterns = [
    path("health/", health, name="health"),
    path("soporte/", admin.site.urls),  # Django admin: solo superusuarios (Kei)
    path("hooks/", include((webhook_urlpatterns, "hooks"))),
    path("cuenta/", include("apps.accounts.urls")),
    path("auditoria/", include("apps.audit.urls")),
    path("avisos/", include("apps.alerts.urls")),
    path("integraciones/", include("apps.integrations.urls")),
    path("", include("apps.core.urls")),
]
