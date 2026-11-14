import logging
from datetime import timedelta

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import ADMIN, VENTAS
from apps.alerts.models import Alert
from apps.audit.models import AuditLog
from apps.catalog.models import Product
from apps.integrations import credentials, guard, ratelimit, registry, services
from apps.integrations.adapters.fake import FakeAdapter
from apps.integrations.http import ChannelClient, ChannelHTTPError
from apps.integrations.models import Channel, ChannelWriteSwitch, InboundEvent, RateLimitBucket, SyncRun

pytestmark = pytest.mark.django_db


@pytest.fixture
def fake(db):
    Channel.objects.create(code="fake", name="Canal de prueba")
    for kind in ("stock", "price"):
        ChannelWriteSwitch.objects.create(channel=Channel.objects.get(code="fake"), kind=kind)
    adapter = registry.register(FakeAdapter())
    yield adapter
    registry.unregister("fake")


def run_jobs(connector, task_suffix="process_event", ignore_schedule=True):
    """Ejecuta los jobs pendientes de la cola en memoria (incluye los programados a futuro)."""
    from apps.integrations.tasks import process_event

    ran = 0
    for job in list(connector.jobs.values()):
        if job["task_name"].endswith(task_suffix) and job["status"] == "todo":
            if not ignore_schedule and job.get("scheduled_at"):
                continue
            job["status"] = "done"
            process_event(**job["args"])
            ran += 1
    return ran


def post_webhook(client, payload, signature="ok"):
    return client.post(
        "/hooks/fake/", data=payload, content_type="application/json", HTTP_X_FAKE_SIGNATURE=signature
    )


# ── Recepción e idempotencia ─────────────────────────────────────────────


def test_webhook_stores_and_enqueues_without_processing(client, fake, in_memory_queue):
    payload = {"event": "product.updated", "id": "p1", "name": "Buzo", "updated_at": "t1"}
    assert post_webhook(client, payload).status_code == 200
    event = InboundEvent.objects.get()
    assert event.status == "pending" and fake.calls == 0  # respondió sin procesar
    assert len(in_memory_queue.jobs) == 1


def test_duplicate_event_processed_once(client, fake, in_memory_queue):
    payload = {"event": "product.updated", "id": "p1", "name": "Buzo", "updated_at": "t1"}
    post_webhook(client, payload)
    post_webhook(client, payload)
    assert InboundEvent.objects.count() == 1
    assert run_jobs(in_memory_queue) == 1
    assert fake.calls == 1 and Product.objects.count() == 1


def test_handler_is_idempotent_on_reprocess(fake):
    for updated in ("t1", "t2"):  # dos eventos distintos de la misma entidad
        event, _ = services.receive_event(
            "fake", "product.updated", f"p1:{updated}", {"id": "p1", "name": f"Buzo {updated}"}, {}
        )
        services.process(event.pk)
    assert Product.objects.count() == 1 and Product.objects.get().name == "Buzo t2"


def test_invalid_signature_rejected(client, fake):
    assert post_webhook(client, {"event": "x", "id": "1"}, signature="mala").status_code == 403
    assert not InboundEvent.objects.exists()


def test_unknown_channel_404(client):
    assert client.post("/hooks/noexiste/", data={}, content_type="application/json").status_code == 404


def test_unknown_topic_is_ignored(fake):
    event, _ = services.receive_event("fake", "otra.cosa", "k1", {"id": "1"}, {})
    services.process(event.pk)
    event.refresh_from_db()
    assert event.status == "ignored"


# ── Reintentos, alerta final y reproceso manual ──────────────────────────


def test_retries_with_backoff_then_succeeds(fake, in_memory_queue):
    fake.fail_times = 2
    services.receive_event("fake", "product.updated", "k1", {"id": "p1", "name": "Buzo"}, {})
    for _ in range(3):
        run_jobs(in_memory_queue)
    event = InboundEvent.objects.get()
    assert event.status == "done" and event.attempts == 3
    scheduled = [j for j in in_memory_queue.jobs.values() if j.get("scheduled_at")]
    assert len(scheduled) == 2  # los dos reintentos se programaron a futuro


def test_exhausted_retries_fail_and_alert(fake, in_memory_queue, users_by_role):
    fake.fail_times = 99
    services.receive_event("fake", "product.updated", "k1", {"id": "p1", "name": "Buzo"}, {})
    for _ in range(services.MAX_ATTEMPTS + 2):
        run_jobs(in_memory_queue)
    event = InboundEvent.objects.get()
    assert event.status == "failed" and event.attempts == services.MAX_ATTEMPTS
    assert "falla simulada" in event.last_error
    assert Alert.objects.filter(alert_type__code="integration.event_failed").count() == 1


