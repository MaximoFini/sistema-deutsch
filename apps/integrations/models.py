from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import TimeStampedModel


class Channel(models.Model):
    TIENDANUBE = "tiendanube"
    MERCADOLIBRE = "mercadolibre"
    CONTABILIUM = "contabilium"
    MAYORISTA = "mayorista"
    MANUAL = "manual"

    code = models.SlugField("código", max_length=30, unique=True)
    name = models.CharField("nombre", max_length=100)
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "canal"
        verbose_name_plural = "canales"
        ordering = ["name"]
        permissions = [
            ("view_status", "Puede ver el estado de las integraciones"),
            ("retry_event", "Puede reprocesar eventos de integración fallidos"),
            ("toggle_write_switch", "Puede encender o apagar la escritura de stock/precio a un canal"),
            ("manage_connection", "Puede conectar o reconectar un canal (OAuth)"),
        ]

    def __str__(self) -> str:
        return self.name


class ExternalRef(TimeStampedModel):
    """Vínculo entre una entidad del sistema y su ID en un canal (principio ERP n.º 5)."""

    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="external_refs")
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField()
    entity = GenericForeignKey("content_type", "object_id")
    external_id = models.CharField("ID externo", max_length=100)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "ID externo"
        verbose_name_plural = "IDs externos"
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "content_type", "external_id"], name="unique_external_id_per_channel"
            )
        ]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.channel.code}:{self.external_id}"


class ChannelCredential(models.Model):
    """Credenciales cifradas (Fernet). Usar solo `integrations.credentials.get/save`."""

    channel = models.OneToOneField(Channel, on_delete=models.CASCADE, related_name="credential")
    data_encrypted = models.BinaryField(editable=False)
    expires_at = models.DateTimeField("vence", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "credencial de canal"
        verbose_name_plural = "credenciales de canales"

    def __str__(self) -> str:
        return f"Credencial de {self.channel} (oculta)"

    __repr__ = __str__


class ChannelWriteSwitch(models.Model):
    """Interruptor de la regla de oro: apagado = el sistema no escribe stock/precio en el canal."""

    class Kind(models.TextChoices):
        STOCK = "stock", "Stock"
        PRICE = "price", "Precio"

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="write_switches")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    enabled = models.BooleanField("escritura habilitada", default=False)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    changed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "interruptor de escritura"
        verbose_name_plural = "interruptores de escritura"
        constraints = [models.UniqueConstraint(fields=["channel", "kind"], name="unique_write_switch")]

    def __str__(self) -> str:
        return f"{self.channel} · {self.get_kind_display()}: {'encendido' if self.enabled else 'apagado'}"


class InboundEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PROCESSING = "processing", "Procesando"
        DONE = "done", "Procesado"
        FAILED = "failed", "Fallido"
        IGNORED = "ignored", "Ignorado"

    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="events")
    topic = models.CharField("tema", max_length=100)
    dedupe_key = models.CharField(max_length=255)
    payload = models.JSONField()
    headers = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField("recibido", auto_now_add=True, db_index=True)
    status = models.CharField(
        "estado", max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveSmallIntegerField("intentos", default=0)
    last_error = models.TextField("último error", blank=True)
    processed_at = models.DateTimeField("procesado", null=True, blank=True)
    # Último cambio de estado: detecta eventos trabados en "procesando" si un worker se cae.
    updated_at = models.DateTimeField("último cambio", auto_now=True, db_index=True)

    class Meta:
        verbose_name = "evento recibido"
        verbose_name_plural = "eventos recibidos"
        ordering = ["-received_at"]
        constraints = [models.UniqueConstraint(fields=["channel", "dedupe_key"], name="unique_event_dedupe")]

    def __str__(self) -> str:
        return f"{self.channel.code}:{self.topic}:{self.dedupe_key}"


class SyncRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "En curso"
        OK = "ok", "OK"
        ERROR = "error", "Error"

    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="sync_runs")
    job = models.CharField("tarea", max_length=60)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    stats = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        verbose_name = "sincronización"
        verbose_name_plural = "sincronizaciones"
        ordering = ["-started_at"]


class RateLimitBucket(models.Model):
    """Token bucket por API, compartido entre workers (se bloquea con SELECT … FOR UPDATE)."""

    key = models.CharField(max_length=60, unique=True)
    capacity = models.FloatField()
    refill_per_second = models.FloatField()
    tokens = models.FloatField()
    updated_at = models.DateTimeField()

    class Meta:
        verbose_name = "límite de velocidad"
        verbose_name_plural = "límites de velocidad"
