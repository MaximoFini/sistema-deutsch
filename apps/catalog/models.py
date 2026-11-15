from django.conf import settings
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
        permissions = [
            ("manage_links", "Puede vincular publicaciones y códigos de canales con SKU"),
            ("import_contabilium", "Puede importar el archivo de productos de Contabilium"),
            ("view_channel_stock", "Puede ver stock y precio por canal"),
            ("view_quality", "Puede ver el panel de calidad de datos"),
            ("view_listing_health", "Puede ver la salud de las publicaciones de Mercado Libre"),
        ]

    def __str__(self) -> str:
        attrs = " / ".join(str(v) for v in self.attributes.values())
        return f"{self.sku} · {self.product.name}" + (f" ({attrs})" if attrs else "")


class Listing(TimeStampedModel):
    """Publicación de un canal (p. ej. Mercado Libre). Genérico: `channel` dice de dónde es."""

    channel = models.ForeignKey("integrations.Channel", on_delete=models.PROTECT, related_name="listings")
    external_id = models.CharField("id en el canal", max_length=64)
    title = models.CharField("título", max_length=255)
    status = models.CharField("estado", max_length=30, db_index=True)
    listing_type = models.CharField("tipo de publicación", max_length=40, blank=True)
    category_id = models.CharField("categoría del canal", max_length=40, blank=True)
    permalink = models.URLField("link", max_length=500, blank=True)
    logistic_type = models.CharField("logística", max_length=40, blank=True)
    price = models.DecimalField("precio", max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField("moneda", max_length=3, default="ARS")
    available_quantity = models.IntegerField("stock en el canal", null=True, blank=True)
    sold_quantity = models.IntegerField("vendidos", null=True, blank=True)
    health = models.DecimalField("salud", max_digits=4, decimal_places=2, null=True, blank=True)
    user_product_id = models.CharField(max_length=64, blank=True)
    data = models.JSONField("datos crudos", default=dict, blank=True)
    last_synced_at = models.DateTimeField("última sincronización", null=True, blank=True)
    needs_review = models.BooleanField("revisar datos", default=False)
    review_notes = models.CharField("motivo de revisión", max_length=255, blank=True)

    class Meta:
        verbose_name = "publicación"
        verbose_name_plural = "publicaciones"
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(fields=["channel", "external_id"], name="unique_listing_per_channel")
        ]

    def __str__(self) -> str:
        return f"{self.external_id} · {self.title}"


class ListingVariation(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="variations")
    external_id = models.CharField("id de variación", max_length=64, blank=True)  # "" = sin variaciones
    variant = models.ForeignKey(
        Variant, null=True, blank=True, on_delete=models.SET_NULL, related_name="listing_variations"
    )
    sku = models.CharField("SKU", max_length=64, blank=True, db_index=True)
    attributes = models.JSONField("atributos", default=dict, blank=True)
    price = models.DecimalField("precio", max_digits=14, decimal_places=2, null=True, blank=True)
    available_quantity = models.IntegerField("stock en el canal", null=True, blank=True)
    user_product_id = models.CharField(max_length=64, blank=True)
    picture_urls = models.JSONField("fotos", default=list, blank=True)
    link_source = models.CharField(
        "origen del vínculo",
        max_length=10,
        blank=True,
        default="",
        choices=[("", "sin vincular"), ("auto", "automático"), ("manual", "manual")],
    )
    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    linked_at = models.DateTimeField("vinculado", null=True, blank=True)

    class Meta:
        verbose_name = "variación de publicación"
        verbose_name_plural = "variaciones de publicación"
        constraints = [
            models.UniqueConstraint(fields=["listing", "external_id"], name="unique_listing_variation")
        ]

    def __str__(self) -> str:
        return f"{self.listing.external_id}:{self.external_id or '-'} ({self.sku or 'sin SKU'})"


class ContabiliumImport(models.Model):
    """Historial de importaciones del archivo de productos de Contabilium (no hay API)."""

    class Status(models.TextChoices):
        PREVIEW = "preview", "Vista previa"
        APPLIED = "applied", "Aplicada"
        DISCARDED = "discarded", "Descartada"

    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField("subido", auto_now_add=True)
    filename = models.CharField("archivo", max_length=255)
    status = models.CharField("estado", max_length=10, choices=Status.choices, default=Status.PREVIEW)
    columns = models.JSONField("columnas detectadas", default=dict)
    rows = models.JSONField("filas", default=list)
    summary = models.JSONField("resumen", default=dict)
    applied_at = models.DateTimeField("aplicada", null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "importación de Contabilium"
        verbose_name_plural = "importaciones de Contabilium"
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return f"{self.filename} ({self.get_status_display()})"
