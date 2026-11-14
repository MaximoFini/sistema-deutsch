from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import CURRENCY_CHOICES, TimeStampedModel, money_field, quantity_field


class SalesDocument(TimeStampedModel):
    """Documento de venta genérico (principio ERP n.º 4): pedidos, devoluciones y, a futuro,
    facturas y notas de crédito/débito. Nunca una tabla de pedidos por canal."""

    class DocType(models.TextChoices):
        ORDER = "order", "Pedido"
        RETURN = "return", "Devolución"
        INVOICE = "invoice", "Factura"  # futuro (F-02)
        CREDIT_NOTE = "credit_note", "Nota de crédito"  # futuro
        DEBIT_NOTE = "debit_note", "Nota de débito"  # futuro

    doc_type = models.CharField("tipo", max_length=20, choices=DocType.choices, default=DocType.ORDER)
    channel = models.ForeignKey("integrations.Channel", on_delete=models.PROTECT, verbose_name="canal")
    number = models.PositiveIntegerField("número interno", editable=False)
    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="documents"
    )
    status = models.CharField("estado", max_length=30, default="new", db_index=True)  # ver sales/states.py
    status_before_claim = models.CharField("estado antes del reclamo", max_length=30, blank=True)
    status_changed_at = models.DateTimeField("último cambio de estado", null=True, blank=True)
    channel_reference = models.CharField("referencia del canal", max_length=60, blank=True, db_index=True)
    invoiced_in_contabilium = models.BooleanField("facturado en Contabilium", default=False)
    invoice_number = models.CharField("número de comprobante", max_length=40, blank=True)
    invoiced_at = models.DateTimeField("facturado", null=True, blank=True)
    channel_status = models.CharField("estado en el canal", max_length=60, blank=True)
    issued_at = models.DateTimeField("fecha", db_index=True)
    currency = models.CharField("moneda", max_length=3, choices=CURRENCY_CHOICES, default="ARS")
    subtotal = money_field("subtotal")
    discount_total = money_field("descuentos")
    shipping_total = money_field("envío")
    tax_total = money_field("impuestos")
    total = money_field("total")
    related_document = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="related_documents"
    )
    notes = models.TextField("observaciones", blank=True)
    fiscal = models.JSONField("datos fiscales", null=True, blank=True)  # futuro: PV, tipo cbte, CAE, vto.

    class Meta:
        verbose_name = "documento de venta"
        verbose_name_plural = "documentos de venta"
        ordering = ["-issued_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["doc_type", "number"], name="unique_doc_number")]
        indexes = [models.Index(fields=["doc_type", "-issued_at"], name="salesdoc_type_issued_idx")]
        permissions = [
            ("change_order_status", "Puede cambiar el estado interno de un pedido"),
            ("cancel_manual_order", "Puede cancelar pedidos manuales"),
            ("add_manual_order", "Puede cargar y editar pedidos manuales"),
            ("receive_return", "Puede registrar devoluciones"),
            ("mark_return_adjusted", "Puede marcar devoluciones como ajustadas en Contabilium"),
        ]

    def __str__(self) -> str:
        return f"{self.get_doc_type_display()} #{self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            from .numbering import next_number

            self.number = next_number(self.doc_type)
        super().save(*args, **kwargs)

    def recalculate_totals(self, save=True):
        lines = list(self.lines.all())
        self.subtotal = sum((line.line_total for line in lines), start=0)
        self.total = self.subtotal - self.discount_total + self.shipping_total
        if save:
            self.save(update_fields=["subtotal", "total", "updated_at"])


class SalesLine(models.Model):
    document = models.ForeignKey(SalesDocument, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey("catalog.Variant", null=True, blank=True, on_delete=models.PROTECT)
    sku_snapshot = models.CharField("SKU", max_length=64)
    description_snapshot = models.CharField("descripción", max_length=300)
    quantity = quantity_field("cantidad")
    unit_price = money_field("precio unitario")
    discount = money_field("descuento")
    vat_rate = models.DecimalField("alícuota IVA %", max_digits=5, decimal_places=2, default=21)
    line_total = money_field("total línea")
    condition = models.CharField(
        "estado de la mercadería",
        max_length=12,
        blank=True,
        default="",
        choices=[("", "—"), ("resellable", "Apto para reventa"), ("damaged", "Dañado")],
    )  # solo en devoluciones

    class Meta:
        verbose_name = "línea"
        verbose_name_plural = "líneas"

    def save(self, *args, **kwargs):
        self.line_total = (
            Decimal(self.quantity) * Decimal(self.unit_price) - Decimal(self.discount)
        ).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class Payment(TimeStampedModel):
    class Method(models.TextChoices):
        MERCADOPAGO = "mercadopago", "Mercado Pago"
        TRANSFER = "transfer", "Transferencia"
        CASH = "cash", "Efectivo"
        CURRENT_ACCOUNT = "current_account", "Cuenta corriente"
        OTHER = "other", "Otro"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        CONFIRMED = "confirmed", "Confirmado"
        REJECTED = "rejected", "Rechazado"
        REFUNDED = "refunded", "Devuelto"

    document = models.ForeignKey(SalesDocument, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField("medio", max_length=20, choices=Method.choices)
    amount = money_field("monto")
    status = models.CharField("estado", max_length=12, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField("fecha de pago", null=True, blank=True)
    external_reference = models.CharField("referencia externa", max_length=100, blank=True)
    receipt_file = models.FileField("comprobante", upload_to="comprobantes/%Y/%m/", null=True, blank=True)

    class Meta:
        verbose_name = "pago"
        verbose_name_plural = "pagos"


class Shipment(TimeStampedModel):
    class Method(models.TextChoices):
        ME_FLEX = "me_flex", "Mercado Envíos Flex"
        ME_FULL = "me_full", "Mercado Envíos Full"
        ME_COLECTA = "me_colecta", "Mercado Envíos Colecta"
        ME_DROP_OFF = "me_drop_off", "Mercado Envíos punto de entrega / correo"
        ME_CUSTOM = "me_custom", "Mercado Libre: acordar con el vendedor"
        ME_OTHER = "me_other", "Mercado Libre: otra modalidad"
        ENVIO_NUBE = "envio_nube", "Envío Nube"
        PICKUP = "pickup", "Retiro en local"
        CARRIER = "carrier", "Transporte"
        OTHER = "other", "Otro"

    document = models.ForeignKey(SalesDocument, on_delete=models.CASCADE, related_name="shipments")
    external_id = models.CharField("id en el canal", max_length=64, blank=True, db_index=True)
    logistic_type = models.CharField("logística (canal)", max_length=40, blank=True)
    dispatch_deadline = models.DateTimeField("despachar antes de", null=True, blank=True)
    substatus = models.CharField("subestado", max_length=60, blank=True)
    label_zpl_file = models.FileField("etiqueta ZPL", upload_to="etiquetas/%Y/%m/", null=True, blank=True)
    method = models.CharField("método", max_length=20, choices=Method.choices)
    carrier_name = models.CharField("transporte", max_length=100, blank=True)
    tracking_number = models.CharField("seguimiento", max_length=100, blank=True)
    status = models.CharField("estado", max_length=30, default="pending")
    label_file = models.FileField("etiqueta", upload_to="etiquetas/%Y/%m/", null=True, blank=True)
    shipped_at = models.DateTimeField("despachado", null=True, blank=True)
    address = models.JSONField("domicilio de entrega", null=True, blank=True)  # snapshot del canal

    class Meta:
        verbose_name = "envío"
        verbose_name_plural = "envíos"
        # Lista de pedidos: ordena por la fecha límite de despacho de cada documento.
        indexes = [models.Index(fields=["document", "dispatch_deadline"], name="shipment_doc_deadline_idx")]


class ReturnInfo(models.Model):
    """Datos de recepción de una devolución (uno a uno con el SalesDocument de tipo devolución)."""

    class Source(models.TextChoices):
        ML_CLAIM = "ml_claim", "Reclamo de Mercado Libre"
        MANUAL = "manual", "Cargada a mano"

    document = models.OneToOneField(SalesDocument, on_delete=models.CASCADE, related_name="return_info")
    source = models.CharField("origen", max_length=10, choices=Source.choices)
    claim = models.ForeignKey(
        "conversations.Claim", null=True, blank=True, on_delete=models.SET_NULL, related_name="returns"
    )
    expected_at = models.DateTimeField("esperada desde", auto_now_add=True)
    received_at = models.DateTimeField("recibida", null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    comment = models.TextField("comentario", blank=True)
    adjusted_in_contabilium = models.BooleanField("ajustado en Contabilium", default=False)
    adjusted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    adjusted_at = models.DateTimeField("ajustado", null=True, blank=True)

    class Meta:
        verbose_name = "devolución"
        verbose_name_plural = "devoluciones"
