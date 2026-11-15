"""Bloque mayorista en la ficha del pedido del panel (M4): quién lo cargó, pago, comprobantes, efectivo,
faltantes, reserva y corrección en Contabilium. En los demás canales no hace ninguna consulta."""

from django import template

from apps.sales import states
from apps.wholesale import payments
from apps.wholesale.models import StoreSettings, WholesaleOrder

register = template.Library()


@register.inclusion_tag("wholesale/_order_panel.html", takes_context=True)
def wholesale_order(context, doc):
    base = {"show": False}
    if doc.channel.code != "mayorista":
        return base
    order = payments.order_of(doc)
    if order is None:
        return base
    perms = context.get("perms")
    transfer = order.payment_method == WholesaleOrder.PaymentMethod.TRANSFER
    store = StoreSettings.load()
    shortages = list(doc.shortages.order_by("-created_at"))
    return {
        "show": True,
        "doc": doc,
        "order": order,
        "placed_by": order.placed_by,
        "transfer": transfer,
        "awaiting_payment": transfer and doc.status == states.AWAITING_PAYMENT,
        "receipts": list(doc.receipts.select_related("uploaded_by")) if transfer else [],
        "cash_pending": payments.cash_pending(doc),
        "bank_missing": transfer and not store.bank_details.strip(),
        "open_shortages": [s for s in shortages if s.resolved_at is None],
        "resolved_shortages": [s for s in shortages if s.resolved_at is not None],
        "can_report": doc.status == states.PREPARING,
        "can_resolve": doc.status == states.AWAITING_CUSTOMER
        and any(s.resolved_at is None for s in shortages),
        "perms": perms,
        "csrf_token": context.get("csrf_token"),
        "request": context.get("request"),
    }
