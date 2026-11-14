"""Conexión con Tiendanube: OAuth (authorization code), registro de webhooks y desconexión."""

import logging
import secrets

import httpx
from django.conf import settings
from django.db import transaction

from apps.alerts import services as alerts
from apps.audit import services as audit
from apps.integrations import credentials
from apps.integrations.models import Channel, ChannelCredential

from .adapter import WEBHOOK_EVENTS
from .client import CHANNEL, TiendanubeClient

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.tiendanube.com/apps/{app_id}/authorize?state={state}"
TOKEN_URL = "https://www.tiendanube.com/apps/authorize/token"
EXPECTED_SCOPES = {"read_products", "write_orders", "read_customers", "write_fulfillment_orders"}
# write implica read: estos cubren a los esperados
IMPLIED = {"write_products": "read_products", "write_customers": "read_customers"}
EXTRA_RISKY_SCOPES = {"write_products"}


class OAuthError(Exception):
    pass


NOT_CONFIGURED = "La app de Tiendanube todavía no está configurada en el sistema. Avisale a Kei Software."
CODE_REJECTED = "La autorización venció o ya se usó: tocá Conectar de nuevo."
UNAVAILABLE = "Tiendanube no responde. Probá en unos minutos."


def new_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(state: str) -> str:
    if not settings.TN_APP_ID:
        logger.warning("Falta TN_APP_ID en la configuración")
        raise OAuthError(NOT_CONFIGURED)
    return AUTHORIZE_URL.format(app_id=settings.TN_APP_ID, state=state)


def exchange_code(code: str, transport: httpx.BaseTransport | None = None) -> dict:
    payload = {
        "client_id": settings.TN_APP_ID,
        "client_secret": settings.TN_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
    }
    try:
        with httpx.Client(timeout=20, transport=transport) as client:
            response = client.post(TOKEN_URL, json=payload, headers={"User-Agent": settings.TN_USER_AGENT})
    except httpx.TransportError as exc:
        logger.warning("No se pudo contactar a Tiendanube para el token: %s", exc)
        raise OAuthError(UNAVAILABLE) from exc
    if response.status_code >= 500:
        logger.warning("Tiendanube respondió %s al pedir el token", response.status_code)
        raise OAuthError(UNAVAILABLE)
    if response.status_code != 200:
        logger.warning("Tiendanube rechazó el código (%s)", response.status_code)
        raise OAuthError(CODE_REJECTED)
    data = response.json()
    if "access_token" not in data:
        logger.warning(
            "Tiendanube no devolvió access_token: %s", data.get("error_description") or data.get("error")
        )
        raise OAuthError(CODE_REJECTED)
    return data


def scope_report(scope: str) -> dict:
    granted = {s.strip() for s in (scope or "").split(",") if s.strip()}
    effective = granted | {IMPLIED[s] for s in granted if s in IMPLIED}
    return {
        "granted": sorted(granted),
        "missing": sorted(EXPECTED_SCOPES - effective),
        "extra_risky": sorted(granted & EXTRA_RISKY_SCOPES),
    }


def register_webhooks(client: TiendanubeClient) -> dict:
    """Registra los webhooks que falten (idempotente). Sin URL pública, no hace nada."""
    base = settings.TN_WEBHOOKS_BASE_URL.rstrip("/")
    if not base:
        return {"mode": "polling", "created": []}
    url = f"{base}/hooks/{CHANNEL}/"
    existing = {(w.get("event"), w.get("url")) for w in client.get_all("/webhooks")}
    created = []
    for event in WEBHOOK_EVENTS:
        if (event, url) not in existing:
            client.post("/webhooks", json={"event": event, "url": url})
            created.append(event)
    return {"mode": "webhooks", "created": created}


def connect(*, code: str, actor, request=None, transport=None) -> dict:
    data = exchange_code(code, transport=transport)
    report = scope_report(data.get("scope", ""))
    with transaction.atomic():
        credentials.save(
            CHANNEL,
            {
                "access_token": data["access_token"],
                "store_id": str(data["user_id"]),
                "scope": data.get("scope", ""),
            },
        )
        Channel.objects.filter(code=CHANNEL).update(is_active=True)
        audit.record(
            actor,
            "integration.connected",
            Channel.objects.get(code=CHANNEL),
            request=request,
            after={"store_id": str(data["user_id"]), **report},
        )
    client = TiendanubeClient(data["access_token"], data["user_id"], transport=transport)
    report["webhooks"] = register_webhooks(client)
    return report


def disconnect(reason: str) -> None:
    with transaction.atomic():
        ChannelCredential.objects.filter(channel__code=CHANNEL).delete()
        audit.record(
            None, "integration.disconnected", Channel.objects.get(code=CHANNEL), after={"reason": reason}
        )
    alerts.emit(
        "integration.disconnected",
        title="Tiendanube se desconectó del sistema",
        body=f"{reason} Los pedidos de Tiendanube dejan de entrar hasta reconectar desde Integraciones.",
        link_url="/integraciones/",
        dedupe_key=f"tn-disconnected:{reason}",
    )
