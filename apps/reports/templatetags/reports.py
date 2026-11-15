from decimal import Decimal

from django import template
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter
def money(value) -> str:
    """$ 1.234,56 (formato argentino). Vacío si no hay dato."""
    if value is None or value == "":
        return "—"
    return f"$ {floatformat(value, '2g')}"


@register.filter
def num(value) -> str:
    """Cantidad sin decimales de más: 3.000 → 3; 1.5 → 1,5."""
    if value is None or value == "":
        return "—"
    value = Decimal(value)
    return floatformat(value, "0g" if value == value.to_integral_value() else "1g")


@register.filter
def hours(value) -> str:
    if value is None:
        return "—"
    return f"{floatformat(value, '1g')} h"


@register.filter
def pct(value) -> str:
    if value is None:
        return "—"
    return f"{floatformat(value, '1g')} %"
