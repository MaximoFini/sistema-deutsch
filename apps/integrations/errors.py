"""Traduce errores técnicos de los canales a mensajes claros para el personal del local.

El detalle técnico (excepción, URL, código) queda en `last_error`, `SyncRun.error` y los logs, para
Kei Software. En alertas y pantallas se muestra `friendly(...)`.
"""

import re

import httpx

AUTH = "Venció o se revocó la autorización del canal: hay que reconectarlo desde Integraciones."
RATE_LIMIT = "El canal limitó las consultas por un rato. El sistema reintenta solo."
UNAVAILABLE = "El canal no responde en este momento. El sistema reintenta solo."
NOT_FOUND = "El canal ya no tiene ese dato (puede que lo hayan borrado allá)."
NO_HANDLER = "Es un aviso del canal que el sistema no usa. No hace falta hacer nada."
GENERIC = "Hubo un error inesperado. Si se repite, avisale a Kei Software (el detalle quedó registrado)."

_STATUS_RE = re.compile(r"respondi[oó] (\d{3})")
_AUTH_NAMES = ("TokenRevoked", "CredentialsMissing")
_NETWORK_NAMES = ("Timeout", "ConnectError", "TransportError", "NetworkError", "ReadError", "RemoteProtocol")


def _from_status(status: int | None) -> str | None:
    if status is None:
        return None
    if status in (401, 403):
        return AUTH
    if status == 429:
        return RATE_LIMIT
    if status == 404:
        return NOT_FOUND
    if status >= 500:
        return UNAVAILABLE
    return None


def friendly(error) -> str:
    """Acepta una excepción o el texto guardado de un error (p. ej. `InboundEvent.last_error`)."""
    if error is None or error == "":
        return ""
    if isinstance(error, BaseException):
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        if (msg := _from_status(status)) is not None:
            return msg
        if isinstance(error, httpx.TransportError) or isinstance(error.__cause__, httpx.TransportError):
            return UNAVAILABLE
        text = f"{type(error).__name__}: {error}"
    else:
        text = str(error)
    if text.startswith("Sin manejador para"):
        return NO_HANDLER
    if any(name in text for name in _AUTH_NAMES):
        return AUTH
    match = _STATUS_RE.search(text)
    if match:
        if (msg := _from_status(int(match.group(1)))) is not None:
            return msg
    elif text.startswith("ChannelHTTPError"):
        return UNAVAILABLE  # sin código de respuesta: falló la conexión (ya se reintentó)
    if any(name.lower() in text.lower() for name in _NETWORK_NAMES) or "timed out" in text:
        return UNAVAILABLE
    return GENERIC
