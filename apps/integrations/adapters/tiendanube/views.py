import json
import logging

from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.accounts.mixins import PanelPermissionRequiredMixin

from . import oauth
from .adapter import HMAC_HEADER, signature_is_valid

logger = logging.getLogger(__name__)
SESSION_STATE_KEY = "tn_oauth_state"
PRIVACY_KINDS = {"store_redact", "customers_redact", "customers_data_request"}


class ConnectView(PanelPermissionRequiredMixin, View):
    permission_required = "integrations.manage_connection"
    http_method_names = ["post"]

    def post(self, request):
        state = oauth.new_state()
        request.session[SESSION_STATE_KEY] = state
        try:
            return redirect(oauth.authorize_url(state))
        except oauth.OAuthError as exc:
            messages.error(request, str(exc))
            return redirect("integrations:status")


class CallbackView(PanelPermissionRequiredMixin, View):
    permission_required = "integrations.manage_connection"
    http_method_names = ["get"]

    def get(self, request):
        expected = request.session.pop(SESSION_STATE_KEY, None)
        if not expected or request.GET.get("state") != expected:
            messages.error(request, "La conexión con Tiendanube no es válida o venció. Probá de nuevo.")
            return redirect("integrations:status")
        code = request.GET.get("code")
        if not code:
            messages.error(request, "Tiendanube no devolvió el código de autorización.")
            return redirect("integrations:status")
        try:
            report = oauth.connect(code=code, actor=request.user, request=request)
        except oauth.OAuthError as exc:
            messages.error(request, f"No se pudo conectar Tiendanube: {exc}")
            return redirect("integrations:status")
        from .tasks import tn_import_catalog, tn_import_orders

        tn_import_catalog.defer()
        tn_import_orders.defer()
        msg = "Tiendanube conectado. Se están importando el catálogo y los pedidos de los últimos 30 días."
        if report["missing"]:
            messages.warning(request, f"Faltan permisos en la app: {', '.join(report['missing'])}.")
        if report["extra_risky"]:
            messages.warning(
                request, f"La app tiene más permisos de los necesarios: {', '.join(report['extra_risky'])}."
            )
        if report["webhooks"]["mode"] == "polling":
            msg += " Sin servidor público: los pedidos entran por consulta periódica."
        messages.success(request, msg)
        return redirect("integrations:status")


class ImportView(PanelPermissionRequiredMixin, View):
    permission_required = "integrations.retry_event"
    http_method_names = ["post"]

    def post(self, request, kind):
        from .tasks import tn_import_catalog, tn_import_orders

        if kind == "catalogo":
            tn_import_catalog.defer()
            messages.success(request, "Importación del catálogo de Tiendanube encolada.")
        elif kind == "pedidos":
            tn_import_orders.defer()
            messages.success(request, "Importación de pedidos de Tiendanube encolada.")
        else:
            return HttpResponseBadRequest()
        return redirect("integrations:status")


@method_decorator(csrf_exempt, name="dispatch")
class PrivacyWebhookView(View):
    """Webhooks obligatorios de privacidad (se configuran en el portal de Partners)."""

    panel_access = "webhook"
    http_method_names = ["post"]

    def post(self, request, kind):
        if kind not in PRIVACY_KINDS:
            return HttpResponseBadRequest()
        if not signature_is_valid(request.body, request.headers.get(HMAC_HEADER)):
            logger.warning("Webhook de privacidad TN con firma inválida")
            return HttpResponseForbidden()
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest()
        from .tasks import tn_privacy

        tn_privacy.defer(kind=kind, payload=payload)
        return HttpResponse(status=200)
