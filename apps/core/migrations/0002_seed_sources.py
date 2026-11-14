from django.db import migrations


def seed(apps, schema_editor):
    DataSource = apps.get_model("core", "DataSource")
    for data_type in ["stock", "price", "product", "customer", "invoice"]:
        DataSource.objects.get_or_create(data_type=data_type, defaults={"source": "contabilium"})


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
