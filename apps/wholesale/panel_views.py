"""Pantallas del panel interno para la tienda mayorista: clientes, configuración y emails."""

from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from apps.accounts.mixins import PanelPermissionRequiredMixin
from apps.audit import services as audit
from apps.sales.models import SalesDocument

from . import accounts, mail
from .forms import AccountDataForm, EmailTemplateForm, StoreSettingsForm
from .models import CustomerAccount, EmailTemplate, OutboundEmail, StoreSettings

STATUS_TABS = [
    ("pending", "Pendientes"),
    ("approved", "Aprobados"),
    ("suspended", "Suspendidos"),
    ("rejected", "Rechazados"),
]

# ── Clientes mayoristas ──────────────────────────────────────────────────────


class CustomerListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "wholesale.view_customeraccount"
    template_name = "wholesale/customer_list.html"
    context_object_name = "accounts"
    paginate_by = 50

    def get_status(self):
        status = self.request.GET.get("estado", "")
        if status not in dict(STATUS_TABS):
            status = "pending" if accounts.pending_count() else "approved"
        return status

    def get_queryset(self):
        qs = CustomerAccount.objects.select_related("customer", "user").filter(status=self.get_status())
        q = self.request.GET.get("q", "").strip()
        if q:
            digits = accounts.normalize_cuit(q)
            cond = Q(customer__legal_name__icontains=q) | Q(customer__trade_name__icontains=q)
            cond |= Q(registration__legal_name__icontains=q) | Q(registration__trade_name__icontains=q)
            cond |= Q(user__email__icontains=q)
            if digits:
                cond |= Q(cuit__contains=digits)
            qs = qs.filter(cond)
        return qs.order_by("created_at" if self.get_status() == "pending" else "-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        counts = {
            row["status"]: row["n"]
            for row in CustomerAccount.objects.values("status").annotate(n=Count("pk"))
        }
        ctx.update(
            tabs=[(code, label, counts.get(code, 0)) for code, label in STATUS_TABS],
            status=self.get_status(),
            q=self.request.GET.get("q", ""),
            querystring=urlencode(
                {"estado": self.get_status(), **({"q": q} if (q := self.request.GET.get("q")) else {})}
            ),
        )
        return ctx


