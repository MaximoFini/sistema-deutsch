from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models


class AlertType(models.Model):
    class Severity(models.TextChoices):
        INFO = "info", "Información"
        WARNING = "warning", "Advertencia"
        CRITICAL = "critical", "Crítica"

    code = models.CharField("código", max_length=80, unique=True)
    name = models.CharField("nombre", max_length=150)
    severity = models.CharField(
        "severidad", max_length=10, choices=Severity.choices, default=Severity.WARNING
    )
    roles = models.ManyToManyField(Group, verbose_name="roles destinatarios", blank=True)
    send_email = models.BooleanField("enviar email", default=True)
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        verbose_name = "tipo de alerta"
        verbose_name_plural = "tipos de alerta"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Alert(models.Model):
    alert_type = models.ForeignKey(AlertType, on_delete=models.PROTECT, related_name="alerts")
    title = models.CharField("título", max_length=200)
    body = models.TextField("detalle", blank=True)
    link_url = models.CharField("link", max_length=500, blank=True)
    dedupe_key = models.CharField(max_length=200)
    created_at = models.DateTimeField("fecha", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "alerta"
        verbose_name_plural = "alertas"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["alert_type", "dedupe_key"], name="unique_alert_dedupe")
        ]

    def __str__(self) -> str:
        return self.title


class AlertReceipt(models.Model):
    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="receipts")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alert_receipts"
    )
    read_at = models.DateTimeField("leída", null=True, blank=True)
    emailed_at = models.DateTimeField("email enviado", null=True, blank=True)
    email_attempts = models.PositiveSmallIntegerField(default=0)
    email_error = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["alert", "user"], name="unique_alert_receipt")]
        ordering = ["-alert__created_at"]
