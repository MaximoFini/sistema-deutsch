from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import F, OuterRef, Q, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.accounts.mixins import PanelPermissionRequiredMixin
from apps.audit.models import AuditLog
from apps.catalog.models import Variant
from apps.customers.models import Customer
from apps.integrations.models import Channel

from . import manual, payments, returns, states
from .models import Payment, ReturnInfo, SalesDocument, Shipment

ORDER = SalesDocument.DocType.ORDER


def _date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def orders_queryset():
    deadline = (
        Shipment.objects.filter(document=OuterRef("pk"), dispatch_deadline__isnull=False)
        .order_by("dispatch_deadline")
        .values("dispatch_deadline")[:1]
    )
    method = Shipment.objects.filter(document=OuterRef("pk")).order_by("id").values("method")[:1]
    return payments.annotate_paid(
        SalesDocument.objects.filter(doc_type=ORDER).select_related("channel", "customer")
    ).annotate(deadline=Subquery(deadline), ship_method=Subquery(method))


def search_orders(qs, q: str):
    """Búsqueda por comprador (nombre, razón social, email) o referencia del pedido."""
    q = (q or "").strip()
    if not q:
        return qs
    return qs.filter(
        Q(customer__legal_name__icontains=q)
        | Q(customer__trade_name__icontains=q)
        | Q(customer__email__icontains=q)
        | Q(channel_reference__icontains=q)
    )


class OrderListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "sales.view_salesdocument"
    template_name = "sales/order_list.html"
    paginate_by = 50
    context_object_name = "orders"

    def get_queryset(self):
        qs = orders_queryset()
        p = self.request.GET
        if p.get("canal"):
            qs = qs.filter(channel__code=p["canal"])
        estados = [e for e in p.getlist("estado") if e]
        if estados == ["abiertos"]:
            qs = qs.filter(status__in=states.OPEN)
        elif estados:
            qs = qs.filter(status__in=estados)
        tz = timezone.get_current_timezone()
        if d := _date(p.get("desde")):
            qs = qs.filter(issued_at__gte=timezone.make_aware(datetime.combine(d, time.min), tz))
        if d := _date(p.get("hasta")):
            qs = qs.filter(issued_at__lte=timezone.make_aware(datetime.combine(d, time.max), tz))
        qs = search_orders(qs, p.get("comprador"))
        if sku := (p.get("sku") or "").strip():
            qs = qs.filter(lines__sku_snapshot__icontains=sku).distinct()
        if p.get("cobro") == "cobrado":
            qs = qs.filter(payments.paid_q())
        elif p.get("cobro") == "pendiente":
            qs = qs.exclude(payments.paid_q())
        return qs.order_by(F("deadline").asc(nulls_last=True), "-issued_at").prefetch_related("lines")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx.update(
            querystring=query.urlencode(),
            f=self.request.GET,
            estados_sel=self.request.GET.getlist("estado"),
            channels=Channel.objects.filter(code__in=["tiendanube", "mercadolibre", "manual", "mayorista"]),
            status_choices=list(states.LABELS.items()),
            now=timezone.now(),
            soon=timezone.now() + timedelta(hours=2),
        )
        return ctx


class OrderDetailView(PanelPermissionRequiredMixin, DetailView):
    permission_required = "sales.view_salesdocument"
    template_name = "sales/order_detail.html"
    context_object_name = "doc"

    def get_queryset(self):
        return orders_queryset()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        doc = self.object
        user = self.request.user
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(SalesDocument)
        messages_list = list(doc.messages.order_by("sent_at")[:50])
        thread_key = next((m.thread_key for m in reversed(messages_list) if m.thread_key), "")
        ctx.update(
            messages_list=messages_list,
            thread_key=thread_key,
            thread_unread=sum(1 for m in messages_list if m.direction == "in" and m.read_at is None),
            lines=doc.lines.select_related("variant"),
            payments=doc.payments.all(),
            shipments=doc.shipments.all(),
            claims=doc.claims.all(),
            returns=doc.related_documents.filter(doc_type=SalesDocument.DocType.RETURN).select_related(
                "return_info"
            ),
            history=AuditLog.objects.filter(content_type=ct, object_id=str(doc.pk)).select_related("actor")[
                :50
            ],
            transitions=[(t, states.label(t)) for t in states.allowed_transitions(doc, user)],
            status_label=states.label(doc.status),
            family=states.FAMILY.get(doc.status, "flow"),
            is_tn=doc.channel.code == "tiendanube",
            is_manual=manual.is_editable(doc),  # cobro y facturación a mano: manuales y mayoristas
            can_edit_manual=manual.is_editable(doc) and user.has_perm("sales.add_manual_order"),
            can_edit_payment=manual.is_editable(doc)
            and user.has_perm("sales.add_manual_order")
            and doc.status != states.AWAITING_PAYMENT,
            payment_methods=(
                {**manual.PAYMENT_METHODS, Payment.Method.CURRENT_ACCOUNT: "Cuenta corriente"}
                if doc.channel.code == "mayorista"
                else manual.PAYMENT_METHODS
            ).items(),
            paid=payments.is_paid(doc),
            now=timezone.now(),
        )
        return ctx


