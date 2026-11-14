"""Enmascarado de secretos en logs (US-9: las credenciales no aparecen en logs)."""

import logging
import re

SENSITIVE_KEYS = (
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
    "client_secret",
    "api_key",
    "apikey",
    "cbu",
    "card",
    "cookie",
)
_KEYS = "|".join(SENSITIVE_KEYS)
# clave=valor, "clave": "valor", 'clave': 'valor', Authorization: Bearer xxx
_PATTERNS = [
    # Primero "Bearer <token>", así el patrón clave=valor no se queda solo con la palabra "Bearer".
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9\-._~+/]+=*)"),
    re.compile(rf"""(?i)(["']?(?:{_KEYS})["']?\s*[:=]\s*["']?)([^"'\s,}}&]+)"""),
]
MASK = "***"


def mask_text(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + MASK, text)
    return text


def mask_mapping(data):
    """Copia de un dict/list con los valores sensibles enmascarados (recursivo)."""
    if isinstance(data, dict):
        return {
            k: (MASK if isinstance(k, str) and k.lower() in SENSITIVE_KEYS else mask_mapping(v))
            for k, v in data.items()
        }
    if isinstance(data, list | tuple):
        return [mask_mapping(v) for v in data]
    return data


class MaskSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        masked = mask_text(message)
        if masked != message:
            record.msg = masked
            record.args = None
        return True
