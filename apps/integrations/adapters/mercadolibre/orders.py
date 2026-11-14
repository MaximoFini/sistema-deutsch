"""Órdenes de Mercado Libre → pedidos (un SalesDocument por pack).

Cada orden guarda un snapshot en su ExternalRef ("order:{id}"). El documento se reconstruye siempre
desde los snapshots de TODAS sus órdenes, así el orden de llegada y los duplicados no importan.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.alerts import services as alerts
from apps.catalog.models import Variant
from apps.customers.models import Customer
from apps.integrations.models import Channel, ExternalRef
from apps.integrations.services import find_by_external, link_external
from apps.sales.models import Payment, SalesDocument, SalesLine

from . import listings
from .common import dec, dt

logger = logging.getLogger(__name__)
CHANNEL = "mercadolibre"

PAYMENT_STATUS = {
    "approved": Payment.Status.CONFIRMED,
    "accredited": Payment.Status.CONFIRMED,
    "pending": Payment.Status.PENDING,
    "in_process": Payment.Status.PENDING,
    "authorized": Payment.Status.PENDING,
    "in_mediation": Payment.Status.PENDING,
    "rejected": Payment.Status.REJECTED,
    "cancelled": Payment.Status.REJECTED,
    "refunded": Payment.Status.REFUNDED,
    "charged_back": Payment.Status.REFUNDED,
}


def _snapshot(order: dict) -> dict:
    return {
        "date_last_updated": order.get("date_last_updated"),
        "date_created": order.get("date_created"),
        "status": order.get("status"),
        "tags": order.get("tags") or [],
        "pack_id": order.get("pack_id"),
        "total_amount": str(order.get("total_amount") or 0),
        "paid_amount": str(order.get("paid_amount") or 0),
        "currency": order.get("currency_id") or "ARS",
        "shipping_id": (order.get("shipping") or {}).get("id"),
        "buyer": order.get("buyer") or {},
        "items": [
            {
                "item_id": (oi.get("item") or {}).get("id"),
                "variation_id": (oi.get("item") or {}).get("variation_id"),
                "title": (oi.get("item") or {}).get("title") or "",
                "seller_sku": (oi.get("item") or {}).get("seller_sku") or "",
                "variation_attributes": (oi.get("item") or {}).get("variation_attributes") or [],
                "quantity": oi.get("quantity") or 0,
                "unit_price": str(oi.get("unit_price") or 0),
            }
            for oi in order.get("order_items") or []
        ],
        "payments": [
            {
                "id": p.get("id"),
                "status": p.get("status"),
                "amount": str(p.get("transaction_amount") or 0),
                "date_approved": p.get("date_approved"),
            }
            for p in order.get("payments") or []
        ],
    }


def document_key(order: dict) -> str:
    return f"pack:{order['pack_id']}" if order.get("pack_id") else f"order:{order['id']}"


def find_document(order_id) -> SalesDocument | None:
    ref = ExternalRef.objects.filter(
        channel__code=CHANNEL, content_type__model="salesdocument", external_id=f"order:{order_id}"
    ).first()
    return SalesDocument.objects.filter(pk=ref.object_id).first() if ref else None


def _customer(buyer: dict) -> Customer | None:
    if not buyer.get("id"):
        return None
    customer = find_by_external(CHANNEL, Customer, buyer["id"])
    nickname = buyer.get("nickname") or ""
    full_name = " ".join(x for x in (buyer.get("first_name"), buyer.get("last_name")) if x).strip()
    if customer is None:
        customer = Customer.objects.create(
            kind=Customer.Kind.RETAIL,
            legal_name=(full_name or nickname or f"Comprador ML {buyer['id']}")[:255],
            trade_name=nickname[:255],
        )
        link_external(CHANNEL, customer, buyer["id"], {"nickname": nickname})
    elif not customer.trade_name and nickname:
        customer.trade_name = nickname[:255]
        customer.save(update_fields=["trade_name", "updated_at"])
    return customer


def _channel_status(snapshots: list[dict], document: SalesDocument) -> str:
    statuses = sorted({s.get("status") or "?" for s in snapshots})
    status = statuses[0] if len(statuses) == 1 else ",".join(statuses)
    tags = {t for s in snapshots for t in s.get("tags") or []}
    for tag in ("delivered", "not_delivered"):
        if tag in tags:
            status += f"+{tag}"
    shipment = document.shipments.exclude(external_id="").first()
    if shipment is not None and shipment.status:
        status += f"/{shipment.status}"
    return status[:60]


def refresh_channel_status(document: SalesDocument) -> None:
    snapshots = [r.extra for r in _order_refs(document)]
    document.channel_status = _channel_status(snapshots, document)
    document.save(update_fields=["channel_status", "updated_at"])


def _order_refs(document: SalesDocument):
    return ExternalRef.objects.filter(
        channel__code=CHANNEL,
        content_type__model="salesdocument",
        object_id=document.pk,
        external_id__startswith="order:",
    ).order_by("external_id")


def rebuild(document: SalesDocument) -> None:
    refs = list(_order_refs(document))
    snapshots = [r.extra for r in refs]
    document.lines.all().delete()
    subtotal = Decimal(0)
    for ref, snap in zip(refs, snapshots, strict=True):
        for item in snap.get("items") or []:
            variant = listings.variant_for(item["item_id"], item.get("variation_id"))
            if variant is None and item.get("seller_sku"):
                variant = Variant.objects.filter(sku=item["seller_sku"]).first()
            attrs = " / ".join(
                str(a.get("value_name"))
                for a in item.get("variation_attributes") or []
                if a.get("value_name")
            )
            description = f"{item['title']} ({attrs})" if attrs else item["title"]
            line = SalesLine.objects.create(
                document=document,
                variant=variant,
                sku_snapshot=(item.get("seller_sku") or (variant.sku if variant else ""))[:64],
                description_snapshot=description[:300],
                quantity=dec(item.get("quantity"), 0),
                unit_price=dec(item.get("unit_price"), 0),
            )
            subtotal += line.line_total
            if variant is None:
                key = item.get("seller_sku") or f"ml-item-{item['item_id']}:{item.get('variation_id') or ''}"
                alerts.emit(
                    "catalog.unknown_sku",
                    title=f"Venta ML {ref.external_id.split(':')[1]} con SKU desconocido: {key}",
                    body=f"La línea «{description}» no coincide con ningún producto del catálogo.",
                    link_url="/integraciones/",
                    dedupe_key=key,
                )
    document.payments.filter(external_reference__startswith="ml:").delete()
    for snap in snapshots:
        for p in snap.get("payments") or []:
            Payment.objects.create(
                document=document,
                method=Payment.Method.MERCADOPAGO,
                amount=dec(p.get("amount"), 0),
                status=PAYMENT_STATUS.get(p.get("status"), Payment.Status.PENDING),
                paid_at=dt(p.get("date_approved")),
                external_reference=f"ml:{p.get('id')}",
            )
    document.subtotal = subtotal.quantize(Decimal("0.01"))
    document.discount_total = Decimal(0)
    document.shipping_total = Decimal(0)  # en ML el envío lo cobra ML
    document.total = sum((dec(s.get("total_amount"), Decimal(0)) for s in snapshots), Decimal(0)).quantize(
        Decimal("0.01")
    )
    document.currency = snapshots[0].get("currency", "ARS") if snapshots else "ARS"
    created = [dt(s.get("date_created")) for s in snapshots if s.get("date_created")]
    if created:
        document.issued_at = min(created)
    if snapshots and document.customer_id is None:
        document.customer = _customer(snapshots[0].get("buyer") or {})
    document.channel_status = _channel_status(snapshots, document)
    document.save()


def _is_newer(ref: ExternalRef | None, order: dict) -> bool:
    if ref is None:
        return True
    stored, incoming = dt(ref.extra.get("date_last_updated")), dt(order.get("date_last_updated"))
    if stored is None or incoming is None:
        return True
    return incoming > stored


@transaction.atomic
def upsert_order(order: dict) -> tuple[SalesDocument, bool]:
    """Devuelve (documento, cambió). Si la orden no es más nueva que la guardada, no escribe nada."""
    order_key = f"order:{order['id']}"
    order_ref = (
        ExternalRef.objects.select_for_update()
        .filter(channel__code=CHANNEL, content_type__model="salesdocument", external_id=order_key)
        .first()
    )
    if order_ref is not None and not _is_newer(order_ref, order):
        return SalesDocument.objects.get(pk=order_ref.object_id), False
    key = document_key(order)
    document = None
    if order_ref is not None:
        document = SalesDocument.objects.get(pk=order_ref.object_id)
    else:
        key_ref = ExternalRef.objects.filter(
            channel__code=CHANNEL, content_type__model="salesdocument", external_id=key
        ).first()
        if key_ref is not None:
            document = SalesDocument.objects.get(pk=key_ref.object_id)
    if document is None:
        document = SalesDocument.objects.create(
            doc_type=SalesDocument.DocType.ORDER,
            channel=Channel.objects.get(code=CHANNEL),
            status="new",
            issued_at=dt(order.get("date_created")) or timezone.now(),
            customer=_customer(order.get("buyer") or {}),
        )
    link_external(CHANNEL, document, key, {"kind": "pack" if order.get("pack_id") else "order"})
    link_external(CHANNEL, document, order_key, _snapshot(order))
    rebuild(document)
    return document, True


def process_order(client, order: dict, refresh_related: bool = True) -> SalesDocument:
    from . import billing, shipments

    document, changed = upsert_order(order)
    if changed and refresh_related:
        shipping_id = (order.get("shipping") or {}).get("id")
        if shipping_id:
            shipments.refresh(client, shipping_id)
        billing.refresh(client, order["id"], document)
    return document


def refresh(client, order_id) -> SalesDocument:
    return process_order(client, client.get(f"/orders/{order_id}"))


def sync_orders(client, updated_since=None, created_since=None, window=timedelta(hours=48)) -> dict:
    params = {"seller": client.user_id, "sort": "date_desc"}
    if created_since is not None:
        params["order.date_created.from"] = created_since.isoformat()
    else:
        start = timezone.now() - window
        if updated_since is not None:
            start = min(start, updated_since)
        params["order.date_last_updated.from"] = start.isoformat()
    stats = {"orders": 0, "errors": []}
    for order in client.search_offset("/orders/search", params):
        try:
            process_order(client, order)
            stats["orders"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error importando la orden ML %s", order.get("id"))
            stats["errors"].append({"id": order.get("id"), "error": f"{type(exc).__name__}: {exc}"[:300]})
    return stats
