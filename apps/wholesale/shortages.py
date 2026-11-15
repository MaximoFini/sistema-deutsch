"""Faltantes en pedidos mayoristas (US-8, §9).

1. **Marcar** (Depósito, en un pedido En preparación): cantidad que falta por línea → Esperando cliente,
   email al cliente y alerta a los administradores.
2. **Resolver** (Administrador, con la respuesta del cliente): quitar, reducir o reemplazar líneas.
   Ajusta la reserva por la diferencia, recalcula el total y, si el pedido ya estaba pago y bajó, deja
   saldo a favor o registra el reintegro (hecho por fuera). Si ya estaba facturado, lo marca "Corregir
   en Contabilium". Vuelve a En preparación. Todo pasa por `change_status` y queda auditado.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.alerts import services as alerts
from apps.audit import services as audit
from apps.catalog.models import Variant
from apps.sales import payments as sales_payments
from apps.sales import states
from apps.sales.models import Payment, SalesDocument, SalesLine

from . import catalog, mail
from .accounts import store_url
from .models import CustomerBalance, Shortage, WholesaleOrder
from .payments import _move_status, change_line_reservation, customer_email, money, order_of

CREDIT, REFUND = "credit", "refund"


class ShortageError(Exception):
    """Mensaje para mostrar tal cual."""


@dataclass
class Replacement:
    variant: Variant
    quantity: int


def qty_text(value) -> str:
    return f"{Decimal(value).normalize():f}"


def open_shortages(doc: SalesDocument):
    return doc.shortages.filter(resolved_at__isnull=True)


def can_report(doc: SalesDocument) -> bool:
    return doc.channel.code == "mayorista" and doc.status == states.PREPARING


def can_resolve(doc: SalesDocument) -> bool:
    return (
        doc.channel.code == "mayorista"
        and doc.status == states.AWAITING_CUSTOMER
        and open_shortages(doc).exists()
    )


def _lines_snapshot(doc) -> list[dict]:
    return [
        {"sku": line.sku_snapshot, "cantidad": qty_text(line.quantity), "precio": str(line.unit_price)}
        for line in doc.lines.order_by("pk")
    ]


# ── Marcar ───────────────────────────────────────────────────────────────────


@transaction.atomic
def report(doc: SalesDocument, missing: dict[int, int], *, user, request=None) -> list[Shortage]:
    """`missing` = {id de línea: unidades que faltan}."""
    if not user.has_perm("wholesale.report_shortage"):
        raise PermissionDenied
    doc = (
        SalesDocument.objects.select_for_update(of=("self",))
        .select_related("channel", "customer")
        .get(pk=doc.pk)
    )
    if doc.channel.code != "mayorista":
        raise ShortageError("Los faltantes se marcan solo en pedidos mayoristas.")
    if doc.status != states.PREPARING:
        raise ShortageError(
            f"El faltante se marca con el pedido En preparación (ahora está «{states.label(doc.status)}»)."
        )
    lines = {line.pk: line for line in doc.lines.all()}
    created = []
    for line_id, quantity in missing.items():
        line = lines.get(line_id)
        if line is None or not quantity:
            continue
        if quantity < 0 or quantity > line.quantity:
            raise ShortageError(
                f"En {line.sku_snapshot} pueden faltar entre 0 y {qty_text(line.quantity)} unidades."
            )
        created.append(
            Shortage.objects.create(
                document=doc,
                line=line,
                sku=line.sku_snapshot,
                description=line.description_snapshot,
                missing_quantity=quantity,
                reported_by=user,
            )
        )
    if not created:
        raise ShortageError("Indicá cuántas unidades faltan de al menos un producto.")
    detail = "\n".join(f"- {s.missing_quantity} × {s.description} ({s.sku})" for s in created)
    _move_status(doc, states.AWAITING_CUSTOMER, user=user, reason="Faltante", request=request)
    audit.record(
        user,
        "wholesale.shortage_reported",
        doc,
        request=request,
        after={s.sku: s.missing_quantity for s in created},
    )
    mail.enqueue(
        "shortage_query",
        customer_email(doc),
        {
            "cliente": str(doc.customer),
            "pedido": doc.channel_reference,
            "detalle": detail,
            "enlace": store_url("store:order_detail", doc.number),
        },
    )
    ref, doc_id, customer = doc.channel_reference, doc.pk, str(doc.customer)
    transaction.on_commit(
        lambda: alerts.emit(
            "wholesale.shortage_reported",
            title=f"Faltante en {ref} ({customer})",
            body=detail + "\n\nConsultale al cliente y ajustá el pedido con su respuesta.",
            link_url=f"/pedidos/{doc_id}/",
            dedupe_key=f"shortage:{doc_id}:{created[0].pk}",
        )
    )
    return created


# ── Resolver ─────────────────────────────────────────────────────────────────


@transaction.atomic
def resolve(
    doc: SalesDocument,
    *,
    quantities: dict[int, int],
    replacements: list[Replacement] | None = None,
    difference: str = "",
    refund_date: date | None = None,
    refund_reference: str = "",
    user,
    request=None,
) -> dict:
    """`quantities` = {id de línea: cantidad final} (0 = quitar). Devuelve un resumen de lo hecho."""
    if not user.has_perm("wholesale.resolve_shortage"):
        raise PermissionDenied
    doc = (
        SalesDocument.objects.select_for_update(of=("self",))
        .select_related("channel", "customer")
        .get(pk=doc.pk)
    )
    order: WholesaleOrder | None = order_of(doc)
    if doc.channel.code != "mayorista" or order is None:
        raise ShortageError("Solo se ajustan así los pedidos mayoristas.")
    pending = list(open_shortages(doc))
    if doc.status != states.AWAITING_CUSTOMER or not pending:
        raise ShortageError("Este pedido no tiene un faltante para resolver.")
    replacements = replacements or []
    old_total = doc.total
    paid_before = sales_payments.is_paid(doc)
    before = {"lineas": _lines_snapshot(doc), "total": str(old_total)}
    ref = doc.channel_reference

    lines = list(doc.lines.select_related("variant").order_by("pk"))
    for line in lines:
        if line.pk not in quantities:
            continue
        new = quantities[line.pk]
        if new < 0 or new > line.quantity:
            raise ShortageError(
                f"La cantidad de {line.sku_snapshot} tiene que quedar entre 0 y {qty_text(line.quantity)}."
            )
        delta = Decimal(new) - line.quantity
        if not delta:
            continue
        change_line_reservation(
            doc, line.variant, delta, user=user, note=f"Ajuste por faltante {ref} ({line.sku_snapshot})"
        )
        if new == 0:
            line.delete()
        else:
            line.quantity = Decimal(new)
            line.save()

    ctx = catalog.Context.load()
    for rep in replacements:
        if rep.quantity <= 0:
            continue
        net = catalog.net_price(rep.variant, ctx)
        if net is None or net <= 0 or not rep.variant.is_active:
            raise ShortageError(f"{rep.variant.sku} no tiene precio mayorista: elegí otra variante.")
        available = catalog.available(rep.variant, ctx)
        if rep.quantity > available:
            raise ShortageError(f"De {rep.variant.sku} hay {available} disponibles.")
        label = catalog.variant_label(rep.variant)
        name = rep.variant.product.name
        SalesLine.objects.create(
            document=doc,
            variant=rep.variant,
            sku_snapshot=rep.variant.sku,
            description_snapshot=(f"{name} ({label})" if label else name)[:300],
            quantity=Decimal(rep.quantity),
            unit_price=net,
            vat_rate=catalog.VAT_RATE,
        )
        change_line_reservation(
            doc,
            rep.variant,
            rep.quantity,
            user=user,
            note=f"Reemplazo por faltante {ref} ({rep.variant.sku})",
        )

    if not doc.lines.exists():
        raise ShortageError(
            "El pedido quedaría sin productos. Si el cliente no quiere nada, cancelalo desde «Pasar a»."
        )

    # Totales. El saldo a favor aplicado no puede superar el nuevo total: lo que sobra vuelve al saldo.
    doc.recalculate_totals(save=False)
    gross = doc.subtotal + doc.tax_total + doc.shipping_total
    returned_balance = Decimal(0)
    if doc.discount_total > gross:
        returned_balance = doc.discount_total - gross
        doc.discount_total = gross
        order.balance_applied = gross
        order.save(update_fields=["balance_applied"])
        doc.recalculate_totals(save=False)
    doc.save()
    new_total = doc.total
    if returned_balance:
        CustomerBalance.objects.create(
            customer_id=doc.customer_id,
            amount=returned_balance,
            document=doc,
            note=f"Devolución de saldo por el ajuste de {ref}",
            created_by=user,
        )
    doc.payments.filter(status=Payment.Status.PENDING).update(amount=new_total, updated_at=timezone.now())

    resolution = {"total_anterior": str(old_total), "total_nuevo": str(new_total)}
    diff = old_total - new_total
    if paid_before and diff > 0:
        if difference == CREDIT:
            CustomerBalance.objects.create(
                customer_id=doc.customer_id,
                amount=diff,
                document=doc,
                note=f"Saldo a favor por faltante en {ref}",
                created_by=user,
            )
            resolution["diferencia"] = {"tipo": "saldo a favor", "monto": str(diff)}
        elif difference == REFUND:
            if not refund_reference.strip():
                raise ShortageError("Anotá la referencia del reintegro (p. ej. el número de transferencia).")
            resolution["diferencia"] = {
                "tipo": "reintegro",
                "monto": str(diff),
                "fecha": (refund_date or timezone.localdate()).isoformat(),
                "referencia": refund_reference.strip()[:120],
            }
        else:
            raise ShortageError(
                f"El pedido ya estaba pago y bajó {money(diff)}: elegí si queda como saldo a favor o si se reintegra."
            )

    if doc.invoiced_in_contabilium:
        order.needs_contabilium_correction = True
        order.save(update_fields=["needs_contabilium_correction"])
        doc_id = doc.pk
        transaction.on_commit(
            lambda: alerts.emit(
                "wholesale.contabilium_correction",
                title=f"Corregir {ref} en Contabilium",
                body="El pedido ya estaba facturado y se ajustó por un faltante. Hacé la nota de crédito o la corrección que corresponda.",
                link_url=f"/pedidos/{doc_id}/",
                dedupe_key=f"correction:{doc_id}:{pending[0].pk}",
            )
        )
        resolution["corregir_en_contabilium"] = True

    now = timezone.now()
    for shortage in pending:
        shortage.resolved_at = now
        shortage.resolution = resolution
        shortage.save(update_fields=["resolved_at", "resolution", "updated_at"])
    _move_status(doc, states.PREPARING, user=user, reason="Faltante resuelto", request=request)
    audit.record(
        user,
        "wholesale.shortage_resolved",
        doc,
        request=request,
        before=before,
        after={"lineas": _lines_snapshot(doc), "total": str(new_total), **resolution},
    )
    return resolution
