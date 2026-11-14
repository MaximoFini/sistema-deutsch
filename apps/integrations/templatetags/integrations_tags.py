from django import template

from apps.integrations import errors

register = template.Library()


@register.filter
def friendly_error(value) -> str:
    """Error técnico guardado → mensaje claro para el personal (ver integrations.errors)."""
    return errors.friendly(value)
