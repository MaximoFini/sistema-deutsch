"""Tareas de Mercado Libre: token, importaciones y conciliaciones periódicas."""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.integrations import services
from apps.integrations.models import ChannelCredential

from . import auth, claims, listings, messages, orders, questions, shipments
from .client import CHANNEL, MLClient

logger = logging.getLogger(__name__)
EVERY = f"*/{settings.ML_POLL_MINUTES} * * * *"


def _connected() -> bool:
    return ChannelCredential.objects.filter(channel__code=CHANNEL).exists()


def _run(job: str, fn):
    if not _connected():
        return None
    client = MLClient()
    return services.run_reconciliation(CHANNEL, job=job, fn=lambda since: fn(client, since))


@app.periodic(cron="*/30 * * * *")
@app.task(queue="integrations", queueing_lock="ml_refresh_token")
def ml_refresh_token(timestamp: int, attempt: int = 1):
    if not _connected():
        return
    try:
        auth.refresh_if_needed()
    except auth.TokenRefreshError as exc:
        logger.warning("Renovación de token ML falló (intento %s): %s", attempt, exc)
        if attempt < 3:
            ml_refresh_token.configure(schedule_in={"minutes": 2 * attempt}, queueing_lock=None).defer(
                timestamp=timestamp, attempt=attempt + 1
            )
    except auth.TokenRevoked:
        pass  # disconnect() ya emitió la alerta


@app.task(queue="integrations", queueing_lock="ml_import_listings")
def ml_import_listings():
    _run("listings_full", lambda client, since: listings.import_all(client))


@app.task(queue="integrations", queueing_lock="ml_import_orders")
def ml_import_orders(days: int | None = None):
    created_since = timezone.now() - timedelta(days=days or settings.ML_INITIAL_ORDER_DAYS)
    _run("orders_initial", lambda client, since: orders.sync_orders(client, created_since=created_since))


@app.periodic(cron=EVERY)
@app.task(queue="integrations", queueing_lock="ml_reconcile_orders")
def ml_reconcile_orders(timestamp: int):
    _run("orders", lambda client, since: orders.sync_orders(client, updated_since=since))


@app.periodic(cron=EVERY)
@app.task(queue="integrations", queueing_lock="ml_reconcile_questions")
def ml_reconcile_questions(timestamp: int):
    _run("questions", lambda client, since: questions.sync_unanswered(client))


@app.periodic(cron=EVERY)
@app.task(queue="integrations", queueing_lock="ml_reconcile_messages")
def ml_reconcile_messages(timestamp: int):
    _run("messages", lambda client, since: messages.sync_unread(client))


@app.periodic(cron="*/15 * * * *")
@app.task(queue="integrations", queueing_lock="ml_reconcile_shipments_claims")
def ml_reconcile_shipments_claims(timestamp: int):
    _run("shipments", lambda client, since: shipments.refresh_open(client))
    _run("claims", lambda client, since: claims.sync_open(client))


@app.periodic(cron="0 4 * * *")
@app.task(queue="integrations", queueing_lock="ml_reconcile_listings")
def ml_reconcile_listings(timestamp: int):
    _run("listings", lambda client, since: listings.import_all(client))
