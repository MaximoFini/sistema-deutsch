"""Estados internos de los pedidos y el único servicio que los cambia (US-2).

Toda transición, manual o automática, pasa por `change_status`: valida, audita y dispara efectos.
"""

from django.db import transaction
from django.utils import timezone

from apps.alerts import services as alerts
from apps.audit import services as audit

from .models import SalesDocument, Shipment

NEW, PREPARING, READY = "new", "preparing", "ready"
DISPATCHED, READY_FOR_PICKUP, DELIVERED = "dispatched", "ready_for_pickup", "delivered"
CANCELLED, CLAIM, AWAITING_PAYMENT, AWAITING_CUSTOMER = (
    "cancelled",
    "claim",
    "awaiting_payment",
    "awaiting_customer",
)

LABELS = {
    NEW: "Nuevo",
    PREPARING: "En preparación",
    READY: "Listo",
    DISPATCHED: "Despachado",
    READY_FOR_PICKUP: "Listo para retirar",
    DELIVERED: "Entregado",
    CANCELLED: "Cancelado",
    CLAIM: "Con reclamo",
    AWAITING_PAYMENT: "Esperando pago",
    AWAITING_CUSTOMER: "Esperando cliente",
}
FAMILY = {  # para el color del badge
    NEW: "flow",
    PREPARING: "flow",
    READY: "flow",
    DISPATCHED: "flow",
    READY_FOR_PICKUP: "flow",
    DELIVERED: "final",
    CANCELLED: "final",
    CLAIM: "special",
    AWAITING_PAYMENT: "special",
    AWAITING_CUSTOMER: "special",
}
FINAL = {DELIVERED, CANCELLED}
OPEN = {NEW, PREPARING, READY, AWAITING_CUSTOMER, AWAITING_PAYMENT, CLAIM}

TRANSITIONS: dict[str, set[str]] = {
    NEW: {PREPARING, AWAITING_CUSTOMER, CANCELLED},
    PREPARING: {READY, NEW, AWAITING_CUSTOMER, CANCELLED},
    READY: {DISPATCHED, READY_FOR_PICKUP, PREPARING, AWAITING_CUSTOMER, CANCELLED},
    DISPATCHED: {DELIVERED},
    READY_FOR_PICKUP: {DELIVERED, READY},
    AWAITING_CUSTOMER: {NEW, PREPARING, READY, CANCELLED},
    AWAITING_PAYMENT: {NEW, CANCELLED},
    CLAIM: set(),  # sale al estado anterior (ver allowed_transitions)
    DELIVERED: set(),
    CANCELLED: set(),
}
# Estados que se informan a Tiendanube cuando los pone una persona.
TN_EFFECTS = {
    READY: "packed",
    DISPATCHED: "dispatched",
    READY_FOR_PICKUP: "dispatched",
    DELIVERED: "delivered",
}


class TransitionNotAllowed(Exception):
    pass


def label(status: str) -> str:
    return LABELS.get(status, status)


def is_pickup(doc: SalesDocument) -> bool:
    return doc.shipments.filter(method=Shipment.Method.PICKUP).exists()


def is_manual(doc: SalesDocument) -> bool:
    return doc.channel.code == "manual"


def allowed_transitions(doc: SalesDocument, user=None) -> list[str]:
    """Destinos que la UI ofrece a este usuario (solo pedidos)."""
    if doc.doc_type != SalesDocument.DocType.ORDER:
        return []
    if user is not None and not user.has_perm("sales.change_order_status"):
        return []
    targets = set(TRANSITIONS.get(doc.status, set()))
    if doc.status == CLAIM and doc.status_before_claim and not doc.claims.filter(status="opened").exists():
        targets = {doc.status_before_claim}
    pickup = is_pickup(doc)
    targets.discard(DISPATCHED if pickup else READY_FOR_PICKUP)
    if CANCELLED in targets and (
        not is_manual(doc) or (user is not None and not user.has_perm("sales.cancel_manual_order"))
    ):
        targets.discard(CANCELLED)
    order = list(LABELS)
    return sorted(targets, key=order.index)


def change_status(
    doc: SalesDocument,
    to: str,
    *,
    user=None,
    reason: str = "",
    tracking_code: str = "",
    tracking_url: str = "",
    system: bool = False,
    request=None,
) -> bool:
    """Cambia el estado. Devuelve True si cambió. Lanza TransitionNotAllowed si no se permite."""
    if to not in LABELS:
        raise TransitionNotAllowed(f"Estado desconocido: {to}")
    with transaction.atomic():
        doc = SalesDocument.objects.select_for_update().select_related("channel").get(pk=doc.pk)
        current = doc.status
        if current == to:
            return False
        if not system:
            if user is None or not user.has_perm("sales.change_order_status"):
                raise TransitionNotAllowed("No tenés permiso para cambiar el estado de los pedidos.")
            if to not in allowed_transitions(doc, user):
                if to == CANCELLED and not is_manual(doc):
                    raise TransitionNotAllowed(
                        f"Los pedidos de {doc.channel.name} se cancelan en el canal; el sistema lo refleja solo."
                    )
                raise TransitionNotAllowed(f"No se puede pasar de «{label(current)}» a «{label(to)}».")
        if to == CLAIM:
            doc.status_before_claim = current
        doc.status = to
        doc.status_changed_at = timezone.now()
        doc.save(update_fields=["status", "status_before_claim", "status_changed_at", "updated_at"])
        audit.record(
            None if system else user,
            "order.status_changed",
            doc,
            request=request,
            before={"estado": current},
            after={"estado": to},
            motivo=reason,
            canal=doc.channel.code,
            **({"seguimiento": tracking_code} if tracking_code else {}),
        )
        if not system and doc.channel.code == "tiendanube" and to in TN_EFFECTS:
            _tn_effect(doc, TN_EFFECTS[to], user, tracking_code, tracking_url)
        if to == CANCELLED and current in (PREPARING, READY):
            doc_ref = doc.channel_reference or str(doc)
            transaction.on_commit(
                lambda: alerts.emit(
                    "orders.cancelled_in_progress",
                    title=f"Se canceló {doc_ref}, que ya estaba {label(current).lower()}",
                    body=reason or "Revisar si hay mercadería separada para devolver a la estantería.",
                    link_url=f"/pedidos/{doc.pk}/",
                    dedupe_key=f"cancel:{doc.pk}",
                )
            )
        if to == NEW and current == AWAITING_PAYMENT:
            emit_new_order(doc)  # recién ahora hay que prepararlo
    return True


def _tn_effect(doc, action, user, tracking_code, tracking_url):
    from apps.integrations.adapters.tiendanube import fulfillment

    if action == "packed":
        fulfillment.mark_packed(doc, actor=user)
    elif action == "dispatched":
        fulfillment.mark_dispatched(doc, actor=user, tracking_code=tracking_code, tracking_url=tracking_url)
    elif action == "delivered":
        fulfillment.mark_delivered(doc, actor=user)


def emit_new_order(doc: SalesDocument) -> None:
    ref = doc.channel_reference or str(doc)
    doc_id = doc.pk
    transaction.on_commit(
        lambda: alerts.emit(
            "orders.new",
            title=f"Pedido nuevo para preparar: {ref}",
            link_url=f"/pedidos/{doc_id}/",
            dedupe_key=f"new:{doc_id}",
        )
    )
