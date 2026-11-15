"""Avisos periódicos de Mercado Libre (M6): preguntas sin responder hace mucho y reclamos por vencer."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.alerts import services as alerts

from . import inbox, labels
from .models import Claim, Question


def _hours_text(delta) -> str:
    minutes = max(round(delta.total_seconds() / 60), 0)
    if minutes < 60:
        return f"{minutes} min"
    return f"{round(minutes / 60)} h"


def check_questions(now=None) -> int:
    """Una alerta por pregunta que pasó el umbral sin respuesta (dedupe por pregunta)."""
    now = now or timezone.now()
    count = 0
    old = Question.objects.filter(
        status__in=inbox.OPEN_STATUSES, asked_at__lt=inbox.warning_limit(now)
    ).select_related("listing")
    for q in old:
        product = q.listing.title if q.listing else q.item_external_id
        if alerts.emit(
            "ml.question_unanswered_long",
            title=f"Pregunta sin responder hace {_hours_text(now - q.asked_at)}: «{q.text[:80]}»",
            body=f"Publicación: {product or 'sin dato'}.",
            link_url=f"/ml/preguntas/{q.pk}/",
            dedupe_key=f"question-long:{q.pk}",
        ):
            count += 1
    return count


def check_claims_due(now=None) -> int:
    """Avisa cuando un reclamo que requiere acción entra en cada umbral (24 h y 4 h por defecto).

    Si cuando se detecta ya pasó más de un umbral (p. ej. entra con 3 h), avisa solo el más chico:
    no tiene sentido mandar dos avisos juntos.
    """
    now = now or timezone.now()
    thresholds = sorted(settings.ML_CLAIM_WARNING_HOURS)
    if not thresholds:
        return 0
    count = 0
    claims = Claim.objects.filter(
        status="opened",
        action_required=True,
        due_date__isnull=False,
        due_date__gt=now,
        due_date__lte=now + timedelta(hours=max(thresholds)),
    ).select_related("document")
    for claim in claims:
        remaining = claim.due_date - now
        hours = min(h for h in thresholds if remaining <= timedelta(hours=h))
        reference = (claim.document.channel_reference if claim.document else "") or claim.order_external_id
        local = timezone.localtime(claim.due_date)
        if alerts.emit(
            "ml.claim_due",
            title=f"Reclamo de la venta {reference or claim.external_id}: vence en {_hours_text(remaining)}",
            body=(
                f"Motivo: {labels.claim_reason(claim.reason) or 'sin detalle'}. "
                f"Hay que responderlo en Mercado Libre antes del {local:%d/%m %H:%M}."
            ),
            link_url=f"/ml/reclamos/{claim.pk}/",
            dedupe_key=f"claim-due:{claim.pk}:{hours}h",
        ):
            count += 1
    return count


@app.periodic(cron="*/5 * * * *")
@app.task(queue="default", queueing_lock="ml_operation_watch")
def ml_operation_watch(timestamp: int):
    check_questions()
    check_claims_due()
