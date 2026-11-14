from django.db import migrations

ALERT_TYPES = [
    ("ml.claim_opened", "Reclamo nuevo en Mercado Libre que requiere respuesta", "critical", ["Administrador", "Ventas"], True),
    ("ml.question_unanswered_long", "Pregunta de Mercado Libre sin responder hace mucho", "warning", ["Administrador", "Ventas"], False),
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
    dependencies = [("alerts", "0003_m1_alert_types")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
