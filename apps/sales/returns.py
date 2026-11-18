"""Devoluciones: esperadas (reclamo de ML o cargadas a mano) → recibidas → ajustadas en Contabilium.

No tocan el stock del sistema: el stock refleja Contabilium y el ajuste se hace allá (US-4).
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.alerts import services as alerts
from apps.audit import services as audit

from .models import ReturnInfo, SalesDocument, SalesLine

EXPECTED, RECEIVED = "expected", "received"


class ReturnError(Exception):
    pass


def _new_return(order: SalesDocument, source: str, claim=None, lines=None) -> SalesDocument:
    doc = SalesDocument.objects.create(
        doc_type=SalesDocument.DocType.RETURN,
        channel=order.channel,
        customer=order.customer,
        status=EXPECTED,
        issued_at=timezone.now(),
        related_document=order,
        channel_reference=f"Dev. {order.channel_reference or order.number}"[:60],
    )
    for line in lines if lines is not None else order.lines.all():
        SalesLine.objects.create(
            document=doc,
            variant=line.variant,
            sku_snapshot=line.sku_snapshot,
            description_snapshot=line.description_snapshot,
            quantity=line.quantity,
            unit_price=line.unit_price,
        )
    doc.recalculate_totals()
    ReturnInfo.objects.create(document=doc, source=source, claim=claim)
    return doc


@transaction.atomic
def ensure_expected_for_claim(claim) -> SalesDocument | None:
    """Reclamo de ML con devolución → devolución esperada (una sola por reclamo)."""
    if claim.document_id is None or not claim.return_status or claim.document.is_historical:
        return None
    existing = ReturnInfo.objects.filter(claim=claim).select_related("document").first()
    if existing:
        return existing.document
    return _new_return(claim.document, ReturnInfo.Source.ML_CLAIM, claim=claim)


def pending_expected(order: SalesDocument) -> SalesDocument | None:
    """Devolución esperada de este pedido que todavía no se recibió (la más reciente)."""
    info = (
        ReturnInfo.objects.filter(document__related_document=order, received_at__isnull=True)
        .select_related("document")
        .order_by("-expected_at", "-pk")
        .first()
    )
    return info.document if info else None


@transaction.atomic
def get_or_create_expected(order: SalesDocument, *, user, request=None) -> tuple[SalesDocument, bool]:
    """Para los botones de la ficha: si el pedido ya tiene una devolución esperada sin recibir, se
    reutiliza (no se crea otra en cada clic ni quedan esperadas huérfanas). Devuelve (doc, creada)."""
    existing = pending_expected(order)
    if existing is not None:
        return existing, False
    return create_expected(order, user=user, request=request), True


@transaction.atomic
def create_expected(order: SalesDocument, *, user, lines=None, request=None) -> SalesDocument:
    if order.is_historical:
        raise ReturnError("Pedido histórico importado de TiendaQuick: solo lectura, no admite devoluciones.")
    doc = _new_return(order, ReturnInfo.Source.MANUAL, lines=lines)
    audit.record(
        user, "return.expected_created", doc, request=request, after={"pedido": order.channel_reference}
    )
    return doc


def validate_quantity(line: SalesLine, quantity) -> None:
    """Entero, mayor a 0 y no más de lo esperado en esa línea."""
    sku = line.sku_snapshot or line.description_snapshot
    try:
        quantity = Decimal(quantity)
    except (ArithmeticError, TypeError, ValueError):
        quantity = None
    if quantity is None or not quantity.is_finite() or quantity != quantity.to_integral_value():
        raise ReturnError(f"La cantidad recibida de {sku} tiene que ser un número entero (sin decimales).")
    if quantity <= 0:
        raise ReturnError(f"La cantidad recibida de {sku} tiene que ser mayor a 0.")
    if quantity > line.quantity:
        raise ReturnError(
            f"De {sku} se esperaba {Decimal(line.quantity).normalize():f}: no se puede registrar más cantidad que la esperada."
        )


@transaction.atomic
def receive(
    return_doc: SalesDocument,
    received: list[tuple[SalesLine, Decimal, str]],
    comment: str,
    *,
    user,
    request=None,
) -> None:
    """`received`: (línea de la devolución, cantidad recibida, condición resellable|damaged)."""
    info = ReturnInfo.objects.select_for_update().get(document=return_doc)
    if info.received_at:
        raise ReturnError("Esta devolución ya fue registrada como recibida.")
    detail = []
    for line, quantity, condition in received:
        if line.document_id != return_doc.pk:
            raise ReturnError("La línea no pertenece a esta devolución.")
        if condition not in ("resellable", "damaged"):
            raise ReturnError("Indicá si cada producto es apto para reventa o está dañado.")
        validate_quantity(line, quantity)
        line.quantity = Decimal(quantity)
        line.condition = condition
        line.save()
        detail.append(
            {"sku": line.sku_snapshot, "cantidad": str(line.quantity), "estado": line.get_condition_display()}
        )
    return_doc.lines.exclude(pk__in=[ln.pk for ln, _, _ in received]).delete()
    return_doc.recalculate_totals()
    return_doc.status = RECEIVED
    return_doc.save(update_fields=["status", "updated_at"])
    info.received_at = timezone.now()
    info.received_by = user
    info.comment = comment
    info.save()
    audit.record(
        user, "return.received", return_doc, request=request, after={"lineas": detail, "comentario": comment}
    )
    ref = return_doc.channel_reference
    lines_txt = "; ".join(f"{d['sku']} x{d['cantidad']} ({d['estado']})" for d in detail)
    doc_id = return_doc.pk
    transaction.on_commit(
        lambda: alerts.emit(
            "returns.received_adjust_stock",
            title=f"{ref}: ajustar stock en Contabilium",
            body=f"Llegó la devolución. {lines_txt}. {comment}".strip(),
            link_url="/pedidos/devoluciones/?vista=recibidas",
            dedupe_key=f"return:{doc_id}",
        )
    )


@transaction.atomic
def receive_unexpected(
    order: SalesDocument, received: list[tuple[SalesLine, Decimal, str]], comment: str, *, user, request=None
) -> SalesDocument:
    """Llegó una devolución que no estaba esperada: se crea y se recibe en un paso.
    `received` trae líneas DEL PEDIDO; se copian a la devolución."""
    doc = create_expected(order, user=user, lines=[ln for ln, _, _ in received], request=request)
    mapped = list(zip(doc.lines.order_by("id"), [(q, c) for _, q, c in received], strict=True))
    receive(doc, [(ln, q, c) for ln, (q, c) in mapped], comment, user=user, request=request)
    return doc


@transaction.atomic
def mark_adjusted(return_doc: SalesDocument, *, user, request=None) -> None:
    info = ReturnInfo.objects.select_for_update().get(document=return_doc)
    if not info.received_at:
        raise ReturnError("Primero hay que registrar la recepción.")
    if info.adjusted_in_contabilium:
        return
    info.adjusted_in_contabilium = True
    info.adjusted_by = user
    info.adjusted_at = timezone.now()
    info.save()
    audit.record(user, "return.adjusted", return_doc, request=request)
