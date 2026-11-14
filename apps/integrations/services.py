"""Recepción y procesamiento de eventos de canales (idempotente, con reintentos)."""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.alerts import services as alerts
from apps.audit import services as audit

from . import errors, registry
from .models import Channel, ExternalRef, InboundEvent, SyncRun

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF_SECONDS = [60, 300, 1500, 7200, 21600]  # 1 min, 5 min, 25 min, 2 h, 6 h


class UnknownTopic(Exception):
    pass


def receive_event(
    channel_code: str, topic: str, dedupe_key: str, payload: dict, headers: dict
) -> tuple[InboundEvent, bool]:
    """Guarda el evento (si no estaba) y encola su procesamiento en la misma transacción.

    Devuelve (evento, creado). Un evento repetido no se vuelve a encolar.
    """
    from .tasks import process_event

    channel = Channel.objects.get(code=channel_code)
    with transaction.atomic():
        event, created = InboundEvent.objects.get_or_create(
            channel=channel,
            dedupe_key=dedupe_key[:255],
            defaults={"topic": topic, "payload": payload, "headers": headers},
        )
        if created:
            process_event.defer(event_id=event.pk)
    return event, created


def process(event_id: int) -> None:
    """Procesa un evento. Lo llama la tarea `process_event`."""
    from .tasks import process_event

    with transaction.atomic():
        event = (
            InboundEvent.objects.select_for_update(skip_locked=True)
            .select_related("channel")
            .filter(pk=event_id, status__in=[InboundEvent.Status.PENDING, InboundEvent.Status.PROCESSING])
            .first()
        )
        if event is None:
            return  # ya procesado, o lo tiene otro worker
        event.status = InboundEvent.Status.PROCESSING
        event.attempts += 1
        event.save(update_fields=["status", "attempts", "updated_at"])

    adapter = registry.get(event.channel.code)
    handler = adapter.handlers.get(event.topic) if adapter else None
    if handler is None:
        event.status = InboundEvent.Status.IGNORED
        event.last_error = f"Sin manejador para {event.channel.code}:{event.topic}"
        event.processed_at = timezone.now()
        event.save(update_fields=["status", "last_error", "processed_at", "updated_at"])
        return

    try:
        with transaction.atomic():
            handler(event)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falló el evento %s (intento %s)", event.pk, event.attempts)
        event.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        if event.attempts >= MAX_ATTEMPTS:
            event.status = InboundEvent.Status.FAILED
            event.save(update_fields=["status", "last_error", "updated_at"])
            alerts.emit(
                "integration.event_failed",
                title=f"Falló un evento de {event.channel.name} ({event.topic})",
                body=f"Se reintentó {event.attempts} veces. {errors.friendly(exc)}",
                link_url="/integraciones/",
                dedupe_key=f"event:{event.pk}",
            )
        else:
            event.status = InboundEvent.Status.PENDING
            event.save(update_fields=["status", "last_error", "updated_at"])
            wait = BACKOFF_SECONDS[event.attempts - 1]
            process_event.configure(schedule_in={"seconds": wait}).defer(event_id=event.pk)
        return

    event.status = InboundEvent.Status.DONE
    event.last_error = ""
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "last_error", "processed_at", "updated_at"])


def retry_failed(*, actor, request, event_ids=None) -> int:
    """Vuelve a encolar eventos fallidos (acción manual desde el panel, auditada)."""
    from .tasks import process_event

    qs = InboundEvent.objects.filter(status=InboundEvent.Status.FAILED)
    if event_ids:
        qs = qs.filter(pk__in=event_ids)
    count = 0
    for event in qs:
        with transaction.atomic():
            event.status = InboundEvent.Status.PENDING
            event.attempts = 0
            event.save(update_fields=["status", "attempts", "updated_at"])
            audit.record(actor, "integration.event_retried", event, request=request)
            process_event.defer(event_id=event.pk)
        count += 1
    return count


STUCK_AFTER = timedelta(minutes=15)


def _has_queued_job(event_id: int) -> bool:
    """¿Hay una tarea `process_event` esperando o corriendo para este evento?"""
    from procrastinate.contrib.django.models import ProcrastinateJob

    from .tasks import process_event

    return ProcrastinateJob.objects.filter(
        task_name=process_event.name, status__in=["todo", "doing"], args__event_id=event_id
    ).exists()


def requeue_stuck(now=None) -> int:
    """Reencola eventos trabados (sin cambios hace más de 15 min):
    - en "procesando": el worker se cayó a mitad de camino;
    - en "pendiente" sin ninguna tarea en la cola (se perdió la tarea).
    Un pendiente con reintento programado (backoff) tiene su tarea en la cola y no se toca."""
    from .tasks import process_event

    limit = (now or timezone.now()) - STUCK_AFTER
    stuck = InboundEvent.objects.filter(
        status__in=[InboundEvent.Status.PENDING, InboundEvent.Status.PROCESSING], updated_at__lt=limit
    ).only("pk", "status")
    count = 0
    for event in stuck:
        if event.status == InboundEvent.Status.PENDING and _has_queued_job(event.pk):
            continue
        with transaction.atomic():
            # Toca updated_at para no reencolarlo de nuevo en la próxima vuelta si sigue en curso.
            InboundEvent.objects.filter(pk=event.pk).update(updated_at=timezone.now())
            process_event.defer(event_id=event.pk)
        logger.warning("Evento %s trabado en %s: se reencoló", event.pk, event.status)
        count += 1
    return count


def link_external(channel_code: str, obj, external_id: str, extra: dict | None = None) -> ExternalRef:
    """Upsert idempotente del vínculo entidad ↔ ID externo."""
    from django.contrib.contenttypes.models import ContentType

    ref, _ = ExternalRef.objects.update_or_create(
        channel=Channel.objects.get(code=channel_code),
        content_type=ContentType.objects.get_for_model(obj),
        external_id=str(external_id),
        defaults={"object_id": obj.pk, "extra": extra or {}},
    )
    return ref


def find_by_external(channel_code: str, model, external_id: str):
    from django.contrib.contenttypes.models import ContentType

    ref = ExternalRef.objects.filter(
        channel__code=channel_code,
        content_type=ContentType.objects.get_for_model(model),
        external_id=str(external_id),
    ).first()
    return model.objects.filter(pk=ref.object_id).first() if ref else None


def run_reconciliation(channel_code: str, job: str = "reconcile", fn=None) -> SyncRun | None:
    """Corre una conciliación y la registra en SyncRun. `fn(since)` permite varias por canal
    (p. ej. pedidos cada 5 min y catálogo diario); sin `fn` usa `adapter.reconcile`."""
    adapter = registry.get(channel_code)
    if adapter is None:
        return None
    fn = fn or adapter.reconcile
    channel = Channel.objects.get(code=channel_code)
    last_ok = SyncRun.objects.filter(channel=channel, job=job, status=SyncRun.Status.OK).first()
    since = None
    if last_ok:
        since = last_ok.started_at - timezone.timedelta(minutes=10)  # margen de solapamiento
    run = SyncRun.objects.create(channel=channel, job=job)
    try:
        stats = fn(since) or {}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falló la conciliación de %s", channel_code)
        run.status = SyncRun.Status.ERROR
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
    else:
        run.status = SyncRun.Status.OK
        run.stats = stats
    run.finished_at = timezone.now()
    run.save()
    return run
