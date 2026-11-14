from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_datetime


def dec(value, default=None):
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return default


def dt(value) -> datetime | None:
    if not value:
        return None
    return parse_datetime(value) if isinstance(value, str) else value


def last_segment(resource: str) -> str:
    return str(resource or "").rstrip("/").split("/")[-1].split("?")[0]


def attr_value(attributes, attr_id: str) -> str:
    for a in attributes or []:
        if a.get("id") == attr_id:
            return (a.get("value_name") or "").strip()
    return ""


def error_body(exc) -> dict:
    """Cuerpo JSON de un error de la API (o {} si no es JSON)."""
    response = getattr(exc, "response", None)
    if response is None:
        return {}
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