class OrderStatusView(PanelPermissionRequiredMixin, View):
    permission_required = "sales.change_order_status"
    http_method_names = ["post"]

    def post(self, request, pk):
        doc = get_object_or_404(SalesDocument, pk=pk, doc_type=ORDER)
        to = request.POST.get("to", "")
        try:
            changed = states.change_status(
                doc,
                to,
                user=request.user,
                reason=request.POST.get("reason", "").strip(),
                tracking_code=request.POST.get("tracking_code", "").strip(),
                tracking_url=request.POST.get("tracking_url", "").strip(),
                request=request,
            )
            if not changed:
                messages.info(request, f"El pedido ya estaba en «{states.label(to)}». No se cambió nada.")
                return redirect("sales:detail", pk=pk)
        except states.TransitionNotAllowed as exc:
            messages.error(request, str(exc))
        else:
            extra = (
                " Se informa a Tiendanube."
                if doc.channel.code == "tiendanube" and to in states.TN_EFFECTS
                else ""
            )
            messages.success(request, f"Pedido en «{states.label(to)}».{extra}")
        return redirect("sales:detail", pk=pk)


# ── Pedidos manuales ──────────────────────────────────────────────────────


def _dec(value, default=None):
    try:
        number = Decimal(str(value).strip().replace(",", ".")) if str(value).strip() else default
    except (InvalidOperation, ValueError):
        return default
    if number is not None and not number.is_finite():
        return default
    return number


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class ManualOrderCreateView(PanelPermissionRequiredMixin, View):
    permission_required = "sales.add_manual_order"
    template = "sales/manual_form.html"

    def context(self, **extra):
        return {
            "delivery_methods": manual.DELIVERY_METHODS.items(),
            "payment_methods": manual.PAYMENT_METHODS.items(),
            "vat_choices": Customer.VatCondition.choices,
            **extra,
        }

    def get(self, request):
        return render(request, self.template, self.context())

    def post(self, request):
        p = request.POST
        try:
            if p.get("customer_id"):
                customer = Customer.objects.filter(pk=_int(p["customer_id"])).first()
                if customer is None:
                    raise manual.ManualOrderError("No encontramos ese cliente. Buscalo de nuevo.")
            else:
                if not p.get("legal_name", "").strip():
                    raise manual.ManualOrderError("Elegí un cliente o cargá el nombre del cliente nuevo.")
                customer = manual.find_or_create_customer(
                    legal_name=p["legal_name"],
                    tax_id=p.get("tax_id", ""),
                    vat_condition=p.get("vat_condition", "CF"),
                    email=p.get("email", ""),
                    phone=p.get("phone", ""),
                )
            lines = []
            for vid, qty, price in zip(
                p.getlist("variant_id"), p.getlist("quantity"), p.getlist("price"), strict=False
            ):
                if not vid:
                    continue
                variant = Variant.objects.select_related("product").filter(pk=_int(vid)).first()
                if variant is None:
                    raise manual.ManualOrderError(
                        "Uno de los productos ya no está en el catálogo. Sacalo y buscalo de nuevo."
                    )
                unit_price = _dec(price)
                if unit_price is None and str(price).strip():
                    raise manual.ManualOrderError(
                        f"Revisá el precio de {variant.sku}: tiene que ser un número."
                    )
                quantity = _dec(qty)
                if quantity is None and str(qty).strip():
                    raise manual.ManualOrderError(
                        f"Revisá la cantidad de {variant.sku}: tiene que ser un número entero."
                    )
                lines.append(manual.ManualLine(variant, quantity or Decimal(0), unit_price))
            address = None
            if p.get("street"):
                address = {
                    "address": p.get("street"),
                    "city": p.get("city", ""),
                    "province": p.get("province", ""),
                }
            doc = manual.create_manual_order(
                customer=customer,
                lines=lines,
                delivery=p.get("delivery", ""),
                address=address,
                notes=p.get("notes", ""),
                paid=p.get("paid") == "1",
                payment_method=p.get("payment_method") or Payment.Method.CASH,
                invoiced=p.get("invoiced") == "1",
                invoice_number=p.get("invoice_number", ""),
                user=request.user,
                request=request,
            )
        except manual.WholesaleNotAllowed as exc:
            # M8: los pedidos mayoristas se cargan en la tienda, «en nombre de» el cliente.
            if request.user.has_perm("wholesale.order_on_behalf"):
                from urllib.parse import urlencode

                from django.urls import reverse

                messages.info(request, f"{exc} Elegí el cliente y armá el pedido en la tienda.")
                return redirect(
                    f"{reverse('store:acting')}?{urlencode({'q': customer.tax_id or customer.legal_name})}"
                )
            messages.error(request, f"{exc} Pedíselo a un vendedor o a un administrador.")
            return render(request, self.template, self.context(form=p), status=400)
        except manual.ManualOrderError as exc:
            messages.error(request, str(exc))
            return render(request, self.template, self.context(form=p), status=400)
        messages.success(request, f"Pedido {doc.channel_reference} creado.")
        return redirect("sales:detail", pk=doc.pk)


