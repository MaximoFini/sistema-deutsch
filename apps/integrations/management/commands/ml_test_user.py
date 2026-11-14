from django.core.management.base import BaseCommand

from apps.integrations.adapters.mercadolibre.client import MLClient


class Command(BaseCommand):
    help = "Crea un usuario de prueba de Mercado Libre (requiere la app conectada). No guarda la contraseña."

    def add_arguments(self, parser):
        parser.add_argument("--site", default="MLA")

    def handle(self, site, **options):
        data = MLClient().post("/users/test_user", json={"site_id": site})
        self.stdout.write(f"Usuario de prueba creado: id={data.get('id')} nickname={data.get('nickname')}")
        self.stdout.write(
            "La contraseña se muestra una sola vez en la respuesta de ML: guardala en tu gestor, no en el repo ni en Plane."
        )
        self.stdout.write(f"password={data.get('password')}")
