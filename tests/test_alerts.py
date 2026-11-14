from unittest import mock

import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.roles import ADMIN, DEPOSITO
from apps.alerts import services as alerts
from apps.alerts.models import Alert, AlertReceipt, AlertType
from apps.alerts.tasks import MAX_EMAIL_ATTEMPTS, send_alert_email

pytestmark = pytest.mark.django_db


def run_email_jobs(connector):
    for job in list(connector.jobs.values()):
        if job["task_name"].endswith("send_alert_email") and job["status"] == "todo":
            job["status"] = "done"
            send_alert_email(**job["args"])


def test_emit_creates_receipts_only_for_target_roles(users_by_role, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        alert = alerts.emit("integration.event_failed", "Falló algo", dedupe_key="e1")
    receipts = AlertReceipt.objects.filter(alert=alert)
    assert [r.user.email for r in receipts] == [users_by_role[ADMIN].email]


def test_same_event_alerts_once(users_by_role, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        first = alerts.emit("integration.event_failed", "Falló", dedupe_key="evento-7")
        second = alerts.emit("integration.event_failed", "Falló", dedupe_key="evento-7")
    assert first is not None and second is None
    assert Alert.objects.count() == 1


def test_email_sent_to_role(users_by_role, in_memory_queue, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        alerts.emit("integration.event_failed", "Falló un evento", body="detalle", dedupe_key="x")
    run_email_jobs(in_memory_queue)
    assert [m.to for m in mail.outbox] == [[users_by_role[ADMIN].email]]
    assert AlertReceipt.objects.get().emailed_at is not None


def test_no_email_when_type_has_it_off(users_by_role, in_memory_queue, django_capture_on_commit_callbacks):
    AlertType.objects.filter(code="integration.event_failed").update(send_email=False)
    with django_capture_on_commit_callbacks(execute=True):
        alerts.emit("integration.event_failed", "Sin email", dedupe_key="y")
    assert not in_memory_queue.jobs


def test_email_failure_retries_and_alert_stays_visible(
    users_by_role, in_memory_queue, client, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        alerts.emit("integration.event_failed", "SMTP caído", dedupe_key="z")
    with mock.patch("apps.alerts.tasks.send_mail", side_effect=OSError("smtp down")):
        for _ in range(MAX_EMAIL_ATTEMPTS):
            run_email_jobs(in_memory_queue)
    receipt = AlertReceipt.objects.get()
    assert receipt.email_attempts == MAX_EMAIL_ATTEMPTS
    assert receipt.emailed_at is None and "smtp down" in receipt.email_error
    pending = [j for j in in_memory_queue.jobs.values() if j["status"] == "todo"]
    assert not pending  # dejó de reintentar
    client.force_login(users_by_role[ADMIN])
    assert "SMTP caído" in client.get(reverse("alerts:list")).content.decode()


def test_read_unread_and_bell(users_by_role, client, django_capture_on_commit_callbacks):
    admin = users_by_role[ADMIN]
    with django_capture_on_commit_callbacks(execute=True):
        alerts.emit("integration.event_failed", "A1", dedupe_key="1")
        alerts.emit("integration.event_failed", "A2", dedupe_key="2")
    client.force_login(admin)
    assert alerts.unread_count(admin) == 2
    receipt = AlertReceipt.objects.filter(user=admin).first()
    client.post(reverse("alerts:mark_read", args=[receipt.pk]))
    assert alerts.unread_count(admin) == 1
    assert ">1<" in client.get(reverse("alerts:bell")).content.decode()
    client.post(reverse("alerts:mark_all_read"))
    assert alerts.unread_count(admin) == 0


def test_user_cannot_mark_someone_elses_alert(users_by_role, client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        alerts.emit("integration.event_failed", "A1", dedupe_key="1")
    receipt = AlertReceipt.objects.get()
    client.force_login(users_by_role[DEPOSITO])
    assert client.post(reverse("alerts:mark_read", args=[receipt.pk])).status_code == 404
