from django.db import migrations

SEQUENCE = "fulfillment_batch_number_seq"  # = batches.BATCH_SEQUENCE


class Migration(migrations.Migration):
    dependencies = [("fulfillment", "0001_initial")]
    operations = [
        migrations.RunSQL(
            f"CREATE SEQUENCE IF NOT EXISTS {SEQUENCE} START 1;",
            f"DROP SEQUENCE IF EXISTS {SEQUENCE};",
        )
    ]
