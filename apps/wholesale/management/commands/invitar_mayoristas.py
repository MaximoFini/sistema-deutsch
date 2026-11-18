"""Cuentas e invitaciones de los clientes mayoristas ya cargados (M9-03).

manage.py invitar_mayoristas preparar [--dry-run]   # crea cuentas e invitaciones «sin enviar»; NO manda nada
manage.py invitar_mayoristas estado                 # totales de seguimiento
manage.py invitar_mayoristas enviar --usuario EMAIL [--reenviar]
                                                    # encola las invitaciones (apagado por defecto)

«enviar» solo funciona con STORE_INVITATIONS_ENABLED=true y con un usuario que tenga el permiso
«manage_customers». Con STORE_EMAIL_DRY_RUN=true solo registra qué mandaría.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from apps.wholesale import invitations


class Command(BaseCommand):
    help = "Prepara y (cuando se habilite) envía las invitaciones a los clientes mayoristas ya cargados."

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=["preparar", "estado", "enviar"])
        parser.add_argument("--dry-run", action="store_true", help="Solo informa, no crea nada (preparar).")
        parser.add_argument("--usuario", help="Email del usuario que envía (enviar).")
        parser.add_argument(
            "--reenviar", action="store_true", help="Reenviar a los que no entraron (enviar)."
        )

    def handle(self, *args, mode, dry_run, usuario, reenviar, **options):
        if mode == "preparar":
            self.preparar(dry_run)
        elif mode == "estado":
            self.estado()
        else:
            self.enviar(usuario, reenviar)

    def preparar(self, dry_run):
        report = invitations.prepare(dry_run=dry_run)
        prefix = "ENSAYO (no se creó nada). " if dry_run else ""
        self.stdout.write(f"{prefix}Cuentas {'a crear' if dry_run else 'creadas'}: {report.created}")
        self.stdout.write(f"Cuentas ya registradas que se vincularon/aprobaron: {report.linked}")
        self.stdout.write(f"Ya estaban: {report.already}")
        self.stdout.write(f"No incluidos: {len(report.excluded)}")
        for code, count in report.by_reason.items():
            self.stdout.write(f"  - {invitations.REASONS[code]}: {count}")
        self.stdout.write("No se mandó ningún email.")

    def estado(self):
        t = invitations.totals()
        self.stdout.write(
            f"Invitados {t['invited']} · sin enviar {t['unsent']} · enviadas {t['sent']} · "
            f"entraron {t['accepted']} · vencidas {t['expired']} · rebotadas {t['bounced']}"
        )

    def enviar(self, email, reenviar):
        if not email:
            raise CommandError("Indicá quién envía con --usuario EMAIL.")
        user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            raise CommandError("No encontramos a ese usuario.")
        targets = invitations.accounts_for("not_entered" if reenviar else "unsent")
        try:
            result = invitations.send_invitations(targets, user)
        except invitations.InvitationsDisabled as exc:
            raise CommandError(str(exc)) from exc
        except PermissionDenied as exc:
            raise CommandError("Ese usuario no tiene permiso para enviar invitaciones.") from exc
        if result.dry_run:
            self.stdout.write(f"ENSAYO: se mandarían {result.would_send}. No se encoló nada.")
        else:
            self.stdout.write(f"Encoladas: {result.queued}.")
        if result.deferred:
            self.stdout.write(f"Quedan {result.deferred} para la próxima por el límite por hora.")
