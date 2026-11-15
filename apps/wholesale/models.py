"""Tienda mayorista (M8a): cuentas de clientes, carrito, comprobantes, faltantes y configuración.

Los pedidos son `SalesDocument` del canal `mayorista`; acá vive solo lo propio de la tienda.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

from apps.core.models import TimeStampedModel, money_field

from .storage import private_storage


class CustomerAccount(TimeStampedModel):
    """El acceso de un cliente a la tienda. Un usuario es cliente si tiene una de estas."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente de aprobación"
        APPROVED = "approved", "Aprobada"
        REJECTED = "rejected", "Rechazada"
        SUSPENDED = "suspended", "Suspendida"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="customer_account"
    )
    # Vacío mientras el registro está pendiente: al aprobar se vincula a un cliente existente con el
    # mismo CUIT o se crea uno nuevo (así nunca se duplica un cliente por un registro rechazado).
    customer = models.OneToOneField(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="store_account",
        verbose_name="cliente",
    )
    status = models.CharField(
        "estado", max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    credit_enabled = models.BooleanField("cuenta corriente habilitada", default=False)
    cuit = models.CharField("CUIT", max_length=11, unique=True)
    registration = models.JSONField("datos del registro", default=dict)  # tal como los cargó
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField("revisado", null=True, blank=True)
    rejection_reason = models.CharField("motivo del rechazo", max_length=500, blank=True)
    accepted_terms_at = models.DateTimeField("aceptó los términos")

    class Meta:
        verbose_name = "cuenta de cliente mayorista"
        verbose_name_plural = "cuentas de clientes mayoristas"
        ordering = ["-created_at"]
        permissions = [
            ("manage_customers", "Puede aprobar, rechazar y suspender clientes mayoristas"),
            ("confirm_payment", "Puede confirmar pagos de pedidos mayoristas"),
            ("order_on_behalf", "Puede armar pedidos mayoristas en nombre de un cliente"),
            ("report_shortage", "Puede marcar faltantes en pedidos mayoristas"),
            ("resolve_shortage", "Puede ajustar pedidos mayoristas con faltantes"),
            ("manage_store", "Puede configurar la tienda mayorista"),
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        if self.customer_id:
            return str(self.customer)
        data = self.registration or {}
        return data.get("trade_name") or data.get("legal_name") or self.cuit

    @property
    def is_approved(self) -> bool:
        return self.status == self.Status.APPROVED


class CustomerBalance(models.Model):
    """Libro de saldo a favor: solo altas (+, p. ej. por faltante) y usos (−). Nunca se edita una fila."""

    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="balance_movements"
    )
    amount = money_field("monto")
    document = models.ForeignKey(
        "sales.SalesDocument", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    note = models.CharField("nota", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    class Meta:
        verbose_name = "movimiento de saldo a favor"
        verbose_name_plural = "movimientos de saldo a favor"
        ordering = ["-created_at", "-id"]

    @classmethod
    def balance_for(cls, customer) -> Decimal:
        total = cls.objects.filter(customer=customer).aggregate(s=Sum("amount"))["s"]
        return max(Decimal(0), total or Decimal(0))


class Cart(TimeStampedModel):
    """Uno por cliente. Lo comparte quien compra «en nombre de» ese cliente."""

    customer = models.OneToOneField("customers.Customer", on_delete=models.CASCADE, related_name="cart")
    # Quién lo está editando «en nombre de» el cliente (para avisarle al cliente que lo comparte).
    acting_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    acting_since = models.DateTimeField("editado por Deutsch desde", null=True, blank=True)

    class Meta:
        verbose_name = "carrito"
        verbose_name_plural = "carritos"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.Variant", on_delete=models.CASCADE, related_name="+")
    quantity = models.PositiveIntegerField("cantidad")
    added_at = models.DateTimeField("agregado", auto_now_add=True)

    class Meta:
        verbose_name = "producto del carrito"
        verbose_name_plural = "productos del carrito"
        constraints = [models.UniqueConstraint(fields=["cart", "variant"], name="unique_cart_variant")]


class PaymentReceipt(TimeStampedModel):
    """Comprobante de transferencia. El archivo es privado (fuera de MEDIA_ROOT)."""

    document = models.ForeignKey("sales.SalesDocument", on_delete=models.CASCADE, related_name="receipts")
    file = models.FileField("archivo", storage=private_storage, upload_to="comprobantes/%Y/%m/")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    original_name = models.CharField("nombre original", max_length=255)
    size = models.PositiveIntegerField("tamaño (bytes)")

    class Meta:
        verbose_name = "comprobante de pago"
        verbose_name_plural = "comprobantes de pago"
        ordering = ["-created_at"]


class WholesaleOrder(models.Model):
    """Datos propios del pedido mayorista (uno a uno con el SalesDocument)."""

    class PaymentMethod(models.TextChoices):
        TRANSFER = "transfer", "Transferencia"
        CASH = "cash", "Efectivo en el local"
        ACCOUNT = "account", "Cuenta corriente"

    document = models.OneToOneField("sales.SalesDocument", on_delete=models.CASCADE, related_name="wholesale")
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name="cargado por"
    )
    on_behalf = models.BooleanField("cargado en nombre del cliente", default=False)
    payment_method = models.CharField("medio de pago", max_length=10, choices=PaymentMethod.choices)
    expires_at = models.DateTimeField("vence", null=True, blank=True)  # solo transferencia
    reminder_sent_at = models.DateTimeField("recordatorio enviado", null=True, blank=True)
    balance_applied = money_field("saldo a favor usado")
    needs_contabilium_correction = models.BooleanField("corregir en Contabilium", default=False)
    reservation_released_at = models.DateTimeField("reserva liberada", null=True, blank=True)
    balance_returned_at = models.DateTimeField("saldo a favor devuelto", null=True, blank=True)
    expired_at = models.DateTimeField("vencido sin pago", null=True, blank=True)  # lo canceló el vencimiento

    class Meta:
        verbose_name = "pedido mayorista"
        verbose_name_plural = "pedidos mayoristas"


class Shortage(TimeStampedModel):
    """Faltante marcado por Depósito en una línea de un pedido mayorista."""

    document = models.ForeignKey("sales.SalesDocument", on_delete=models.PROTECT, related_name="shortages")
    # Si al resolver se quita la línea, el vínculo queda vacío (el detalle queda en `sku`, `description`).
    line = models.ForeignKey(
        "sales.SalesLine", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sku = models.CharField("SKU", max_length=64, blank=True)
    description = models.CharField("descripción", max_length=300, blank=True)
    missing_quantity = models.PositiveIntegerField("cantidad que falta")
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    resolved_at = models.DateTimeField("resuelto", null=True, blank=True)
    resolution = models.JSONField("resolución", default=dict, blank=True)

    class Meta:
        verbose_name = "faltante"
        verbose_name_plural = "faltantes"


class StoreSettings(models.Model):
    """Configuración de la tienda (una sola fila, editable desde el panel)."""

    min_order_amount = money_field("mínimo por pedido", default=Decimal("300000"))
    min_order_includes_vat = models.BooleanField("el mínimo incluye IVA", default=False)
    transfer_expiry_days = models.PositiveSmallIntegerField("días para pagar una transferencia", default=3)
    bank_details = models.TextField("datos bancarios", blank=True)
    safety_margin_units = models.PositiveSmallIntegerField("margen de seguridad (unidades)", default=0)
    terms_text = models.TextField("términos de venta mayorista", blank=True)
    privacy_text = models.TextField("política de privacidad", blank=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "configuración de la tienda"
        verbose_name_plural = "configuración de la tienda"

    def __str__(self) -> str:
        return "Configuración de la tienda mayorista"

    @classmethod
    def load(cls) -> "StoreSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class EmailTemplate(models.Model):
    """Texto editable de cada email a clientes. Variables entre llaves: {cliente}, {pedido}, {total}…"""

    code = models.CharField("código", max_length=40, unique=True)
    name = models.CharField("nombre", max_length=100)
    subject = models.CharField("asunto", max_length=200)
    body = models.TextField("texto")
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "plantilla de email"
        verbose_name_plural = "plantillas de email"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class OutboundEmail(TimeStampedModel):
    """Cola de emails a clientes: se envían cuando hay correo saliente configurado (DDEV-7)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente de envío"
        SENT = "sent", "Enviado"
        FAILED = "failed", "Falló"

    to = models.EmailField("para")
    template_code = models.CharField("plantilla", max_length=40)
    subject = models.CharField("asunto", max_length=200)
    body_text = models.TextField("texto")
    body_html = models.TextField("HTML")
    status = models.CharField(
        "estado", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveSmallIntegerField("intentos", default=0)
    last_error = models.CharField("último error", max_length=500, blank=True)
    sent_at = models.DateTimeField("enviado", null=True, blank=True)

    class Meta:
        verbose_name = "email a cliente"
        verbose_name_plural = "emails a clientes"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.subject} → {self.to}"
