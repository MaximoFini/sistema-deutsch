import json
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView

from apps.accounts.mixins import PanelPermissionRequiredMixin
from apps.core.logging import mask_mapping

from . import guard, registry, services
from .models import Channel, ChannelCredential, ChannelWriteSwitch, InboundEvent, SyncRun

logger = logging.getLogger(__name__)

STORED_HEADERS = ("content-type", "user-agent", "x-linkedstore-hmac-sha256", "x-request-id")


@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(View):
    """Recibe webhooks/notificaciones: guarda, encola y responde de inmediato."""

    panel_access = "webhook"  # autenticado por firma del canal, no por login
    http_method_names = ["post"]

    def post(self, request, channel_code):
        adapter = registry.get(channel_code)
        if adapter is None or not Channel.objects.filter(code=channel_code, is_active=True).exists():
            return HttpResponseNotFound()
        if not adapter.verify_webhook(request):
            logger.warning("Webhook de %s con firma inválida", channel_code)
            return HttpResponseForbidden()
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("JSON inválido")
        headers = {k.lower(): v for k, v in request.headers.items() if k.lower() in STORED_HEADERS}
        services.receive_event(
            channel_code,
            topic=adapter.topic(payload, headers),
            dedupe_key=adapter.dedupe_key(payload, headers),
            payload=payload,
            headers=mask_mapping(headers),
        )
        return HttpResponse(status=200)


class IntegrationStatusView(PanelPermissionRequiredMixin, TemplateView):
    permission_required = "integrations.view_status"
    template_name = "integrations/status.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        since = timezone.now() - timedelta(hours=24)
        cards = []
        channels = Channel.objects.exclude(code=Channel.MANUAL).order_by("name")
        for channel in channels:
            counts = InboundEvent.objects.filter(channel=channel).aggregate(
                pending=Count("id", filter=Q(status__in=["pending", "processing"])),
                failed=Count("id", filter=Q(status="failed")),
                done_24h=Count("id", filter=Q(status="done", processed_at__gte=since)),
            )
            last_ok = SyncRun.objects.filter(channel=channel, status=SyncRun.Status.OK).first()
            stale = bool(
                channel.code in (Channel.TIENDANUBE, Channel.MERCADOLIBRE)
                and registry.get(channel.code)
                and (last_ok is None or timezone.now() - last_ok.started_at > timedelta(hours=1))
            )
            cred = ChannelCredential.objects.filter(channel=channel).only("expires_at").first()
            cards.append(
                {
                    "channel": channel,
                    "has_adapter": registry.get(channel.code) is not None,
                    "counts": counts,
                    "last_ok": last_ok,
                    "stale": stale,
                    "errors": InboundEvent.objects.filter(channel=channel, status="failed")
                    .exclude(last_error="")
                    .order_by("-received_at")[:10],
                    "switches": {s.kind: s for s in ChannelWriteSwitch.objects.filter(channel=channel)},
                    "credential_expires": cred.expires_at if cred else None,
                    "has_credential": cred is not None,
                }
            )
        ctx["cards"] = cards
        ctx["tn"] = self._tiendanube_info()
        ctx["ml"] = self._mercadolibre_info()
        ctx["writes_allowed_by_server"] = settings.ALLOW_CHANNEL_WRITES
        return ctx

    def _mercadolibre_info(self):
        from django.utils.dateparse import parse_datetime

        from . import credentials

        info = {
            "configured": bool(settings.ML_APP_ID and settings.ML_REDIRECT_URI),
            "connected": False,
            "label_format": settings.ML_LABEL_FORMAT,
            "every": settings.ML_POLL_MINUTES,
        }
        try:
            data = credentials.get(Channel.MERCADOLIBRE)
        except credentials.CredentialsMissing:
            data = None
        if data:
            info.update(
                connected=True,
                user_id=data.get("user_id"),
                expires_at=parse_datetime(data.get("expires_at") or ""),
            )
        return info

    def _tiendanube_info(self):
        from . import credentials

        info = {"configured": bool(settings.TN_APP_ID), "connected": False}
        try:
            data = credentials.get(Channel.TIENDANUBE)
        except credentials.CredentialsMissing:
            data = None
        if data:
            info.update(
                connected=True,
                store_id=data.get("store_id"),
                scope=data.get("scope", ""),
                mode="webhooks" if settings.TN_WEBHOOKS_BASE_URL else "polling",
                every=settings.TN_ORDERS_RECONCILE_MINUTES,
            )
        return info


class RetryFailedEventsView(PanelPermissionRequiredMixin, View):
    permission_required = "integrations.retry_event"
    http_method_names = ["post"]

    def post(self, request, channel_code):
        ids = list(
            InboundEvent.objects.filter(channel__code=channel_code, status="failed").values_list(
                "pk", flat=True
            )
        )
        count = services.retry_failed(actor=request.user, request=request, event_ids=ids)
        messages.success(request, f"{count} evento(s) reencolados.")
        return redirect("integrations:status")


class ToggleWriteSwitchView(PanelPermissionRequiredMixin, View):
    permission_required = "integrations.toggle_write_switch"
    http_method_names = ["post"]

    def post(self, request, channel_code, kind):
        channel = get_object_or_404(Channel, code=channel_code)
        if kind not in ChannelWriteSwitch.Kind.values:
            return HttpResponseBadRequest()
        enable = request.POST.get("enabled") == "1"
        if enable and not settings.ALLOW_CHANNEL_WRITES:
            messages.error(
                request,
                "El servidor tiene la escritura a canales deshabilitada (ALLOW_CHANNEL_WRITES). "
                "No se puede encender el interruptor.",
            )
            return redirect("integrations:status")
        guard.set_switch(actor=request.user, request=request, channel=channel, kind=kind, enabled=enable)
        messages.success(request, f"Escritura de {kind} a {channel} {'encendida' if enable else 'apagada'}.")
        return redirect("integrations:status")
