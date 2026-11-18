"""Texto propuesto del email de invitación (Deutsch lo revisa y lo edita desde el panel)."""

from django.db import migrations

CODE = "invitation"
NAME = "Invitación a crear la contraseña"
SUBJECT = "Ya podés ingresar a la tienda mayorista de Deutsch"
BODY = (
    "Hola, {cliente}:\n\n"
    "Ya tenés tu cuenta en la tienda mayorista de Deutsch. Para empezar solo tenés que elegir tu "
    "contraseña y aceptar los términos de venta.\n\n"
    "Creá tu contraseña acá: {enlace}\n\n"
    "El enlace se puede usar una sola vez y vence el {vence}. Si se vence, pedí otro desde la pantalla "
    "de ingreso con tu CUIT y tu email.\n\n"
    "Si no esperabas este email, ignoralo o respondenos."
)


def seed(apps, schema_editor):
    EmailTemplate = apps.get_model("wholesale", "EmailTemplate")
    EmailTemplate.objects.get_or_create(code=CODE, defaults={"name": NAME, "subject": SUBJECT, "body": BODY})


class Migration(migrations.Migration):
    dependencies = [("wholesale", "0005_invitaciones")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
