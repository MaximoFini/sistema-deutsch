"""URLconf para el dominio propio de la tienda (WHOLESALE_HOST): la tienda en la raíz, nada del panel."""

from django.urls import include, path

from apps.core.views import health

urlpatterns = [
    path("health/", health, name="health"),
    path("", include("apps.wholesale.urls")),
]

handler404 = "apps.wholesale.errors.page_not_found"
handler403 = "apps.wholesale.errors.permission_denied"
