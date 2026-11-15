"""Avisos periódicos de Mercado Libre (M6): preguntas sin responder hace mucho y reclamos por vencer."""

from datetime import timedelta

from django.conf import settings
from django.db.models import CharField, Exists, OuterRef, Q, Value
from django.db.models.functions import Cast, Concat
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.alerts import services as alerts
from apps.alerts.models import Alert

from . import inbox, labels
from .models import Claim, Question


def _hours_text(delta) -> str:
    minutes = max(round(delta.total_seconds() / 60), 0)
    if minutes < 60:
        return f"{minutes} min"
    return f"{round(minutes / 60)} h"


QUESTION_SUMMARY_OVER = 10  # más avisos nuevos que esto en una corrida → uno solo de resumen
CLAIM_ALERT = "ml.claim_due"
QUESTION_ALERT = "ml.question_unanswered_long"


def questions_to_alert(now=None):
    """Preguntas que pasaron el umbral sin respuesta, hechas en los últimos días y todavía sin avisar."""
    now = now or timezone.now()
    oldest = now - timedelta(days=settings.ML_QUESTION_ALERT_MAX_AGE_DAYS)
    return Question.objects.filter(
        status__in=inbox.OPEN_STATUSES,
        asked_at__lt=inbox.warning_limit(now),
        asked_at__gte=oldest,
        alerted_at__isnull=True,
    )


def check_questions(now=None) -> int:
    """Avisa por las preguntas que pasaron el umbral sin respuesta. Devuelve cuántos avisos mandó.

    - Solo preguntas de los últimos `ML_QUESTION_ALERT_MAX_AGE_DAYS` días: al conectar ML se importan
      todas las viejas y no tiene sentido avisar por cada una (auditoría M6, A2).
    - Si en una corrida hay más de 10, se manda un solo aviso de resumen en lugar de uno por pregunta.
    - Cada pregunta avisada (sola o en el resumen) queda marcada con `alerted_at` y la consulta la
      saltea en las corridas siguientes: no se repite ni se vuelve a recorrer (A3).
    """
    now = now or timezone.now()
    pending = list(questions_to_alert(now).select_related("listing").order_by("asked_at", "pk"))
    if not pending:
        return 0
    count = 0
    if len(pending) > QUESTION_SUMMARY_OVER:
        oldest = now - pending[0].asked_at
        if alerts.emit(
            QUESTION_ALERT,
            title=(
                f"Hay {len(pending)} preguntas sin responder hace más de "
                f"{settings.ML_QUESTION_WARNING_HOURS} h"
            ),
            body=f"La más vieja espera hace {_hours_text(oldest)}. Respondelas desde Preguntas, en orden.",
            link_url="/ml/preguntas/",
            dedupe_key=f"question-long-summary:{now.isoformat()}:{pending[0].pk}",
        ):
            count = 1
    else:
        for q in pending:
            product = q.listing.title if q.listing else q.item_external_id
            if alerts.emit(
                QUESTION_ALERT,
                title=f"Pregunta sin responder hace {_hours_text(now - q.asked_at)}: «{q.text[:80]}»",
                body=f"Publicación: {product or 'sin dato'}.",
                link_url=f"/ml/preguntas/{q.pk}/",
                dedupe_key=f"question-long:{q.pk}",
            ):
                count += 1
    Question.objects.filter(pk__in=[q.pk for q in pending]).update(alerted_at=now)
    return count


def _claim_key(hours: int):
    return Concat(Value("claim-due:"), Cast(OuterRef("pk"), CharField()), Value(f":{hours}h"))


def check_claims_due(now=None) -> int:
    """Avisa cuando un reclamo que requiere acción entra en cada umbral (24 h y 4 h por defecto).

    Si cuando se detecta ya pasó más de un umbral (p. ej. entra con 3 h), avisa solo el más chico:
    no tiene sentido mandar dos avisos juntos. La consulta ya saltea los reclamos que tienen el aviso
    de su umbral actual (auditoría M6, A3): las corridas siguientes no recorren nada.
    """
    now = now or timezone.now()
    thresholds = sorted(settings.ML_CLAIM_WARNING_HOURS)
    if not thresholds:
        return 0
    # Umbral que le toca a cada reclamo: el más chico que ya alcanzó. Tramos (ahora, ahora+h1], (…, h2]…
    pending = Q()
    lower = now
    for hours in thresholds:
        upper = now + timedelta(hours=hours)
        alerted = Exists(Alert.objects.filter(alert_type__code=CLAIM_ALERT, dedupe_key=_claim_key(hours)))
        pending |= Q(due_date__gt=lower, due_date__lte=upper) & ~alerted
        lower = upper
    count = 0
    claims = Claim.objects.filter(
        pending, status="opened", action_required=True, due_date__isnull=False
    ).select_related("document")
    for claim in claims:
        remaining = claim.due_date - now
        hours = min(h for h in thresholds if remaining <= timedelta(hours=h))
        reference = (claim.document.channel_reference if claim.document else "") or claim.order_external_id
        local = timezone.localtime(claim.due_date)
        if alerts.emit(
            CLAIM_ALERT,
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
