from django.db import models

from apps.core.models import TimeStampedModel


class Product(TimeStampedModel):
    name = models.CharField("nombre", max_length=255)
    description = models.TextField("descripción", blank=True)
    brand = models.CharField("marca", max_length=100, blank=True, default="Deutsch")
    category = models.CharField("categoría", max_length=150, blank=True)
    categories = models.JSONField("categorías", default=list, blank=True)  # nombres, desde TN
    images = models.JSONField("fotos", default=list, blank=True)  # [{url, position, alt}]
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Variant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="variants")
    sku = models.CharField("SKU", max_length=64, unique=True)
    barcode = models.CharField("código de barras", max_length=64, unique=True, null=True, blank=True)
    attributes = models.JSONField("atributos", default=dict, blank=True)  # {"talle": "M", "color": "Negro"}
    weight_g = models.PositiveIntegerField("peso (g)", null=True, blank=True)
    length_mm = models.PositiveIntegerField("largo (mm)", null=True, blank=True)
    width_mm = models.PositiveIntegerField("ancho (mm)", null=True, blank=True)
    height_mm = models.PositiveIntegerField("alto (mm)", null=True, blank=True)
    is_active = models.BooleanField("activa", default=True)
    needs_review = models.BooleanField("revisar datos", default=False)
    review_notes = models.CharField("motivo de revisión", max_length=255, blank=True)

    class Meta:
        verbose_name = "variante"
        verbose_name_plural = "variantes"
        ordering = ["sku"]

    def __str__(self) -> str:
        attrs = " / ".join(str(v) for v in self.attributes.values())
        return f"{self.sku} · {self.product.name}" + (f" ({attrs})" if attrs else "")
