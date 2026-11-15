"""Reacciones de la tienda a los cambios de los pedidos mayoristas (sin que `sales` dependa de la tienda).

- Cancelado (desde M4, por vencimiento, por lo que sea): libera la reserva y devuelve el saldo usado.
- Despachado / Listo para retirar: email al cliente (con seguimiento o con el cobro en efectivo).
- Facturado en Contabilium: libera la reserva (desde ahí el stock lo descuenta Contabilium).
"""

import logging

from django.db import transaction

from apps.alerts import services as alerts
from apps.sales import states
from apps.sales.models import SalesDocument, Shipment

from . import mail, payments
from .accounts import store_url

logger = logging.getLogger(__name__)


def on_status_changed(sender, document, old, new, system=False, **kwargs):
    """Llega después del commit (ver `apps.sales.signals`). Nunca rompe la pantalla que cambió el estado."""
    if document.channel.code != "mayorista":
        return
    try:
        doc = SalesDocument.objects.select_related("channel", "customer").get(pk=document.pk)
        if new == states.CANCELLED:
            payments.on_cancelled(doc)
        elif new == states.DISPATCHED:
            _dispatched_email(doc)
        elif new == states.READY_FOR_PICKUP:
            _pickup_email(doc)
    except Exception:  # noqa: BLE001 - se registra y se alerta; el cambio de estado ya está hecho
        logger.exception("Falló la reacción de la tienda al cambio de estado de %s", document.pk)
        alerts.emit(
            "wholesale.contabilium_correction",
            title=f"Revisar {document.channel_reference}: no se pudo completar el cambio a «{states.label(new)}»",
            body="Puede haber quedado stock reservado o un email sin encolar. Avisale a soporte.",
            link_url=f"/pedidos/{document.pk}/",
            dedupe_key=f"signal-fail:{document.pk}:{new}",
        )


def _dispatched_email(doc: SalesDocument) -> None:
    shipment = doc.shipments.filter(method=Shipment.Method.CARRIER).first() or doc.shipments.first()
    mail.enqueue(
        "dispatched",
        payments.customer_email(doc),
        {
            "cliente": str(doc.customer),
            "pedido": doc.channel_reference,
            "transporte": (shipment.carrier_name if shipment else "") or "el expreso que elegiste",
            "seguimiento": (shipment.tracking_number if shipment else "")
            or "te lo pasamos apenas el expreso nos lo dé",
            "enlace": store_url("store:order_detail", doc.number),
        },
    )


def _pickup_email(doc: SalesDocument) -> None:
    pending = payments.cash_pending(doc)
    cobro = (
        f"Lo pagás en efectivo al retirarlo: {payments.money(doc.total)}."
        if pending is not None
        else "El pedido ya está pago."
    )
    mail.enqueue(
        "ready_for_pickup",
        payments.customer_email(doc),
        {
            "cliente": str(doc.customer),
            "pedido": doc.channel_reference,
            "total": payments.money(doc.total),
            "cobro": cobro,
            "enlace": store_url("store:order_detail", doc.number),
        },
    )


def on_invoice_changed(sender, document, invoiced, user=None, **kwargs):
    """Dentro de la transacción de `manual.update_invoice`."""
    if invoiced and document.channel.code == "mayorista":
        with transaction.atomic():
            payments.on_invoiced(document, user=user)
