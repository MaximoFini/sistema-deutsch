from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_datetime


def text(value, lang: str = "es") -> str:
    """Los textos de TN vienen como {"es": "...", "pt": "..."} o como string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return value.get(lang) or next((v for v in value.values() if v), "") or ""
    return str(value)


def dec(value, default=None) -> Decimal | None:
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


def kg_to_g(value) -> int | None:
    d = dec(value)
    return int(d * 1000) if d is not None else None


def cm_to_mm(value) -> int | None:
    d = dec(value)
    return int(d * 10) if d is not None else None


def normalize(value: str) -> str:
    import unicodedata

    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return value.lower().replace("-", " ").replace("_", " ")
