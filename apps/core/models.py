from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        abstract = True


def money_field(verbose_name: str, **kwargs) -> models.DecimalField:
    """Montos: siempre Decimal(14,2), nunca float."""
    kwargs.setdefault("default", 0)
    return models.DecimalField(verbose_name, max_digits=14, decimal_places=2, **kwargs)


def quantity_field(verbose_name: str, **kwargs) -> models.DecimalField:
    """Cantidades: Decimal(12,3) para soportar unidades fraccionarias a futuro."""
    kwargs.setdefault("default", 0)
    return models.DecimalField(verbose_name, max_digits=12, decimal_places=3, **kwargs)


CURRENCY_CHOICES = [("ARS", "Peso argentino"), ("USD", "Dólar")]


class DataSource(models.Model):
    """Fuente de verdad por tipo de dato (principio ERP n.º 2)."""

    class DataType(models.TextChoices):
        STOCK = "stock", "Stock"
        PRICE = "price", "Precios"
        PRODUCT = "product", "Productos"
        CUSTOMER = "customer", "Clientes"
        INVOICE = "invoice", "Facturación"

    class Source(models.TextChoices):
        CONTABILIUM = "contabilium", "Contabilium"
        SYSTEM = "system", "Sistema Deutsch"

    data_type = models.CharField("tipo de dato", max_length=20, choices=DataType.choices, unique=True)
    source = models.CharField("fuente de verdad", max_length=20, choices=Source.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    changed_at = models.DateTimeField("cambiado", auto_now=True)

    class Meta:
        verbose_name = "fuente de verdad"
        verbose_name_plural = "fuentes de verdad"
        permissions = [("change_source_of_truth", "Puede cambiar la fuente de verdad de un dato")]

    def __str__(self) -> str:
        return f"{self.get_data_type_display()}: {self.get_source_display()}"


class WorkerHeartbeat(models.Model):
    """Una fila por worker; la actualiza una tarea periodica y la lee /health/."""

    name = models.CharField(max_length=50, unique=True, default="default")
    beat_at = models.DateTimeField()

    class Meta:
        verbose_name = "latido del worker"
