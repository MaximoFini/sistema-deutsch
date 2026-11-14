from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, TemplateView

from apps.accounts.mixins import PanelPermissionRequiredMixin

from .models import AlertReceipt
from .services import unread_count


class AlertListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "alerts.view_alert"
    template_name = "alerts/list.html"
    paginate_by = 30
    context_object_name = "receipts"

    def get_queryset(self):
        qs = AlertReceipt.objects.filter(user=self.request.user).select_related("alert__alert_type")
        if self.request.GET.get("unread"):
            qs = qs.filter(read_at__isnull=True)
        return qs


class AlertBellView(PanelPermissionRequiredMixin, TemplateView):
    """Fragmento HTMX con el contador de no leídas (se refresca cada 60 s)."""

    permission_required = "alerts.view_alert"
    template_name = "alerts/_bell.html"

    def get_context_data(self, **kwargs):
        return {"unread": unread_count(self.request.user)}


class AlertMarkReadView(PanelPermissionRequiredMixin, View):
    permission_required = "alerts.view_alert"
    http_method_names = ["post"]

    def post(self, request, pk=None):
        qs = AlertReceipt.objects.filter(user=request.user, read_at__isnull=True)
        if pk is not None:
            receipt = get_object_or_404(AlertReceipt, pk=pk, user=request.user)
            qs = qs.filter(pk=receipt.pk)
        qs.update(read_at=timezone.now())
        return redirect(request.POST.get("next") or "alerts:list")
