"""Confirmación del pedido mayorista (US-4 y US-5, §5).

`place_order` corre en una sola transacción:
1. Bloquea los `StockLevel` de las variantes del carrito (en orden de pk, para no trabarse con otro
   pedido que bloquee las mismas).
2. Recalcula disponible y precio. Si algo cambió respecto de lo que el cliente vio, no confirma:
   ajusta el carrito y devuelve la lista de cambios (`CartChanged`).
3. Crea el pedido (canal mayorista) con los precios congelados, el envío, el pago y el `WholesaleOrder`;
   aplica el saldo a favor.
4. Reserva el stock de cada línea (`inventory.services.change_reserved`). La reserva se libera al
   facturar, cancelar o ajustar por faltante (T9/T12), nunca al confirmar el pago.
5. Vacía el carrito, audita, encola el email y, si entra en Nuevo, avisa a Depósito.

M8a (T1): si el saldo a favor cubre todo (total $0), el pago queda confirmado ("Saldo a favor") y el
pedido no espera nada: sin vencimiento, sin recordatorio ni comprobante. Por transferencia pasa de
Esperando pago a Nuevo por `change_status` (que avisa a Depósito), como al confirmar un pago.

Regla de oro: nada de esto escribe stock ni precios en Tiendanube o Mercado Libre; la reserva es interna.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.core import signing
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.catalog.models import Variant
from apps.customers.models import Address
from apps.integrations.models import Channel
from apps.inventory import services as inventory
from apps.inventory.models import StockLevel
from apps.sales import states
from apps.sales.models import Payment, SalesDocument, SalesLine, Shipment

from . import cart as cart_service
from . import catalog, mail
from .access import Shopper
from .accounts import store_url
from .models import CartItem, CustomerBalance, StoreSettings, WholesaleOrder

SNAPSHOT_SALT = "wholesale.checkout.snapshot"
DELIVERY_PICKUP = "pickup"
DELIVERY_CARRIER = "carrier"
PAYMENT_TO_SALES = {
    WholesaleOrder.PaymentMethod.TRANSFER: Payment.Method.TRANSFER,
    WholesaleOrder.PaymentMethod.CASH: Payment.Method.CASH,
    WholesaleOrder.PaymentMethod.ACCOUNT: Payment.Method.CURRENT_ACCOUNT,
}


class CheckoutError(Exception):
    """Algo que el cliente tiene que corregir (mensaje para mostrar tal cual)."""


class CartChanged(Exception):
    """Cambió el precio o el stock desde que el cliente vio el carrito. El carrito ya quedó ajustado."""

    def __init__(self, changes: list[str]):
        super().__init__("; ".join(changes))
        self.changes = changes


@dataclass
class Delivery:
    method: str  # pickup | carrier
    carrier_name: str = ""


def sign_snapshot(summary: cart_service.Summary) -> str:
    return signing.dumps(summary.snapshot(), salt=SNAPSHOT_SALT, compress=True)


def read_snapshot(token: str) -> dict[int, tuple[int, str]]:
    try:
        rows = signing.loads(token or "", salt=SNAPSHOT_SALT)
    except signing.BadSignature:
        return {}
    return {int(v): (int(q), str(p)) for v, q, p in rows}


def allowed_payments(shopper: Shopper, delivery_method: str | None = None) -> list[tuple[str, str]]:
    """Medios de pago que puede elegir este cliente (el efectivo solo con retiro en el local)."""
    methods = [(WholesaleOrder.PaymentMethod.TRANSFER, "Transferencia bancaria")]
    if delivery_method in (None, DELIVERY_PICKUP):
        methods.append((WholesaleOrder.PaymentMethod.CASH, "Efectivo al retirar en el local"))
    if shopper.account.credit_enabled:
        methods.append((WholesaleOrder.PaymentMethod.ACCOUNT, "Cuenta corriente"))
    return methods


def next_steps(
    payment_method: str,
    delivery_method: str,
    settings_row: StoreSettings | None = None,
    *,
    paid_with_balance: bool = False,
) -> str:
    if paid_with_balance:
        where = "retirar" if delivery_method == DELIVERY_PICKUP else "despachar"
        return (
            "Pagaste el pedido entero con tu saldo a favor: no tenés que transferir ni subir comprobante. "
            f"Ya estamos preparando tu pedido. Te avisamos cuando esté listo para {where}."
        )
    settings_row = settings_row or StoreSettings.load()
    if payment_method == WholesaleOrder.PaymentMethod.TRANSFER:
        days = settings_row.transfer_expiry_days
        if not settings_row.bank_details.strip():
            return (
                "Te pasamos los datos para transferir por email o WhatsApp. Cuando transfieras, subí el "
                f"comprobante dentro de los próximos {days} días. Cuando confirmemos el pago, preparamos tu "
                "pedido. Si no recibimos el pago a tiempo, el pedido se cancela y liberamos la mercadería."
            )
        return (
            f"Transferí el total y subí el comprobante dentro de los próximos {days} días. "
            "Cuando confirmemos el pago, preparamos tu pedido. Si no recibimos el pago a tiempo, "
            "el pedido se cancela y liberamos la mercadería."
        )
    if payment_method == WholesaleOrder.PaymentMethod.CASH:
        return "Ya estamos preparando tu pedido. Te avisamos cuando esté listo para retirar; lo pagás en efectivo en el local."
    where = "retirar" if delivery_method == DELIVERY_PICKUP else "despachar"
    return f"Ya estamos preparando tu pedido con tu cuenta corriente. Te avisamos cuando esté listo para {where}."


def _changes(summary: cart_service.Summary, seen: dict[int, tuple[int, str]]) -> list[str]:
    changes = []
    current = {line.variant.pk: line for line in summary.lines}
    for line in summary.lines:
        name = f"{line.variant.product.name} {line.label}".strip()
        if not line.sellable:
            changes.append(f"{name} ya no está a la venta: lo sacamos del carrito.")
            continue
        if line.available <= 0:
            changes.append(f"{name} se agotó: lo sacamos del carrito.")
            continue
        if line.over_stock:
            changes.append(f"De {name} quedan {line.available}: ajustamos la cantidad.")
        before = seen.get(line.variant.pk)
        if before is not None and before[1] != str(line.net):
            try:
                old = Decimal(before[1])
            except ArithmeticError:
                old = None
            if old is not None:
                verb = "subió" if line.net > old else "bajó"
                changes.append(f"El precio de {name} {verb} de {money(old)} a {money(line.net)} (sin IVA).")
        elif before is not None and before[0] != line.quantity:
            changes.append(f"Cambió la cantidad de {name} en el carrito: revisala.")
    for variant_id in seen:
        if variant_id not in current:
            changes.append("Un producto que habías visto ya no está en el carrito.")
            break
    if len(seen) != len(current) and not changes:
        changes.append("El carrito cambió mientras lo revisabas.")
    return changes


def money(value) -> str:
    return catalog.format_money(value)


def _fix_cart(summary: cart_service.Summary) -> None:
    """Deja el carrito con lo que sí se puede comprar (sin agotados y con cantidades posibles)."""
    for line in summary.lines:
        if not line.sellable or line.available <= 0:
            line.item.delete()
        elif line.over_stock:
            CartItem.objects.filter(pk=line.item.pk).update(quantity=line.available)


def place_order(
    shopper: Shopper,
    *,
    delivery: Delivery,
    payment_method: str,
    snapshot: str,
    notes: str = "",
    request=None,
) -> SalesDocument:
    """Confirma el pedido. Lanza CheckoutError (dato a corregir) o CartChanged (cambió precio/stock)."""
    seen = read_snapshot(snapshot)
    if not seen:
        raise CartChanged(["Volvé a revisar el carrito antes de confirmar."])
    try:
        with transaction.atomic():
            return _place(shopper, delivery, payment_method, seen, notes, request)
    except CartChanged as exc:
        with transaction.atomic():  # el ajuste del carrito queda guardado aunque el pedido no
            cart = shopper.cart()
            _fix_cart(cart_service.summarize(cart, apply_min=not shopper.acting))
        raise exc


def _place(shopper, delivery, payment_method, seen, notes, request) -> SalesDocument:
    account = shopper.account
    customer = account.customer
    cart = shopper.cart()
    cart = type(cart).objects.select_for_update().get(pk=cart.pk)  # un checkout a la vez por carrito
    ctx = catalog.Context.load()
    variant_ids = sorted(cart.items.values_list("variant_id", flat=True))
    if not variant_ids:
        raise CheckoutError("Tu carrito está vacío.")
    # 1. Bloqueo de stock en orden de pk (crea la fila si no existe, para poder bloquearla).
    for vid in variant_ids:
        StockLevel.objects.get_or_create(variant_id=vid, warehouse_id=ctx.warehouse_id)
    list(
        StockLevel.objects.select_for_update()
        .filter(variant_id__in=variant_ids, warehouse_id=ctx.warehouse_id)
        .order_by("pk")
    )
    # 2. Recalcular con los datos bloqueados.
    summary = cart_service.summarize(cart, apply_min=not shopper.acting, ctx=ctx)
    changes = _changes(summary, seen)
    if changes:
        raise CartChanged(changes)
    if not summary.reaches_min:
        raise CheckoutError(
            f"Te faltan {money(summary.missing_for_min)} para llegar al mínimo de compra de {money(summary.min_amount)}."
        )
    if delivery.method not in (DELIVERY_PICKUP, DELIVERY_CARRIER):
        raise CheckoutError("Elegí cómo querés recibir el pedido.")
    if delivery.method == DELIVERY_CARRIER and not delivery.carrier_name.strip():
        raise CheckoutError("Elegí el expreso que te lleva el pedido.")
    if payment_method not in dict(allowed_payments(shopper, delivery.method)):
        raise CheckoutError(
            "El efectivo es solo para retirar en el local."
            if payment_method == WholesaleOrder.PaymentMethod.CASH
            else "Elegí un medio de pago de la lista."
        )
    # 3. Pedido con precios congelados.
    now = timezone.now()
    store = StoreSettings.load()
    transfer = payment_method == WholesaleOrder.PaymentMethod.TRANSFER
    doc = SalesDocument.objects.create(
        doc_type=SalesDocument.DocType.ORDER,
        channel=Channel.objects.get(code=Channel.MAYORISTA),
        customer=customer,
        status=states.AWAITING_PAYMENT if transfer else states.NEW,
        status_changed_at=now,
        issued_at=now,
        ready_at=None if transfer else now,  # M7: listo para preparar desde que entra en Nuevo
        notes=notes.strip()[:2000],
    )
    doc.channel_reference = f"Mayorista #{doc.number}"
    for line in summary.lines:
        variant: Variant = line.variant
        description = f"{variant.product.name} ({line.label})" if line.label else variant.product.name
        SalesLine.objects.create(
            document=doc,
            variant=variant,
            sku_snapshot=variant.sku,
            description_snapshot=description[:300],
            quantity=Decimal(line.quantity),
            unit_price=line.net,
            vat_rate=catalog.VAT_RATE,
        )
    doc.discount_total = Decimal(0)
    doc.recalculate_totals(save=False)
    balance = CustomerBalance.balance_for(customer)
    applied = min(balance, doc.total)
    if applied > 0:
        doc.discount_total = applied
        doc.recalculate_totals(save=False)
    doc.save()
    if applied > 0:
        CustomerBalance.objects.create(
            customer=customer,
            amount=-applied,
            document=doc,
            note=f"Usado en el pedido {doc.channel_reference}",
            created_by=shopper.user,
        )
    paid_with_balance = applied > 0 and doc.total <= 0
    if paid_with_balance:  # T1: el saldo cubrió todo; no hay nada que cobrar
        Payment.objects.create(
            document=doc,
            method=Payment.Method.BALANCE,
            amount=applied,
            status=Payment.Status.CONFIRMED,
            paid_at=now,
            external_reference="mayorista",
        )
    else:
        Payment.objects.create(
            document=doc,
            method=PAYMENT_TO_SALES[payment_method],
            amount=doc.total,
            status=Payment.Status.PENDING,
            external_reference="mayorista",
        )
    Shipment.objects.create(
        document=doc,
        method=Shipment.Method.PICKUP if delivery.method == DELIVERY_PICKUP else Shipment.Method.CARRIER,
        carrier_name=delivery.carrier_name.strip()[:100] if delivery.method == DELIVERY_CARRIER else "",
        address=_address_snapshot(customer) if delivery.method == DELIVERY_CARRIER else None,
        status="pending",
    )
    WholesaleOrder.objects.create(
        document=doc,
        placed_by=shopper.user,
        on_behalf=shopper.acting,
        payment_method=payment_method,
        expires_at=now + timedelta(days=store.transfer_expiry_days)
        if transfer and not paid_with_balance
        else None,
        balance_applied=applied,
    )
    # 4. Reserva interna de stock (nunca se escribe en los canales).
    warehouse = inventory.default_warehouse()
    for line in summary.lines:
        inventory.change_reserved(
            line.variant,
            warehouse,
            Decimal(line.quantity),
            reference=doc,
            user=shopper.user,
            note=f"Reserva {doc.channel_reference}",
        )
    # 5. Cierre.
    cart.items.all().delete()
    audit.record(
        shopper.user,
        "wholesale.order_placed",
        doc,
        request=request,
        after={
            "cliente": str(customer),
            "total": str(doc.total),
            "medio_de_pago": payment_method,
            "entrega": delivery.method,
            "en_nombre_de": shopper.acting,
            "saldo_usado": str(applied),
            "pagado_con_saldo": paid_with_balance,
        },
        cargado_por=str(shopper.user),
    )
    if transfer and paid_with_balance:
        # Esperando pago → Nuevo por el camino de siempre (historial + aviso de pedido nuevo a Depósito).
        states.change_status(
            doc,
            states.NEW,
            user=shopper.user,
            system=True,
            reason="Pagado con saldo a favor",
            request=request,
        )
        doc.refresh_from_db(fields=["status", "status_changed_at", "ready_at"])
    steps = next_steps(payment_method, delivery.method, store, paid_with_balance=paid_with_balance)
    if transfer and not paid_with_balance:
        from .payments import bank_details_text

        steps += "\n\nDatos para transferir:\n" + bank_details_text(store)
    mail.enqueue(
        "order_received",
        account.user.email,
        {
            "cliente": str(customer),
            "pedido": doc.channel_reference,
            "total": money(doc.total),
            "proximos_pasos": steps,
            "enlace": store_url("store:order_done", doc.number),
        },
    )
    if not transfer:
        states.emit_new_order(doc)
    return doc


def _address_snapshot(customer) -> dict | None:
    address = customer.addresses.filter(kind=Address.Kind.FISCAL).first()
    if address is None:
        return None
    return {
        "address": address.street,
        "number": address.number,
        "floor": address.floor,
        "city": address.city,
        "province": address.province,
        "zipcode": address.postal_code,
        "name": str(customer),
        "phone": customer.phone,
    }
