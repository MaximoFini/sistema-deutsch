from django.db import migrations

ALERT_TYPES = [
    ("ml.claim_due", "Reclamo por vencer", "critical", ["Administrador", "Ventas"], True),
    ("ml.question_unanswered_long", "Pregunta de Mercado Libre sin responder hace mucho", "warning", ["Administrador", "Ventas"], False),
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


def relink_claim_alerts(apps, schema_editor):
    """Los avisos de reclamo nuevo ya emitidos llevaban a Integraciones: ahora van a la ficha del reclamo."""
    Alert = apps.get_model("alerts", "Alert")
    Claim = apps.get_model("conversations", "Claim")
    for alert in Alert.objects.filter(alert_type__code="ml.claim_opened", dedupe_key__startswith="claim:"):
        claim = Claim.objects.filter(external_id=alert.dedupe_key.split(":", 1)[1]).first()
        if claim is not None:
            alert.link_url = f"/ml/reclamos/{claim.pk}/"
            alert.save(update_fields=["link_url"])


class Migration(migrations.Migration):
    dependencies = [("alerts", "0005_m4_alert_types"), ("conversations", "0001_initial")]
    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.RunPython(relink_claim_alerts, migrations.RunPython.noop),
    ]
