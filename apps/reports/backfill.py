"""Backfills de M7 (§1 del diseño). Se pueden repetir: cada corrida deja el mismo resultado.

- `timestamps`: `ready_at` y `dispatched_at` desde la auditoría de cambios de estado.
- `stock`: `on_hand_after` reconstruido hacia atrás desde el saldo actual.
- `ml_fees`: comisiones y costos de envío de las ventas de ML con neto pendiente (solo lecturas a ML).
"""

import logging

from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.db.models import CharField, Exists, F, OuterRef, Subquery
from django.db.models.functions import Cast

from apps.audit.models import AuditLog
from apps.sales import states
from apps.sales.models import SalesDocument, Shipment

logger = logging.getLogger(__name__)

DISPATCH_STATES = [states.DISPATCHED, states.READY_FOR_PICKUP]


# ── Momentos del pedido ───────────────────────────────────────────────────


def _status_audits(after: list[str], before: list[str] | None = None):
    ct = ContentType.objects.get_for_model(SalesDocument)
    qs = AuditLog.objects.filter(
        action="order.status_changed",
        content_type=ct,
        object_id=Cast(OuterRef("pk"), output_field=CharField()),
        after__estado__in=after,
    )
    if before is not None:
        qs = qs.filter(before__estado__in=before)
    return qs


def _first(audits) -> Subquery:
    return Subquery(audits.order_by("created_at", "id").values("created_at")[:1])


@transaction.atomic
def backfill_timestamps() -> dict:
    """Completa solo lo vacío (no pisa lo que ya fijó `change_status`). Devuelve cuántos llenó."""
    orders = SalesDocument.objects.filter(doc_type=SalesDocument.DocType.ORDER)
    empty_ready = orders.filter(ready_at__isnull=True)
    empty_dispatched = orders.filter(dispatched_at__isnull=True)
    before = {"ready_at": empty_ready.count(), "dispatched_at": empty_dispatched.count()}

    # Listo para preparar: cuando se confirmó el pago (Esperando pago → Nuevo) …
    paid = _status_audits([states.NEW], [states.AWAITING_PAYMENT])
    empty_ready.filter(Exists(paid)).update(ready_at=_first(paid))
    # … o, si nunca esperó pago, desde que entró (un "volver a Nuevo" posterior no cuenta).
    (
        orders.filter(ready_at__isnull=True)
        .exclude(status=states.AWAITING_PAYMENT)
        .exclude(Exists(_status_audits([states.AWAITING_PAYMENT])))
        .update(ready_at=F("issued_at"))
    )

    # Despachado: la primera vez que pasó a Despachado o Listo para retirar …
    out = _status_audits(DISPATCH_STATES)
    empty_dispatched.filter(Exists(out)).update(dispatched_at=_first(out))
    # … sin auditoría y todavía en ese estado: el último cambio de estado fue la salida …
    orders.filter(
        dispatched_at__isnull=True, status__in=DISPATCH_STATES, status_changed_at__isnull=False
    ).update(dispatched_at=F("status_changed_at"))
    # … y si ya se entregó, vale la fecha de salida que informó el canal (si no hay, queda vacío).
    shipped = Shipment.objects.filter(document=OuterRef("pk"), shipped_at__isnull=False)
    orders.filter(dispatched_at__isnull=True, status=states.DELIVERED).filter(Exists(shipped)).update(
        dispatched_at=Subquery(shipped.order_by("shipped_at").values("shipped_at")[:1])
    )
    return {
        "ready_at": before["ready_at"] - orders.filter(ready_at__isnull=True).count(),
        "dispatched_at": before["dispatched_at"] - orders.filter(dispatched_at__isnull=True).count(),
    }


# ── Historial de stock ────────────────────────────────────────────────────

STOCK_SQL = """
UPDATE inventory_stockmovement AS m
SET on_hand_after = calc.after
FROM (
    SELECT mv.id,
           lv.on_hand - COALESCE(SUM(mv.quantity) OVER (
               PARTITION BY mv.variant_id, mv.warehouse_id
               ORDER BY mv.created_at DESC, mv.id DESC
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
           ), 0) AS after
    FROM inventory_stockmovement mv
    JOIN inventory_stocklevel lv
      ON lv.variant_id = mv.variant_id AND lv.warehouse_id = mv.warehouse_id
    WHERE mv.affects = 'on_hand'
) AS calc
WHERE m.id = calc.id AND m.on_hand_after IS DISTINCT FROM calc.after
"""


