"""Motor de alertas. Los módulos llaman a `emit`; nunca escriben en las tablas directamente."""

import logging

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from .models import Alert, AlertReceipt, AlertType

logger = logging.getLogger(__name__)


def emit(code: str, title: str, body: str = "", link_url: str = "", dedupe_key: str = "") -> Alert | None:
    """Emite una alerta. Si ya existe una con el mismo (tipo, dedupe_key), no hace nada.

    Devuelve la alerta nueva, o None si era duplicada o el tipo está inactivo/no existe.
    """
    try:
        alert_type = AlertType.objects.get(code=code)
    except AlertType.DoesNotExist:
        logger.error("Tipo de alerta inexistente: %s", code)
        return None
    if not alert_type.is_active:
        return None
    dedupe_key = dedupe_key or title
    try:
        with transaction.atomic():
            alert = Alert.objects.create(
                alert_type=alert_type,
                title=title[:200],
                body=body,
                link_url=link_url,
                dedupe_key=dedupe_key[:200],
            )
    except IntegrityError:
        return None  # mismo evento, ya alertado

    users = get_user_model().objects.filter(is_active=True, groups__in=alert_type.roles.all()).distinct()
    receipts = AlertReceipt.objects.bulk_create([AlertReceipt(alert=alert, user=u) for u in users])
    if alert_type.send_email:
        from .tasks import send_alert_email

        for receipt in receipts:
            receipt_id = receipt.pk
            transaction.on_commit(lambda rid=receipt_id: send_alert_email.defer(receipt_id=rid))
    return alert


def unread_count(user) -> int:
    return AlertReceipt.objects.filter(user=user, read_at__isnull=True).count()
