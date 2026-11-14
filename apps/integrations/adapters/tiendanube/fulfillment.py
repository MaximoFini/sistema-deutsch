"""Marcar el despacho en Tiendanube (fulfillment orders, API 2025-03).

Lo usa la pantalla de despacho (M5). Solo toca estados y seguimiento: nunca stock ni precios.
"""

import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from procrastinate.contrib.django import app

from apps.alerts import services as alerts
from apps.audit import services as audit
from apps.integrations import errors
from apps.integrations.http import ChannelHTTPError
from apps.integrations.models import ExternalRef
from apps.sales.models import SalesDocument

from .client import CHANNEL, TiendanubeClient

logger = logging.getLogger(__name__)

PACKED, DISPATCHED, DELIVERED = "packed", "dispatched", "delivered"
ACTION_LABELS = {PACKED: "Listo", DISPATCHED: "Despachado", DELIVERED: "Entregado"}
ORDER = ["UNPACKED", "IN_PREPARATION", "PACKED", "DISPATCHED", "READY_FOR_PICKUP", "DELIVERED"]
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = [60, 300, 1500, 7200]


def _enqueue(document, action, actor, **extra):
    document_id = document.pk
    actor_id = getattr(actor, "pk", None)
    transaction.on_commit(
        lambda: tn_fulfillment_update.defer(
            document_id=document_id, action=action, actor_id=actor_id, **extra
        )
    )


def mark_packed(document, *, actor) -> None:
    _enqueue(document, PACKED, actor)


def mark_dispatched(document, *, actor, tracking_code: str = "", tracking_url: str = "") -> None:
    _enqueue(document, DISPATCHED, actor, tracking_code=tracking_code, tracking_url=tracking_url)


def mark_delivered(document, *, actor) -> None:
    _enqueue(document, DELIVERED, actor)


def _target_status(action: str, fo: dict) -> str:
    if action == PACKED:
        return "PACKED"
    if action == DISPATCHED:
        shipping_type = (fo.get("shipping") or {}).get("type")
        return "READY_FOR_PICKUP" if shipping_type == "pickup" else "DISPATCHED"
    return "DELIVERED"


def _already_there(current: str, target: str) -> bool:
    if current == target:
        return True
    if current in ORDER and target in ORDER:
        return ORDER.index(current) >= ORDER.index(target)
    return False


def apply_update(
    client: TiendanubeClient, order_id: str, action: str, tracking_code="", tracking_url=""
) -> tuple[list, list]:
    """Aplica el cambio en cada fulfillment order. Devuelve (estados antes, estados después)."""
    fulfillment_orders = client.get(f"/orders/{order_id}/fulfillment-orders")
    before, after = [], []
    for fo in fulfillment_orders:
        current = fo.get("status") or ""
        target = _target_status(action, fo)
        before.append({"id": fo["id"], "status": current})
        if _already_there(current, target):
            after.append({"id": fo["id"], "status": current})
            continue
        path = f"/orders/{order_id}/fulfillment-orders/{fo['id']}"
        if target == "DELIVERED":
            client.post(f"{path}/tracking-events", json={"status": "delivered"})
        else:
            body = {"status": target}
            if target == "DISPATCHED" and (tracking_code or tracking_url):
                body["tracking_info"] = {"code": tracking_code, "url": tracking_url}
            client.patch(path, json=body)
        after.append({"id": fo["id"], "status": target})
    return before, after


@app.task(queue="integrations")
def tn_fulfillment_update(
    document_id: int,
    action: str,
    actor_id: int | None = None,
    tracking_code: str = "",
    tracking_url: str = "",
    attempt: int = 1,
):
    document = SalesDocument.objects.filter(pk=document_id).first()
    ref = ExternalRef.objects.filter(
        channel__code=CHANNEL, content_type__model="salesdocument", object_id=document_id
    ).first()
    if document is None or ref is None:
        logger.warning("Despacho TN: documento %s sin vínculo con Tiendanube", document_id)
        return
    try:
        before, after = apply_update(
            TiendanubeClient.from_credentials(), ref.external_id, action, tracking_code, tracking_url
        )
    except ChannelHTTPError as exc:
        logger.warning("Despacho TN falló (pedido %s, intento %s): %s", ref.external_id, attempt, exc)
        if attempt < MAX_ATTEMPTS:
            tn_fulfillment_update.configure(schedule_in={"seconds": BACKOFF_SECONDS[attempt - 1]}).defer(
                document_id=document_id,
                action=action,
                actor_id=actor_id,
                tracking_code=tracking_code,
                tracking_url=tracking_url,
                attempt=attempt + 1,
            )
        else:
            alerts.emit(
                "integration.write_failed",
                title=f"No se pudo marcar como «{ACTION_LABELS.get(action, action)}» el pedido TN #{ref.extra.get('number')}",
                body=f"Se reintentó {attempt} veces. {errors.friendly(exc)}",
                link_url="/integraciones/",
                dedupe_key=f"tn-fulfillment:{document_id}:{action}",
            )
        return
    if before == after:
        return  # ya estaba en ese estado: nada que auditar
    actor = get_user_model().objects.filter(pk=actor_id).first() if actor_id else None
    with transaction.atomic():
        ref.extra = {**ref.extra, "fulfillment_status": [a["status"] for a in after]}
        ref.save(update_fields=["extra", "updated_at"])
        audit.record(
            actor,
            "order.status_changed",
            document,
            before={"tiendanube": before},
            after={"tiendanube": after},
            action_tn=action,
            tracking_code=tracking_code,
        )
