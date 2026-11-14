"""Tests de las correcciones de la auditoría M0–M4 (docs/auditoria-m0-m4.md)."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import httpx
import pytest
import respx
from django.contrib.messages import get_messages
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import ADMIN, DEPOSITO
from apps.alerts.models import Alert
from apps.audit.models import AuditLog
from apps.catalog.models import Product, Variant
from apps.conversations.models import Claim
from apps.customers.models import Customer
from apps.integrations import errors, services
from apps.integrations.adapters.mercadolibre import auth as ml_auth
from apps.integrations.adapters.tiendanube import oauth as tn_oauth
from apps.integrations.http import ChannelHTTPError
from apps.integrations.models import Channel, InboundEvent, SyncRun
from apps.inventory.models import StockLevel, Warehouse
from apps.sales import manual, payments, returns, states, sync
from apps.sales.models import Payment, ReturnInfo, SalesDocument, SalesLine, Shipment
from apps.sales.tasks import check_manual_pending

pytestmark = pytest.mark.django_db


def order(channel="manual", status=states.NEW, total=Decimal("1000"), paid_amount=None, **fields):
    doc = SalesDocument.objects.create(
        channel=Channel.objects.get(code=channel),
        status=status,
        issued_at=timezone.now(),
        total=total,
        channel_reference=f"{channel} test",
        **fields,
    )
    Shipment.objects.create(document=doc, method=Shipment.Method.CARRIER)
    if paid_amount:
        Payment.objects.create(
            document=doc, method="cash", amount=paid_amount, status=Payment.Status.CONFIRMED
        )
    return doc


def status_changes(doc):
    return list(
        AuditLog.objects.filter(action="order.status_changed", object_id=str(doc.pk))
        .order_by("id")
        .values_list("before__estado", "after__estado")
    )


def msgs(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


@pytest.fixture
def variant(db):
    p = Product.objects.create(name="Buzo")
    return Variant.objects.create(product=p, sku="BUZ-1")


# ── B1: reclamo sobre pedido entregado ───────────────────────────────────


def test_b1_claim_on_delivered_order_is_stable(db):
    doc = order("mercadolibre", status=states.DELIVERED, paid_amount=Decimal("1000"))
    Shipment.objects.filter(document=doc).update(status="delivered")
    claim = Claim.objects.create(channel=doc.channel, external_id="C1", document=doc, status="opened")

    assert sync.sync_internal_status(doc) == states.CLAIM
    doc.refresh_from_db()
    assert doc.status == states.CLAIM and doc.status_before_claim == states.DELIVERED
    logs = AuditLog.objects.count()
    for _ in range(3):  # varias sincronizaciones seguidas: no oscila ni audita de nuevo
        assert sync.sync_internal_status(doc) is None
    assert AuditLog.objects.count() == logs
    doc.refresh_from_db()
    assert doc.status == states.CLAIM

    claim.status = "closed"
    claim.save()
    assert sync.sync_internal_status(doc) == states.DELIVERED
    assert sync.sync_internal_status(doc) is None


def test_b1_delivered_while_claim_open_waits_until_claim_closes(db):
    doc = order("mercadolibre", status=states.DISPATCHED, paid_amount=Decimal("1000"))
    claim = Claim.objects.create(channel=doc.channel, external_id="C2", document=doc, status="opened")
    sync.sync_internal_status(doc)
    Shipment.objects.filter(document=doc).update(status="delivered")
    assert sync.sync_internal_status(doc) is None
    doc.refresh_from_db()
    assert doc.status == states.CLAIM

    claim.status = "closed"
    claim.save()
    assert sync.sync_internal_status(doc) == states.DELIVERED
    assert status_changes(doc) == [
        (states.DISPATCHED, states.CLAIM),
        (states.CLAIM, states.DISPATCHED),  # vuelve al estado anterior…
        (states.DISPATCHED, states.DELIVERED),  # …y recién ahí corre "entregado"
    ]


# ── B2 y B3: cobrado ─────────────────────────────────────────────────────


def test_b2_ml_paid_with_coupon_leaves_awaiting_payment(db):
    doc = order(
        "mercadolibre",
        status=states.AWAITING_PAYMENT,
        paid_amount=Decimal("800"),  # pagó menos que el total (cupón)
        channel_status="paid/ready_to_ship",
    )
    assert payments.is_paid(doc)
    assert sync.sync_internal_status(doc) == states.NEW


@pytest.mark.parametrize(
    ("channel", "channel_status", "expected"),
    [
        ("mercadolibre", "paid", True),
        ("mercadolibre", "paid+delivered/delivered", True),
        ("mercadolibre", "cancelled,paid", False),  # pack con una orden cancelada
        ("mercadolibre", "payment_required", False),
        ("tiendanube", "paid", False),  # la regla de estado del canal es solo de ML
    ],
)
def test_b2_ml_channel_status_paid_rule(db, channel, channel_status, expected):
    doc = order(channel, paid_amount=Decimal("100"), channel_status=channel_status)
    assert payments.is_paid(doc) is expected
    paid_ids = set(
        payments.annotate_paid(SalesDocument.objects.filter(pk=doc.pk))
        .filter(payments.paid_q())
        .values_list("pk", flat=True)
    )
    assert (doc.pk in paid_ids) is expected  # el filtro de la lista coincide


def test_b3_partial_payment_is_pending_everywhere(admin_client):
    doc = order("manual", paid_amount=Decimal("400"))  # pago parcial de un total de 1000
    assert not manual.is_paid(doc)
    assert not payments.is_paid(doc)
    assert not sync.facts(doc).paid
    detail = admin_client.get(reverse("sales:detail", args=[doc.pk]))
    assert detail.context["paid"] is False
    pending = admin_client.get(reverse("sales:list"), {"cobro": "pendiente"})
    assert doc.pk in [o.pk for o in pending.context["orders"]]
    paid = admin_client.get(reverse("sales:list"), {"cobro": "cobrado"})
    assert doc.pk not in [o.pk for o in paid.context["orders"]]
    assert "Pendiente" in pending.content.decode()


def test_b3_full_payment_is_paid_everywhere(admin_client):
    doc = order("manual", paid_amount=Decimal("1000"))
    assert manual.is_paid(doc) and sync.facts(doc).paid
    assert admin_client.get(reverse("sales:detail", args=[doc.pk])).context["paid"] is True
    paid = admin_client.get(reverse("sales:list"), {"cobro": "cobrado"})
    assert doc.pk in [o.pk for o in paid.context["orders"]]


# ── B4 y B5: tareas periódicas ───────────────────────────────────────────


def _cron(task_name):
    from procrastinate.contrib.django import app

    import apps.integrations.tasks  # noqa: F401
    import apps.sales.tasks  # noqa: F401

    return app.periodic_registry.periodic_tasks[(task_name, "")].cron


def test_b4_orders_watch_every_5_minutes():
    assert _cron("apps.sales.tasks.orders_watch") == "*/5 * * * *"


def test_b5_requeue_stuck_task_is_periodic():
    assert _cron("apps.integrations.tasks.requeue_stuck_events") == "*/5 * * * *"


def test_b5_requeue_stuck_events(in_memory_queue):
    channel = Channel.objects.get(code="tiendanube")
    old = timezone.now() - timedelta(minutes=20)

    def event(key, status, updated_at=None):
        e = InboundEvent.objects.create(channel=channel, topic="t", dedupe_key=key, payload={}, status=status)
        if updated_at:
            InboundEvent.objects.filter(pk=e.pk).update(updated_at=updated_at)
        return e

    stuck_processing = event("a", InboundEvent.Status.PROCESSING, old)
    lost_pending = event("b", InboundEvent.Status.PENDING, old)
    scheduled_pending = event("c", InboundEvent.Status.PENDING, old)
    event("d", InboundEvent.Status.PROCESSING)  # reciente: puede estar procesándose
    event("e", InboundEvent.Status.DONE, old)
    event("f", InboundEvent.Status.FAILED, old)  # los fallidos se reprocesan a mano

    real = services._has_queued_job
    assert real(lost_pending.pk) is False  # la consulta a la tabla de tareas funciona
    with mock.patch.object(services, "_has_queued_job", side_effect=lambda pk: pk == scheduled_pending.pk):
        assert services.requeue_stuck() == 2
        requeued = {j["args"]["event_id"] for j in in_memory_queue.jobs.values()}
        assert requeued == {stuck_processing.pk, lost_pending.pk}
        assert services.requeue_stuck() == 0  # no los reencola de nuevo en la vuelta siguiente


def test_b5_process_updates_last_change(db):
    channel = Channel.objects.get(code="tiendanube")
    e = InboundEvent.objects.create(channel=channel, topic="sin-manejador", dedupe_key="x", payload={})
    old = timezone.now() - timedelta(hours=1)
    InboundEvent.objects.filter(pk=e.pk).update(updated_at=old)
    services.process(e.pk)
    e.refresh_from_db()
    assert e.status == InboundEvent.Status.IGNORED and e.updated_at > old


# ── B6, B7, B8: devoluciones ─────────────────────────────────────────────


@pytest.fixture
def order_with_line(variant):
    o = order(paid_amount=Decimal("1000"))
    SalesLine.objects.create(
        document=o,
        variant=variant,
        sku_snapshot="BUZ-1",
        description_snapshot="Buzo",
        quantity=2,
        unit_price=500,
    )
    return o


@pytest.mark.parametrize(
    ("qty", "message"),
    [
        ("1.5", "número entero"),
        ("3", "más cantidad que la esperada"),
        ("-1", "mayor a 0"),
        ("abc", "número entero"),
    ],
)
def test_b6_receive_validates_quantity(client, users_by_role, order_with_line, qty, message):
    ret = returns.create_expected(order_with_line, user=users_by_role[DEPOSITO])
    line = ret.lines.get()
    client.force_login(users_by_role[DEPOSITO])
    response = client.post(
        reverse("sales:return_receive", args=[ret.pk]),
        {f"qty_{line.pk}": qty, f"cond_{line.pk}": "resellable"},
    )
    assert response.status_code == 400
    assert any(message in m for m in msgs(response))
    assert ReturnInfo.objects.get(document=ret).received_at is None


def test_b6_service_rejects_more_than_expected(users_by_role, order_with_line):
    ret = returns.create_expected(order_with_line, user=users_by_role[DEPOSITO])
    line = ret.lines.get()
    with pytest.raises(returns.ReturnError, match="más cantidad"):
        returns.receive(ret, [(line, Decimal(5), "resellable")], "", user=users_by_role[DEPOSITO])
    with pytest.raises(returns.ReturnError, match="entero"):
        returns.receive(ret, [(line, Decimal("0.5"), "resellable")], "", user=users_by_role[DEPOSITO])
    returns.receive(ret, [(line, Decimal(2), "resellable")], "", user=users_by_role[DEPOSITO])  # igual: OK


def test_b7_arrived_return_reuses_pending_expected(client, users_by_role, order_with_line):
    client.force_login(users_by_role[DEPOSITO])
    url = reverse("sales:return_create", args=[order_with_line.pk])
    first = client.post(url, {"receive_now": "1"})
    second = client.post(url, {"receive_now": "1"})
    assert SalesDocument.objects.filter(doc_type="return").count() == 1
    assert first["Location"] == second["Location"]
    third = client.post(url, {"receive_now": "0"})
    assert SalesDocument.objects.filter(doc_type="return").count() == 1
    assert any("ya tenía una devolución esperada" in m for m in msgs(third))

    ret = SalesDocument.objects.get(doc_type="return")
    line = ret.lines.get()
    returns.receive(ret, [(line, Decimal(1), "resellable")], "", user=users_by_role[DEPOSITO])
    client.post(url, {"receive_now": "1"})  # ya recibida: una nueva devolución sí crea otra
    assert SalesDocument.objects.filter(doc_type="return").count() == 2


def test_b7_receive_unexpected_still_creates_its_own(users_by_role, order_with_line):
    returns.create_expected(order_with_line, user=users_by_role[DEPOSITO])
    line = order_with_line.lines.get()
    ret = returns.receive_unexpected(
        order_with_line, [(line, Decimal(1), "damaged")], "", user=users_by_role[DEPOSITO]
    )
    assert ret.status == returns.RECEIVED and ret.lines.get().quantity == 1


def test_b8_return_without_info_is_friendly_404(admin_client, order_with_line):
    ret = SalesDocument.objects.create(
        doc_type=SalesDocument.DocType.RETURN,
        channel=order_with_line.channel,
        issued_at=timezone.now(),
        related_document=order_with_line,
    )
    for method in (admin_client.get, admin_client.post):
        response = method(reverse("sales:return_receive", args=[ret.pk]))
        assert response.status_code == 404
        assert "No encontramos esa página" in response.content.decode()


# ── B9: pedido manual ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("qty", "price", "message"),
    [
        ("1.5", "100", "número entero"),
        ("1", "-10", "no puede ser negativo"),
        ("0", "100", "mayor a 0"),
        ("1", "abc", "tiene que ser un número"),
    ],
)
def test_b9_manual_form_validates_lines(admin_client, variant, qty, price, message):
    response = admin_client.post(
        reverse("sales:manual_create"),
        {
            "legal_name": "Cliente Nuevo",
            "variant_id": [str(variant.pk)],
            "quantity": [qty],
            "price": [price],
            "delivery": "pickup",
        },
    )
    assert response.status_code == 400
    assert any(message in m for m in msgs(response))
    assert not SalesDocument.objects.filter(doc_type="order").exists()


def test_b9_missing_product_is_form_error_not_404(admin_client):
    response = admin_client.post(
        reverse("sales:manual_create"),
        {
            "legal_name": "X",
            "variant_id": ["999999"],
            "quantity": ["1"],
            "price": ["1"],
            "delivery": "pickup",
        },
    )
    assert response.status_code == 400
    assert any("ya no está en el catálogo" in m for m in msgs(response))


def test_b9_service_validates(users_by_role, variant):
    customer = Customer.objects.create(legal_name="X")
    for line, message in (
        (manual.ManualLine(variant, Decimal("2.5"), Decimal(1)), "entero"),
        (manual.ManualLine(variant, Decimal(1), Decimal(-1)), "negativo"),
    ):
        with pytest.raises(manual.ManualOrderError, match=message):
            manual.create_manual_order(
                customer=customer, lines=[line], delivery="pickup", user=users_by_role[ADMIN]
            )
    assert not SalesDocument.objects.exists()


# ── B10: mensaje al cambiar estado ───────────────────────────────────────


def test_b10_same_status_says_nothing_changed(admin_client):
    doc = order("tiendanube", status=states.READY, paid_amount=Decimal("1000"))
    response = admin_client.post(reverse("sales:status", args=[doc.pk]), {"to": states.READY})
    texts = msgs(response)
    assert any("ya estaba en «Listo»" in m for m in texts)
    assert not any("Tiendanube" in m for m in texts)


# ── B11: stock del depósito por defecto ──────────────────────────────────


def test_b11_check_stock_uses_default_warehouse(variant, users_by_role, django_capture_on_commit_callbacks):
    other = Warehouse.objects.create(code="OTRO", name="Otro depósito")
    StockLevel.objects.create(variant=variant, warehouse=other, on_hand=10)  # se crea primero
    default = Warehouse.objects.get(is_default=True)
    StockLevel.objects.create(variant=variant, warehouse=default, on_hand=0, reserved=1)
    doc = order("tiendanube", paid_amount=Decimal("1000"))
    SalesLine.objects.create(
        document=doc,
        variant=variant,
        sku_snapshot="BUZ-1",
        description_snapshot="Buzo",
        quantity=1,
        unit_price=1,
    )
    with django_capture_on_commit_callbacks(execute=True):
        sync.check_stock(doc)
    alert = Alert.objects.get(alert_type__code="orders.out_of_stock")
    assert "BUZ-1 (disponible -1" in alert.body


# ── B12: alertas de manuales pendientes ──────────────────────────────────


def test_b12_manual_pending_only_iterates_pending(users_by_role):
    later = timezone.now() + timedelta(hours=25)
    for _ in range(5):  # cobrados y facturados: no deberían recorrerse
        order("manual", paid_amount=Decimal("1000"), invoiced_in_contabilium=True, invoice_number="B-1")
    pending = order("manual", paid_amount=Decimal("400"), invoiced_in_contabilium=True, invoice_number="B-2")
    with mock.patch("apps.sales.payments.is_paid", wraps=payments.is_paid) as spy:
        assert check_manual_pending(now=later) == 1
    assert spy.call_count == 1
    assert (
        Alert.objects.get(alert_type__code="orders.manual_pending").dedupe_key == f"manual:{pending.pk}:pago"
    )


# ── E1: páginas de error en castellano ───────────────────────────────────


def test_e1_404_in_spanish_for_anonymous(client, settings):
    assert settings.DEBUG is False
    response = client.get("/no-existe-esta-pagina/")
    assert response.status_code == 404
    content = response.content.decode()
    assert "No encontramos esa página" in content and "Not Found" not in content
    assert "Salir" not in content  # no usa datos del usuario


def test_e1_404_for_logged_in_user(admin_client):
    response = admin_client.get("/no-existe-esta-pagina/")
    assert response.status_code == 404 and "No encontramos esa página" in response.content.decode()


def test_e1_500_in_spanish_without_db_or_context():
    from django.template import engines
    from django.views.defaults import server_error

    response = server_error(RequestFactory().get("/"))
    content = response.content.decode()
    assert response.status_code == 500 and "Algo salió mal de nuestro lado" in content
    source = engines["django"].engine.find_template("500.html")[0].source
    assert "{%" not in source and "{{" not in source  # plantilla estática: sin tags ni contexto


def test_e1_csrf_failure_in_spanish():
    client = Client(enforce_csrf_checks=True)
    response = client.post(reverse("accounts:login"), {"username": "a@b.c", "password": "x"})
    assert response.status_code == 403
    content = response.content.decode()
    assert "La página estuvo abierta mucho tiempo" in content and "CSRF verification failed" not in content


# ── E2: bloqueo por intentos fallidos ────────────────────────────────────


def test_e2_lockout_template_in_spanish(make_user, settings):
    assert settings.AXES_LOCKOUT_TEMPLATE == "accounts/lockout.html"
    make_user("bloqueo@test.local")
    with override_settings(AXES_ENABLED=True):
        client = Client()
        response = None
        for _ in range(settings.AXES_FAILURE_LIMIT + 1):
            response = client.post(
                reverse("accounts:login"), {"username": "bloqueo@test.local", "password": "mala-clave-123"}
            )
    content = response.content.decode()
    assert response.status_code in (403, 429)
    assert "Por seguridad bloqueamos el ingreso por 30 minutos" in content
    assert "Account locked" not in content


# ── E3: errores técnicos traducidos ──────────────────────────────────────


def _http_error(status):
    return ChannelHTTPError(f"GET /orders respondió {status}", response=httpx.Response(status))


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_http_error(401), errors.AUTH),
        (_http_error(403), errors.AUTH),
        (_http_error(429), errors.RATE_LIMIT),
        (_http_error(500), errors.UNAVAILABLE),
        (_http_error(503), errors.UNAVAILABLE),
        (_http_error(404), errors.NOT_FOUND),
        (httpx.ConnectTimeout("timed out"), errors.UNAVAILABLE),
        (ml_auth.TokenRevoked("Hay que volver a autorizar Mercado Libre."), errors.AUTH),
        (ValueError("algo raro"), errors.GENERIC),
        ("ChannelHTTPError: GET /orders respondió 401", errors.AUTH),
        ("ChannelHTTPError: GET /orders respondió 429", errors.RATE_LIMIT),
        ("ChannelHTTPError: GET /orders respondió 502", errors.UNAVAILABLE),
        ("ChannelHTTPError: GET /orders: timed out", errors.UNAVAILABLE),
        ("KeyError: 'id'", errors.GENERIC),
        ("", ""),
    ],
)
def test_e3_friendly_mapping(error, expected):
    assert errors.friendly(error) == expected


def test_e3_transport_error_wrapped_by_client_is_unavailable():
    try:
        try:
            raise httpx.ConnectError("conexión rechazada")
        except httpx.ConnectError as exc:
            raise ChannelHTTPError("GET /orders: conexión rechazada") from exc
    except ChannelHTTPError as wrapped:
        assert errors.friendly(wrapped) == errors.UNAVAILABLE


def test_e3_event_failed_alert_is_friendly(users_by_role):
    channel = Channel.objects.get(code="tiendanube")
    event = InboundEvent.objects.create(
        channel=channel, topic="order/updated", dedupe_key="k", payload={}, attempts=services.MAX_ATTEMPTS - 1
    )

    def boom(_event):
        raise _http_error(401)

    adapter = mock.Mock(handlers={"order/updated": boom})
    with mock.patch("apps.integrations.services.registry.get", return_value=adapter):
        services.process(event.pk)
    event.refresh_from_db()
    assert event.status == "failed" and "respondió 401" in event.last_error  # detalle técnico guardado
    alert = Alert.objects.get(alert_type__code="integration.event_failed")
    assert errors.AUTH in alert.body and "ChannelHTTPError" not in alert.body


def test_e3_status_page_shows_friendly_errors(admin_client):
    channel = Channel.objects.get(code="tiendanube")
    InboundEvent.objects.create(
        channel=channel,
        topic="order/updated",
        dedupe_key="k",
        payload={},
        status="failed",
        last_error="ChannelHTTPError: GET /orders respondió 401",
    )
    SyncRun.objects.create(
        channel=channel,
        job="orders",
        status=SyncRun.Status.ERROR,
        error="ChannelHTTPError: GET /x respondió 503",
    )
    content = admin_client.get(reverse("integrations:status")).content.decode()
    assert errors.AUTH in content and errors.UNAVAILABLE in content
    assert "respondió 401" not in content and "ChannelHTTPError" not in content


def test_e3_fulfillment_alert_is_friendly(users_by_role):
    from apps.integrations.adapters.tiendanube import fulfillment
    from apps.integrations.services import link_external

    doc = order("tiendanube", paid_amount=Decimal("1000"))
    link_external("tiendanube", doc, "777", {"number": 1234})
    with (
        mock.patch.object(fulfillment, "apply_update", side_effect=_http_error(500)),
        mock.patch.object(fulfillment.TiendanubeClient, "from_credentials"),
    ):
        fulfillment.tn_fulfillment_update(
            document_id=doc.pk, action="packed", attempt=fulfillment.MAX_ATTEMPTS
        )
    alert = Alert.objects.get(alert_type__code="integration.write_failed")
    assert errors.UNAVAILABLE in alert.body and "respondió" not in alert.body
    assert "«Listo»" in alert.title


# ── E4, E5, E6: mensajes de conexión e importación ───────────────────────


def test_e4_not_configured_messages():
    with override_settings(ML_APP_ID=""), pytest.raises(ml_auth.OAuthError) as ml_exc:
        ml_auth.authorize_url("s")
    assert str(ml_exc.value) == ml_auth.NOT_CONFIGURED and "ML_APP_ID" not in str(ml_exc.value)
    with override_settings(TN_APP_ID=""), pytest.raises(tn_oauth.OAuthError) as tn_exc:
        tn_oauth.authorize_url("s")
    assert "Avisale a Kei Software" in str(tn_exc.value) and "TN_APP_ID" not in str(tn_exc.value)


def test_e5_ml_code_rejected_and_unavailable():
    with respx.mock() as m:
        m.post(ml_auth.TOKEN_URL).mock(return_value=httpx.Response(400, json={"message": "invalid_grant"}))
        with pytest.raises(ml_auth.OAuthError) as exc:
            ml_auth.exchange_code("x")
        assert str(exc.value) == "La autorización venció o ya se usó: tocá Conectar de nuevo."
    with respx.mock() as m:
        m.post(ml_auth.TOKEN_URL).mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(ml_auth.OAuthError) as exc:
            ml_auth.exchange_code("x")
        assert str(exc.value) == "Mercado Libre no responde. Probá en unos minutos."


def test_e5_tn_code_rejected_and_unavailable():
    rejected = httpx.MockTransport(lambda request: httpx.Response(400, json={}))
    with pytest.raises(tn_oauth.OAuthError, match="tocá Conectar de nuevo"):
        tn_oauth.exchange_code("x", transport=rejected)

    def down(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(tn_oauth.OAuthError, match="no responde"):
        tn_oauth.exchange_code("x", transport=httpx.MockTransport(down))


@pytest.mark.parametrize(
    ("url_name", "kind"),
    [
        ("mercadolibre:import", "publicaciones"),
        ("mercadolibre:import", "ventas"),
        ("tiendanube:import", "catalogo"),
        ("tiendanube:import", "pedidos"),
    ],
)
def test_e6_import_messages_without_jargon(admin_client, url_name, kind):
    response = admin_client.post(reverse(url_name, args=[kind]))
    texts = msgs(response)
    assert any("Empezó la importación" in m and "van apareciendo solos" in m for m in texts)
    assert not any("encolad" in m for m in texts)


# ── P1: paginación de Stock y precios y de Calidad ───────────────────────


@pytest.fixture
def many_variants(db):
    product = Product.objects.create(name="Remera")
    Variant.objects.bulk_create([Variant(product=product, sku=f"REM-{i:03d}") for i in range(150)])


def test_p1_channel_stock_paginated_and_export_all(admin_client, many_variants):
    url = reverse("catalog:channel_stock")
    first = admin_client.get(url, {"q": "REM"})
    assert len(first.context["rows"]) == 100 and first.context["paginator"].count == 150
    content = first.content.decode()
    assert "q=REM&page=2" in content  # el link de página conserva el filtro
    second = admin_client.get(url, {"q": "REM", "page": 2})
    assert len(second.context["rows"]) == 50
    export = admin_client.get(url, {"q": "REM", "formato": "xlsx"})
    from io import BytesIO

    from openpyxl import load_workbook

    ws = load_workbook(BytesIO(export.content)).active
    assert ws.max_row == 151  # encabezado + todas las filas


def test_p1_quality_paginated_and_export_all(admin_client, many_variants):
    url = reverse("catalog:quality")
    first = admin_client.get(url, {"tipo": "no_barcode"})
    assert len(first.context["issues"]) == 100 and first.context["paginator"].count == 150
    assert "tipo=no_barcode&page=2" in first.content.decode()
    assert len(admin_client.get(url, {"tipo": "no_barcode", "page": 2}).context["issues"]) == 50
    export = admin_client.get(url, {"tipo": "no_barcode", "formato": "xlsx"})
    from io import BytesIO

    from openpyxl import load_workbook

    assert load_workbook(BytesIO(export.content)).active.max_row == 151


# ── P2: índices de la lista de pedidos ───────────────────────────────────


def test_p2_order_list_indexes():
    assert "shipment_doc_deadline_idx" in {i.name for i in Shipment._meta.indexes}
    assert "salesdoc_type_issued_idx" in {i.name for i in SalesDocument._meta.indexes}


# ── Olvidos: buscador de pedido en Devoluciones ──────────────────────────


def test_returns_screen_order_search(client, users_by_role):
    doc = order("tiendanube", paid_amount=Decimal("1000"))
    doc.customer = Customer.objects.create(legal_name="Carla Ruiz")
    doc.channel_reference = "TN #4321"
    doc.save()
    client.force_login(users_by_role[DEPOSITO])
    url = reverse("sales:returns")
    content = client.get(url, {"pedido": "carla"}).content.decode()
    assert reverse("sales:detail", args=[doc.pk]) in content and "TN #4321" in content
    assert "Llegó una devolución" in content
    assert "TN #4321" in client.get(url, {"pedido": "4321"}).content.decode()
    assert "No encontramos pedidos" in client.get(url, {"pedido": "zzzz"}).content.decode()
