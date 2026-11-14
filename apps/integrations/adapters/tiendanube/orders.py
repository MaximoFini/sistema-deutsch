"""Pedidos de Tiendanube → SalesDocument (upsert idempotente con control de frescura)."""

import logging

from django.db import transaction
from django.utils import timezone

from apps.alerts import services as alerts
from apps.catalog.models import Variant
from apps.customers.models import Address, Customer
from apps.integrations.models import Channel, ExternalRef
from apps.integrations.services import find_by_external, link_external
from apps.sales.models import Payment, SalesDocument, SalesLine, Shipment

from .client import CHANNEL
from .common import dec, dt, normalize, text

logger = logging.getLogger(__name__)

PAYMENT_STATUS = {
    "paid": Payment.Status.CONFIRMED,
    "pending": Payment.Status.PENDING,
    "authorized": Payment.Status.PENDING,
    "partially_paid": Payment.Status.PENDING,
    "abandoned": Payment.Status.REJECTED,
    "voided": Payment.Status.REJECTED,
    "refunded": Payment.Status.REFUNDED,
    "partially_refunded": Payment.Status.REFUNDED,
}


def payment_method(order: dict) -> str:
    gateway = normalize(f"{order.get('gateway') or ''} {order.get('gateway_name') or ''}")
    if "mercado" in gateway or "mercadopago" in gateway.replace(" ", ""):
        return Payment.Method.MERCADOPAGO
    if any(w in gateway for w in ("transfer", "deposit", "offline", "wire")):
        return Payment.Method.TRANSFER
    if any(w in gateway for w in ("cash", "efectivo")):
        return Payment.Method.CASH
    return Payment.Method.OTHER


def shipping_method(order: dict) -> str:
    if order.get("shipping_pickup_type") == "pickup":
        return Shipment.Method.PICKUP
    haystack = normalize(
        " ".join(
            str(order.get(k) or "")
            for k in ("shipping_option_code", "shipping_option", "shipping", "shipping_option_reference")
        )
    )
    compact = haystack.replace(" ", "")
    if "envionube" in compact or "nuvemenvio" in compact or "enviosnube" in compact:
        return Shipment.Method.ENVIO_NUBE
    return Shipment.Method.CARRIER


def _tax_id(identification: str) -> tuple[str, str]:
    digits = "".join(ch for ch in (identification or "") if ch.isdigit())
    if len(digits) == 11:
        return Customer.TaxIdType.CUIT, digits
    if digits:
        return Customer.TaxIdType.DNI, digits
    return Customer.TaxIdType.CF, ""


def upsert_customer(order: dict) -> Customer | None:
    tn_customer = order.get("customer") or {}
    email = (order.get("contact_email") or tn_customer.get("email") or "").strip().lower()
    name = order.get("contact_name") or tn_customer.get("name") or order.get("billing_name") or ""
    phone = order.get("contact_phone") or tn_customer.get("phone") or ""
    identification = order.get("contact_identification") or tn_customer.get("identification") or ""
    if not (email or name or tn_customer.get("id")):
        return None

    customer = find_by_external(CHANNEL, Customer, tn_customer["id"]) if tn_customer.get("id") else None
    if customer is None and email:
        customer = Customer.objects.filter(email__iexact=email).order_by("id").first()
    tax_type, tax_id = _tax_id(identification)
    if customer is None:
        customer = Customer.objects.create(
            kind=Customer.Kind.RETAIL,
            legal_name=(name or email)[:255],
            email=email,
            phone=phone[:50],
            tax_id_type=tax_type,
            tax_id=tax_id,
        )
    else:
        # Solo completa lo vacío: no pisa datos cargados a mano.
        changed = []
        for field, value in (
            ("legal_name", name),
            ("email", email),
            ("phone", phone[:50]),
            ("tax_id", tax_id),
        ):
            if value and not getattr(customer, field):
                setattr(customer, field, value)
                changed.append(field)
        if "tax_id" in changed:
            customer.tax_id_type = tax_type
            changed.append("tax_id_type")
        if changed:
            customer.save(update_fields=[*changed, "updated_at"])
    if tn_customer.get("id"):
        link_external(CHANNEL, customer, tn_customer["id"])

    addr = order.get("shipping_address") or {}
    if addr.get("address"):
        Address.objects.get_or_create(
            customer=customer,
            kind=Address.Kind.SHIPPING,
            street=(addr.get("address") or "")[:255],
            number=str(addr.get("number") or "")[:20],
            defaults={
                "floor": str(addr.get("floor") or "")[:50],
                "city": (addr.get("city") or addr.get("locality") or "")[:100],
                "province": (addr.get("province") or "")[:100],
                "postal_code": str(addr.get("zipcode") or "")[:10],
                "country": (addr.get("country") or "AR")[:2],
            },
        )
    return customer


