from datetime import timedelta

from django.db import connection
from django.http import JsonResponse
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.mixins import PanelLoginRequiredMixin

from .models import WorkerHeartbeat

HEARTBEAT_MAX_AGE = timedelta(minutes=5)


def health(request):
    """Chequeo para monitoreo externo: base de datos + último latido del worker."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    beat = WorkerHeartbeat.objects.filter(name="default").first() if db_ok else None
    worker_ok = bool(beat and timezone.now() - beat.beat_at < HEARTBEAT_MAX_AGE)
    return JsonResponse({"db": db_ok, "worker": worker_ok}, status=200 if db_ok else 503)


class HomeView(PanelLoginRequiredMixin, TemplateView):
    template_name = "core/home.html"
