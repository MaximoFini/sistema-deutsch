from django.db import migrations

# code, nombre, severidad, roles, email
ALERT_TYPES = [
    ("catalog.unknown_sku", "Pedido con SKU que no está en el catálogo", "warning", ["Administrador", "Ventas"], True),
    ("integration.write_failed", "No se pudo actualizar un pedido en el canal", "critical", ["Administrador", "Depósito"], True),
    ("integration.disconnected", "Un canal de venta se desconectó", "critical", ["Administrador"], True),
    ("privacy.data_request", "Pedido de datos personales de un cliente", "warning", ["Administrador"], True),
]


def seed(apps, schema_editor):
    AlertType = apps.get_model("alerts", "AlertType")
    Group = apps.get_model("auth", "Group")
    for code, name, severity, roles, email in ALERT_TYPES:
        alert_type, created = AlertType.objects.get_or_create(
            code=code, defaults={"name": name, "severity": severity, "send_email": email}
        )
        if created:
            alert_type.roles.set([Group.objects.get_or_create(name=r)[0] for r in roles])


class Migration(migrations.Migration):
    dependencies = [("alerts", "0002_seed_alert_types")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