class CustomerDetailView(PanelPermissionRequiredMixin, FormView):
    permission_required = "wholesale.view_customeraccount"
    template_name = "wholesale/customer_detail.html"
    form_class = AccountDataForm

    def dispatch(self, request, *args, **kwargs):
        self.account = get_object_or_404(
            CustomerAccount.objects.select_related("customer", "user", "reviewed_by"), pk=kwargs["pk"]
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["account"] = self.account
        return kwargs

    def get_initial(self):
        return {"cuit": accounts.format_cuit(self.account.cuit), **self.account.registration}

    def post(self, request, *args, **kwargs):
        if not request.user.has_perm("wholesale.manage_customers"):
            messages.error(request, "No tenés permiso para editar clientes mayoristas.")
            return redirect("wholesale_customers:detail", pk=self.account.pk)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        data = dict(form.cleaned_data)
        if form.fields["cuit"].disabled:
            data.pop("cuit", None)
        try:
            accounts.update_data(self.account, data=data, user=self.request.user, request=self.request)
        except accounts.AccountError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Guardamos los datos.")
        return redirect("wholesale_customers:detail", pk=self.account.pk)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        orders = []
        if self.account.customer_id:
            orders = (
                SalesDocument.objects.filter(
                    customer_id=self.account.customer_id,
                    doc_type=SalesDocument.DocType.ORDER,
                )
                .select_related("channel")
                .order_by("-issued_at")[:50]
            )
        ctx.update(
            account=self.account,
            orders=orders,
            can_manage=self.request.user.has_perm("wholesale.manage_customers"),
            cuit=accounts.format_cuit(self.account.cuit),
        )
        return ctx


class CustomerActionView(PanelPermissionRequiredMixin, View):
    """Aprobar, rechazar, suspender, reactivar y cuenta corriente (POST `action`)."""

    permission_required = "wholesale.manage_customers"
    http_method_names = ["post"]

    def post(self, request, pk):
        account = get_object_or_404(CustomerAccount, pk=pk)
        action = request.POST.get("action")
        kwargs = {"user": request.user, "request": request}
        try:
            if action == "approve":
                customer = accounts.approve(account, **kwargs)
                messages.success(request, f"Aprobamos a {customer}. Le avisamos por email.")
            elif action == "reject":
                accounts.reject(account, reason=request.POST.get("reason", ""), **kwargs)
                messages.success(request, "Rechazamos el registro. Le avisamos por email con el motivo.")
            elif action == "suspend":
                accounts.set_suspended(account, suspended=True, **kwargs)
                messages.success(request, "Suspendimos la cuenta: no puede entrar a la tienda.")
            elif action == "reactivate":
                accounts.set_suspended(account, suspended=False, **kwargs)
                messages.success(request, "Reactivamos la cuenta.")
            elif action in ("credit_on", "credit_off"):
                accounts.set_credit(account, enabled=action == "credit_on", **kwargs)
                messages.success(
                    request,
                    "Habilitamos la cuenta corriente."
                    if action == "credit_on"
                    else "Deshabilitamos la cuenta corriente.",
                )
            else:
                messages.error(request, "Acción desconocida.")
        except accounts.AccountError as exc:
            messages.error(request, str(exc))
        return redirect("wholesale_customers:detail", pk=pk)


# ── Configuración de la tienda, textos y cola de emails ──────────────────────


class StoreSettingsView(PanelPermissionRequiredMixin, FormView):
    permission_required = "wholesale.manage_store"
    template_name = "wholesale/settings.html"
    form_class = StoreSettingsForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = StoreSettings.load()
        return kwargs

    def form_valid(self, form):
        before = {f: str(v) for f, v in form.initial.items()}
        row = form.save()
        audit.record(
            self.request.user,
            "wholesale.settings_changed",
            row,
            request=self.request,
            before={k: before.get(k) for k in form.changed_data},
            after={k: str(form.cleaned_data[k]) for k in form.changed_data},
        )
        messages.success(self.request, "Guardamos la configuración de la tienda.")
        return redirect("store_admin:settings")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["pending_emails"] = mail.pending_count()
        ctx["bank_missing"] = not StoreSettings.load().bank_details.strip()
        return ctx


class EmailTemplateListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "wholesale.manage_store"
    template_name = "wholesale/email_templates.html"
    context_object_name = "templates"
    queryset = EmailTemplate.objects.order_by("name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["pending_emails"] = mail.pending_count()
        return ctx


class EmailTemplateEditView(PanelPermissionRequiredMixin, FormView):
    permission_required = "wholesale.manage_store"
    template_name = "wholesale/email_template_edit.html"
    form_class = EmailTemplateForm

    def dispatch(self, request, *args, **kwargs):
        self.template = get_object_or_404(EmailTemplate, code=kwargs["code"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.template
        return kwargs

    def form_valid(self, form):
        before = {"asunto": self.template.subject, "texto": self.template.body}
        form.save()
        audit.record(
            self.request.user,
            "wholesale.email_template_changed",
            self.template,
            request=self.request,
            before=before,
            after={"asunto": self.template.subject, "texto": self.template.body},
        )
        messages.success(self.request, f"Guardamos el texto de «{self.template.name}».")
        return redirect("store_admin:email_templates")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sample = {k: f"[{v.lower()}]" for k, v in mail.VARIABLES.items()}
        sample.update(cliente="Natatorio Ejemplo SRL", pedido="Mayorista #1234", total="$ 350.000,00")
        subject = mail.render_text(self.template.subject, sample)
        ctx.update(
            template=self.template,
            variables=mail.VARIABLES,
            preview_subject=subject,
            preview_body=mail.render_text(self.template.body, sample),
        )
        return ctx


class OutboundEmailListView(PanelPermissionRequiredMixin, TemplateView):
    permission_required = "wholesale.manage_store"
    template_name = "wholesale/outbound_emails.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status = self.request.GET.get("estado", "pending")
        if status not in dict(OutboundEmail.Status.choices):
            status = "pending"
        qs = OutboundEmail.objects.filter(status=status).order_by("-created_at")
        page = Paginator(qs, 50).get_page(self.request.GET.get("page"))
        ctx.update(
            page_obj=page,
            emails=page.object_list,
            status=status,
            statuses=OutboundEmail.Status.choices,
            pending_emails=mail.pending_count(),
            emails_enabled=settings.STORE_EMAILS_ENABLED,
            is_paginated=page.has_other_pages(),
            paginator=page.paginator,
            querystring=f"estado={status}",
        )
        return ctx
