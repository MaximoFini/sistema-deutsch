"""Control de acceso del panel.

Toda vista del panel debe usar una de estas dos clases:
- PanelPermissionRequiredMixin con `permission_required` explícito, o
- PanelLoginRequiredMixin (solo para vistas sin datos sensibles, p. ej. el inicio).

`tests/accounts/test_url_permissions.py` recorre todas las URLs y falla si alguna vista
del panel no declara una de las dos.

Los clientes de la tienda mayorista (usuarios con `CustomerAccount`) nunca entran al panel: estas
dos clases los mandan a la tienda (M8).
"""

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import redirect


def is_store_customer(user) -> bool:
    """True si el usuario es un cliente de la tienda mayorista (no un usuario interno)."""
    if not getattr(user, "is_authenticated", False):
        return False
    try:
        return user.customer_account is not None
    except ObjectDoesNotExist:  # sin cuenta de cliente: usuario interno
        return False


class RejectStoreCustomersMixin:
    def dispatch(self, request, *args, **kwargs):
        if is_store_customer(request.user):
            return redirect("store:home")
        return super().dispatch(request, *args, **kwargs)


class PanelLoginRequiredMixin(RejectStoreCustomersMixin, LoginRequiredMixin):
    panel_access = "login"


class PanelPermissionRequiredMixin(RejectStoreCustomersMixin, LoginRequiredMixin, PermissionRequiredMixin):
    panel_access = "permission"
    # Usuario logueado sin permiso -> 403 (sin datos). Anónimo -> login.
