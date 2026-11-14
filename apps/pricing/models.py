from django.db import models
from django.utils import timezone

from apps.catalog.models import Variant
from apps.core.models import CURRENCY_CHOICES, TimeStampedModel, money_field


class PriceList(TimeStampedModel):
    code = models.CharField("código", max_length=30, unique=True)  # MINORISTA, MAYORISTA
    name = models.CharField("nombre", max_length=100)
    currency = models.CharField("moneda", max_length=3, choices=CURRENCY_CHOICES, default="ARS")
    prices_include_vat = models.BooleanField("precios con IVA incluido", default=True)
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        verbose_name = "lista de precios"
        verbose_name_plural = "listas de precios"

    def __str__(self) -> str:
        return self.name


class PriceListItem(TimeStampedModel):
    """Precio con vigencia: nunca se pisa, se agrega una fila nueva (historial)."""

    price_list = models.ForeignKey(PriceList, on_delete=models.PROTECT, related_name="items")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="prices")
    price = money_field("precio")
    vat_rate = models.DecimalField("alícuota IVA %", max_digits=5, decimal_places=2, default=21)
    valid_from = models.DateTimeField("vigente desde", default=timezone.now)

    class Meta:
        verbose_name = "precio"
        verbose_name_plural = "precios"
        constraints = [
            models.UniqueConstraint(
                fields=["price_list", "variant", "valid_from"], name="unique_price_validity"
            )
        ]
        indexes = [models.Index(fields=["price_list", "variant", "-valid_from"])]
