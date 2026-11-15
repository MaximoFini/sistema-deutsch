"""Pedidos en nombre de clientes (US-7, §7).

Un Vendedor o Administrador (`wholesale.order_on_behalf`) elige un cliente aprobado: la sesión guarda
`acting_customer_id` y la tienda muestra una franja fija. Usa el carrito de ese cliente (lo comparten),
sin mínimo de compra y con los medios de pago que tenga habilitados. El pedido queda con
`placed_by = vendedor` y `on_behalf = True`; el cliente lo ve como "Cargado por Deutsch".
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.utils import timezone

from apps.audit import services as audit

from .access import ACTING_SESSION_KEY
from .models import Cart, CartItem, CustomerAccount

# Cuánto tiempo se le avisa al cliente que Deutsch está editando su carrito.
SHARED_CART_NOTICE = timedelta(hours=8)


class ActingError(Exception):
    pass


def search_accounts(q: str, limit: int = 30):
    qs = CustomerAccount.objects.select_related("customer", "user").filter(
        status=CustomerAccount.Status.APPROVED, customer__isnull=False
    )
    q = (q or "").strip()
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        cond = (
            Q(customer__legal_name__icontains=q)
            | Q(customer__trade_name__icontains=q)
            | Q(user__email__icontains=q)
        )
        if digits:
            cond |= Q(cuit__contains=digits)
        qs = qs.filter(cond)
    return qs.order_by("customer__legal_name")[:limit]


def start(request, account: CustomerAccount) -> int:
    """Empieza a comprar para el cliente. Devuelve las unidades que ya tenía en su carrito."""
    user = request.user
    if not user.has_perm("wholesale.order_on_behalf"):
        raise PermissionDenied
    if account.status != CustomerAccount.Status.APPROVED or account.customer_id is None:
        raise ActingError("Ese cliente no tiene la cuenta aprobada: no se puede comprar en su nombre.")
    previous = request.session.get(ACTING_SESSION_KEY)
    if previous and previous != account.customer_id:
        Cart.objects.filter(customer_id=previous, acting_user=user).update(
            acting_user=None, acting_since=None
        )
    request.session[ACTING_SESSION_KEY] = account.customer_id
    cart, _ = Cart.objects.get_or_create(customer=account.customer)
    cart.acting_user = user
    cart.acting_since = timezone.now()
    cart.save(update_fields=["acting_user", "acting_since", "updated_at"])
    audit.record(user, "wholesale.acting_started", account, request=request, cliente=str(account.customer))
    return CartItem.objects.filter(cart=cart).aggregate(s=Sum("quantity"))["s"] or 0


def stop(request) -> None:
    customer_id = request.session.pop(ACTING_SESSION_KEY, None)
    if customer_id:
        Cart.objects.filter(customer_id=customer_id, acting_user=request.user).update(
            acting_user=None, acting_since=None
        )
        account = CustomerAccount.objects.filter(customer_id=customer_id).first()
        if account is not None:
            audit.record(request.user, "wholesale.acting_finished", account, request=request)


def shared_with_deutsch(cart: Cart) -> bool:
    """True si un vendedor está armando un pedido con este carrito (para avisarle al cliente)."""
    return bool(
        cart.acting_user_id and cart.acting_since and timezone.now() - cart.acting_since < SHARED_CART_NOTICE
    )
