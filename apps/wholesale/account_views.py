"""Pantallas de la tienda para después de comprar: Mi cuenta, detalle del pedido, comprobantes y repetir
pedido (T9, T11), y el pedido «en nombre de» un cliente (T10)."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.mixins import PanelPermissionRequiredMixin
from apps.audit import services as audit
from apps.customers.models import Address
from apps.sales import states
from apps.sales.models import SalesDocument

from . import accounts, acting, checkout, labels, payments
from . import cart as cart_service
from .access import StoreAccessMixin, acting_account
from .forms import ChangeRequestForm
from .models import CustomerAccount, CustomerBalance, StoreSettings, WholesaleOrder


def store_order(shopper, number) -> SalesDocument:
    """Un pedido mayorista del cliente que está comprando (de otro cliente: 404)."""
    return get_object_or_404(
        SalesDocument.objects.select_related("wholesale", "channel", "customer"),
        number=number,
        doc_type=SalesDocument.DocType.ORDER,
        channel__code="mayorista",
        customer=shopper.customer,
    )


def delivery_of(shipment) -> str:
    return checkout.DELIVERY_PICKUP if shipment and shipment.method == "pickup" else checkout.DELIVERY_CARRIER


# ── Mi cuenta ────────────────────────────────────────────────────────────────


class AccountView(StoreAccessMixin, TemplateView):
    template_name = "store/account.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        customer = self.shopper.customer
        orders = (
            SalesDocument.objects.filter(
                customer=customer, doc_type=SalesDocument.DocType.ORDER, channel__code="mayorista"
            )
            .select_related("wholesale")
            .order_by("-issued_at", "-id")
        )
        page = Paginator(orders, 20).get_page(self.request.GET.get("page"))
        for doc in page.object_list:
            doc.client_status = labels.client_status(doc.status)
            doc.client_tone = labels.client_tone(doc.status)
        account = self.shopper.account
        ctx.update(
            page_obj=page,
            orders=page.object_list,
            balance=CustomerBalance.balance_for(customer),
            movements=list(CustomerBalance.objects.filter(customer=customer).select_related("document")[:20]),
            account=account,
            customer=customer,
            address=customer.addresses.filter(kind=Address.Kind.FISCAL).first(),
            cuit=accounts.format_cuit(account.cuit),
            change_form=ChangeRequestForm(),
        )
        return ctx


class ChangeRequestView(StoreAccessMixin, View):
    """«Pedir un cambio» de datos: avisa a los administradores (el CUIT no se cambia)."""

    http_method_names = ["post"]

    def post(self, request):
        form = ChangeRequestForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Contanos qué dato querés cambiar.")
            return redirect("store:account")
        accounts.request_change(
            self.shopper.account, text=form.cleaned_data["text"], user=request.user, request=request
        )
        messages.success(request, "Recibimos tu pedido de cambio. Lo revisamos y te avisamos por email.")
        return redirect("store:account")


# ── Detalle del pedido, comprobantes y repetir ───────────────────────────────


class StoreOrderDetailView(StoreAccessMixin, TemplateView):
    template_name = "store/order_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        doc = store_order(self.shopper, self.kwargs["number"])
        order = payments.order_of(doc)
        shipment = doc.shipments.first()
        store = StoreSettings.load()
        transfer = order is not None and order.payment_method == WholesaleOrder.PaymentMethod.TRANSFER
        ctx.update(
            doc=doc,
            order=order,
            shipment=shipment,
            store=store,
            lines=list(doc.lines.all()),
            receipts=list(doc.receipts.all()) if transfer else [],
            client_status=labels.client_status(doc.status),
            client_tone=labels.client_tone(doc.status),
            awaiting_payment=transfer and doc.status == states.AWAITING_PAYMENT,
            bank_missing=payments.BANK_DETAILS_MISSING,
            shortages=list(doc.shortages.filter(resolved_at__isnull=True)),
            next_steps=checkout.next_steps(
                order.payment_method,
                delivery_of(shipment),
                store,
                paid_with_balance=order.paid_with_balance,
            )
            if order
            else "",
        )
        return ctx


class ReceiptUploadView(StoreAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, number):
        doc = store_order(self.shopper, number)
        name = "store:order_done" if request.POST.get("next") == "done" else "store:order_detail"
        target = reverse(name, args=[doc.number])
        try:
            payments.upload_receipt(doc, request.FILES.get("file"), user=request.user, request=request)
        except payments.PaymentError as exc:
            messages.error(request, str(exc))
            return redirect(target)
        messages.success(
            request, "¡Gracias! Recibimos el comprobante. Te avisamos por email cuando confirmemos el pago."
        )
        return redirect(target)


def receipt_response(receipt) -> FileResponse:
    """Descarga protegida del comprobante: nunca hay una URL pública del archivo."""
    try:
        handle = receipt.file.open("rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404("No encontramos el archivo del comprobante.") from exc
    response = FileResponse(handle, content_type=payments.content_type_of(receipt))
    response["Content-Disposition"] = content_disposition_header(False, receipt.original_name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    response["Cache-Control"] = "private, no-store"
    return response


class ReceiptDownloadView(StoreAccessMixin, View):
    """Comprobante de un pedido propio. Otro cliente recibe 404; un vendedor «en nombre de», también."""

    def get(self, request, number, receipt_id):
        doc = store_order(self.shopper, number)
        if not payments.can_view_receipts(request.user, doc):
            raise Http404("Comprobante inexistente")
        return receipt_response(get_object_or_404(doc.receipts, pk=receipt_id))


class RepeatOrderView(StoreAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, number):
        doc = store_order(self.shopper, number)
        added, warnings = cart_service.repeat(self.shopper.cart(), doc)
        for warning in warnings:
            messages.warning(request, warning)
        if added:
            audit.record(request.user, "wholesale.order_repeated", doc, request=request)
            messages.success(request, "Cargamos el pedido en el carrito con los precios y el stock de hoy.")
        else:
            messages.error(request, "Ninguno de los productos de ese pedido está disponible ahora.")
        return redirect("store:cart")


# ── Pedido en nombre de un cliente ───────────────────────────────────────────


class ActingPickView(PanelPermissionRequiredMixin, TemplateView):
    """Buscador de clientes aprobados para comprar en su nombre (Vendedor y Administrador)."""

    permission_required = "wholesale.order_on_behalf"
    template_name = "store/acting_pick.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "")
        ctx.update(q=q, results=list(acting.search_accounts(q)), current=acting_account(self.request))
        return ctx

    def post(self, request):
        raw = request.POST.get("account") or ""
        account = (
            CustomerAccount.objects.select_related("customer").filter(pk=int(raw)).first()
            if raw.isdigit()
            else None
        )
        if account is None:
            messages.error(request, "No encontramos ese cliente. Buscalo de nuevo.")
            return redirect("store:acting")
        try:
            units = acting.start(request, account)
        except acting.ActingError as exc:
            messages.error(request, str(exc))
            return redirect("store:acting")
        if units:
            plural = "es" if units != 1 else ""
            messages.warning(
                request,
                f"{account.customer} ya tenía {units} unidad{plural} en su carrito. "
                "Revisalas en el carrito: las podés dejar o vaciar el carrito.",
            )
        messages.success(request, f"Estás armando un pedido para «{account.customer}». Sin mínimo de compra.")
        return redirect("store:home")


class ActingStopView(PanelPermissionRequiredMixin, View):
    permission_required = "wholesale.order_on_behalf"
    http_method_names = ["post"]

    def post(self, request):
        acting.stop(request)
        messages.success(request, "Listo, dejaste de comprar en nombre del cliente.")
        return redirect("store:acting")
