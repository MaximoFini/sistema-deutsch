"""Pedidos manuales: los que no vienen de ningún canal (US-3)."""

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.catalog.models import Variant
from apps.customers.models import Customer
from apps.integrations.models import Channel
from apps.pricing import services as pricing
from apps.pricing.models import PriceList

from . import payments, states
from .models import Payment, SalesDocument, SalesLine, Shipment
from .signals import order_invoice_changed

# Canales cuyo cobro y facturación se editan a mano desde la ficha (M4; M8 suma la tienda mayorista).
EDITABLE_CHANNELS = ("manual", "mayorista")

DELIVERY_METHODS = {
    Shipment.Method.PICKUP: "Retiro en local",
    Shipment.Method.CARRIER: "Transporte",
    Shipment.Method.OTHER: "Otro",
}
PAYMENT_METHODS = {
    Payment.Method.CASH: "Efectivo",
    Payment.Method.TRANSFER: "Transferencia",
    Payment.Method.MERCADOPAGO: "Mercado Pago",
    Payment.Method.OTHER: "Otro",
}


class WholesaleNotAllowed(Exception):
    pass


class ManualOrderError(Exception):
    pass


@dataclass
class ManualLine:
    variant: Variant
    quantity: Decimal
    unit_price: Decimal | None = None  # None = precio minorista vigente


def reference_price(variant: Variant) -> Decimal | None:
    item = pricing.current_price(PriceList.objects.get(code="MINORISTA"), variant)
    return item.price if item else None


def find_or_create_customer(
    *,
    legal_name: str,
    tax_id: str = "",
    vat_condition: str = Customer.VatCondition.CF,
    email: str = "",
    phone: str = "",
) -> Customer:
    digits = "".join(ch for ch in tax_id if ch.isdigit())
    customer = None
    if digits:
        customer = Customer.objects.filter(tax_id=digits).order_by("id").first()
    if customer is None and email:
        customer = Customer.objects.filter(email__iexact=email.strip()).order_by("id").first()
    if customer is None:
        tax_type = (
            (Customer.TaxIdType.CUIT if len(digits) == 11 else Customer.TaxIdType.DNI)
            if digits
            else Customer.TaxIdType.CF
        )
        customer = Customer.objects.create(
            kind=Customer.Kind.RETAIL,
            legal_name=legal_name.strip()[:255],
            tax_id=digits,
            tax_id_type=tax_type,
            vat_condition=vat_condition or Customer.VatCondition.CF,
            email=email.strip().lower(),
            phone=phone[:50],
        )
    return customer


@transaction.atomic
def create_manual_order(
    *,
    customer: Customer,
    lines: list[ManualLine],
    delivery: str,
    address: dict | None = None,
    notes: str = "",
    paid: bool = False,
    payment_method: str = Payment.Method.CASH,
    invoiced: bool = False,
    invoice_number: str = "",
    user,
    request=None,
) -> SalesDocument:
    if not user.has_perm("sales.add_manual_order"):
        raise PermissionDenied
    if customer.kind == Customer.Kind.WHOLESALE:
        raise WholesaleNotAllowed(
            "Los pedidos de clientes mayoristas se cargan desde la tienda mayorista (vendedor en nombre del cliente)."
        )
    if not lines:
        raise ManualOrderError("Agregá al menos un producto.")
    if delivery not in DELIVERY_METHODS:
        raise ManualOrderError("Elegí la forma de entrega.")
    for ml in lines:
        _validate_line(ml)
    now = timezone.now()
    doc = SalesDocument.objects.create(
        doc_type=SalesDocument.DocType.ORDER,
        channel=Channel.objects.get(code="manual"),
        customer=customer,
        status=states.NEW,
        status_changed_at=now,
        issued_at=now,
        ready_at=now,  # M7: los manuales entran como Nuevo (listos para preparar)
        notes=notes,
    )
    doc.channel_reference = f"Manual #{doc.number}"
    for ml in lines:
        price = ml.unit_price if ml.unit_price is not None else (reference_price(ml.variant) or Decimal(0))
        attrs = " / ".join(str(v) for v in ml.variant.attributes.values())
        SalesLine.objects.create(
            document=doc,
            variant=ml.variant,
            sku_snapshot=ml.variant.sku,
            description_snapshot=(
                f"{ml.variant.product.name} ({attrs})" if attrs else ml.variant.product.name
            )[:300],
            quantity=Decimal(ml.quantity),
            unit_price=Decimal(price),
        )
    doc.recalculate_totals(save=False)
    _set_invoice(doc, invoiced, invoice_number)
    doc.save()
    Payment.objects.create(
        document=doc,
        method=payment_method,
        amount=doc.total,
        status=Payment.Status.CONFIRMED if paid else Payment.Status.PENDING,
        paid_at=timezone.now() if paid else None,
        external_reference="manual",
    )
    Shipment.objects.create(document=doc, method=delivery, address=address or None, status="pending")
    audit.record(
        user,
        "order.manual_created",
        doc,
        request=request,
        after={"cliente": str(customer), "total": str(doc.total), "cobrado": paid, "facturado": invoiced},
    )
    states.emit_new_order(doc)
    return doc


