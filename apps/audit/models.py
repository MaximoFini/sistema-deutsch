from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ImmutableRecordError(Exception):
    pass


class AuditLog(models.Model):
    """Registro inmutable de acciones de negocio. Ver `apps.audit.services.record`."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, verbose_name="usuario"
    )
    actor_label = models.CharField("usuario (texto)", max_length=200)
    action = models.CharField("acción", max_length=100, db_index=True)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField("objeto", max_length=300, blank=True)
    before = models.JSONField("antes", null=True, blank=True)
    after = models.JSONField("después", null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField("fecha", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "registro de auditoría"
        verbose_name_plural = "auditoría"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_label}: {self.action}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ImmutableRecordError("Los registros de auditoría no se pueden modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Los registros de auditoría no se pueden borrar.")