def test_manual_retry_from_panel(fake, in_memory_queue, admin_client):
    fake.fail_times = services.MAX_ATTEMPTS
    services.receive_event("fake", "product.updated", "k1", {"id": "p1", "name": "Buzo"}, {})
    for _ in range(services.MAX_ATTEMPTS):
        run_jobs(in_memory_queue)
    assert InboundEvent.objects.get().status == "failed"
    admin_client.post(reverse("integrations:retry_failed", args=["fake"]))
    run_jobs(in_memory_queue)
    assert InboundEvent.objects.get().status == "done"
    assert AuditLog.objects.filter(action="integration.event_retried").count() == 1


def test_retry_requires_permission(fake, client, users_by_role):
    client.force_login(users_by_role[VENTAS])
    assert client.post(reverse("integrations:retry_failed", args=["fake"])).status_code == 403


# ── Conciliación ─────────────────────────────────────────────────────────


def test_reconciliation_records_runs_and_uses_last_success(fake):
    run1 = services.run_reconciliation("fake")
    assert run1.status == "ok" and fake.reconcile_calls == [None]
    services.run_reconciliation("fake")
    assert fake.reconcile_calls[1] == run1.started_at - timedelta(minutes=10)


def test_reconciliation_error_is_recorded(fake):
    fake.reconcile = lambda since: (_ for _ in ()).throw(RuntimeError("API caída"))
    run = services.run_reconciliation("fake")
    assert run.status == "error" and "API caída" in run.error


def test_periodic_task_enqueues_one_per_adapter(fake, in_memory_queue):
    from apps.integrations.tasks import reconcile_all

    reconcile_all(timestamp=0)
    names = [j["args"]["channel_code"] for j in in_memory_queue.jobs.values()]
    assert names == ["fake"]


# ── Credenciales ─────────────────────────────────────────────────────────


def test_credentials_roundtrip_and_encrypted_at_rest(fake):
    credentials.save("fake", {"access_token": "TOKEN-SUPER-SECRETO"})
    from apps.integrations.models import ChannelCredential

    raw = bytes(ChannelCredential.objects.get().data_encrypted)
    assert b"TOKEN-SUPER-SECRETO" not in raw
    assert credentials.get("fake") == {"access_token": "TOKEN-SUPER-SECRETO"}
    assert "TOKEN" not in repr(ChannelCredential.objects.get())


def test_credentials_key_rotation(fake, settings):
    credentials.save("fake", {"k": "v"})
    new_key = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEYS = [new_key, *settings.FIELD_ENCRYPTION_KEYS]
    assert credentials.rotate_all() == 1
    settings.FIELD_ENCRYPTION_KEYS = [new_key]
    assert credentials.get("fake") == {"k": "v"}


def test_missing_credentials(fake):
    with pytest.raises(credentials.CredentialsMissing):
        credentials.get("fake")


def test_token_never_in_logs_during_full_flow(fake, caplog, client, in_memory_queue):
    credentials.save("fake", {"access_token": "TOKEN-SUPER-SECRETO"})
    with caplog.at_level(logging.DEBUG), respx.mock(base_url="https://api.fake") as mock:
        mock.get("/items").mock(return_value=httpx.Response(200, json={}))
        token = credentials.get("fake")["access_token"]
        c = ChannelClient("fake", base_url="https://api.fake", sleep=lambda s: None)
        c.get(f"/items?access_token={token}", headers={"Authorization": f"Bearer {token}"})
        post_webhook(client, {"event": "product.updated", "id": "p1", "name": "B", "updated_at": "1"})
        run_jobs(in_memory_queue)
    assert "TOKEN-SUPER-SECRETO" not in caplog.text


# ── Cliente HTTP y límite de velocidad ───────────────────────────────────


