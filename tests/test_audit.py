from datetime import timedelta

import pytest
from django.db import DatabaseError, connection, transaction
from django.urls import reverse
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditLog, ImmutableRecordError

pytestmark = pytest.mark.django_db


def test_record_stores_everything(admin_user):
    log = audit.record(admin_user, "user.updated", admin_user, before={"a": 1}, after={"a": 2}, motivo="test")
    assert log.actor == admin_user and log.actor_label == str(admin_user)
    assert log.before == {"a": 1} and log.after == {"a": 2}
    assert log.object_id == str(admin_user.pk) and log.metadata == {"motivo": "test"}


def test_system_actor():
    log = audit.record(None, "integration.write_blocked", after={"channel": "x"})
    assert log.actor is None and log.actor_label == "sistema"


def test_uncatalogued_action_rejected(admin_user):
    with pytest.raises(ValueError):
        audit.record(admin_user, "algo.inventado")


def test_model_blocks_update_and_delete(admin_user):
    log = audit.record(admin_user, "user.updated", admin_user)
    log.action = "user.created"
    with pytest.raises(ImmutableRecordError):
        log.save()
    with pytest.raises(ImmutableRecordError):
        log.delete()


def test_database_trigger_blocks_update_and_delete(admin_user):
    log = audit.record(admin_user, "user.updated", admin_user)
    for sql in ["UPDATE audit_auditlog SET action='x' WHERE id=%s", "DELETE FROM audit_auditlog WHERE id=%s"]:
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, [log.pk])
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=log.pk).update(action="x")


def test_screen_filters(admin_client, admin_user, make_user):
    other = make_user("otro@test.local")
    audit.record(admin_user, "user.created", other)
    audit.record(other, "user.updated", other)
    url = reverse("audit:list")
    assert len(admin_client.get(url).context["object_list"]) == 2
    assert len(admin_client.get(url, {"user": other.pk}).context["object_list"]) == 1
    assert len(admin_client.get(url, {"action": "user.created"}).context["object_list"]) == 1
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    assert len(admin_client.get(url, {"since": tomorrow}).context["object_list"]) == 0
