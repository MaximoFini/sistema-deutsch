from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core.views import health
from apps.integrations.adapters.tiendanube.urls import privacy_urlpatterns as tn_privacy_urlpatterns
from apps.integrations.urls import webhook_urlpatterns
from apps.wholesale.panel_urls import customer_urlpatterns, order_urlpatterns, store_admin_urlpatterns

admin.site.site_header = "Sistema Deutsch · soporte técnico"

urlpatterns = [
    path("health/", health, name="health"),
    path("soporte/", admin.site.urls),  # Django admin: solo superusuarios (Kei)
    path("hooks/tiendanube/privacy/", include((tn_privacy_urlpatterns, "tn_privacy"))),
    path("hooks/", include((webhook_urlpatterns, "hooks"))),
    path("cuenta/", include("apps.accounts.urls")),
    path("auditoria/", include("apps.audit.urls")),
    path("avisos/", include("apps.alerts.urls")),
    path("pedidos/", include("apps.sales.urls")),
    path("catalogo/", include("apps.catalog.urls")),
    path("ml/", include("apps.conversations.urls")),
    path("reportes/", include("apps.reports.urls")),
    path("integraciones/tiendanube/", include("apps.integrations.adapters.tiendanube.urls")),
    path("integraciones/mercadolibre/", include("apps.integrations.adapters.mercadolibre.urls")),
    path("integraciones/", include("apps.integrations.urls")),
    path("clientes-mayoristas/", include((customer_urlpatterns, "wholesale_customers"))),
    path("tienda-mayorista/", include((store_admin_urlpatterns, "store_admin"))),
    path("pedidos-mayoristas/", include((order_urlpatterns, "wholesale_orders"))),
    path(settings.WHOLESALE_PATH, include("apps.wholesale.urls")),  # la tienda (M8)
    path("", include("apps.core.urls")),
]

# Errores con la marca de la tienda cuando corresponde (el panel sigue con sus plantillas).
handler404 = "apps.wholesale.errors.page_not_found"
handler403 = "apps.wholesale.errors.permission_denied"
