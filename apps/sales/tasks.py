"""Alertas periódicas de pedidos (US-5): Flex/Colecta por vencer y manuales o mayoristas pendientes."""

from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.alerts import services as alerts

from . import payments, states
from .models import SalesDocument, Shipment

DEADLINE_METHODS = [Shipment.Method.ME_FLEX, Shipment.Method.ME_COLECTA]
NOT_DISPATCHED = [states.NEW, states.PREPARING, states.READY, states.AWAITING_CUSTOMER]


def check_flex_due(now=None) -> int:
    now = now or timezone.now()
    limit = now + timedelta(minutes=settings.ORDERS_FLEX_WARNING_MINUTES)
    count = 0
    shipments = Shipment.objects.filter(
        method__in=DEADLINE_METHODS,
        dispatch_deadline__isnull=False,
        dispatch_deadline__lte=limit,
        document__status__in=NOT_DISPATCHED,
        document__doc_type=SalesDocument.DocType.ORDER,
    ).select_related("document")
    for shipment in shipments:
        doc = shipment.document
        minutes = int((shipment.dispatch_deadline - now).total_seconds() // 60)
        when = f"en {minutes} min" if minutes >= 0 else f"hace {-minutes} min (vencido)"
        local = timezone.localtime(shipment.dispatch_deadline)
        if alerts.emit(
            "orders.flex_due",
            title=f"{doc.channel_reference}: despachar antes de las {local:%H:%M} ({when})",
            body=f"Estado actual: {states.label(doc.status)}. Modalidad: {shipment.get_method_display()}.",
            link_url=f"/pedidos/{doc.pk}/",
            dedupe_key=f"flex:{shipment.pk}:{shipment.dispatch_deadline:%Y%m%d%H%M}",
        ):
            count += 1
    return count


def check_manual_pending(now=None) -> int:
    """Pedidos manuales y (M8a) mayoristas confirmados que siguen sin cobrar o sin facturar.

    Un mayorista sin «Facturado en Contabilium» mantiene la reserva de stock: si nadie lo marca, esa
    mercadería queda descontada de la tienda para siempre. Para el mayorista cuenta desde que quedó
    confirmado (entró en Nuevo); los que esperan la transferencia no avisan.
    """
    now = now or timezone.now()
    older = now - timedelta(hours=settings.ORDERS_MANUAL_PENDING_HOURS)
    count = 0
    manual = Q(channel__code="manual", issued_at__lte=older)
    confirmed_before = Q(ready_at__lte=older) | Q(ready_at__isnull=True, issued_at__lte=older)
    wholesale = Q(channel__code="mayorista") & confirmed_before & ~Q(status=states.AWAITING_PAYMENT)
    # Solo los que todavía deben cobro o factura (no toda la historia de pedidos).
    docs = (
        payments.annotate_paid(
            SalesDocument.objects.filter(manual | wholesale, doc_type=SalesDocument.DocType.ORDER).exclude(
                status=states.CANCELLED
            )
        )
        .filter(~payments.paid_q() | Q(invoiced_in_contabilium=False))
        .select_related("channel", "wholesale")
    )
    for doc in docs:
        is_wholesale = doc.channel.code == "mayorista"
        wholesale_order = getattr(doc, "wholesale", None) if is_wholesale else None
        # La cuenta corriente se cobra después por definición: avisar "sin cobrar" sería ruido.
        on_account = wholesale_order is not None and wholesale_order.payment_method == "account"
        unpaid = not payments.is_paid(doc) and not on_account
        since = timezone.localtime((doc.ready_at if is_wholesale else None) or doc.issued_at)
        # La referencia ya nombra el canal ("Manual #12", "Mayorista #40").
        ref = doc.channel_reference or f"Pedido {doc.channel.name} {doc.number}"
        when = "Pedido mayorista confirmado" if is_wholesale else "Cargado"
        body = f"{when} el {since:%d/%m %H:%M}. Total ${doc.total}."
        for reason, missing in (("pago", unpaid), ("factura", not doc.invoiced_in_contabilium)):
            if not missing:
                continue
            what = "cobrar" if reason == "pago" else "facturar en Contabilium"
            extra = ""
            if is_wholesale and reason == "factura":
                extra = " Mientras no se marque «Facturado en Contabilium», la mercadería sigue reservada en la tienda."
            if alerts.emit(
                "orders.manual_pending",
                title=f"{ref} sin {what}",
                body=body + extra,
                link_url=f"/pedidos/{doc.pk}/",
                dedupe_key=f"manual:{doc.pk}:{reason}",
            ):
                count += 1
    return count


@app.periodic(cron="*/5 * * * *")
@app.task(queue="default", queueing_lock="orders_watch")
def orders_watch(timestamp: int):
    check_flex_due()
    check_manual_pending()
