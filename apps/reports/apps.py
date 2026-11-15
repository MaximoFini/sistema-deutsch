from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = "apps.reports"
    verbose_name = "Reportes"

    def ready(self):
        from django.db.models.signals import post_migrate

        from .backfill import enqueue_ml_fees_after_migrate

        post_migrate.connect(
            enqueue_ml_fees_after_migrate, sender=self, dispatch_uid="reports.enqueue_ml_fees"
        )
