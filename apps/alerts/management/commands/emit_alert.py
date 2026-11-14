from django.core.management.base import BaseCommand, CommandError

from apps.alerts.services import emit


class Command(BaseCommand):
    help = "Emite una alerta (usado por scripts del servidor, p. ej. backup fallido)."

    def add_arguments(self, parser):
        parser.add_argument("code")
        parser.add_argument("title")
        parser.add_argument("--body", default="")
        parser.add_argument("--dedupe-key", default="")

    def handle(self, code, title, body, dedupe_key, **options):
        alert = emit(code, title, body=body, dedupe_key=dedupe_key)
        if alert is None:
            raise CommandError("No se emitió la alerta (duplicada, inactiva o tipo inexistente).")
        self.stdout.write(f"Alerta {alert.pk} emitida")
