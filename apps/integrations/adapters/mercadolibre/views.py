from django import forms
from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.views import View

from apps.accounts.mixins import PanelPermissionRequiredMixin

from . import auth

SESSION_STATE_KEY = "ml_oauth_state"


class PasteReturnUrlForm(forms.Form):
    return_url = forms.CharField(label="URL a la que volvió el navegador", max_length=2000)


def _finish(request, code: str, state: str):
    expected = request.session.pop(SESSION_STATE_KEY, None)
    if not expected or state != expected:
        messages.error(
            request, "La conexión con Mercado Libre no es válida o venció. Tocá Conectar de nuevo."
        )
        return redirect("integrations:status")
    try:
        cred = auth.connect(code=code, actor=request.user, request=request)
    except auth.OAuthError as exc:
        messages.error(request, f"No se pudo conectar Mercado Libre. {exc}")
        return redirect("integrations:status")
    from .tasks import ml_import_listings, ml_import_orders

    ml_import_listings.defer()
    ml_import_orders.defer()
    messages.success(
        request,
        f"Mercado Libre conectado (vendedor {cred['user_id']}). Se están importando publicaciones y ventas de 30 días.",
    )
    return redirect("integrations:status")


class ConnectView(PanelPermissionRequiredMixin, View):
    permission_required = "integrations.manage_connection"
    http_method_names = ["post"]

    def post(self, request):
        state = auth.new_state()
        request.session[SESSION_STATE_KEY] = state
        try:
            return redirect(auth.authorize_url(state))
        except auth.OAuthError as exc:
            messages.error(request, str(exc))
            return redirect("integrations:status")


class CallbackView(PanelPermissionRequiredMixin, View):
    """Con servidor: ML vuelve acá directamente."""

    permission_required = "integrations.manage_connection"
    http_method_names = ["get"]

    def get(self, request):
        return _finish(request, request.GET.get("code", ""), request.GET.get("state", ""))


class PasteReturnUrlView(PanelPermissionRequiredMixin, View):
    """Sin servidor: el admin pega la URL https a la que volvió el navegador después de autorizar."""

    permission_required = "integrations.manage_connection"
    http_method_names = ["post"]

    def post(self, request):
        form = PasteReturnUrlForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Pegá la URL completa a la que volvió el navegador.")
            return redirect("integrations:status")
        try:
            code, state = auth.parse_return_url(form.cleaned_data["return_url"])
        except auth.OAuthError as exc:
            messages.error(request, str(exc))
            return redirect("integrations:status")
        return _finish(request, code, state)


class ImportView(PanelPermissionRequiredMixin, View):
    permission_required = "integrations.retry_event"
    http_method_names = ["post"]

    def post(self, request, kind):
        from .tasks import ml_import_listings, ml_import_orders

        if kind == "publicaciones":
            ml_import_listings.defer()
            messages.success(
                request,
                "Empezó la importación de publicaciones de Mercado Libre. Puede tardar unos minutos; los datos van apareciendo solos.",
            )
        elif kind == "ventas":
            ml_import_orders.defer()
            messages.success(
                request,
                "Empezó la importación de ventas de Mercado Libre. Puede tardar unos minutos; los datos van apareciendo solos.",
            )
        else:
            return HttpResponseBadRequest()
        return redirect("integrations:status")
