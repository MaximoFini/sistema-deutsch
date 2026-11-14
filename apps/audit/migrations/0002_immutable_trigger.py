"""Segunda capa de inmutabilidad: Postgres rechaza UPDATE y DELETE sobre audit_auditlog."""

from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION audit_auditlog_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditlog es inmutable (% bloqueado)', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_auditlog_no_update_delete
BEFORE UPDATE OR DELETE ON audit_auditlog
FOR EACH ROW EXECUTE FUNCTION audit_auditlog_immutable();
"""

DROP = """
DROP TRIGGER IF EXISTS audit_auditlog_no_update_delete ON audit_auditlog;
DROP FUNCTION IF EXISTS audit_auditlog_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunSQL(CREATE, DROP)]
