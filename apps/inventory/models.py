from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.catalog.models import Variant
from apps.core.models import TimeStampedModel, quantity_field


class Warehouse(TimeStampedModel):
    code = models.CharField("código", max_length=20, unique=True)
    name = models.CharField("nombre", max_length=100)
    is_default = models.BooleanField("depósito por defecto", default=False)

    class Meta:
        verbose_name = "depósito"
        verbose_name_plural = "depósitos"

    def __str__(self) -> str:
        return self.name


class StockLevel(TimeStampedModel):
    """Saldo actual por variante y depósito. Solo lo modifica `inventory.services`."""

    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="stock_levels")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_levels")
    on_hand = quantity_field("físico")
    reserved = quantity_field("reservado")

    class Meta:
        verbose_name = "stock"
        verbose_name_plural = "stock"
        constraints = [models.UniqueConstraint(fields=["variant", "warehouse"], name="unique_stock_level")]

    @property
    def available(self):
        return self.on_hand - self.reserved


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        SYNC_ADJUSTMENT = "sync_adjustment", "Ajuste por sincronización"
        SALE = "sale", "Venta"
        RETURN = "return", "Devolución"
        RESERVATION = "reservation", "Reserva"
        RELEASE = "release", "Liberación de reserva"
        PURCHASE = "purchase", "Compra"  # futuro (F-04)
        ADJUSTMENT = "adjustment", "Ajuste manual"  # futuro (F-01)
        TRANSFER = "transfer", "Transferencia"  # futuro

    class Source(models.TextChoices):
        CONTABILIUM_SYNC = "contabilium_sync", "Sincronización Contabilium"
        SYSTEM = "system", "Sistema"

    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="stock_movements")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_movements")
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices)
    quantity = quantity_field("cantidad")  # + entra, − sale
    affects = models.CharField(
        "afecta", max_length=10, choices=[("on_hand", "Físico"), ("reserved", "Reservado")], default="on_hand"
    )
    source = models.CharField("origen", max_length=20, choices=Source.choices)
    reference_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.PROTECT)
    reference_id = models.CharField(max_length=64, blank=True)
    reference = GenericForeignKey("reference_type", "reference_id")
    note = models.CharField("nota", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField("fecha", auto_now_add=True, db_index=True)
    # M7: stock físico que quedó después del movimiento (solo si afecta `on_hand`). Vacío = sin historial.
    on_hand_after = models.DecimalField(
        "físico después", max_digits=12, decimal_places=3, null=True, blank=True
    )

    class Meta:
        verbose_name = "movimiento de stock"
        verbose_name_plural = "movimientos de stock"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["variant", "created_at"], name="stockmov_variant_created_idx")]
