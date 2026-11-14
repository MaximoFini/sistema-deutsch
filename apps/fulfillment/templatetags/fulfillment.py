from django import template

from apps.fulfillment import batches, labels

register = template.Library()


@register.filter
def qty(value) -> str:
    return batches.qty_text(value)


@register.inclusion_tag("fulfillment/_order_panel.html", takes_context=True)
def order_fulfillment(context, doc, shipments):
    """Bloque de preparación en la ficha del pedido: tanda, etiqueta o rótulo, "ya impresa"."""
    shipment = labels.label_shipment(doc, shipments)
    kind = labels.label_kind(shipment)
    return {
        "doc": doc,
        "shipment": shipment,
        "kind": kind,
        "batch": batches.active_batch_for(doc),
        "tn_url": labels.tn_admin_url(doc) if kind == "envio_nube" else "",
        "perms": context.get("perms"),
        "csrf_token": context.get("csrf_token"),
        "request": context.get("request"),
    }
