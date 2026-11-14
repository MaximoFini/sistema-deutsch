"""Alertas periódicas de pedidos (US-5): Flex/Colecta por vencer y manuales pendientes."""

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
    now = now or timezone.now()
    older = now - timedelta(hours=settings.ORDERS_MANUAL_PENDING_HOURS)
    count = 0
    # Solo los que todavía deben cobro o factura (no toda la historia de pedidos manuales).
    docs = (
        payments.annotate_paid(
            SalesDocument.objects.filter(
                channel__code="manual",
                doc_type=SalesDocument.DocType.ORDER,
                issued_at__lte=older,
            ).exclude(status=states.CANCELLED)
        )
        .filter(~payments.paid_q() | Q(invoiced_in_contabilium=False))
        .select_related("channel")
    )
    for doc in docs:
        unpaid = not payments.is_paid(doc)
        for reason, missing in (("pago", unpaid), ("factura", not doc.invoiced_in_contabilium)):
            if missing and alerts.emit(
                "orders.manual_pending",
                title=f"{doc.channel_reference} sin {'cobrar' if reason == 'pago' else 'facturar en Contabilium'}",
                body=f"Cargado el {timezone.localtime(doc.issued_at):%d/%m %H:%M}. Total ${doc.total}.",
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