class ManualEditView(PanelPermissionRequiredMixin, View):
    permission_required = "sales.add_manual_order"
    http_method_names = ["post"]

    def post(self, request, pk, what):
        doc = get_object_or_404(SalesDocument, pk=pk, doc_type=ORDER)
        try:
            if what == "cobro":
                manual.update_payment(
                    doc,
                    paid=request.POST.get("paid") == "1",
                    method=request.POST.get("payment_method") or Payment.Method.CASH,
                    user=request.user,
                    request=request,
                )
            elif what == "factura":
                manual.update_invoice(
                    doc,
                    invoiced=request.POST.get("invoiced") == "1",
                    number=request.POST.get("invoice_number", ""),
                    user=request.user,
                    request=request,
                )
            else:
                raise manual.ManualOrderError("Acción desconocida.")
        except manual.ManualOrderError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Datos actualizados.")
        return redirect("sales:detail", pk=pk)


class CustomerSearchView(PanelPermissionRequiredMixin, TemplateView):
    permission_required = "sales.add_manual_order"
    template_name = "sales/_customer_search.html"

    def get_context_data(self, **kwargs):
        q = self.request.GET.get("q", "").strip()
        results = []
        if len(q) >= 2:
            results = Customer.objects.filter(
                Q(legal_name__icontains=q)
                | Q(trade_name__icontains=q)
                | Q(tax_id__icontains=q)
                | Q(email__icontains=q)
            ).order_by("legal_name")[:8]
        return {"results": results}


class ProductSearchView(PanelPermissionRequiredMixin, TemplateView):
    permission_required = "sales.add_manual_order"
    template_name = "sales/_product_search.html"

    def get_context_data(self, **kwargs):
        q = self.request.GET.get("q", "").strip()
        rows = []
        if len(q) >= 2:
            variants = (
                Variant.objects.filter(is_active=True)
                .select_related("product")
                .filter(Q(sku__icontains=q) | Q(product__name__icontains=q) | Q(barcode__icontains=q))[:8]
            )
            rows = [(v, manual.reference_price(v)) for v in variants]
        return {"rows": rows}


# ── Devoluciones ──────────────────────────────────────────────────────────


class ReturnListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "sales.receive_return"
    template_name = "sales/return_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        vista = self.request.GET.get("vista", "esperadas")
        qs = ReturnInfo.objects.select_related(
            "document__related_document__channel", "document__customer", "claim"
        )
        if vista == "recibidas":
            qs = qs.filter(received_at__isnull=False).order_by("adjusted_in_contabilium", "-received_at")
        else:
            qs = qs.filter(received_at__isnull=True).order_by("-expected_at")
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["vista"] = self.request.GET.get("vista", "esperadas")
        ctx["pending_adjust"] = ReturnInfo.objects.filter(
            received_at__isnull=False, adjusted_in_contabilium=False
        ).count()
        # Buscador de pedido: para registrar una devolución que llegó sin estar esperada (US-4).
        q = (self.request.GET.get("pedido") or "").strip()
        ctx["pedido_q"] = q
        ctx["order_results"] = (
            search_orders(
                SalesDocument.objects.filter(doc_type=ORDER).select_related("channel", "customer"), q
            ).order_by("-issued_at")[:10]
            if len(q) >= 2
            else None
        )
        return ctx


def _return_or_404(pk) -> SalesDocument:
    doc = get_object_or_404(
        SalesDocument.objects.select_related("return_info", "related_document"),
        pk=pk,
        doc_type=SalesDocument.DocType.RETURN,
    )
    if not hasattr(doc, "return_info"):
        raise Http404("Esta devolución no tiene datos de recepción.")
    return doc


class ReturnReceiveView(PanelPermissionRequiredMixin, View):
    permission_required = "sales.receive_return"
    template = "sales/return_receive.html"

    def get(self, request, pk):
        doc = _return_or_404(pk)
        return render(request, self.template, {"ret": doc, "lines": doc.lines.all(), "info": doc.return_info})

    def post(self, request, pk):
        doc = _return_or_404(pk)
        received = []
        try:
            for line in doc.lines.all():
                raw = (request.POST.get(f"qty_{line.pk}") or "").strip()
                if not raw:
                    continue
                qty = _dec(raw)
                if qty is None:
                    raise returns.ReturnError(
                        f"Revisá la cantidad de {line.sku_snapshot}: tiene que ser un número entero."
                    )
                if qty == 0:
                    continue  # no llegó ese producto
                returns.validate_quantity(line, qty)
                received.append((line, qty, request.POST.get(f"cond_{line.pk}", "")))
            if not received:
                raise returns.ReturnError("Indicá la cantidad recibida de al menos un producto.")
            returns.receive(
                doc, received, request.POST.get("comment", "").strip(), user=request.user, request=request
            )
        except returns.ReturnError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                self.template,
                {"ret": doc, "lines": doc.lines.all(), "info": doc.return_info},
                status=400,
            )
        messages.success(
            request, "Devolución registrada. Se avisó a administración para ajustar el stock en Contabilium."
        )
        return redirect(f"{_url('sales:returns')}?vista=recibidas")


class ReturnCreateExpectedView(PanelPermissionRequiredMixin, View):
    permission_required = "sales.receive_return"
    http_method_names = ["post"]

    def post(self, request, pk):
        order = get_object_or_404(SalesDocument, pk=pk, doc_type=ORDER)
        doc, created = returns.get_or_create_expected(order, user=request.user, request=request)
        if request.POST.get("receive_now") == "1":
            return redirect("sales:return_receive", pk=doc.pk)
        if created:
            messages.success(request, "Devolución esperada cargada.")
        else:
            messages.info(
                request, "Este pedido ya tenía una devolución esperada sin recibir. No se cargó otra."
            )
        return redirect("sales:detail", pk=pk)


class ReturnAdjustedView(PanelPermissionRequiredMixin, View):
    permission_required = "sales.mark_return_adjusted"
    http_method_names = ["post"]

    def post(self, request, pk):
        doc = get_object_or_404(SalesDocument, pk=pk, doc_type=SalesDocument.DocType.RETURN)
        try:
            returns.mark_adjusted(doc, user=request.user, request=request)
        except returns.ReturnError as exc:
            messages.error(request, str(exc))
        return redirect(f"{_url('sales:returns')}?vista=recibidas")


def _url(name):
    from django.urls import reverse

    return reverse(name)