def _variant_for_line(line: dict) -> Variant | None:
    if line.get("variant_id"):
        variant = find_by_external(CHANNEL, Variant, line["variant_id"])
        if variant:
            return variant
    sku = (line.get("sku") or "").strip()
    return Variant.objects.filter(sku=sku).first() if sku else None


def _is_newer(ref: ExternalRef | None, order: dict) -> bool:
    if ref is None:
        return True
    stored, incoming = dt(ref.extra.get("updated_at")), dt(order.get("updated_at"))
    if stored is None or incoming is None:
        return True
    return incoming > stored


@transaction.atomic
def upsert_order(order: dict) -> SalesDocument:
    ref = (
        ExternalRef.objects.select_for_update()
        .filter(channel__code=CHANNEL, content_type__model="salesdocument", external_id=str(order["id"]))
        .first()
    )
    if ref is not None and not _is_newer(ref, order):
        return SalesDocument.objects.get(pk=ref.object_id)  # evento viejo: no pisa datos nuevos

    document = SalesDocument.objects.get(pk=ref.object_id) if ref else None
    customer = upsert_customer(order)
    values = {
        "customer": customer,
        "channel_status": f"{order.get('status')}/{order.get('payment_status')}/{order.get('shipping_status')}"[
            :60
        ],
        "issued_at": dt(order.get("created_at")) or timezone.now(),
        "currency": (order.get("currency") or "ARS")[:3],
        "subtotal": dec(order.get("subtotal"), 0),
        "discount_total": dec(order.get("discount"), 0),
        "shipping_total": dec(order.get("shipping_cost_customer"), 0),
        "total": dec(order.get("total"), 0),
        "notes": order.get("note") or "",
    }
    if document is None:
        document = SalesDocument.objects.create(
            doc_type=SalesDocument.DocType.ORDER,
            channel=Channel.objects.get(code=CHANNEL),
            status="new",
            **values,
        )
    else:
        for key, value in values.items():  # el estado interno (status) es de M4: no se toca
            setattr(document, key, value)
        document.save()

    # Líneas, pagos y envíos: se reemplazan por la versión de Tiendanube.
    document.lines.all().delete()
    for line in order.get("products") or []:
        variant = _variant_for_line(line)
        sku = (line.get("sku") or "").strip()
        description = text(line.get("name"))
        variant_values = line.get("variant_values") or []
        if variant_values and isinstance(variant_values, list):
            extra = " / ".join(text(v) for v in variant_values if v)
            if extra and extra not in description:
                description = f"{description} ({extra})"
        SalesLine.objects.create(
            document=document,
            variant=variant,
            sku_snapshot=sku[:64] or (variant.sku if variant else ""),
            description_snapshot=description[:300],
            quantity=dec(line.get("quantity"), 0),
            unit_price=dec(line.get("price"), 0),
        )
        if variant is None:
            key = sku or f"tn-variant-{line.get('variant_id')}"
            alerts.emit(
                "catalog.unknown_sku",
                title=f"Pedido TN #{order.get('number')} con SKU desconocido: {key}",
                body=f"La línea «{description}» no coincide con ningún producto del catálogo.",
                link_url="/integraciones/",
                dedupe_key=key,
            )

    document.payments.filter(external_reference__startswith="tn:").delete()
    Payment.objects.create(
        document=document,
        method=payment_method(order),
        amount=dec(order.get("total"), 0),
        status=PAYMENT_STATUS.get(order.get("payment_status"), Payment.Status.PENDING),
        paid_at=dt(order.get("paid_at")),
        external_reference=f"tn:{order.get('gateway') or ''}"[:100],
    )

    document.shipments.all().delete()
    if order.get("shipping_pickup_type") or order.get("shipping_option") or order.get("shipping_address"):
        Shipment.objects.create(
            document=document,
            method=shipping_method(order),
            carrier_name=text(order.get("shipping_option"))[:100],
            tracking_number=(order.get("shipping_tracking_number") or "")[:100],
            status=order.get("shipping_status") or "pending",
            address=order.get("shipping_address") or None,
        )

    previous = ref.extra if ref else {}
    link_external(
        CHANNEL,
        document,
        order["id"],
        {
            **previous,
            "number": order.get("number"),
            "updated_at": order.get("updated_at"),
            "token": order.get("token"),
        },
    )
    return document


def sync_orders(client, updated_since=None, created_since=None) -> dict:
    params = {}
    if updated_since:
        params["updated_at_min"] = updated_since.isoformat()
    if created_since:
        params["created_at_min"] = created_since.isoformat()
    stats = {"orders": 0, "errors": []}
    for order in client.get_all("/orders", params):
        try:
            upsert_order(order)
            stats["orders"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error importando el pedido TN %s", order.get("id"))
            stats["errors"].append({"id": order.get("id"), "error": f"{type(exc).__name__}: {exc}"[:300]})
    return stats