@transaction.atomic
def backfill_stock() -> int:
    """Reconstruye `on_hand_after` desde el saldo actual restando los deltas en orden inverso.

    El último movimiento queda con el saldo actual; el anterior, con saldo − delta del último; etc.
    Devuelve cuántos movimientos cambiaron (0 en una segunda corrida).
    """
    with connection.cursor() as cursor:
        cursor.execute(STOCK_SQL)
        return cursor.rowcount


# ── Comisiones y costos de envío de ML ───────────────────────────────────


def pending_ml_documents():
    return (
        SalesDocument.objects.filter(
            channel__code="mercadolibre", doc_type=SalesDocument.DocType.ORDER, net_pending=True
        )
        .exclude(status=states.CANCELLED)  # una venta cancelada no suma: no hace falta su neto
        .order_by("pk")
    )


class Disconnected(Exception):
    """ML no está conectado o el token no se pudo renovar: la corrida se corta y sigue mañana."""


def _order_ids(doc: SalesDocument) -> list[str]:
    from apps.integrations.models import ExternalRef

    refs = ExternalRef.objects.filter(
        channel__code="mercadolibre",
        content_type__model="salesdocument",
        object_id=doc.pk,
        external_id__startswith="order:",
    ).values_list("external_id", flat=True)
    return [r.split(":", 1)[1] for r in refs]


def complete_document(client, doc: SalesDocument) -> bool:
    """Lee de ML lo que falta de una venta. Devuelve si quedó completa."""
    from apps.integrations.adapters.mercadolibre import orders, shipments

    if doc.lines.filter(channel_fee__isnull=True).exists():
        for order_id in _order_ids(doc):
            orders.upsert_order(client.get(f"/orders/{order_id}"), force=True)
    doc.refresh_from_db()
    for shipment in doc.shipments.exclude(external_id="").filter(seller_cost__isnull=True):
        shipments.fetch_seller_cost(client, shipment)
    orders.refresh_net_pending(doc)
    return not doc.net_pending


def backfill_ml_fees(client, batch_size: int = 50, max_batches: int | None = None) -> dict:
    """Recorre las ventas de ML con neto pendiente en tandas de `batch_size`.

    El límite de la API lo respeta el cliente (token bucket de M0 en cada pedido). Una venta que
    falla queda pendiente para la próxima corrida; si ML se desconecta, se corta todo.
    """
    from apps.integrations.adapters.mercadolibre import auth
    from apps.integrations.credentials import CredentialsMissing

    stats = {"completed": 0, "still_pending": 0, "errors": [], "stopped": ""}
    last_pk = 0
    batches = 0
    while max_batches is None or batches < max_batches:
        batch = list(pending_ml_documents().filter(pk__gt=last_pk)[:batch_size])
        if not batch:
            break
        batches += 1
        for doc in batch:
            last_pk = doc.pk
            try:
                if complete_document(client, doc):
                    stats["completed"] += 1
                else:
                    stats["still_pending"] += 1
            except (CredentialsMissing, auth.TokenRevoked, auth.TokenRefreshError, TimeoutError) as exc:
                stats["stopped"] = f"{type(exc).__name__}: {exc}"[:300]
                logger.warning("Backfill de comisiones ML cortado: %s", exc)
                return stats
            except Exception as exc:  # noqa: BLE001 — una venta con problemas no frena las demás
                logger.info("Comisiones de %s no disponibles: %s", doc.channel_reference, exc)
                stats["errors"].append({"id": doc.pk, "error": f"{type(exc).__name__}: {exc}"[:300]})
    return stats


def enqueue_ml_fees_after_migrate(sender, using="default", **kwargs):
    """Al migrar, si ML está conectado y hay ventas con neto pendiente, encola el backfill.

    Nunca rompe el migrate: si la cola no está disponible, queda la corrida diaria.
    """
    try:
        from apps.integrations.models import ChannelCredential

        if not ChannelCredential.objects.using(using).filter(channel__code="mercadolibre").exists():
            return
        if not pending_ml_documents().using(using).exists():
            return
        from .tasks import reports_ml_fees

        reports_ml_fees.configure(queueing_lock="reports_ml_fees").defer(timestamp=0)
    except Exception as exc:  # noqa: BLE001
        logger.info("No se encoló el backfill de comisiones ML al migrar: %s", exc)
