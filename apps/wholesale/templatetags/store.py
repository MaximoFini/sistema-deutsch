from django import template

from apps.catalog.attributes import attributes_text
from apps.wholesale.catalog import format_money

register = template.Library()


@register.filter
def money(value) -> str:
    """$ 1.234,56 (formato argentino)."""
    if value is None or value == "":
        return "—"
    return format_money(value)


@register.filter
def attrs(variant) -> str:
    """«M / Negro» (talle primero, después color)."""
    return attributes_text(getattr(variant, "attributes", None))
