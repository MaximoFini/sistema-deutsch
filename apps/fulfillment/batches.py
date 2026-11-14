"""Tandas de preparación (US-1, US-4): crear desde pedidos Nuevos, lista de picking, sacar pedidos y
cierre automático.

Ningún cambio de estado se hace acá por fuera de `apps.sales.states.change_status`.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Exists, F, OuterRef, Prefetch, QuerySet
from django.utils import timezone

from apps.audit import services as audit
from apps.sales import states
from apps.sales.models import SalesDocument, SalesLine, Shipment
from apps.sales.views import orders_queryset

from .models import PickBatch, PickBatchOrder

CHANNELS = ("tiendanube", "mercadolibre", "manual")
# Todos los métodos menos Full (lo despacha Mercado Libre).
PREPARABLE_METHODS = [m for m in Shipment.Method.values if m != Shipment.Method.ME_FULL]
# Estados con los que un pedido sale de la tanda ("resuelto").
RESOLVED = {states.DISPATCHED, states.READY_FOR_PICKUP, states.DELIVERED, states.CANCELLED}
BATCH_SEQUENCE = "fulfillment_batch_number_seq"


class BatchError(Exception):
    """Error que se le muestra tal cual a Depósito."""


@dataclass
class Excluded:
    document: SalesDocument
    reason: str

    @property
    def ref(self) -> str:
        return order_ref(self.document)


@dataclass
class PickRow:
    sku: str
    description: str
    total: Decimal = Decimal(0)
    destinations: list[tuple[str, Decimal]] = field(default_factory=list)
    in_catalog: bool = True

    @property
    def destinations_text(self) -> str:
        return ", ".join(f"{ref} ({qty_text(q)})" for ref, q in self.destinations)


@dataclass
class PickingList:
    rows: list[PickRow]
    unknown: list[PickRow]  # líneas sin variante del catálogo
    orders: list[SalesDocument]  # ordenados por fecha límite y antigüedad
    units: Decimal

    @property
    def is_empty(self) -> bool:
        return not self.rows and not self.unknown


def qty_text(value) -> str:
    """Cantidad sin ceros de más: 3.000 → "3", 1.500 → "1.5"."""
    if value is None:
        return ""
    return f"{Decimal(value).normalize():f}"


def order_ref(doc: SalesDocument) -> str:
    return doc.channel_reference or str(doc)


def active_items() -> QuerySet[PickBatchOrder]:
    return PickBatchOrder.objects.filter(removed_at__isnull=True, resolved_at__isnull=True)


def preparable_orders() -> QuerySet[SalesDocument]:
    """Pedidos Nuevos de TN, ML (sin Full) y manuales que no están en una tanda activa."""
    full = Shipment.objects.filter(document=OuterRef("pk"), method=Shipment.Method.ME_FULL)
    in_batch = active_items().filter(document=OuterRef("pk"))
    return (
        orders_queryset()
        .filter(status=states.NEW, channel__code__in=CHANNELS)
        .exclude(Exists(full))
        .exclude(Exists(in_batch))
        .order_by(F("deadline").asc(nulls_last=True), "issued_at", "id")
    )


def _next_number() -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s)", [BATCH_SEQUENCE])
        return cursor.fetchone()[0]


def _exclusion_reason(doc: SalesDocument, active_batch: dict[int, int], full_ids: set[int]) -> str | None:
    if doc.doc_type != SalesDocument.DocType.ORDER or doc.channel.code not in CHANNELS:
        return "no es un pedido que se prepare desde acá"
    if doc.pk in full_ids:
        return "es Full: lo despacha Mercado Libre"
    if doc.pk in active_batch:
        return f"ya está en la tanda {active_batch[doc.pk]}"
    if doc.status != states.NEW:
        return f"ya no está Nuevo (ahora: «{states.label(doc.status)}»)"
    return None


def _transition_reason(doc: SalesDocument) -> str:
    """Motivo claro cuando `change_status` no deja pasar a En preparación (sin el texto técnico)."""
    doc.refresh_from_db(fields=["status"])
    if doc.status != states.NEW:
        return f"ya no está Nuevo (ahora: «{states.label(doc.status)}»)"
    return "no se pudo pasar a En preparación"


def create_batch(document_ids, *, user, request=None) -> tuple[PickBatch | None, list[Excluded]]:
    """Arma una tanda con los pedidos elegidos que sigan Nuevos y los pasa a En preparación.

    Devuelve (tanda, excluidos). Si no queda ningún pedido válido, la tanda no se crea (None).
    """
    ids = sorted({int(i) for i in document_ids})
    if not ids:
        raise BatchError("Marcá al menos un pedido para armar la tanda.")
    limit = settings.FULFILLMENT_MAX_BATCH
    if len(ids) > limit:
        raise BatchError(f"Una tanda puede tener hasta {limit} pedidos. Marcaste {len(ids)}.")
    if not user.has_perm("sales.change_order_status"):
        raise BatchError("No tenés permiso para cambiar el estado de los pedidos.")

    excluded: list[Excluded] = []
    with transaction.atomic():
        # Bloqueo en orden de pk: dos personas armando tandas a la vez no se cruzan (sin deadlocks).
        docs = list(
            SalesDocument.objects.select_for_update(of=("self",))
            .select_related("channel", "customer")
            .filter(pk__in=ids)
            .order_by("pk")
        )
        active_batch = dict(
            active_items().filter(document__in=docs).values_list("document_id", "batch__number")
        )
        full_ids = set(
            Shipment.objects.filter(document__in=docs, method=Shipment.Method.ME_FULL).values_list(
                "document_id", flat=True
            )
        )
        valid = []
        for doc in docs:
            reason = _exclusion_reason(doc, active_batch, full_ids)
            if reason:
                excluded.append(Excluded(doc, reason))
            else:
                valid.append(doc)
        if not valid:
            return None, excluded

        batch = PickBatch.objects.create(number=_next_number(), created_by=user)
        added = []
        for doc in valid:
            try:
                states.change_status(
                    doc, states.PREPARING, user=user, reason=f"Tanda {batch.number}", request=request
                )
            except states.TransitionNotAllowed:
                excluded.append(Excluded(doc, _transition_reason(doc)))
                continue
            PickBatchOrder.objects.create(batch=batch, document=doc)
            added.append(doc)
        if not added:
            batch.delete()
            return None, excluded
        audit.record(
            user,
            "fulfillment.batch_created",
            batch,
            request=request,
            pedidos=[order_ref(d) for d in added],
            quedaron_afuera=[f"{e.ref}: {e.reason}" for e in excluded],
        )
    return batch, excluded


def batch_orders(batch: PickBatch, *, include_cancelled: bool = False) -> list[SalesDocument]:
    """Pedidos de la tanda que no se sacaron, por fecha límite y antigüedad. Con líneas y envíos."""
    doc_ids = batch.items.filter(removed_at__isnull=True).values("document_id")
    qs = (
        orders_queryset()
        .filter(pk__in=doc_ids)
        .prefetch_related(
            Prefetch("lines", queryset=SalesLine.objects.select_related("variant__product").order_by("id")),
            "shipments",
        )
        .order_by(F("deadline").asc(nulls_last=True), "issued_at", "id")
    )
    if not include_cancelled:
        qs = qs.exclude(status=states.CANCELLED)
    return list(qs)


ATTRIBUTE_ORDER = ("talle", "color")  # Postgres (jsonb) no conserva el orden de las claves


def variant_description(variant) -> str:
    """Producto, talle y color: "Buzo Canguro (M / Negro)"."""
    items = sorted(
        (variant.attributes or {}).items(),
        key=lambda kv: (
            ATTRIBUTE_ORDER.index(kv[0].lower())
            if kv[0].lower() in ATTRIBUTE_ORDER
            else len(ATTRIBUTE_ORDER),
            kv[0].lower(),
        ),
    )
    attrs = " / ".join(str(v) for _, v in items if v)
    return variant.product.name + (f" ({attrs})" if attrs else "")


def picking_list(batch: PickBatch, orders: list[SalesDocument] | None = None) -> PickingList:
    """Lista de picking: una fila por variante (SKU), con total y a qué pedidos va cada unidad.

    Toma los pedidos que siguen en la tanda (no sacados ni cancelados). Las líneas sin variante del
    catálogo van aparte, agrupadas por el SKU que trajo el canal.
    """
    if orders is None:
        orders = batch_orders(batch)
    rows: dict = OrderedDict()
    unknown: dict = OrderedDict()
    units = Decimal(0)
    for doc in orders:
        ref = order_ref(doc)
        for line in doc.lines.all():
            qty = Decimal(line.quantity)
            if line.variant_id:
                key, target = line.variant_id, rows
                if key not in target:
                    target[key] = PickRow(line.variant.sku, variant_description(line.variant))
            else:
                key, target = (line.sku_snapshot or line.description_snapshot).strip().upper(), unknown
                if key not in target:
                    target[key] = PickRow(
                        line.sku_snapshot or "—", line.description_snapshot, in_catalog=False
                    )
            row = target[key]
            row.total += qty
            units += qty
            if row.destinations and row.destinations[-1][0] == ref:
                row.destinations[-1] = (ref, row.destinations[-1][1] + qty)
            else:
                row.destinations.append((ref, qty))
    return PickingList(
        rows=sorted(rows.values(), key=lambda r: r.sku),
        unknown=sorted(unknown.values(), key=lambda r: r.sku),
        orders=orders,
        units=units,
    )


def remove_order(batch: PickBatch, document: SalesDocument, *, user, request=None) -> bool:
    """Saca un pedido de la tanda. Si estaba En preparación, vuelve a Nuevo.

    Devuelve True si el pedido volvió a Nuevo.
    """
    back_to_new = False
    with transaction.atomic():
        item = active_items().select_for_update().filter(batch=batch, document=document).first()
        if item is None:
            raise BatchError("Ese pedido ya no está en la tanda.")
        item.removed_at = timezone.now()
        item.removed_by = user
        item.save(update_fields=["removed_at", "removed_by", "updated_at"])
        document.refresh_from_db(fields=["status"])
        if document.status == states.PREPARING:
            try:
                states.change_status(
                    document,
                    states.NEW,
                    user=user,
                    reason=f"Sacado de la tanda {batch.number}",
                    request=request,
                )
            except states.TransitionNotAllowed as exc:
                raise BatchError(str(exc)) from exc
            back_to_new = True
        audit.record(
            user,
            "fulfillment.order_removed",
            batch,
            request=request,
            pedido=order_ref(document),
            volvio_a_nuevo=back_to_new,
        )
        close_if_done(batch, user=user, request=request)
    return back_to_new


def on_status_changed(document: SalesDocument, old: str, new: str) -> None:
    """Un pedido de una tanda cambió de estado (por Despacho, la ficha o el canal)."""
    now = timezone.now()
    with transaction.atomic():
        items = list(active_items().select_for_update().filter(document_id=document.pk))
        if not items:
            return
        if new in RESOLVED:
            for item in items:
                item.resolved_at = now
                item.save(update_fields=["resolved_at", "updated_at"])
        elif new == states.NEW:  # alguien lo devolvió a Nuevo desde la ficha
            for item in items:
                item.removed_at = now
                item.save(update_fields=["removed_at", "updated_at"])
        else:
            return
        for batch_id in {i.batch_id for i in items}:
            close_if_done(PickBatch.objects.get(pk=batch_id))


def on_status_changed_signal(sender, document, old, new, system=False, **kwargs):
    on_status_changed(document, old, new)


def close_if_done(batch: PickBatch, *, user=None, request=None) -> bool:
    """Cierra la tanda si ya no le quedan pedidos activos. Devuelve True si la cerró."""
    with transaction.atomic():
        batch = PickBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.status != PickBatch.Status.OPEN:
            return False
        if batch.items.filter(removed_at__isnull=True, resolved_at__isnull=True).exists():
            return False
        batch.status = PickBatch.Status.CLOSED
        batch.closed_at = timezone.now()
        batch.save(update_fields=["status", "closed_at", "updated_at"])
        audit.record(user, "fulfillment.batch_closed", batch, request=request)
    return True


def active_batch_for(document: SalesDocument) -> PickBatch | None:
    item = active_items().select_related("batch").filter(document=document).first()
    return item.batch if item else None
