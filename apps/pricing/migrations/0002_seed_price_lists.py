from django.db import migrations


def seed(apps, schema_editor):
    PriceList = apps.get_model("pricing", "PriceList")
    PriceList.objects.get_or_create(
        code="MINORISTA", defaults={"name": "Minorista", "prices_include_vat": True}
    )
    # Mayorista: precios netos, el IVA se muestra aparte (decisión PRD M8).
    PriceList.objects.get_or_create(
        code="MAYORISTA", defaults={"name": "Mayorista", "prices_include_vat": False}
    )


class Migration(migrations.Migration):
    dependencies = [("pricing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
