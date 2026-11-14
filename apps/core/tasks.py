from django.utils import timezone
from procrastinate.contrib.django import app

from .models import WorkerHeartbeat


@app.periodic(cron="*/1 * * * *")
@app.task(queue="default", queueing_lock="worker_heartbeat")
def worker_heartbeat(timestamp: int):
    WorkerHeartbeat.objects.update_or_create(name="default", defaults={"beat_at": timezone.now()})
