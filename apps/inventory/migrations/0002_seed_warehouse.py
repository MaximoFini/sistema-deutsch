from django.db import migrations


def seed(apps, schema_editor):
    Warehouse = apps.get_model("inventory", "Warehouse")
    Warehouse.objects.get_or_create(code="LOCAL", defaults={"name": "Local", "is_default": True})


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
