from django import template
from django.utils import timezone

from apps.conversations import labels

register = template.Library()


def _span(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours = round(minutes / 60)
    if hours < 48:
        return f"{hours} h"
    return f"{hours // 24} días"


@register.filter
def remaining(due) -> str:
    """Plazo restante legible: «vence en 5 h» o «venció hace 2 h»."""
    if not due:
        return "sin plazo informado"
    minutes = round((due - timezone.now()).total_seconds() / 60)
    if minutes >= 0:
        return f"vence en {_span(minutes)}"
    return f"venció hace {_span(-minutes)}"


@register.filter
def ago(moment) -> str:
    if not moment:
        return "—"
    minutes = max(round((timezone.now() - moment).total_seconds() / 60), 0)
    return f"hace {_span(minutes)}"


register.filter("claim_type", labels.claim_type)
register.filter("claim_stage", labels.claim_stage)
register.filter("claim_reason", labels.claim_reason)
register.filter("claim_status", labels.claim_status)
register.filter("return_status", labels.return_status)


@register.filter
def listing_status(code: str) -> str:
    return labels.listing_status(code)
