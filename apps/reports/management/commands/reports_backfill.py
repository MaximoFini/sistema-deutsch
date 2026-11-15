"""Completa los datos que usan los reportes (M7). Se puede repetir sin problemas.

manage.py reports_backfill timestamps   # ready_at / dispatched_at desde la auditoría
manage.py reports_backfill stock        # on_hand_after desde el saldo actual
manage.py reports_backfill ml_fees      # comisiones y costos de envío de ML (lee la API)
"""

from django.core.management.base import BaseCommand, CommandError

from apps.reports import backfill, tasks


class Command(BaseCommand):
    help = "Completa los datos de los reportes: timestamps, stock o ml_fees."

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=["timestamps", "stock", "ml_fees"])
        parser.add_argument("--tanda", type=int, default=None, help="Ventas de ML por tanda (ml_fees).")

    def handle(self, *args, mode, tanda, **options):
        if mode == "timestamps":
            stats = backfill.backfill_timestamps()
            self.stdout.write(
                f"Listo: {stats['ready_at']} pedidos con «listo para preparar» y "
                f"{stats['dispatched_at']} con «despachado»."
            )
        elif mode == "stock":
            changed = backfill.backfill_stock()
            self.stdout.write(f"Listo: {changed} movimientos de stock con el saldo reconstruido.")
        else:
            stats = tasks.run_ml_fees(batch_size=tanda)
            if stats is None:
                raise CommandError("Mercado Libre no está conectado: no se pueden leer comisiones.")
            self.stdout.write(
                f"Listo: {stats['completed']} ventas completas, {stats['still_pending']} siguen pendientes, "
                f"{len(stats['errors'])} con error."
                + (f" Se cortó: {stats['stopped']}" if stats["stopped"] else "")
            )
