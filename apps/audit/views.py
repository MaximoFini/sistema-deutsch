from datetime import datetime, time

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.views.generic import ListView

from apps.accounts.mixins import PanelPermissionRequiredMixin

from .actions import ACTIONS
from .models import AuditLog


def _parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


class AuditLogListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "audit.view_auditlog"
    template_name = "audit/list.html"
    paginate_by = 50

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        params = self.request.GET
        if params.get("user"):
            qs = qs.filter(actor_id=params["user"])
        if params.get("action"):
            qs = qs.filter(action=params["action"])
        tz = timezone.get_current_timezone()
        if d := _parse_date(params.get("since")):
            qs = qs.filter(created_at__gte=timezone.make_aware(datetime.combine(d, time.min), tz))
        if d := _parse_date(params.get("until")):
            qs = qs.filter(created_at__lte=timezone.make_aware(datetime.combine(d, time.max), tz))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["users"] = get_user_model().objects.order_by("full_name")
        ctx["actions"] = sorted(ACTIONS.items(), key=lambda kv: kv[1])
        ctx["filters"] = self.request.GET
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx["querystring"] = query.urlencode()
        return ctx
