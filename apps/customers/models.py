from django.db import models

from apps.core.models import TimeStampedModel, money_field


class Customer(TimeStampedModel):
    class Kind(models.TextChoices):
        RETAIL = "retail", "Minorista"
        WHOLESALE = "wholesale", "Mayorista"

    class TaxIdType(models.TextChoices):
        CUIT = "CUIT", "CUIT"
        DNI = "DNI", "DNI"
        CF = "CF", "Consumidor final sin identificar"

    class VatCondition(models.TextChoices):
        RI = "RI", "Responsable inscripto"
        MONOTRIBUTO = "MONOTRIBUTO", "Monotributo"
        EXENTO = "EXENTO", "Exento"
        CF = "CF", "Consumidor final"

    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, default=Kind.RETAIL)
    legal_name = models.CharField("razón social / nombre", max_length=255)
    trade_name = models.CharField("nombre de fantasía", max_length=255, blank=True)
    tax_id_type = models.CharField(
        "tipo de documento", max_length=5, choices=TaxIdType.choices, default=TaxIdType.DNI
    )
    tax_id = models.CharField("número de documento", max_length=20, blank=True, db_index=True)
    vat_condition = models.CharField(
        "condición de IVA", max_length=12, choices=VatCondition.choices, default=VatCondition.CF
    )
    email = models.EmailField("email", blank=True, db_index=True)
    phone = models.CharField("teléfono", max_length=50, blank=True)
    price_list = models.ForeignKey(
        "pricing.PriceList", null=True, blank=True, on_delete=models.PROTECT, verbose_name="lista de precios"
    )
    credit_enabled = models.BooleanField("cuenta corriente habilitada", default=False)
    credit_limit = money_field("límite de crédito", null=True, blank=True, default=None)
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["legal_name"]

    def __str__(self) -> str:
        return self.trade_name or self.legal_name


class Address(TimeStampedModel):
    class Kind(models.TextChoices):
        FISCAL = "fiscal", "Fiscal"
        SHIPPING = "shipping", "Envío"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="addresses")
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, default=Kind.SHIPPING)
    street = models.CharField("calle", max_length=255)
    number = models.CharField("número", max_length=20, blank=True)
    floor = models.CharField("piso / depto", max_length=50, blank=True)
    city = models.CharField("localidad", max_length=100)
    province = models.CharField("provincia", max_length=100)
    postal_code = models.CharField("código postal", max_length=10, blank=True)
    country = models.CharField("país", max_length=2, default="AR")

    class Meta:
        verbose_name = "domicilio"
        verbose_name_plural = "domicilios"

    def __str__(self) -> str:
        return f"{self.street} {self.number}, {self.city}"
