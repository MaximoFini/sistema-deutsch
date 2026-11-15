"""Consultas de las bandejas de Mercado Libre (M6): preguntas y conversaciones postventa. Solo lectura,
salvo `mark_read`, que marca leído en el sistema (no en ML)."""

from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db.models import Case, Count, F, IntegerField, Max, OuterRef, Q, QuerySet, Subquery, Value, When
from django.utils import timezone

from apps.catalog.models import Listing
from apps.integrations.models import ChannelCredential
from apps.inventory.models import StockLevel
from apps.sales.models import SalesDocument

from . import health
from .models import Message, Question

CHANNEL = "mercadolibre"
PREVIOUS_LIMIT = 10
# Sin responder = sin respuesta todavía, incluidas las que fallaron al enviar (siguen esperando respuesta).
OPEN_STATUSES = [Question.Status.UNANSWERED, Question.Status.ERROR]


def ml_connected() -> bool:
    """ML desconectado = no hay credencial guardada (se borra al revocarse el token)."""
    return ChannelCredential.objects.filter(channel__code=CHANNEL).exists()


def warning_limit(now=None):
    """Preguntas hechas antes de este momento se muestran en rojo y generan aviso."""
    return (now or timezone.now()) - timedelta(hours=settings.ML_QUESTION_WARNING_HOURS)


# ── Preguntas ────────────────────────────────────────────────────────────


def unanswered_questions() -> QuerySet[Question]:
    return (
        Question.objects.filter(status__in=OPEN_STATUSES)
        .select_related("listing")
        .order_by(F("asked_at").asc(nulls_last=True), "pk")
    )


def answered_questions(q: str = "", item: str = "") -> QuerySet[Question]:
    qs = (
        Question.objects.filter(status=Question.Status.ANSWERED)
        .select_related("listing", "answered_by")
        .order_by(F("answered_at").desc(nulls_last=True), "-pk")
    )
    q, item = (q or "").strip(), (item or "").strip()
    if q:
        qs = qs.filter(Q(text__icontains=q) | Q(answer_text__icontains=q) | Q(listing__title__icontains=q))
    if item:
        qs = qs.filter(Q(item_external_id__icontains=item) | Q(listing__title__icontains=item))
    return qs


@dataclass
class VariationRow:
    label: str
    sku: str
    ml_stock: int | None
    variant: object | None
    catalog_stock: object | None  # disponible en el depósito por defecto (None = sin dato)


@dataclass
class QuestionContext:
    listing: Listing | None
    variations: list[VariationRow] = field(default_factory=list)
    size_chart: dict | None = None
    previous: list[Question] = field(default_factory=list)

    @property
    def picture(self) -> str:
        pictures = ((self.listing.data or {}) if self.listing else {}).get("pictures") or []
        return pictures[0] if pictures else ""


def question_context(question: Question, client=None) -> QuestionContext:
    listing = question.listing
    ctx = QuestionContext(listing=listing)
    if listing is not None:
        variations = list(listing.variations.select_related("variant").order_by("pk"))
        variant_ids = [v.variant_id for v in variations if v.variant_id]
        stock = {
            s.variant_id: s.available
            for s in StockLevel.objects.filter(variant_id__in=variant_ids, warehouse__is_default=True)
        }
        for v in variations:
            label = " / ".join(str(x) for x in (v.attributes or {}).values() if x) or "Única"
            ctx.variations.append(
                VariationRow(label, v.sku, v.available_quantity, v.variant, stock.get(v.variant_id))
            )
        ctx.size_chart = health.size_chart(listing, client=client)
    prev = Question.objects.filter(status=Question.Status.ANSWERED).exclude(pk=question.pk)
    if listing is not None:
        prev = prev.filter(listing=listing)
    elif question.item_external_id:
        prev = prev.filter(item_external_id=question.item_external_id)
    else:
        prev = prev.none()
    ctx.previous = list(prev.order_by(F("answered_at").desc(nulls_last=True), "-pk")[:PREVIOUS_LIMIT])
    return ctx


def next_unanswered(after: Question | None = None) -> Question | None:
    qs = unanswered_questions()
    if after is not None:
        qs = qs.exclude(pk=after.pk)
    return qs.first()


# ── Conversaciones ───────────────────────────────────────────────────────


@dataclass
class ThreadRow:
    thread_key: str
    last_sent: object
    unread: int
    total: int
    last_text: str
    last_direction: str
    document: SalesDocument | None = None

    @property
    def last_from_buyer(self) -> bool:
        return self.last_direction == Message.Direction.IN


UNREAD = Q(direction=Message.Direction.IN, read_at__isnull=True)


def threads_queryset(*, only_unread: bool = False):
    """Una fila por conversación (pack u orden) con sus agregados. Con no leídos primero."""
    last = Message.objects.filter(thread_key=OuterRef("thread_key")).order_by(
        F("sent_at").desc(nulls_last=True), "-id"
    )
    with_doc = last.filter(document__isnull=False)
    qs = (
        Message.objects.exclude(thread_key="")
        .values("thread_key")
        .annotate(
            last_sent=Max("sent_at"),
            unread=Count("id", filter=UNREAD),
            total=Count("id"),
            last_text=Subquery(last.values("text")[:1]),
            last_direction=Subquery(last.values("direction")[:1]),
            document_id=Subquery(with_doc.values("document_id")[:1]),
        )
        .annotate(
            has_unread=Case(When(unread__gt=0, then=Value(0)), default=Value(1), output_field=IntegerField())
        )
        .order_by("has_unread", F("last_sent").desc(nulls_last=True), "thread_key")
    )
    if only_unread:
        qs = qs.filter(unread__gt=0)
    return qs


def thread_rows(values) -> list[ThreadRow]:
    """Convierte filas de `threads_queryset` en ThreadRow con su pedido (una sola consulta)."""
    values = list(values)
    ids = {v["document_id"] for v in values if v["document_id"]}
    docs = SalesDocument.objects.select_related("customer", "channel").in_bulk(ids) if ids else {}
    return [
        ThreadRow(
            thread_key=v["thread_key"],
            last_sent=v["last_sent"],
            unread=v["unread"],
            total=v["total"],
            last_text=v["last_text"] or "",
            last_direction=v["last_direction"] or "",
            document=docs.get(v["document_id"]),
        )
        for v in values
    ]


def threads(*, only_unread: bool = False) -> list[ThreadRow]:
    return thread_rows(threads_queryset(only_unread=only_unread))


def thread(thread_key: str) -> tuple[SalesDocument | None, list[Message]]:
    msgs = list(
        Message.objects.filter(thread_key=thread_key).select_related("sent_by").order_by("sent_at", "id")
    )
    document_id = next((m.document_id for m in reversed(msgs) if m.document_id), None)
    document = (
        SalesDocument.objects.select_related("customer", "channel").filter(pk=document_id).first()
        if document_id
        else None
    )
    return document, msgs


def mark_read(thread_key: str, user=None) -> int:
    """Marca leídos en el sistema los mensajes del comprador. En ML siguen sin leer (a propósito)."""
    return Message.objects.filter(UNREAD, thread_key=thread_key).update(read_at=timezone.now())


def unread_threads_count() -> int:
    return Message.objects.filter(UNREAD).exclude(thread_key="").values("thread_key").distinct().count()
