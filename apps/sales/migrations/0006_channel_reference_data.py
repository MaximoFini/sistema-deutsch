from django.db import migrations


def fill(apps, schema_editor):
    SalesDocument = apps.get_model("sales", "SalesDocument")
    ExternalRef = apps.get_model("integrations", "ExternalRef")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.filter(app_label="sales", model="salesdocument").first()
    for doc in SalesDocument.objects.filter(channel_reference="").select_related("channel"):
        code = doc.channel.code
        ref_text = ""
        if ct is not None:
            refs = list(ExternalRef.objects.filter(content_type=ct, object_id=doc.pk, channel__code=code))
            if code == "tiendanube" and refs:
                ref_text = f"TN #{refs[0].extra.get('number') or refs[0].external_id}"
            elif code == "mercadolibre" and refs:
                pack = next((r.external_id for r in refs if r.external_id.startswith("pack:")), None)
                order = next((r.external_id for r in refs if r.external_id.startswith("order:")), None)
                ref_text = f"ML pack {pack.split(':', 1)[1]}" if pack else f"ML {order.split(':', 1)[1]}" if order else ""
        if not ref_text and code == "manual":
            ref_text = f"Manual #{doc.number}"
        if ref_text:
            doc.channel_reference = ref_text[:60]
            doc.save(update_fields=["channel_reference"])


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0005_alter_salesdocument_options_and_more"),
        ("integrations", "0003_alter_channel_options"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
