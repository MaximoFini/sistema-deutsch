"""Control de acceso del panel.

Toda vista del panel debe usar una de estas dos clases:
- PanelPermissionRequiredMixin con `permission_required` explícito, o
- PanelLoginRequiredMixin (solo para vistas sin datos sensibles, p. ej. el inicio).

`tests/accounts/test_url_permissions.py` recorre todas las URLs y falla si alguna vista
del panel no declara una de las dos.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin


class PanelLoginRequiredMixin(LoginRequiredMixin):
    panel_access = "login"


class PanelPermissionRequiredMixin(LoginRequiredMixin, PermissionRequiredMixin):
    panel_access = "permission"
    # Usuario logueado sin permiso -> 403 (sin datos). Anónimo -> login.
