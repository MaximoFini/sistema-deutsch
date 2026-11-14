"""Tareas de Tiendanube: importaciones, conciliaciones periódicas y privacidad."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.integrations import services
from apps.integrations.models import ChannelCredential

from . import catalog, orders, privacy
from .client import CHANNEL, TiendanubeClient


def _connected() -> bool:
    return ChannelCredential.objects.filter(channel__code=CHANNEL).exists()


@app.task(queue="integrations", queueing_lock="tn_import_catalog")
def tn_import_catalog():
    if not _connected():
        return
    client = TiendanubeClient.from_credentials()
    services.run_reconciliation(CHANNEL, job="catalog_full", fn=lambda since: catalog.import_all(client))


@app.task(queue="integrations", queueing_lock="tn_import_orders")
def tn_import_orders(days: int | None = None):
    if not _connected():
        return
    days = days or settings.TN_INITIAL_ORDER_DAYS
    client = TiendanubeClient.from_credentials()
    created_since = timezone.now() - timedelta(days=days)
    services.run_reconciliation(
        CHANNEL,
        job="orders_initial",
        fn=lambda since: orders.sync_orders(client, created_since=created_since),
    )


@app.periodic(cron=f"*/{settings.TN_ORDERS_RECONCILE_MINUTES} * * * *")
@app.task(queue="integrations", queueing_lock="tn_reconcile_orders")
def tn_reconcile_orders(timestamp: int):
    """Sin webhooks (local) es la vía principal de entrada de pedidos; con webhooks, la red de seguridad."""
    if not _connected():
        return
    client = TiendanubeClient.from_credentials()
    services.run_reconciliation(
        CHANNEL, job="orders", fn=lambda since: orders.sync_orders(client, updated_since=since)
    )


@app.periodic(cron="30 3 * * *")
@app.task(queue="integrations", queueing_lock="tn_reconcile_catalog")
def tn_reconcile_catalog(timestamp: int):
    """Diario: recorrido completo del catálogo (recupera cambios y borrados que no llegaron)."""
    if not _connected():
        return
    client = TiendanubeClient.from_credentials()
    services.run_reconciliation(CHANNEL, job="catalog", fn=lambda since: catalog.import_all(client))


@app.task(queue="integrations")
def tn_privacy(kind: str, payload: dict):
    privacy.handle(kind, payload)
