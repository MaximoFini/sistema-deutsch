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

from . import accounts, invitations, mail
from .forms import AccountDataForm, EmailTemplateForm, InvitationEmailForm, StoreSettingsForm
from .models import CustomerAccount, EmailTemplate, Invitation, OutboundEmail, StoreSettings

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


# ── Invitaciones a los clientes ya cargados (M9-03) ───────────────────────────

EXCLUSION_LIMIT = 300  # filas de «no incluidos» que se listan (los totales son siempre completos)


class InvitationTrackingView(PanelPermissionRequiredMixin, TemplateView):
    """Seguimiento de invitaciones: totales, tabla filtrable, no incluidos y el botón de envío."""

    permission_required = "wholesale.manage_customers"
    template_name = "wholesale/invitations.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        totals = invitations.totals()  # también pone al día vencidas y rebotadas
        status = self.request.GET.get("estado", "")
        if status not in dict(Invitation.Status.choices):
            status = ""
        q = self.request.GET.get("q", "").strip()
        qs = Invitation.objects.select_related("account__customer", "account__user")
        if status:
            qs = qs.filter(status=status)
        if q:
            digits = accounts.normalize_cuit(q)
            cond = Q(account__customer__legal_name__icontains=q) | Q(
                account__customer__trade_name__icontains=q
            )
            cond |= Q(account__user__email__icontains=q)
            if digits:
                cond |= Q(account__cuit__contains=digits)
            qs = qs.filter(cond)
        page = Paginator(qs.order_by("account__customer__legal_name", "pk"), 50).get_page(
            self.request.GET.get("page")
        )
        excluded = invitations.exclusions()
        reason = self.request.GET.get("motivo", "")
        if reason not in invitations.REASONS:
            reason = ""
        shown = [d for d in excluded if not reason or d.reason == reason]
        reason_counts = [
            (code, label, sum(1 for d in excluded if d.reason == code))
            for code, label in invitations.REASONS.items()
        ]
        ctx.update(
            totals=totals,
            invitations=page.object_list,
            page_obj=page,
            is_paginated=page.has_other_pages(),
            paginator=page.paginator,
            status=status,
            q=q,
            querystring=urlencode({k: v for k, v in {"estado": status, "q": q}.items() if v}),
            statuses=Invitation.Status.choices,
            excluded_total=len(excluded),
            reason_counts=reason_counts,
            reason=reason,
            excluded=shown[:EXCLUSION_LIMIT],
            excluded_more=max(0, len(shown) - EXCLUSION_LIMIT),
            enabled=invitations.sending_enabled(),
            dry_run=settings.STORE_EMAIL_DRY_RUN,
            disabled_message=invitations.DISABLED_MESSAGE,
            days=settings.STORE_INVITATION_DAYS,
            per_hour=settings.STORE_INVITATIONS_PER_HOUR,
            budget=invitations.hourly_budget(),
            not_entered=totals["sent"] + totals["expired"] + totals["bounced"],
            emails_enabled=settings.STORE_EMAILS_ENABLED,
        )
        return ctx


def _report_send(request, result) -> None:
    if result.dry_run:
        messages.warning(
            request,
            f"Ensayo: se mandarían {result.would_send} invitaciones. No se envió ni se encoló nada.",
        )
    elif result.queued:
        messages.success(
            request,
            f"Dejamos {result.queued} invitaciones en la cola de emails. "
            "Salen cuando el correo saliente esté activo.",
        )
    else:
        messages.info(request, "No había invitaciones para enviar.")
    if result.deferred:
        messages.warning(
            request,
            f"Quedaron {result.deferred} para más tarde por el límite de {settings.STORE_INVITATIONS_PER_HOUR} "
            "por hora. Volvé a apretar el botón en un rato.",
        )
    for account, why in result.skipped[:5]:
        messages.info(request, f"{account.display_name}: {why}")


class InvitationSendView(PanelPermissionRequiredMixin, View):
    """«Enviar invitaciones»: a los que faltan, a los seleccionados o reenviar a los que no entraron."""

    permission_required = "wholesale.manage_customers"
    http_method_names = ["post"]

    def post(self, request):
        scope = request.POST.get("scope", "unsent")
        if scope == "selected":
            ids = [int(v) for v in request.POST.getlist("accounts") if v.isdigit()]
            if not ids:
                messages.error(request, "Marcá al menos un cliente de la tabla.")
                return redirect("wholesale_customers:invitations")
            targets = CustomerAccount.objects.filter(pk__in=ids)
        elif scope in ("unsent", "not_entered"):
            targets = invitations.accounts_for(scope)
        else:
            messages.error(request, "Acción desconocida.")
            return redirect("wholesale_customers:invitations")
        try:
            result = invitations.send_invitations(targets, request.user, request=request)
        except invitations.InvitationsDisabled as exc:
            messages.error(request, str(exc))
        else:
            _report_send(request, result)
        return redirect("wholesale_customers:invitations")


class InvitationSwitchView(PanelPermissionRequiredMixin, View):
    """Interruptor «Habilitar envío»: lo prende o apaga un administrador, con confirmación en pantalla."""

    permission_required = "wholesale.manage_customers"
    http_method_names = ["post"]

    def post(self, request):
        enable = request.POST.get("enabled") == "1"
        invitations.set_sending_enabled(enable, request.user, request=request)
        if enable:
            messages.success(request, "Envío de invitaciones habilitado. Todavía no se mandó ninguna.")
        else:
            messages.success(request, "Envío de invitaciones apagado.")
        return redirect("wholesale_customers:invitations")


class InvitationResendView(PanelPermissionRequiredMixin, View):
    permission_required = "wholesale.manage_customers"
    http_method_names = ["post"]

    def post(self, request, pk):
        account = get_object_or_404(CustomerAccount, pk=pk)
        try:
            result = invitations.send_invitations([account], request.user, request=request)
        except invitations.InvitationsDisabled as exc:
            messages.error(request, str(exc))
        else:
            _report_send(request, result)
        return redirect("wholesale_customers:invitations")


class InvitationEmailView(PanelPermissionRequiredMixin, View):
    """Corregir el email de un cliente antes de mandarle la invitación."""

    permission_required = "wholesale.manage_customers"
    http_method_names = ["post"]

    def post(self, request, pk):
        account = get_object_or_404(CustomerAccount, pk=pk)
        form = InvitationEmailForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Escribí un email válido.")
        else:
            try:
                invitations.change_email(
                    account, form.cleaned_data["email"], user=request.user, request=request
                )
            except accounts.AccountError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Corregimos el email de {account.display_name}. Si ya tenía un enlace, quedó anulado.",
                )
        return redirect("wholesale_customers:invitations")


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
        for email in page.object_list:  # el enlace personal de una invitación no se muestra en el panel
            email.body_text = invitations.mask_token(email.body_text)
        ctx.update(
            page_obj=page,
            emails=page.object_list,
            status=status,
            statuses=OutboundEmail.Status.choices,
            pending_emails=mail.pending_count(),
            expired_emails=mail.expired_count(),
            max_age_hours=settings.STORE_EMAIL_MAX_AGE_HOURS,
            emails_enabled=settings.STORE_EMAILS_ENABLED,
            is_paginated=page.has_other_pages(),
            paginator=page.paginator,
            querystring=f"estado={status}",
        )
        return ctx
