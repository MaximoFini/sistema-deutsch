"""Tarea diaria de M7: completa comisiones y costos de envío de ML que quedaron pendientes."""

import logging

from django.conf import settings
from procrastinate.contrib.django import app

from . import backfill

logger = logging.getLogger(__name__)


def run_ml_fees(client=None, batch_size: int | None = None) -> dict | None:
    from apps.integrations.adapters.mercadolibre.client import MLClient
    from apps.integrations.models import ChannelCredential

    if not ChannelCredential.objects.filter(channel__code="mercadolibre").exists():
        return None  # ML desconectado: se reintenta en la próxima corrida diaria
    stats = backfill.backfill_ml_fees(
        client or MLClient(), batch_size=batch_size or settings.REPORTS_ML_FEES_BATCH
    )
    logger.info("Backfill de comisiones ML: %s", {k: v for k, v in stats.items() if k != "errors"})
    return stats


@app.periodic(cron="30 5 * * *")
@app.task(queue="integrations", queueing_lock="reports_ml_fees")
def reports_ml_fees(timestamp: int):
    run_ml_fees()
