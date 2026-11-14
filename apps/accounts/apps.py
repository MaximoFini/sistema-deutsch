from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    verbose_name = "Usuarios y permisos"

    def ready(self):
        from django.db.models.signals import post_migrate

        from .roles import sync_roles_signal

        post_migrate.connect(sync_roles_signal, dispatch_uid="accounts.sync_roles")