def _validate_line(ml: ManualLine) -> None:
    sku = ml.variant.sku
    try:
        quantity = Decimal(ml.quantity) if ml.quantity is not None else None
    except (ArithmeticError, TypeError, ValueError):
        quantity = None
    if quantity is None or not quantity.is_finite() or quantity <= 0:
        raise ManualOrderError(f"La cantidad de {sku} tiene que ser mayor a 0.")
    if quantity != quantity.to_integral_value():
        raise ManualOrderError(f"La cantidad de {sku} tiene que ser un número entero (sin decimales).")
    if ml.unit_price is not None:
        try:
            price = Decimal(ml.unit_price)
        except (ArithmeticError, TypeError, ValueError):
            price = None
        if price is None or not price.is_finite():
            raise ManualOrderError(f"Revisá el precio de {sku}: tiene que ser un número.")
        if price < 0:
            raise ManualOrderError(f"El precio de {sku} no puede ser negativo.")


def _set_invoice(doc: SalesDocument, invoiced: bool, number: str) -> None:
    if invoiced and not number.strip():
        raise ManualOrderError("Indicá el número de comprobante de Contabilium.")
    doc.invoiced_in_contabilium = invoiced
    doc.invoice_number = number.strip()[:40] if invoiced else ""
    doc.invoiced_at = (doc.invoiced_at or timezone.now()) if invoiced else None


def is_editable(doc) -> bool:
    """Cobro y facturación a mano: pedidos manuales y mayoristas."""
    return doc.channel.code in EDITABLE_CHANNELS and not doc.is_historical


def _require_manual(doc, user):
    if not user.has_perm("sales.add_manual_order"):
        raise PermissionDenied
    if doc.is_historical:
        raise ManualOrderError("Pedido histórico importado de TiendaQuick: solo lectura, no se edita.")
    if not is_editable(doc):
        raise ManualOrderError("Solo se edita cobro y facturación de pedidos manuales o mayoristas.")


@transaction.atomic
def update_payment(doc: SalesDocument, *, paid: bool, method: str, user, request=None) -> None:
    _require_manual(doc, user)
    if doc.channel.code == "mayorista" and doc.status == states.AWAITING_PAYMENT:
        raise ManualOrderError(
            "Este pedido espera la transferencia: confirmá el pago desde «Pago por transferencia»."
        )
    reference = doc.channel.code  # "manual" o "mayorista"
    payment = doc.payments.filter(external_reference=reference).first()
    before = {
        "cobrado": bool(payment and payment.status == Payment.Status.CONFIRMED),
        "medio": getattr(payment, "method", ""),
    }
    if payment is None:
        payment = Payment(document=doc, external_reference=reference, amount=doc.total)
    payment.method = method
    payment.status = Payment.Status.CONFIRMED if paid else Payment.Status.PENDING
    payment.paid_at = (payment.paid_at or timezone.now()) if paid else None
    payment.amount = doc.total
    payment.save()
    audit.record(
        user,
        "order.payment_updated",
        doc,
        request=request,
        before=before,
        after={"cobrado": paid, "medio": method},
    )


@transaction.atomic
def update_invoice(doc: SalesDocument, *, invoiced: bool, number: str, user, request=None) -> None:
    _require_manual(doc, user)
    before = {"facturado": doc.invoiced_in_contabilium, "comprobante": doc.invoice_number}
    _set_invoice(doc, invoiced, number)
    doc.save(update_fields=["invoiced_in_contabilium", "invoice_number", "invoiced_at", "updated_at"])
    order_invoice_changed.send(sender=SalesDocument, document=doc, invoiced=invoiced, user=user)
    audit.record(
        user,
        "order.invoice_updated",
        doc,
        request=request,
        before=before,
        after={"facturado": invoiced, "comprobante": doc.invoice_number},
    )


def is_paid(doc: SalesDocument) -> bool:
    return payments.is_paid(doc)
