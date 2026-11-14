import json
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder

from .actions import ACTIONS
from .models import AuditLog


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def record(actor, action: str, obj=None, before=None, after=None, request=None, **metadata) -> AuditLog:
    """Registra una acción. Llamar dentro de la misma transacción que el cambio.

    `actor` puede ser un usuario o None (= acción del sistema).
    """
    if action not in ACTIONS:
        raise ValueError(f"Acción de auditoría no catalogada: {action}")
    actor_user = actor if getattr(actor, "is_authenticated", False) else None
    log = AuditLog(
        actor=actor_user,
        actor_label=str(actor_user) if actor_user else "sistema",
        action=action,
        before=_jsonable(before),
        after=_jsonable(after),
        metadata=_jsonable(metadata) or {},
    )
    if obj is not None:
        log.content_type = ContentType.objects.get_for_model(obj)
        log.object_id = str(obj.pk)
        log.object_repr = str(obj)[:300]
    if request is not None:
        log.ip = request.META.get("REMOTE_ADDR")
    log.save()
    return log
