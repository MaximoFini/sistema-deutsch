from django.db import migrations

ALERT_TYPES = [
    (
        "wholesale.data_change_requested",
        "Un cliente mayorista pidió cambiar sus datos",
        "info",
        ["Administrador"],
        True,
    ),
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
    dependencies = [("alerts", "0007_m8_alert_types")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
