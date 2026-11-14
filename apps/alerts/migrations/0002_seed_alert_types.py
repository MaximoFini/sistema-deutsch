from django.db import migrations

# code, nombre, severidad, roles, email
ALERT_TYPES = [
    ("integration.event_failed", "Falló un evento de integración", "critical", ["Administrador"], True),
    ("integration.sync_stale", "Integración sin sincronizar", "warning", ["Administrador"], True),
    ("backup.failed", "Falló el backup diario", "critical", ["Administrador"], True),
]


def seed(apps, schema_editor):
    AlertType = apps.get_model("alerts", "AlertType")
    Group = apps.get_model("auth", "Group")
    for code, name, severity, roles, email in ALERT_TYPES:
        alert_type, created = AlertType.objects.get_or_create(
            code=code, defaults={"name": name, "severity": severity, "send_email": email}
        )
        if created:
            groups = [Group.objects.get_or_create(name=r)[0] for r in roles]
            alert_type.roles.set(groups)


class Migration(migrations.Migration):
    dependencies = [("alerts", "0001_initial"), ("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
