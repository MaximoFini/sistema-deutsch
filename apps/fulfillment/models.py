"""Preparación de pedidos (M5): tandas de picking y expresos.

Las tandas no saben de canales: trabajan con documentos de venta y sus líneas (base del futuro
módulo de depósito del ERP).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class PickBatch(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        CLOSED = "closed", "Cerrada"

    number = models.PositiveIntegerField("número", unique=True)
    status = models.CharField(
        "estado", max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name="armada por"
    )
    closed_at = models.DateTimeField("cerrada", null=True, blank=True)

    class Meta:
        verbose_name = "tanda de preparación"
        verbose_name_plural = "tandas de preparación"
        ordering = ["-number"]

    def __str__(self) -> str:
        return f"Tanda {self.number}"


class PickBatchOrder(TimeStampedModel):
    batch = models.ForeignKey(PickBatch, on_delete=models.CASCADE, related_name="items")
    document = models.ForeignKey("sales.SalesDocument", on_delete=models.PROTECT, related_name="pick_items")
    resolved_at = models.DateTimeField(
        "resuelto", null=True, blank=True
    )  # despachado / para retirar / cancelado
    removed_at = models.DateTimeField("sacado de la tanda", null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "pedido de la tanda"
        verbose_name_plural = "pedidos de la tanda"
        ordering = ["id"]
        constraints = [
            # Un pedido está como máximo en UNA tanda activa.
            models.UniqueConstraint(
                fields=["document"],
                condition=Q(removed_at__isnull=True, resolved_at__isnull=True),
                name="one_active_batch_per_order",
            )
        ]

    @property
    def is_active(self) -> bool:
        return self.removed_at is None and self.resolved_at is None


class Carrier(TimeStampedModel):
    """Expresos / transportes para el rótulo propio. Lista editable por un administrador."""

    name = models.CharField("nombre", max_length=100, unique=True)
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "expreso"
        verbose_name_plural = "expresos"
        ordering = ["name"]
        permissions = [("manage_carriers", "Puede editar la lista de expresos")]

    def __str__(self) -> str:
        return self.name
