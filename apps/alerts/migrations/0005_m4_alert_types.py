from django.db import migrations

ALERT_TYPES = [
    ("orders.new", "Pedido nuevo para preparar", "info", ["Depósito"], False),
    ("orders.flex_due", "Pedido Flex/Colecta por vencer su despacho", "critical", ["Depósito"], True),
    ("orders.cancelled_in_progress", "Pedido cancelado que ya estaba en preparación", "warning", ["Administrador"], True),
    ("orders.out_of_stock", "Venta de un producto sin stock en el depósito", "critical", ["Administrador"], True),
    ("orders.manual_pending", "Pedido manual sin cobrar o sin facturar", "warning", ["Administrador", "Ventas"], True),
    ("returns.received_adjust_stock", "Devolución recibida: ajustar stock en Contabilium", "warning", ["Administrador"], True),
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
    dependencies = [("alerts", "0004_m2_alert_types")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
