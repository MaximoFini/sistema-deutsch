"""Sincronización automática del estado interno con lo que informan los canales (US-2).

Los adaptadores (M1, M2) llaman a `sync_internal_status` al final de cada upsert. Las reglas
leen hechos genéricos del documento: no hay lógica de estados dentro de los adaptadores.
"""

from dataclasses import dataclass

from django.db import transaction

from apps.alerts import services as alerts
from apps.inventory.models import StockLevel

from . import payments, states
from .models import SalesDocument, Shipment


@dataclass
class Facts:
    cancelled: bool
    paid: bool
    delivered: bool
    full: bool
    claim_open: bool
    shipped: bool = False  # el canal dice que el paquete ya salió (Flex escaneado, Envío Nube despachado)
    pickup: bool = False


def facts(doc: SalesDocument) -> Facts:
    channel_status = (doc.channel_status or "").lower()
    shipments = list(doc.shipments.all())
    tn_shipping = channel_status.split("/")[-1] if doc.channel.code == "tiendanube" else ""
    # TN: "status/payment/shipping"; el tercer tramo es el shipping_status.
    tn_parts = channel_status.split("/") if doc.channel.code == "tiendanube" else []
    tn_shipping_status = tn_parts[2] if len(tn_parts) > 2 else ""
    return Facts(
        # Solo si TODO el pedido está cancelado: "cancelled/…" (TN) o "cancelled" (ML, todas las órdenes
        # del pack). Una cancelación parcial de un pack ("cancelled,paid") no cancela el pedido.
        cancelled=channel_status.split("/")[0].split("+")[0] == "cancelled",
        paid=payments.is_paid(doc),
        delivered=any(s.status == "delivered" for s in shipments) or tn_shipping == "delivered",
        full=any(s.method == Shipment.Method.ME_FULL for s in shipments),
        claim_open=doc.claims.filter(status="opened").exists(),
        shipped=any(s.status == "shipped" for s in shipments) or tn_shipping_status == "shipped",
        pickup=any(s.method == Shipment.Method.PICKUP for s in shipments),
    )


# Estados en los que un pedido todavía no salió del depósito según el sistema.
NOT_DISPATCHED = (states.NEW, states.PREPARING, states.READY, states.AWAITING_CUSTOMER)


def _target(doc: SalesDocument, f: Facts, created: bool) -> tuple[str | None, str]:
    name = doc.channel.name
    status = doc.status
    if f.cancelled and status not in states.FINAL:
        return states.CANCELLED, f"Cancelado en {name}"
    # Con reclamo abierto (o todavía en Con reclamo) no se pasa a Entregado: si no, el pedido
    # oscila Con reclamo → Entregado → Con reclamo en cada sincronización. Al cerrarse el reclamo
    # vuelve al estado anterior y recién ahí corre esta regla.
    in_claim = f.claim_open or status == states.CLAIM
    if f.delivered and status not in states.FINAL and not in_claim:
        return states.DELIVERED, f"Entregado según {name}"
    if f.claim_open and status not in (states.CLAIM, states.CANCELLED):
        return states.CLAIM, "Reclamo abierto"
    if not f.claim_open and status == states.CLAIM:
        return (doc.status_before_claim or states.NEW), "Reclamo cerrado"
    # El paquete salió por el canal sin que nadie lo marcara acá (Flex escaneado por el repartidor,
    # Envío Nube despachado desde el admin de TN). Full tiene su propia regla, más abajo.
    if f.shipped and not f.full and status in NOT_DISPATCHED:
        if f.pickup:
            return states.READY_FOR_PICKUP, f"Listo para retirar según {name}"
        return states.DISPATCHED, f"Despachado según {name}"
    if f.full and status in (states.NEW, states.AWAITING_PAYMENT, states.PREPARING, states.READY):
        return states.DISPATCHED, "Full: despacha Mercado Libre"
    if created and not f.paid and status == states.NEW:
        return states.AWAITING_PAYMENT, "Entró sin pagar"
    if status == states.AWAITING_PAYMENT and f.paid:
        return states.NEW, "Pago confirmado"
    return None, ""


def sync_internal_status(doc: SalesDocument, *, created: bool = False) -> str | None:
    """Aplica las reglas una vez (idempotente). Devuelve el estado nuevo o None si no cambió."""
    if doc.doc_type != SalesDocument.DocType.ORDER or doc.is_historical:
        return None
    doc = SalesDocument.objects.select_related("channel").get(pk=doc.pk)
    f = facts(doc)
    applied = None
    # Hasta 3 pasos (p. ej. creado sin pagar y con reclamo); cada paso es una regla.
    for _ in range(3):
        target, reason = _target(doc, f, created)
        if target is None:
            break
        states.change_status(doc, target, reason=reason, system=True)
        applied = target
        doc.refresh_from_db()
        created = False
    return applied


def on_document_created(doc: SalesDocument, *, notify: bool = True) -> None:
    """Primer ingreso de un pedido de canal: estado inicial, aviso de nuevo y control de stock.

    `notify=False` cuando el canal todavía tiene que traer datos que cambian el aviso (en ML el
    envío llega después: un pedido Full no se prepara); en ese caso llamar a `after_created_complete`.
    """
    sync_internal_status(doc, created=True)
    doc.refresh_from_db(fields=["status", "ready_at", "issued_at"])
    states.mark_ready_on_create(doc)
    if notify:
        after_created_complete(doc)


def after_created_complete(doc: SalesDocument) -> None:
    doc.refresh_from_db()
    if doc.is_historical:
        return
    if doc.status == states.NEW:
        states.emit_new_order(doc)  # dedupe por pedido: un solo aviso
    if doc.status not in states.FINAL and doc.status != states.DISPATCHED:
        check_stock(doc)


def check_stock(doc: SalesDocument) -> None:
    """Alerta si alguna línea no tiene stock disponible en el depósito (venta de más)."""
    if doc.is_historical:
        return
    if doc.shipments.filter(method=Shipment.Method.ME_FULL).exists():
        return
    problems = []
    # Las líneas con SKU desconocido (sin variante) ya las alerta la integración.
    lines = [ln for ln in doc.lines.select_related("variant") if ln.variant is not None]
    # Se mira el depósito por defecto (con varios depósitos, `first()` podía tomar cualquiera).
    levels = {
        lv.variant_id: lv
        for lv in StockLevel.objects.filter(
            warehouse__is_default=True, variant_id__in=[ln.variant_id for ln in lines]
        )
    }
    for line in lines:
        level = levels.get(line.variant_id)
        if level is None or (level.on_hand - level.reserved) < 0:
            available = (
                "sin stock registrado" if level is None else f"disponible {level.on_hand - level.reserved:g}"
            )
            problems.append(f"{line.variant.sku} ({available})")
    if problems:
        ref = doc.channel_reference or str(doc)
        doc_id = doc.pk
        transaction.on_commit(
            lambda: alerts.emit(
                "orders.out_of_stock",
                title=f"{ref}: venta sin stock en el depósito",
                body="Productos: " + ", ".join(problems),
                link_url=f"/pedidos/{doc_id}/",
                dedupe_key=f"oos:{doc_id}",
            )
        )
