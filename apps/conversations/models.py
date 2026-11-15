"""Interacción con compradores en los canales: preguntas, mensajes postventa y reclamos.

Genérico por canal (FK a Channel): no hay tablas "de Mercado Libre".
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Question(TimeStampedModel):
    class Status(models.TextChoices):
        UNANSWERED = "unanswered", "Sin responder"
        ANSWERED = "answered", "Respondida"
        CLOSED = "closed", "Cerrada"
        DELETED = "deleted", "Borrada"
        BANNED = "banned", "Usuario bloqueado"
        ERROR = "error", "Error al responder"

    channel = models.ForeignKey("integrations.Channel", on_delete=models.PROTECT)
    external_id = models.CharField(max_length=64)
    listing = models.ForeignKey(
        "catalog.Listing", null=True, blank=True, on_delete=models.SET_NULL, related_name="questions"
    )
    item_external_id = models.CharField("publicación", max_length=64, blank=True)
    text = models.TextField("pregunta")
    asker_nickname = models.CharField("comprador", max_length=100, blank=True)
    asked_at = models.DateTimeField("preguntada", null=True, blank=True)
    status = models.CharField(
        "estado", max_length=12, choices=Status.choices, default=Status.UNANSWERED, db_index=True
    )
    answer_text = models.TextField("respuesta", blank=True)
    answered_at = models.DateTimeField("respondida", null=True, blank=True)
    answered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    answer_error = models.CharField("error al responder", max_length=255, blank=True)
    draft_answer = models.TextField("borrador", blank=True)

    class Meta:
        verbose_name = "pregunta"
        verbose_name_plural = "preguntas"
        ordering = ["-asked_at"]
        constraints = [
            models.UniqueConstraint(fields=["channel", "external_id"], name="unique_question_per_channel")
        ]
        indexes = [models.Index(fields=["status", "asked_at"], name="question_status_asked")]
        permissions = [("answer_question", "Puede responder preguntas de los canales")]

    def __str__(self) -> str:
        return self.text[:80]


class Message(models.Model):
    class Direction(models.TextChoices):
        IN = "in", "Del comprador"
        OUT = "out", "Del vendedor"

    channel = models.ForeignKey("integrations.Channel", on_delete=models.PROTECT)
    external_id = models.CharField(max_length=64)
    document = models.ForeignKey(
        "sales.SalesDocument", null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    thread_key = models.CharField("conversación", max_length=64, db_index=True)  # pack u orden
    direction = models.CharField(max_length=3, choices=Direction.choices)
    text = models.TextField(blank=True)
    attachments = models.JSONField(default=list, blank=True)
    sent_at = models.DateTimeField("enviado", null=True, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    read_at = models.DateTimeField("leído", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "mensaje"
        verbose_name_plural = "mensajes"
        ordering = ["sent_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["channel", "external_id"], name="unique_message_per_channel")
        ]
        indexes = [
            models.Index(fields=["thread_key", "sent_at"], name="message_thread_sent"),
            models.Index(
                fields=["thread_key"],
                name="message_unread_in",
                condition=models.Q(direction="in", read_at__isnull=True),
            ),
        ]
        permissions = [("send_message", "Puede enviar mensajes postventa")]

    def __str__(self) -> str:
        return f"{self.get_direction_display()}: {self.text[:60]}"


class Claim(TimeStampedModel):
    channel = models.ForeignKey("integrations.Channel", on_delete=models.PROTECT)
    external_id = models.CharField(max_length=64)
    document = models.ForeignKey(
        "sales.SalesDocument", null=True, blank=True, on_delete=models.SET_NULL, related_name="claims"
    )
    order_external_id = models.CharField("orden", max_length=64, blank=True)
    claim_type = models.CharField("tipo", max_length=40, blank=True)
    stage = models.CharField("etapa", max_length=40, blank=True)
    status = models.CharField("estado", max_length=20, db_index=True)
    reason = models.CharField("motivo", max_length=100, blank=True)
    reason_detail = models.CharField("detalle del motivo", max_length=255, blank=True)
    action_required = models.BooleanField("requiere acción", default=False)
    due_date = models.DateTimeField("plazo de respuesta", null=True, blank=True)
    return_status = models.CharField("estado de la devolución", max_length=40, blank=True)
    return_data = models.JSONField(default=dict, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "reclamo"
        verbose_name_plural = "reclamos"
        ordering = ["due_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["channel", "external_id"], name="unique_claim_per_channel")
        ]

    def __str__(self) -> str:
        return f"Reclamo {self.external_id} ({self.status})"


class SavedReply(TimeStampedModel):
    """Respuesta guardada, compartida por todo el equipo (M6). Se inserta en la respuesta y se edita."""

    title = models.CharField("título", max_length=80)
    text = models.TextField("texto")
    is_active = models.BooleanField("activa", default=True)  # baja lógica
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        verbose_name = "respuesta guardada"
        verbose_name_plural = "respuestas guardadas"
        ordering = ["title"]
        permissions = [("manage_saved_replies", "Puede crear y editar respuestas guardadas")]

    def __str__(self) -> str:
        return self.title
