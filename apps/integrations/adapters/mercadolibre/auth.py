"""OAuth de Mercado Libre y renovación atómica del token.

El access token dura ~6 h y el refresh token es de UN solo uso: cada renovación devuelve uno
nuevo y el anterior deja de servir. Por eso la renovación se hace con lock sobre la fila de la
credencial: dos workers nunca renuevan a la vez.
"""

import logging
import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.alerts import services as alerts
from apps.audit import services as audit
from apps.integrations import credentials
from apps.integrations.models import Channel, ChannelCredential

logger = logging.getLogger(__name__)

CHANNEL = "mercadolibre"
AUTH_URL = "https://auth.mercadolibre.com.ar/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
REFRESH_MARGIN = timedelta(minutes=30)


class OAuthError(Exception):
    pass


class TokenRevoked(Exception):
    """El refresh token venció o fue revocado: hay que volver a autorizar."""


class TokenRefreshError(Exception):
    """Error transitorio al renovar (red, 5xx): se puede reintentar."""


def new_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(state: str) -> str:
    if not (settings.ML_APP_ID and settings.ML_REDIRECT_URI):
        raise OAuthError("Faltan ML_APP_ID o ML_REDIRECT_URI en la configuración.")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.ML_APP_ID,
            "redirect_uri": settings.ML_REDIRECT_URI,
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def parse_return_url(url: str) -> tuple[str, str]:
    """Extrae (code, state) de la URL a la que volvió el navegador (modo sin servidor)."""
    query = parse_qs(urlparse(url.strip()).query)
    code = (query.get("code") or [""])[0]
    state = (query.get("state") or [""])[0]
    if not code:
        raise OAuthError("La URL pegada no tiene el código de autorización (parámetro code).")
    return code, state


def _token_request(data: dict) -> httpx.Response:
    payload = {"client_id": settings.ML_APP_ID, "client_secret": settings.ML_CLIENT_SECRET, **data}
    with httpx.Client(timeout=20) as client:
        return client.post(TOKEN_URL, data=payload, headers={"Accept": "application/json"})


def _to_credential(data: dict) -> dict:
    expires_at = timezone.now() + timedelta(seconds=int(data.get("expires_in", 21600)))
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": expires_at.isoformat(),
        "user_id": str(data["user_id"]),
        "scope": data.get("scope", ""),
    }


def exchange_code(code: str) -> dict:
    try:
        response = _token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.ML_REDIRECT_URI}
        )
    except httpx.TransportError as exc:
        raise OAuthError(f"No se pudo contactar a Mercado Libre: {exc}") from exc
    if response.status_code != 200:
        detail = (
            response.json().get("message", "")
            if response.headers.get("content-type", "").startswith("application/json")
            else ""
        )
        raise OAuthError(f"Mercado Libre rechazó el código ({response.status_code}). {detail}".strip())
    return response.json()


def connect(*, code: str, actor, request=None) -> dict:
    data = exchange_code(code)
    cred = _to_credential(data)
    with transaction.atomic():
        credentials.save(CHANNEL, cred, expires_at=cred["expires_at"])
        Channel.objects.filter(code=CHANNEL).update(is_active=True)
        audit.record(
            actor,
            "integration.connected",
            Channel.objects.get(code=CHANNEL),
            request=request,
            after={"user_id": cred["user_id"], "scope": cred["scope"]},
        )
    return cred


def _remaining(data: dict) -> timedelta:
    from django.utils.dateparse import parse_datetime

    expires = parse_datetime(data.get("expires_at") or "")
    return (expires - timezone.now()) if expires else timedelta(0)


def get_credentials() -> dict:
    return credentials.get(CHANNEL)


def get_access_token() -> str:
    data = get_credentials()
    if _remaining(data) > REFRESH_MARGIN:
        return data["access_token"]
    return _refresh(stale_token=data["access_token"], margin=REFRESH_MARGIN)


def force_refresh(stale_token: str) -> str:
    """Renueva aunque no esté por vencer (la API dijo 401). Si otro worker ya renovó, usa ese."""
    return _refresh(stale_token=stale_token, margin=None)


def _refresh(stale_token: str, margin: timedelta | None) -> str:
    revoked = False
    with transaction.atomic():
        row = ChannelCredential.objects.select_for_update().get(channel__code=CHANNEL)
        data = credentials.decrypt(row.data_encrypted)
        if data["access_token"] != stale_token:
            return data["access_token"]  # otro worker renovó mientras esperábamos el lock
        if margin is not None and _remaining(data) > margin:
            return data["access_token"]
        try:
            response = _token_request({"grant_type": "refresh_token", "refresh_token": data["refresh_token"]})
        except httpx.TransportError as exc:
            raise TokenRefreshError(str(exc)) from exc
        if response.status_code == 200:
            new = _to_credential(response.json())
            row.data_encrypted = credentials.encrypt(new)
            row.expires_at = new["expires_at"]
            row.save(update_fields=["data_encrypted", "expires_at", "updated_at"])
            return new["access_token"]
        body = response.json() if "json" in response.headers.get("content-type", "") else {}
        if response.status_code in (400, 401) and body.get("error") in (
            "invalid_grant",
            "invalid_token",
            "unauthorized_client",
        ):
            revoked = True
        else:
            raise TokenRefreshError(f"Mercado Libre respondió {response.status_code} al renovar el token.")
    if revoked:
        disconnect("Mercado Libre rechazó la renovación del token (vencido o revocado).")
        raise TokenRevoked("Hay que volver a autorizar Mercado Libre.")
    raise TokenRefreshError("Renovación sin resultado")  # pragma: no cover


def refresh_if_needed(min_remaining: timedelta = timedelta(minutes=60)) -> bool:
    """Para la tarea periódica: renueva si faltan menos de `min_remaining`. Devuelve si renovó."""
    data = get_credentials()
    if _remaining(data) > min_remaining:
        return False
    _refresh(stale_token=data["access_token"], margin=min_remaining)
    return True


def disconnect(reason: str) -> None:
    with transaction.atomic():
        ChannelCredential.objects.filter(channel__code=CHANNEL).delete()
        audit.record(
            None, "integration.disconnected", Channel.objects.get(code=CHANNEL), after={"reason": reason}
        )
    alerts.emit(
        "integration.disconnected",
        title="Mercado Libre se desconectó del sistema",
        body=(
            f"{reason} Las ventas, preguntas y mensajes de Mercado Libre dejan de entrar. "
            "Hay que reconectar desde Integraciones: la autorización la tiene que hacer el dueño de la cuenta."
        ),
        link_url="/integraciones/",
        dedupe_key=f"ml-disconnected:{timezone.now():%Y%m%d}",
    )
