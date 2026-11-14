from django.db import migrations

CHANNELS = [
    ("tiendanube", "Tiendanube"),
    ("mercadolibre", "Mercado Libre"),
    ("contabilium", "Contabilium"),
    ("mayorista", "Tienda mayorista"),
    ("manual", "Pedido manual"),
]


def seed(apps, schema_editor):
    Channel = apps.get_model("integrations", "Channel")
    Switch = apps.get_model("integrations", "ChannelWriteSwitch")
    for code, name in CHANNELS:
        channel, _ = Channel.objects.get_or_create(code=code, defaults={"name": name})
        # Regla de oro: todo apagado por defecto.
        for kind in ("stock", "price"):
            Switch.objects.get_or_create(channel=channel, kind=kind, defaults={"enabled": False})


class Migration(migrations.Migration):
    dependencies = [("integrations", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
