"""Reportes (M7): app de solo lectura. No tiene tablas propias.

`Report` es un modelo sin tabla (managed=False) que existe solo para colgar el permiso
`reports.view_reports` (Django necesita un content type para cada permiso).
"""

from django.db import models


class Report(models.Model):
    class Meta:
        managed = False
        default_permissions = ()
        permissions = [("view_reports", "Puede ver los reportes")]
        verbose_name = "reporte"
        verbose_name_plural = "reportes"
