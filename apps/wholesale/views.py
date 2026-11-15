"""Pantallas de la tienda mayorista (lo que ve el cliente)."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.accounts.mixins import PanelLoginRequiredMixin, is_store_customer
from apps.catalog.models import Product
from apps.sales import states
from apps.sales.models import SalesDocument

from . import accounts, acting, catalog, checkout, payments
from . import cart as cart_service
from .access import StoreAccessMixin, StorePublicMixin
from .forms import (
    CheckoutForm,
    RegistrationForm,
    StoreLoginForm,
    StorePasswordResetForm,
    StoreSetPasswordForm,
)
from .models import CustomerAccount, StoreSettings, WholesaleOrder

# ── Ingreso, registro, recuperación y legales (sin sesión) ────────────────────


class StoreLoginView(StorePublicMixin, auth_views.LoginView):
    template_name = "store/login.html"
    authentication_form = StoreLoginForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        return reverse("store:home")


class StoreLogoutView(StorePublicMixin, auth_views.LogoutView):
    next_page = reverse_lazy("store:login")


class StorePasswordResetView(StorePublicMixin, auth_views.PasswordResetView):
    template_name = "store/password_reset.html"
    form_class = StorePasswordResetForm
    email_template_name = "store/email/password_reset.txt"
    subject_template_name = "store/email/password_reset_subject.txt"
    success_url = reverse_lazy("store:password_reset_done")


class StorePasswordResetDoneView(StorePublicMixin, auth_views.PasswordResetDoneView):
    template_name = "store/password_reset_done.html"


class StorePasswordResetConfirmView(StorePublicMixin, auth_views.PasswordResetConfirmView):
    template_name = "store/password_reset_confirm.html"
    form_class = StoreSetPasswordForm
    success_url = reverse_lazy("store:password_reset_complete")


class StorePasswordResetCompleteView(StorePublicMixin, auth_views.PasswordResetCompleteView):
    template_name = "store/password_reset_complete.html"


class LegalView(StorePublicMixin, TemplateView):
    template_name = "store/legal.html"
    kind = "terms"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        row = StoreSettings.load()
        if self.kind == "terms":
            ctx.update(title="Términos de venta mayorista", text=row.terms_text)
        else:
            ctx.update(title="Política de privacidad", text=row.privacy_text)
        return ctx


def client_ip(request) -> str | None:
    return request.META.get("REMOTE_ADDR")


class RegisterView(StorePublicMixin, FormView):
    template_name = "store/register.html"
    form_class = RegistrationForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("store:home")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_bot:  # campo trampa: se responde como si nada para no dar pistas
            return redirect("store:register_done")
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        if not accounts.registration_allowed(client_ip(self.request)):
            form.add_error(
                None,
                "Recibimos muchos registros seguidos desde esta conexión. Esperá una hora y probá de nuevo, "
                "o escribinos.",
            )
            return self.form_invalid(form)
        data = form.cleaned_data
        try:
            accounts.register(data=data, password=data["password1"], request=self.request)
        except accounts.AccountError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return redirect("store:register_done")


class RegisterDoneView(StorePublicMixin, TemplateView):
    template_name = "store/register_done.html"


class PendingView(StorePublicMixin, TemplateView):
    """Lo que ve un cliente logueado cuya cuenta todavía no está aprobada (o fue rechazada)."""

    template_name = "store/pending.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("store:login")
        if not is_store_customer(request.user):
            return redirect("store:home")
        self.account = CustomerAccount.objects.get(user=request.user)
        if self.account.is_approved:
            return redirect("store:home")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["account"] = self.account
        return ctx


# ── Guía de estilo (solo usuarios internos) ───────────────────────────────────


class StyleGuideView(PanelLoginRequiredMixin, TemplateView):
    template_name = "store/style.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["demo_form"] = RegistrationForm(data={"cuit": "20-11111111-1", "email": "demo"})
        ctx["demo_form"].is_valid()
        ctx["swatches"] = [
            ("Tinta (Pantone Black 6)", "--brand-ink", "#231F20", "white"),
            ("Azul de marca (Pantone 3005)", "--brand-blue", "#007DC5", "white"),
            ("Azul para texto y botones", "--brand-blue-text", "#00659F", "white"),
            ("Azul oscuro (hover)", "--brand-blue-dark", "#004F7C", "white"),
            ("Agua 40 %", "--brand-water-300", "#99CBE8", "ink"),
            ("Agua 20 %", "--brand-water", "#CBE6F5", "ink"),
            ("Agua 5 % (fondo)", "--brand-water-50", "#F4FAFE", "ink"),
            ("Gris texto", "--brand-gray-600", "#5B6670", "white"),
            ("Éxito", "--brand-success", "#1E6B3C", "white"),
            ("Atención", "--brand-warning", "#7A4D00", "white"),
            ("Error", "--brand-danger", "#A3221A", "white"),
        ]
        demo_cells = [
            catalog.Cell(variant=None, net=Decimal("12500"), available=a, in_cart=q)
            for a, q in [(5, 2), (0, 0), (3, 0), (8, 0), (2, 1), (0, 0)]
        ]
        ctx["demo_grid"] = {
            "sizes": ["S", "M"],
            "colors": ["Azul", "Negro", "Rojo"],
            "rows": [("S", demo_cells[:3]), ("M", demo_cells[3:])],
        }
        return ctx


# ── Catálogo ─────────────────────────────────────────────────────────────────


class CatalogView(StoreAccessMixin, TemplateView):
    template_name = "store/catalog.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = catalog.Filters.from_request(self.request)
        cctx = catalog.Context.load()
        products = catalog.store_products(filters, cctx)
        page = Paginator(products, catalog.PAGE_SIZE).get_page(self.request.GET.get("page"))
        for product in page.object_list:
            product.image = catalog.main_image(product)
            prices = [catalog.to_net(v.list_price) for v in product.store_variants]
            product.price_from = min(prices) if prices else None
            product.price_varies = len(set(prices)) > 1
        ctx.update(
            page_obj=page,
            products=page.object_list,
            filters=filters,
            querystring=filters.querystring(),
            options=catalog.filter_options(cctx),
        )
        return ctx


class ProductView(StoreAccessMixin, TemplateView):
    template_name = "store/product_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cctx = catalog.Context.load()
        product = get_object_or_404(Product, pk=self.kwargs["pk"], is_active=True)
        variants = list(catalog.sellable_variants(cctx).filter(product=product).order_by("sku"))
        if not variants:
            raise Http404("Producto sin precio mayorista")
        cart = self.shopper.cart()
        grid = catalog.build_grid(variants, cctx, cart_service.quantities_in_cart(cart))
        images = sorted(product.images or [], key=lambda i: i.get("position") or 0)
        ctx.update(
            product=product,
            grid=grid,
            prices=sorted({c.net for c in grid.all_cells}),
            images=[i for i in images if i.get("url")],
            vat_rate=catalog.VAT_RATE,
        )
        return ctx


class AddToCartView(StoreAccessMixin, View):
    """POST con todas las cantidades de la grilla de un producto (`qty-<variante>`)."""

    http_method_names = ["post"]

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)  # enlace viejo o id inválido: 404 de la tienda, no 500
        quantities = {}
        try:
            for key, value in request.POST.items():
                if key.startswith("qty-"):
                    quantities[int(key[4:])] = cart_service.parse_quantity(value)
        except (ValueError, cart_service.QuantityError) as exc:
            messages.error(
                request, str(exc) if isinstance(exc, cart_service.QuantityError) else "Revisá las cantidades."
            )
            return redirect("store:product", pk=pk)
        # Solo variantes de este producto (no se puede colar otra cosa por el formulario).
        valid = set(product.variants.values_list("pk", flat=True)) if quantities else set()
        quantities = {k: v for k, v in quantities.items() if k in valid}
        warnings = cart_service.set_quantities(self.shopper.cart(), quantities)
        for warning in warnings:
            messages.warning(request, warning)
        if any(quantities.values()):
            messages.success(request, "Listo, actualizamos tu carrito.")
            if request.POST.get("next") == "cart":
                return redirect("store:cart")
        else:
            messages.info(request, "No cargaste cantidades: el producto no está en tu carrito.")
        return redirect("store:product", pk=pk)


# ── Carrito ──────────────────────────────────────────────────────────────────


class CartView(StoreAccessMixin, TemplateView):
    template_name = "store/cart.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cart = self.shopper.cart()
        summary = cart_service.summarize(cart, apply_min=not self.shopper.acting)
        ctx["summary"] = summary
        # §13: el cliente y el vendedor «en nombre de» comparten el carrito; se les avisa a los dos.
        if self.shopper.acting:
            ctx["shared_notice"] = "Este carrito es el del cliente: él también lo ve y lo puede editar."
        elif acting.shared_with_deutsch(cart):
            ctx["shared_notice"] = "Este carrito también lo está editando Deutsch para armar tu pedido."
        return ctx


class CartUpdateView(StoreAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        cart = self.shopper.cart()
        if "remove" in request.POST:
            try:
                cart_service.remove(cart, int(request.POST["remove"]))
            except ValueError:
                pass
            messages.success(request, "Sacamos el producto del carrito.")
            return redirect("store:cart")
        if "clear" in request.POST:
            cart_service.clear(cart)
            messages.success(request, "Vaciamos el carrito.")
            return redirect("store:cart")
        quantities = {}
        try:
            for key, value in request.POST.items():
                if key.startswith("qty-"):
                    quantities[int(key[4:])] = cart_service.parse_quantity(value)
        except (ValueError, cart_service.QuantityError) as exc:
            messages.error(
                request, str(exc) if isinstance(exc, cart_service.QuantityError) else "Revisá las cantidades."
            )
            return redirect("store:cart")
        in_cart = set(cart_service.quantities_in_cart(cart))
        warnings = cart_service.set_quantities(cart, {k: v for k, v in quantities.items() if k in in_cart})
        for warning in warnings:
            messages.warning(request, warning)
        messages.success(request, "Actualizamos las cantidades.")
        return redirect("store:cart")


# ── Checkout ─────────────────────────────────────────────────────────────────


class CheckoutView(StoreAccessMixin, FormView):
    template_name = "store/checkout.html"
    form_class = CheckoutForm

    def dispatch(self, request, *args, **kwargs):
        self.changes = []
        return super().dispatch(request, *args, **kwargs)

    def get_summary(self):
        return cart_service.summarize(self.shopper.cart(), apply_min=not self.shopper.acting)

    def get(self, request, *args, **kwargs):
        summary = self.get_summary()
        if not summary.lines:
            messages.info(request, "Tu carrito está vacío.")
            return redirect("store:cart")
        if not summary.can_checkout:
            return redirect("store:cart")
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["payments"] = checkout.allowed_payments(self.shopper)
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        summary = self.get_summary()
        form = ctx["form"]
        token = checkout.sign_snapshot(summary)
        form.initial["snapshot"] = token
        if form.is_bound:  # al volver a mostrar después de un cambio, el formulario lleva el carrito nuevo
            data = form.data.copy()
            data["snapshot"] = token
            form.data = data
        ctx.update(
            summary=summary,
            changes=self.changes,
            store=StoreSettings.load(),
            credit_enabled=self.shopper.account.credit_enabled,
            bank_missing=payments.BANK_DETAILS_MISSING,
        )
        return ctx

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            doc = checkout.place_order(
                self.shopper,
                delivery=checkout.Delivery(method=data["delivery"], carrier_name=data.get("carrier", "")),
                payment_method=data["payment"],
                snapshot=data["snapshot"],
                notes=data.get("notes", ""),
                request=self.request,
            )
        except checkout.CartChanged as exc:
            self.changes = exc.changes
            if not cart_service.summarize(self.shopper.cart()).lines:
                for change in exc.changes:
                    messages.warning(self.request, change)
                return redirect("store:cart")
            return self.form_invalid(form)
        except checkout.CheckoutError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return redirect("store:order_done", number=doc.number)


class OrderDoneView(StoreAccessMixin, TemplateView):
    template_name = "store/order_done.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        doc = get_object_or_404(
            SalesDocument.objects.select_related("wholesale", "channel"),
            number=self.kwargs["number"],
            doc_type=SalesDocument.DocType.ORDER,
            channel__code="mayorista",
            customer=self.shopper.customer,
        )
        order: WholesaleOrder = doc.wholesale
        shipment = doc.shipments.first()
        store = StoreSettings.load()
        ctx.update(
            doc=doc,
            order=order,
            shipment=shipment,
            store=store,
            bank_missing=payments.BANK_DETAILS_MISSING,
            receipts=list(doc.receipts.all()),
            awaiting_payment=doc.status == states.AWAITING_PAYMENT
            and order.payment_method == WholesaleOrder.PaymentMethod.TRANSFER,
            lines=list(doc.lines.all()),
            next_steps=checkout.next_steps(
                order.payment_method,
                checkout.DELIVERY_PICKUP
                if shipment and shipment.method == "pickup"
                else checkout.DELIVERY_CARRIER,
                store,
                paid_with_balance=order.paid_with_balance,
            ),
        )
        return ctx
