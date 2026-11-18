"""Despacho en lote (US-4): aplica `change_status` a varios pedidos y junta los que no pudieron avanzar.

En pedidos de Tiendanube, `change_status` ya encola el aviso a Tiendanube (M1): acá no se agrega nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Prefetch

from apps.sales import payments, states
from apps.sales.models import Payment, SalesDocument, Shipment

from .batches import order_ref

LISTO, DESPACHAR, ENTREGAR = "listo", "despachar", "entregar"
# acción → (estado de origen, texto del botón)
ACTIONS = {
    LISTO: (states.PREPARING, "Marcar como Listo"),
    DESPACHAR: (states.READY, "Despachar / Listo para retirar"),
    ENTREGAR: (states.READY_FOR_PICKUP, "Entregado (lo retiró)"),
}


class DispatchError(Exception):
    pass


@dataclass
class Result:
    done: list[tuple[SalesDocument, str]] = field(default_factory=list)  # (pedido, estado nuevo)
    failed: list[tuple[SalesDocument, str]] = field(default_factory=list)  # (pedido, motivo)
    stale: int = 0  # cuántos fallaron porque cambiaron de estado mientras la página estaba abierta

    def failed_text(self) -> str:
        return "; ".join(f"{order_ref(doc)} ({reason})" for doc, reason in self.failed)


def target_for(doc: SalesDocument, action: str, shipments: list[Shipment]) -> str:
    if action == LISTO:
        return states.READY
    if action == ENTREGAR:
        return states.DELIVERED
    pickup = any(s.method == Shipment.Method.PICKUP for s in shipments)
    return states.READY_FOR_PICKUP if pickup else states.DISPATCHED


def cash_due_ids(docs) -> set[int]:
    """M8: pedidos mayoristas en efectivo que todavía no se cobraron (una consulta para toda la pantalla)."""
    docs = [d for d in docs if not payments.is_paid(d, getattr(d, "paid_amount", None))]
    if not docs:
        return set()
    return set(
        Payment.objects.filter(
            document__in=[d.pk for d in docs],
            method=Payment.Method.CASH,
            status=Payment.Status.PENDING,
            external_reference="mayorista",
        ).values_list("document_id", flat=True)
    )


def advance(
    document_ids,
    action: str,
    *,
    user,
    request=None,
    tracking: dict | None = None,
    cash_collected: set[int] | None = None,
) -> Result:
    """Avanza cada pedido por separado: uno que falla no frena a los demás.

    M8: un pedido mayorista en efectivo se entrega solo si se marca que se cobró (`cash_collected`).
    """
    cash_collected = cash_collected or set()
    if action not in ACTIONS:
        raise DispatchError("Acción desconocida.")
    origin = ACTIONS[action][0]
    tracking = tracking or {}
    ids = sorted({int(i) for i in document_ids})
    if not ids:
        raise DispatchError("Marcá al menos un pedido.")
    docs = (
        SalesDocument.objects.filter(pk__in=ids, doc_type=SalesDocument.DocType.ORDER, is_historical=False)
        .select_related("channel", "customer")
        .prefetch_related(Prefetch("shipments", queryset=Shipment.objects.order_by("id")))
        .order_by("pk")
    )
    result = Result()
    for doc in docs:
        shipments = list(doc.shipments.all())
        if doc.status != origin:
            result.failed.append((doc, f"ahora está «{states.label(doc.status)}»"))
            result.stale += 1
            continue
        to = target_for(doc, action, shipments)
        cash_due = action == ENTREGAR and doc.channel.code == "mayorista" and bool(cash_due_ids([doc]))
        if cash_due and doc.pk not in cash_collected:
            from apps.wholesale.catalog import format_money

            result.failed.append((doc, f"falta cobrar {format_money(doc.total)} en efectivo: tildá «Cobré»"))
            continue
        code = (
            (tracking.get(doc.pk) or tracking.get(str(doc.pk)) or "").strip()[:100]
            if action == DESPACHAR
            else ""
        )
        try:
            with transaction.atomic():
                if cash_due:
                    from apps.wholesale.payments import mark_cash_collected

                    mark_cash_collected(doc, user=user, request=request)
                states.change_status(
                    doc, to, user=user, tracking_code=code, reason="Despacho", request=request
                )
                if code:
                    for s in shipments:
                        if s.method == Shipment.Method.CARRIER:
                            s.tracking_number = code
                            s.save(update_fields=["tracking_number", "updated_at"])
        except states.TransitionNotAllowed as exc:
            result.failed.append((doc, str(exc)))
            continue
        result.done.append((doc, to))
    return result
