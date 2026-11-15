"""Consultas de las bandejas de Mercado Libre (M6): preguntas y conversaciones postventa. Solo lectura,
salvo `mark_read`, que marca leído en el sistema (no en ML)."""

from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db.models import Case, Count, F, IntegerField, Max, Q, QuerySet, Value, When
from django.utils import timezone

from apps.catalog.attributes import attributes_text
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
    size_chart_pending: bool = False  # hay guía pero el caché venció: se carga aparte (HTMX)
    previous: list[Question] = field(default_factory=list)

    @property
    def picture(self) -> str:
        pictures = ((self.listing.data or {}) if self.listing else {}).get("pictures") or []
        return pictures[0] if pictures else ""


def question_context(question: Question) -> QuestionContext:
    """Contexto de la ficha de una pregunta. Solo lee la base: la guía de talles vencida se pide a ML
    después, desde el fragmento `ml:question_size_chart`."""
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
            label = attributes_text(v.attributes) or "Única"  # talle primero, como en M5
            ctx.variations.append(
                VariationRow(label, v.sku, v.available_quantity, v.variant, stock.get(v.variant_id))
            )
        ctx.size_chart, ctx.size_chart_pending = health.cached_size_chart(listing)
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


RECENT_THREAD_DAYS = 60


def recent_threads_since(now=None):
    """Por defecto la lista muestra las conversaciones con actividad desde este momento (más las no leídas)."""
    return (now or timezone.now()) - timedelta(days=RECENT_THREAD_DAYS)


def threads_queryset(*, only_unread: bool = False, since=None):
    """Una fila por conversación (pack u orden) con sus agregados. Con no leídos primero.

    Con `since`, solo las que tuvieron actividad desde esa fecha o tienen mensajes sin leer (las no
    leídas se ven siempre). El último texto y el pedido NO se calculan acá: los agrega `thread_rows`
    solo para las filas de la página (auditoría M6, R1: antes se calculaban para todas).
    """
    qs = (
        Message.objects.exclude(thread_key="")
        .values("thread_key")
        .annotate(last_sent=Max("sent_at"), unread=Count("id", filter=UNREAD), total=Count("id"))
        .annotate(
            has_unread=Case(When(unread__gt=0, then=Value(0)), default=Value(1), output_field=IntegerField())
        )
        .order_by("has_unread", F("last_sent").desc(nulls_last=True), "thread_key")
    )
    if only_unread:
        qs = qs.filter(unread__gt=0)
    elif since is not None:
        qs = qs.filter(Q(last_sent__gte=since) | Q(unread__gt=0))
    return qs


def older_threads_exist(since) -> bool:
    """¿Hay conversaciones leídas sin actividad desde `since`? (para mostrar "Ver más viejas")."""
    return threads_queryset().filter(Q(last_sent__lt=since) | Q(last_sent__isnull=True), unread=0).exists()


def thread_rows(values) -> list[ThreadRow]:
    """Convierte filas de `threads_queryset` en ThreadRow con último mensaje y pedido.

    Tres consultas fijas para toda la página: último mensaje de cada conversación, último pedido
    vinculado y los pedidos (con cliente y canal).
    """
    values = list(values)
    keys = [v["thread_key"] for v in values]
    if not keys:
        return []
    newest = ("thread_key", F("sent_at").desc(nulls_last=True), "-id")
    last = {
        m["thread_key"]: m
        for m in Message.objects.filter(thread_key__in=keys)
        .order_by(*newest)
        .distinct("thread_key")
        .values("thread_key", "text", "direction")
    }
    doc_ids = dict(
        Message.objects.filter(thread_key__in=keys, document__isnull=False)
        .order_by(*newest)
        .distinct("thread_key")
        .values_list("thread_key", "document_id")
    )
    ids = set(doc_ids.values())
    docs = SalesDocument.objects.select_related("customer", "channel").in_bulk(ids) if ids else {}
    rows = []
    for v in values:
        message = last.get(v["thread_key"]) or {}
        rows.append(
            ThreadRow(
                thread_key=v["thread_key"],
                last_sent=v["last_sent"],
                unread=v["unread"],
                total=v["total"],
                last_text=message.get("text") or "",
                last_direction=message.get("direction") or "",
                document=docs.get(doc_ids.get(v["thread_key"])),
            )
        )
    return rows


def threads(*, only_unread: bool = False, since=None) -> list[ThreadRow]:
    return thread_rows(threads_queryset(only_unread=only_unread, since=since))


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
