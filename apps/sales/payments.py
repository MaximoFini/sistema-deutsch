"""Cuándo un pedido está cobrado: una sola definición para la ficha, la lista, las alertas y la
sincronización de estados.

Cobrado si:
- el total es 0 o menos, o
- la suma de pagos confirmados cubre el total, o
- en Mercado Libre, todas las órdenes del pack están en estado `paid` (cubre pagos con cupón o
  descuento, donde lo pagado es menor que el total).
"""

from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from .models import Payment, SalesDocument

# Estado de canal de ML: "paid", "paid+delivered", "paid/shipped"… (si hay varias órdenes con
# estados distintos van separadas por coma, p. ej. "cancelled,paid", y eso NO es todo pagado).
ML_PAID_REGEX = r"^paid([+/].*)?$"
MONEY = DecimalField(max_digits=14, decimal_places=2)


def channel_says_paid(channel_code: str, channel_status: str) -> bool:
    if channel_code != "mercadolibre":
        return False
    status = (channel_status or "").lower()
    return status.split("/")[0].split("+")[0] == "paid"


def confirmed_amount(doc: SalesDocument) -> Decimal:
    total = doc.payments.filter(status=Payment.Status.CONFIRMED).aggregate(s=Sum("amount"))["s"]
    return total or Decimal(0)


def is_paid(doc: SalesDocument, paid_amount: Decimal | None = None) -> bool:
    """`paid_amount` evita una consulta si ya se calculó (p. ej. la anotación de `annotate_paid`)."""
    if doc.total <= 0:
        return True
    if channel_says_paid(doc.channel.code, doc.channel_status):
        return True
    if paid_amount is None:
        paid_amount = getattr(doc, "paid_amount", None)
    if paid_amount is None:
        paid_amount = confirmed_amount(doc)
    return paid_amount >= doc.total


def annotate_paid(qs: QuerySet) -> QuerySet:
    """Agrega `paid_amount` (suma de pagos confirmados) a un queryset de documentos."""
    paid = (
        Payment.objects.filter(document=OuterRef("pk"), status=Payment.Status.CONFIRMED)
        .values("document")
        .annotate(s=Sum("amount"))
        .values("s")
    )
    zero = Value(Decimal(0), output_field=MONEY)
    return qs.annotate(paid_amount=Coalesce(Subquery(paid, output_field=MONEY), zero))


def paid_q() -> Q:
    """Filtro equivalente a `is_paid` para un queryset con `annotate_paid`."""
    return (
        Q(total__lte=0)
        | Q(paid_amount__gte=F("total"))
        | Q(channel__code="mercadolibre", channel_status__iregex=ML_PAID_REGEX)
    )
