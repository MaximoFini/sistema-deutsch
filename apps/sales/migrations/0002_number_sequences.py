from django.db import migrations

from apps.sales.numbering import SEQUENCES

create = "\n".join(f"CREATE SEQUENCE IF NOT EXISTS {name} START 1;" for name in SEQUENCES.values())
drop = "\n".join(f"DROP SEQUENCE IF EXISTS {name};" for name in SEQUENCES.values())


class Migration(migrations.Migration):
    dependencies = [("sales", "0001_initial")]
    operations = [migrations.RunSQL(create, drop)]
