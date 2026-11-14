from django import template

from apps.audit.actions import label

register = template.Library()


@register.filter
def action_label(action: str) -> str:
    return label(action)