@respx.mock(base_url="https://api.fake")
def test_http_retries_on_429_then_ok(respx_mock, db):
    route = respx_mock.get("/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    waits = []
    client = ChannelClient("fake", base_url="https://api.fake", sleep=waits.append)
    assert client.get("/x").json() == {"ok": True}
    assert route.call_count == 2 and 2.0 in waits


@respx.mock(base_url="https://api.fake")
def test_http_gives_up_after_retries(respx_mock, db):
    respx_mock.get("/x").mock(return_value=httpx.Response(503))
    client = ChannelClient("fake", base_url="https://api.fake", sleep=lambda s: None, max_retries=2)
    with pytest.raises(ChannelHTTPError):
        client.get("/x")


def test_rate_limit_waits_when_bucket_empty(db):
    RateLimitBucket.objects.create(
        key="lento", capacity=2, refill_per_second=1, tokens=2, updated_at=timezone.now()
    )
    assert ratelimit.try_acquire("lento") == 0
    assert ratelimit.try_acquire("lento") == 0
    assert ratelimit.try_acquire("lento") > 0  # el tercer pedido tiene que esperar


def test_rate_limit_acquire_sleeps_until_refill(db):
    RateLimitBucket.objects.create(
        key="lento", capacity=1, refill_per_second=1, tokens=0, updated_at=timezone.now()
    )
    waits = []

    def fake_sleep(seconds):
        waits.append(seconds)
        # simula que pasó el tiempo: retrocede la última actualización del bucket
        RateLimitBucket.objects.filter(key="lento").update(
            updated_at=timezone.now() - timedelta(seconds=seconds + 0.1)
        )

    ratelimit.acquire("lento", sleep=fake_sleep)
    assert len(waits) == 1 and waits[0] > 0


# ── Interruptor de escritura (regla de oro) ──────────────────────────────


@respx.mock(base_url="https://api.fake", assert_all_called=False)
def test_write_blocked_by_default_and_no_http(respx_mock, fake):
    route = respx_mock.put("/stock/SKU1").mock(return_value=httpx.Response(200))
    http = ChannelClient("fake", base_url="https://api.fake", sleep=lambda s: None)
    with pytest.raises(guard.WriteBlocked):
        fake.write_stock("SKU1", 5, http=http)
    assert route.call_count == 0
    assert AuditLog.objects.filter(action="integration.write_blocked").exists()


@override_settings(ALLOW_CHANNEL_WRITES=False)
def test_switch_on_but_server_lock_off_still_blocks(fake):
    ChannelWriteSwitch.objects.filter(channel__code="fake", kind="stock").update(enabled=True)
    with pytest.raises(guard.WriteBlocked):
        fake.write_stock("SKU1", 5)


@override_settings(ALLOW_CHANNEL_WRITES=True)
@respx.mock(base_url="https://api.fake")
def test_both_locks_open_allows_write(respx_mock, fake):
    route = respx_mock.put("/stock/SKU1").mock(return_value=httpx.Response(200))
    ChannelWriteSwitch.objects.filter(channel__code="fake", kind="stock").update(enabled=True)
    fake.write_stock("SKU1", 5, http=ChannelClient("fake", base_url="https://api.fake", sleep=lambda s: None))
    assert route.call_count == 1


@override_settings(ALLOW_CHANNEL_WRITES=False)
def test_panel_refuses_to_turn_on_when_server_lock_off(admin_client):
    admin_client.post(
        reverse("integrations:toggle_write_switch", args=["tiendanube", "stock"]), {"enabled": "1"}
    )
    assert not ChannelWriteSwitch.objects.get(channel__code="tiendanube", kind="stock").enabled


@override_settings(ALLOW_CHANNEL_WRITES=True)
def test_panel_toggle_is_audited(admin_client):
    admin_client.post(
        reverse("integrations:toggle_write_switch", args=["tiendanube", "stock"]), {"enabled": "1"}
    )
    assert ChannelWriteSwitch.objects.get(channel__code="tiendanube", kind="stock").enabled
    log = AuditLog.objects.get(action="integration.write_switch_changed")
    assert log.before == {"enabled": False} and log.after == {"enabled": True}


# ── Panel de estado ──────────────────────────────────────────────────────


def test_status_panel_counts(fake, admin_client, in_memory_queue):
    fake.fail_times = 99
    services.receive_event("fake", "product.updated", "a", {"id": "1", "name": "x"}, {})
    services.receive_event("fake", "product.updated", "b", {"id": "2", "name": "y"}, {})
    for _ in range(services.MAX_ATTEMPTS):
        run_jobs(in_memory_queue)
    InboundEvent.objects.filter(dedupe_key="b").update(status="pending")
    response = admin_client.get(reverse("integrations:status"))
    card = next(c for c in response.context["cards"] if c["channel"].code == "fake")
    assert card["counts"]["failed"] == 1 and card["counts"]["pending"] == 1


def test_status_panel_marks_stale_channels(admin_client):
    registry.register(type("TN", (), {"code": "tiendanube", "handlers": {}})())
    try:
        SyncRun.objects.create(channel=Channel.objects.get(code="tiendanube"), job="reconcile", status="ok")
        SyncRun.objects.filter(channel__code="tiendanube").update(
            started_at=timezone.now() - timedelta(hours=2)
        )
        response = admin_client.get(reverse("integrations:status"))
        card = next(c for c in response.context["cards"] if c["channel"].code == "tiendanube")
        assert card["stale"] is True
    finally:
        registry.unregister("tiendanube")


def test_status_panel_permission(client, users_by_role):
    client.force_login(users_by_role[VENTAS])
    assert client.get(reverse("integrations:status")).status_code == 403
    client.force_login(users_by_role[ADMIN])
    assert client.get(reverse("integrations:status")).status_code == 200
