"""Quién puede usar la tienda y en nombre de qué cliente (§1 y §7 del diseño).

- Un cliente aprobado compra para sí mismo.
- Un usuario interno con `wholesale.order_on_behalf` compra para el cliente que eligió (sesión
  `acting_customer_id`).
- Nadie más: los pendientes, rechazados y suspendidos ven un aviso; sin sesión, solo ingreso,
  registro, recuperación de contraseña y páginas legales.
"""

from dataclasses import dataclass

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.accounts.mixins import is_store_customer

from .models import Cart, CartItem, CustomerAccount

ACTING_SESSION_KEY = "acting_customer_id"
SUSPENDED_MESSAGE = "Tu cuenta está suspendida, escribinos para resolverlo."


@dataclass
class Shopper:
    """Para quién se está comprando y quién está del otro lado de la pantalla."""

    account: CustomerAccount
    user: object  # el usuario logueado (el cliente o el vendedor)
    acting: bool = False  # True si es un usuario interno comprando "en nombre de"

    @property
    def customer(self):
        return self.account.customer

    def cart(self) -> Cart:
        cart, _ = Cart.objects.get_or_create(customer=self.account.customer)
        return cart


def acting_account(request) -> CustomerAccount | None:
    customer_id = request.session.get(ACTING_SESSION_KEY)
    if not customer_id or not request.user.has_perm("wholesale.order_on_behalf"):
        return None
    return (
        CustomerAccount.objects.select_related("customer", "user")
        .filter(customer_id=customer_id, status=CustomerAccount.Status.APPROVED)
        .first()
    )


class StorePublicMixin:
    """Pantallas de la tienda que se ven sin sesión (ingreso, registro, recuperación, legales)."""

    panel_access = "store_public"


class StoreAccessMixin:
    """Pantallas de la tienda que necesitan un cliente aprobado (o un interno "en nombre de")."""

    panel_access = "store"
    shopper: Shopper | None = None

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("store:login"))
        if is_store_customer(user):
            account = CustomerAccount.objects.select_related("customer").get(user=user)
            if account.status == CustomerAccount.Status.SUSPENDED:
                logout(request)
                messages.error(request, SUSPENDED_MESSAGE)
                return redirect("store:login")
            if account.status != CustomerAccount.Status.APPROVED or account.customer_id is None:
                return redirect("store:pending")
            self.shopper = Shopper(account=account, user=user)
        else:
            account = acting_account(request)
            if account is None:
                return render(request, "store/internal_only.html", status=403)
            self.shopper = Shopper(account=account, user=user, acting=True)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["shopper"] = self.shopper
        ctx["cart_units"] = cart_units(self.shopper)
        return ctx


def cart_units(shopper: Shopper | None) -> int:
    if shopper is None:
        return 0
    return (
        CartItem.objects.filter(cart__customer=shopper.account.customer).aggregate(s=Sum("quantity"))["s"]
        or 0
    )
