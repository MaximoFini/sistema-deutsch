"""M8a (T3): la alerta de pedidos sin cobrar o sin facturar también cubre los pedidos mayoristas."""

from django.db import migrations

OLD = "Pedido manual sin cobrar o sin facturar"
NEW = "Pedido manual o mayorista sin cobrar o sin facturar"


def rename(apps, schema_editor):
    apps.get_model("alerts", "AlertType").objects.filter(code="orders.manual_pending", name=OLD).update(name=NEW)


def restore(apps, schema_editor):
    apps.get_model("alerts", "AlertType").objects.filter(code="orders.manual_pending", name=NEW).update(name=OLD)


class Migration(migrations.Migration):
    dependencies = [("alerts", "0008_m8_data_change")]
    operations = [migrations.RunPython(rename, restore)]
