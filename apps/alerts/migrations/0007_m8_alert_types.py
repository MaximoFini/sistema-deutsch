from django.db import migrations

ALERT_TYPES = [
    ("wholesale.registration_new", "Nuevo registro en la tienda mayorista", "info", ["Administrador"], True),
    ("wholesale.receipt_uploaded", "Comprobante de pago subido", "info", ["Administrador"], True),
    ("wholesale.order_expired", "Pedido mayorista vencido sin pago", "warning", ["Administrador"], True),
    ("wholesale.shortage_reported", "Faltante en un pedido mayorista", "warning", ["Administrador"], True),
    (
        "wholesale.contabilium_correction",
        "Pedido mayorista para corregir en Contabilium",
        "warning",
        ["Administrador"],
        True,
    ),
    ("wholesale.email_failed", "No se pudo enviar un email a un cliente", "warning", ["Administrador"], False),
]


def seed(apps, schema_editor):
    AlertType = apps.get_model("alerts", "AlertType")
    Group = apps.get_model("auth", "Group")
    for code, name, severity, roles, email in ALERT_TYPES:
        alert_type, created = AlertType.objects.get_or_create(
            code=code, defaults={"name": name, "severity": severity, "send_email": email}
        )
        if created or not alert_type.roles.exists():
            alert_type.roles.set([Group.objects.get_or_create(name=r)[0] for r in roles])


class Migration(migrations.Migration):
    dependencies = [("alerts", "0006_m6_alert_types")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
