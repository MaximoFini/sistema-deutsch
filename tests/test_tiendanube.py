import base64
import hashlib
import hmac
import json
from datetime import timedelta
from unittest import mock

import httpx
import pytest
import respx
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.alerts.models import Alert
from apps.audit.models import AuditLog
from apps.catalog.models import Product, Variant
from apps.customers.models import Customer
from apps.integrations import credentials, registry
from apps.integrations.adapters.tiendanube import catalog, fulfillment, oauth, orders, privacy
from apps.integrations.adapters.tiendanube.adapter import signature_is_valid
from apps.integrations.adapters.tiendanube.client import TiendanubeClient, parse_next_link
from apps.integrations.guard import WriteBlocked
from apps.integrations.models import ChannelCredential, ExternalRef, InboundEvent, SyncRun
from apps.inventory.models import StockMovement
from apps.pricing.models import PriceListItem
from apps.sales.models import Payment, SalesDocument, Shipment
from tests import tn_samples

pytestmark = pytest.mark.django_db

API = "https://api.tiendanube.com/2025-03/8434848"
SECRET = "secreto-de-test"


@pytest.fixture
def connected(db):
    credentials.save(
        "tiendanube",
        {
            "access_token": "TN-TOKEN-SECRETO",
            "store_id": "8434848",
            "scope": "read_products,write_orders,read_customers,write_fulfillment_orders",
        },
    )


@pytest.fixture
def api(connected):
    with respx.mock(base_url=API, assert_all_called=False) as mock_api:
        yield mock_api


def sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def run_jobs(connector, suffix):
    from apps.integrations.tasks import process_event

    tasks = {
        "process_event": process_event,
        "tn_fulfillment_update": fulfillment.tn_fulfillment_update,
    }
    ran = 0
    for job in list(connector.jobs.values()):
        if job["task_name"].endswith(suffix) and job["status"] == "todo":
            job["status"] = "done"
            tasks[suffix](**job["args"])
            ran += 1
    return ran


# ── Cliente ──────────────────────────────────────────────────────────────


def test_parse_link_header():
    header = f'<{API}/products?page=2>; rel="next", <{API}/products?page=5>; rel="last"'
    assert parse_next_link(header) == f"{API}/products?page=2"
    assert parse_next_link(f'<{API}/products?page=5>; rel="last"') is None
    assert parse_next_link(None) is None


def test_client_headers_and_pagination(api):
    route = api.get("/products").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[{"id": 1}, {"id": 2}],
                headers={"Link": f'<{API}/products?page=2&per_page=200>; rel="next"'},
            ),
            httpx.Response(
                200, json=[{"id": 3}], headers={"Link": f'<{API}/products?page=3&per_page=200>; rel="next"'}
            ),
            httpx.Response(200, json=[]),
        ]
    )
    client = TiendanubeClient.from_credentials(sleep=lambda s: None)
    assert [p["id"] for p in client.get_all("/products")] == [1, 2, 3]
    assert route.call_count == 3
    assert route.calls[1].request.url.params["page"] == "2"
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer TN-TOKEN-SECRETO"
    assert request.headers["User-Agent"].startswith("Sistema Deutsch")


def test_client_retries_on_429(api):
    route = api.get("/store").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json={"id": 8434848})]
    )
    client = TiendanubeClient.from_credentials(sleep=lambda s: None)
    assert client.get_store()["id"] == 8434848
    assert route.call_count == 2


# ── Firma y deduplicación ────────────────────────────────────────────────


def test_signature_hex_and_base64():
    body = b'{"store_id":8434848,"event":"order/created","id":1}'
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
    assert signature_is_valid(body, digest.hex())
    assert signature_is_valid(body, base64.b64encode(digest).decode())
    assert not signature_is_valid(body, "mala")
    assert not signature_is_valid(body, None)


def post_hook(client, payload, signature=None):
    body = json.dumps(payload).encode()
    return client.post(
        "/hooks/tiendanube/",
        data=body,
        content_type="application/json",
        HTTP_X_LINKEDSTORE_HMAC_SHA256=signature if signature is not None else sign(body),
    )


def test_webhook_rejects_bad_signature(client):
    assert post_hook(client, {"event": "order/created", "id": 1}, signature="mala").status_code == 403
    assert not InboundEvent.objects.exists()


def test_webhook_dedupe_by_minute(client, in_memory_queue):
    payload = {"store_id": 8434848, "event": "order/updated", "id": 9001}
    t0 = timezone.now().replace(second=5)
    with mock.patch("django.utils.timezone.now", return_value=t0):
        post_hook(client, payload)
        post_hook(client, payload)  # reintento en el mismo minuto
    assert InboundEvent.objects.count() == 1
    with mock.patch("django.utils.timezone.now", return_value=t0 + timedelta(minutes=2)):
        post_hook(client, payload)  # cambio posterior legítimo
    assert InboundEvent.objects.count() == 2


# ── Catálogo ─────────────────────────────────────────────────────────────


def test_upsert_product_maps_everything():
    product = catalog.upsert_product(tn_samples.product())
    assert product.name == "Buzo Canguro Oversize" and product.categories == ["Buzos", "Invierno"]
    assert [i["url"] for i in product.images] == ["https://cdn.example/b1.jpg", "https://cdn.example/b2.jpg"]
    v = Variant.objects.get(sku="BUZ-001-M-NEG")
    assert v.attributes == {"Talle": "M", "Color": "Negro"}
    assert (v.weight_g, v.width_mm, v.height_mm, v.length_mm) == (650, 300, 50, 400)
    price = PriceListItem.objects.get(variant=v, price_list__code="MINORISTA")
    assert str(price.price) == "45000.00" and str(price.promotional_price) == "39900.00"
    assert v.stock_levels.get().on_hand == 12
    ref = ExternalRef.objects.get(
        channel__code="tiendanube", content_type__model="variant", external_id="5001"
    )
    assert ref.extra["stock"] == 12 and ref.extra["product_id"] == 1001


def test_second_pass_without_changes_creates_nothing():
    catalog.upsert_product(tn_samples.product())
    counts = (
        Product.objects.count(),
        Variant.objects.count(),
        PriceListItem.objects.count(),
        StockMovement.objects.count(),
        ExternalRef.objects.count(),
    )
    catalog.upsert_product(tn_samples.product())
    assert counts == (
        Product.objects.count(),
        Variant.objects.count(),
        PriceListItem.objects.count(),
        StockMovement.objects.count(),
        ExternalRef.objects.count(),
    )


def test_price_and_stock_changes_are_recorded():
    catalog.upsert_product(tn_samples.product())
    data = tn_samples.product()
    data["variants"][0]["price"] = "47000.00"
    data["variants"][0]["stock"] = 10
    catalog.upsert_product(data)
    v = Variant.objects.get(sku="BUZ-001-M-NEG")
    assert PriceListItem.objects.filter(variant=v).count() == 2
    assert [m.quantity for m in StockMovement.objects.filter(variant=v).order_by("id")] == [12, -2]


def test_variant_without_sku_and_null_stock():
    data = tn_samples.product()
    data["variants"][1]["sku"] = ""
    data["variants"][1]["stock"] = None
    catalog.upsert_product(data)
    v = Variant.objects.get(sku="TN-5002")
    assert v.needs_review and "Sin SKU" in v.review_notes
    assert not v.stock_levels.exists()


def test_duplicate_barcode_is_flagged():
    catalog.upsert_product(tn_samples.product())
    other = tn_samples.product(product_id=1002)
    other["variants"] = [dict(other["variants"][0], id=6001, sku="OTRO-1")]
    catalog.upsert_product(other)
    v = Variant.objects.get(sku="OTRO-1")
    assert v.barcode is None and v.needs_review


@override_settings(STOCK_FEED_CHANNEL="contabilium")
def test_stock_not_fed_when_tn_is_not_the_feed():
    catalog.upsert_product(tn_samples.product())
    assert not StockMovement.objects.exists()
    ref = ExternalRef.objects.get(content_type__model="variant", external_id="5001")
    assert ref.extra["stock"] == 12  # el stock del canal se guarda igual


def test_removed_variant_and_deleted_product_become_inactive():
    catalog.upsert_product(tn_samples.product())
    data = tn_samples.product()
    data["variants"] = data["variants"][:1]
    catalog.upsert_product(data)
    assert not Variant.objects.get(sku="BUZ-001-L-NEG").is_active
    catalog.deactivate_product(1001)
    assert not Product.objects.get().is_active
    assert Product.objects.count() == 1  # nunca se borra


def test_import_all_continues_after_error_and_deactivates_missing(api):
    catalog.upsert_product(tn_samples.product(product_id=999))  # ya no existe en TN
    api.get("/products").mock(return_value=httpx.Response(200, json=[tn_samples.product(), {"id": 1003}]))
    real_upsert = catalog.upsert_product

    def flaky(data):
        if data["id"] == 1003:
            raise RuntimeError("roto")
        return real_upsert(data)

    with mock.patch.object(catalog, "upsert_product", side_effect=flaky):
        stats = catalog.import_all(TiendanubeClient.from_credentials(sleep=lambda s: None))
    assert stats["products"] == 1 and stats["errors"][0]["id"] == 1003
    assert stats["deactivated"] == 1
    gone = ExternalRef.objects.get(content_type__model="product", external_id="999")
    assert not Product.objects.get(pk=gone.object_id).is_active


def test_product_webhook_flow(client, api, in_memory_queue):
    api.get("/products/1001").mock(return_value=httpx.Response(200, json=tn_samples.product()))
    post_hook(client, {"store_id": 8434848, "event": "product/updated", "id": 1001})
    run_jobs(in_memory_queue, "process_event")
    assert InboundEvent.objects.get().status == "done"
    assert Variant.objects.count() == 2


def test_product_webhook_404_deactivates(client, api, in_memory_queue):
    catalog.upsert_product(tn_samples.product())
    api.get("/products/1001").mock(return_value=httpx.Response(404, json={}))
    post_hook(client, {"store_id": 8434848, "event": "product/updated", "id": 1001})
    run_jobs(in_memory_queue, "process_event")
    assert not Product.objects.get().is_active


# ── Pedidos ──────────────────────────────────────────────────────────────


def test_upsert_order_envio_nube_paid():
    catalog.upsert_product(tn_samples.product())
    doc = orders.upsert_order(tn_samples.order())
    assert doc.channel.code == "tiendanube" and doc.status == "new"
    assert doc.channel_status == "open/paid/unpacked"
    assert (str(doc.subtotal), str(doc.discount_total), str(doc.shipping_total), str(doc.total)) == (
        "84900.00",
        "4900.00",
        "5500.00",
        "85500.00",
    )
    lines = list(doc.lines.order_by("id"))
    assert [ln.variant.sku for ln in lines] == ["BUZ-001-M-NEG", "BUZ-001-L-NEG"]
    assert lines[0].description_snapshot == "Buzo Canguro Oversize (M / Negro)"
    payment = doc.payments.get()
    assert payment.method == Payment.Method.MERCADOPAGO and payment.status == Payment.Status.CONFIRMED
    shipment = doc.shipments.get()
    assert shipment.method == Shipment.Method.ENVIO_NUBE and shipment.address["city"] == "CABA"
    customer = doc.customer
    assert customer.email == "lucia@example.com" and customer.tax_id == "30111222"
    assert customer.addresses.get().street == "Av. Corrientes"


def test_pickup_order_with_transfer():
    doc = orders.upsert_order(tn_samples.pickup_order())
    assert doc.shipments.get().method == Shipment.Method.PICKUP
    assert doc.payments.get().method == Payment.Method.TRANSFER
    assert doc.payments.get().status == Payment.Status.PENDING


def test_same_order_twice_is_one_document():
    catalog.upsert_product(tn_samples.product())
    orders.upsert_order(tn_samples.order())
    orders.upsert_order(tn_samples.order(updated_at="2026-11-12T16:00:00+0000", status="closed"))
    assert SalesDocument.objects.count() == 1
    doc = SalesDocument.objects.get()
    assert doc.channel_status.startswith("closed") and doc.lines.count() == 2 and doc.payments.count() == 1


def test_old_event_does_not_overwrite_newer():
    orders.upsert_order(tn_samples.order(updated_at="2026-11-12T16:00:00+0000", payment_status="paid"))
    orders.upsert_order(tn_samples.order(updated_at="2026-11-12T15:00:00+0000", payment_status="pending"))
    assert SalesDocument.objects.get().channel_status == "open/paid/unpacked"


def test_update_does_not_touch_internal_status():
    doc = orders.upsert_order(tn_samples.order())
    SalesDocument.objects.filter(pk=doc.pk).update(status="preparing")
    # "fulfilled" (empaquetado en TN) no dispara ninguna regla. Con "shipped" ahora sí pasa a
    # Despachado (auditoría M4-M5, L1): ver tests/test_auditoria_m5.py.
    orders.upsert_order(tn_samples.order(updated_at="2026-11-13T10:00:00+0000", shipping_status="fulfilled"))
    doc.refresh_from_db()
    assert doc.status == "preparing" and doc.channel_status.endswith("fulfilled")


def test_cancelled_order():
    doc = orders.upsert_order(tn_samples.order(status="cancelled", payment_status="refunded"))
    assert doc.channel_status.startswith("cancelled")
    assert doc.payments.get().status == Payment.Status.REFUNDED


def test_unknown_sku_alerts_once(users_by_role):
    orders.upsert_order(tn_samples.order())  # catálogo vacío: los 2 SKU son desconocidos
    orders.upsert_order(tn_samples.order(order_id=9003, updated_at="2026-11-13T10:00:00+0000"))
    assert set(Alert.objects.values_list("dedupe_key", flat=True)) == {"BUZ-001-M-NEG", "BUZ-001-L-NEG"}
    assert (
        SalesDocument.objects.get(
            pk=ExternalRef.objects.get(content_type__model="salesdocument", external_id="9001").object_id
        )
        .lines.filter(variant=None)
        .count()
        == 2
    )


def test_customer_manual_data_not_overwritten():
    c = Customer.objects.create(
        legal_name="Lucía G. (cargado a mano)", email="lucia@example.com", phone="111"
    )
    orders.upsert_order(tn_samples.order())
    c.refresh_from_db()
    assert c.legal_name == "Lucía G. (cargado a mano)" and c.phone == "111" and c.tax_id == "30111222"
    assert Customer.objects.count() == 1


def test_order_reconciliation_uses_last_ok_minus_margin(api):
    from apps.integrations import services

    route = api.get("/orders").mock(return_value=httpx.Response(200, json=[tn_samples.order()]))
    client = TiendanubeClient.from_credentials(sleep=lambda s: None)
    run1 = services.run_reconciliation(
        "tiendanube", job="orders", fn=lambda since: orders.sync_orders(client, updated_since=since)
    )
    assert run1.status == "ok" and run1.stats["orders"] == 1
    assert "updated_at_min" not in route.calls[0].request.url.params
    services.run_reconciliation(
        "tiendanube", job="orders", fn=lambda since: orders.sync_orders(client, updated_since=since)
    )
    sent = route.calls[1].request.url.params["updated_at_min"]
    assert sent.startswith((run1.started_at - timedelta(minutes=10)).isoformat()[:16])


def test_initial_import_filters_by_creation_date(api, in_memory_queue):
    from apps.integrations.adapters.tiendanube.tasks import tn_import_orders

    route = api.get("/orders").mock(return_value=httpx.Response(200, json=[]))
    tn_import_orders(days=30)
    created_min = route.calls[0].request.url.params["created_at_min"]
    assert created_min[:10] == (timezone.now() - timedelta(days=30)).date().isoformat()
    assert SyncRun.objects.get(job="orders_initial").status == "ok"


def test_order_webhook_flow(client, api, in_memory_queue):
    api.get("/orders/9001").mock(return_value=httpx.Response(200, json=tn_samples.order()))
    post_hook(client, {"store_id": 8434848, "event": "order/created", "id": 9001})
    run_jobs(in_memory_queue, "process_event")
    assert SalesDocument.objects.count() == 1


def test_periodic_tasks_skip_when_not_connected(in_memory_queue):
    from apps.integrations.adapters.tiendanube.tasks import tn_reconcile_orders

    tn_reconcile_orders(timestamp=0)
    assert not SyncRun.objects.exists()


# ── Despacho (fulfillment orders) ────────────────────────────────────────


@pytest.fixture
def tn_document(connected):
    return orders.upsert_order(tn_samples.order())


def test_mark_dispatched_with_tracking(
    api, tn_document, admin_user, in_memory_queue, django_capture_on_commit_callbacks
):
    api.get("/orders/9001/fulfillment-orders").mock(
        return_value=httpx.Response(200, json=tn_samples.fulfillment_orders("PACKED"))
    )
    patch = api.patch("/orders/9001/fulfillment-orders/01HXFO000000000000000000AA").mock(
        return_value=httpx.Response(200, json={})
    )
    with django_capture_on_commit_callbacks(execute=True):
        fulfillment.mark_dispatched(
            tn_document, actor=admin_user, tracking_code="AB123", tracking_url="https://t/AB123"
        )
    run_jobs(in_memory_queue, "tn_fulfillment_update")
    body = json.loads(patch.calls[0].request.content)
    assert body == {"status": "DISPATCHED", "tracking_info": {"code": "AB123", "url": "https://t/AB123"}}
    log = AuditLog.objects.get(action="order.status_changed")
    assert (
        log.before["tiendanube"][0]["status"] == "PACKED"
        and log.after["tiendanube"][0]["status"] == "DISPATCHED"
    )
    assert log.actor == admin_user


def test_mark_packed_and_delivered(
    api, tn_document, admin_user, in_memory_queue, django_capture_on_commit_callbacks
):
    api.get("/orders/9001/fulfillment-orders").mock(
        return_value=httpx.Response(200, json=tn_samples.fulfillment_orders("UNPACKED", "pickup"))
    )
    patch = api.patch("/orders/9001/fulfillment-orders/01HXFO000000000000000000AA").mock(
        return_value=httpx.Response(200, json={})
    )
    event = api.post("/orders/9001/fulfillment-orders/01HXFO000000000000000000AA/tracking-events").mock(
        return_value=httpx.Response(201, json={})
    )
    with django_capture_on_commit_callbacks(execute=True):
        fulfillment.mark_packed(tn_document, actor=admin_user)
        fulfillment.mark_delivered(tn_document, actor=admin_user)
    run_jobs(in_memory_queue, "tn_fulfillment_update")
    assert json.loads(patch.calls[0].request.content) == {"status": "PACKED"}
    assert json.loads(event.calls[0].request.content) == {"status": "delivered"}


def test_pickup_dispatch_means_ready_for_pickup(api, tn_document):
    api.get("/orders/9001/fulfillment-orders").mock(
        return_value=httpx.Response(200, json=tn_samples.fulfillment_orders("PACKED", "pickup"))
    )
    patch = api.patch("/orders/9001/fulfillment-orders/01HXFO000000000000000000AA").mock(
        return_value=httpx.Response(200, json={})
    )
    fulfillment.apply_update(TiendanubeClient.from_credentials(sleep=lambda s: None), "9001", "dispatched")
    assert json.loads(patch.calls[0].request.content) == {"status": "READY_FOR_PICKUP"}


def test_already_in_state_does_nothing(api, tn_document, admin_user, in_memory_queue):
    api.get("/orders/9001/fulfillment-orders").mock(
        return_value=httpx.Response(200, json=tn_samples.fulfillment_orders("DISPATCHED"))
    )
    patch = api.patch("/orders/9001/fulfillment-orders/01HXFO000000000000000000AA")
    fulfillment.tn_fulfillment_update(document_id=tn_document.pk, action="packed", actor_id=admin_user.pk)
    assert patch.call_count == 0
    assert not AuditLog.objects.filter(action="order.status_changed").exists()


def test_failure_retries_then_alerts(api, tn_document, users_by_role, in_memory_queue):
    api.get("/orders/9001/fulfillment-orders").mock(
        return_value=httpx.Response(200, json=tn_samples.fulfillment_orders())
    )
    api.patch("/orders/9001/fulfillment-orders/01HXFO000000000000000000AA").mock(
        return_value=httpx.Response(422, json={"error": "transición inválida"})
    )
    fulfillment.tn_fulfillment_update(document_id=tn_document.pk, action="packed")
    for _ in range(fulfillment.MAX_ATTEMPTS):
        run_jobs(in_memory_queue, "tn_fulfillment_update")
    alert = Alert.objects.get(alert_type__code="integration.write_failed")
    assert "1234" in alert.title
    assert not [j for j in in_memory_queue.jobs.values() if j["status"] == "todo"]


def test_fulfillment_never_calls_product_endpoints(api, tn_document):
    api.get("/orders/9001/fulfillment-orders").mock(
        return_value=httpx.Response(200, json=tn_samples.fulfillment_orders())
    )
    api.patch("/orders/9001/fulfillment-orders/01HXFO000000000000000000AA").mock(
        return_value=httpx.Response(200, json={})
    )
    fulfillment.apply_update(TiendanubeClient.from_credentials(sleep=lambda s: None), "9001", "packed")
    assert not [c for c in api.calls if "/products" in str(c.request.url)]


# ── Regla de oro ─────────────────────────────────────────────────────────


def test_write_stock_and_price_blocked(api):
    route = api.route(method="PATCH", path__startswith="/2025-03/8434848/products")
    adapter = registry.get("tiendanube")
    with pytest.raises(WriteBlocked):
        adapter.write_stock("5001", "1001", 3)
    with pytest.raises(WriteBlocked):
        adapter.write_price("5001", "1001", "100")
    assert route.call_count == 0


# ── Conexión (OAuth) ─────────────────────────────────────────────────────


def test_connect_requires_permission(client, users_by_role):
    from apps.accounts.roles import VENTAS

    client.force_login(users_by_role[VENTAS])
    assert client.post(reverse("tiendanube:connect")).status_code == 403


def test_connect_redirects_with_state(admin_client):
    response = admin_client.post(reverse("tiendanube:connect"))
    state = admin_client.session["tn_oauth_state"]
    assert response["Location"] == f"https://www.tiendanube.com/apps/1234/authorize?state={state}"


def test_callback_rejects_invalid_state(admin_client):
    admin_client.post(reverse("tiendanube:connect"))
    admin_client.get(reverse("tiendanube:callback"), {"code": "abc", "state": "otro"})
    assert not ChannelCredential.objects.exists()


@respx.mock(assert_all_called=False)
def test_callback_exchanges_code_saves_encrypted_and_enqueues(respx_mock, admin_client, in_memory_queue):
    token = respx_mock.post("https://www.tiendanube.com/apps/authorize/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "NUEVO-TOKEN",
                "token_type": "bearer",
                "scope": "read_products,write_orders,read_customers,write_fulfillment_orders",
                "user_id": "8434848",
            },
        )
    )
    admin_client.post(reverse("tiendanube:connect"))
    state = admin_client.session["tn_oauth_state"]
    admin_client.get(reverse("tiendanube:callback"), {"code": "abc", "state": state})
    assert json.loads(token.calls[0].request.content)["code"] == "abc"
    assert credentials.get("tiendanube")["store_id"] == "8434848"
    assert b"NUEVO-TOKEN" not in bytes(ChannelCredential.objects.get().data_encrypted)
    assert AuditLog.objects.filter(action="integration.connected").exists()
    names = sorted(j["task_name"].rsplit(".", 1)[-1] for j in in_memory_queue.jobs.values())
    assert names == ["tn_import_catalog", "tn_import_orders"]


def test_scope_report():
    report = oauth.scope_report("write_products,write_orders,read_customers")
    assert report["missing"] == ["write_fulfillment_orders"]
    assert report["extra_risky"] == ["write_products"]


@override_settings(TN_WEBHOOKS_BASE_URL="https://panel.deutsch.com.ar")
def test_register_webhooks_is_idempotent(api):
    url = "https://panel.deutsch.com.ar/hooks/tiendanube/"
    api.get("/webhooks").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "event": "order/created", "url": url}])
    )
    created = api.post("/webhooks").mock(return_value=httpx.Response(201, json={}))
    result = oauth.register_webhooks(TiendanubeClient.from_credentials(sleep=lambda s: None))
    assert result["mode"] == "webhooks" and "order/created" not in result["created"]
    assert created.call_count == len(result["created"]) == 11


def test_register_webhooks_local_mode_does_nothing(api):
    route = api.get("/webhooks")
    assert oauth.register_webhooks(TiendanubeClient.from_credentials())["mode"] == "polling"
    assert route.call_count == 0


def test_app_uninstalled_disconnects(client, connected, users_by_role, in_memory_queue):
    post_hook(client, {"store_id": 8434848, "event": "app/uninstalled", "id": 8434848})
    run_jobs(in_memory_queue, "process_event")
    assert not ChannelCredential.objects.exists()
    assert Alert.objects.filter(alert_type__code="integration.disconnected").exists()
    assert AuditLog.objects.filter(action="integration.disconnected").exists()


# ── Privacidad ───────────────────────────────────────────────────────────


def post_privacy(client, kind, payload, signature=None):
    body = json.dumps(payload).encode()
    return client.post(
        f"/hooks/tiendanube/privacy/{kind}/",
        data=body,
        content_type="application/json",
        HTTP_X_LINKEDSTORE_HMAC_SHA256=signature or sign(body),
    )


def test_customer_redact_anonymizes_but_keeps_documents(client, in_memory_queue):
    doc = orders.upsert_order(tn_samples.order())
    assert (
        post_privacy(client, "customers_redact", {"store_id": 8434848, "customer": {"id": 777}}).status_code
        == 200
    )
    job = next(iter(in_memory_queue.jobs.values()))
    privacy.handle(**job["args"])
    customer = Customer.objects.get()
    assert customer.legal_name == privacy.ANON_NAME and customer.email == "" and customer.tax_id == ""
    assert not customer.addresses.exists()
    doc.refresh_from_db()
    assert doc.total and doc.shipments.get().address is None
    assert AuditLog.objects.filter(action="privacy.customer_redacted").exists()


def test_privacy_bad_signature(client):
    assert post_privacy(client, "store_redact", {"store_id": 1}, signature="mala").status_code == 403


def test_store_redact_and_data_request(connected, users_by_role):
    orders.upsert_order(tn_samples.order())
    privacy.handle(
        "customers_data_request", {"customer": {"id": 777, "email": "x@y"}, "data_request": {"id": 5}}
    )
    assert Alert.objects.filter(alert_type__code="privacy.data_request").exists()
    privacy.handle("store_redact", {"store_id": 8434848})
    assert Customer.objects.get().legal_name == privacy.ANON_NAME
    assert not ChannelCredential.objects.exists()


# ── Panel ────────────────────────────────────────────────────────────────


def test_panel_shows_connect_and_import(admin_client, connected):
    content = admin_client.get(reverse("integrations:status")).content.decode()
    assert "Reconectar" in content and "Importar catálogo" in content and "consulta cada 5 min" in content


def test_import_buttons_enqueue(admin_client, connected, in_memory_queue):
    admin_client.post(reverse("tiendanube:import", args=["catalogo"]))
    admin_client.post(reverse("tiendanube:import", args=["pedidos"]))
    assert len(in_memory_queue.jobs) == 2


def test_hidden_in_tiendanube_does_not_deactivate_an_active_product():
    catalog.upsert_product(tn_samples.product())
    hidden = tn_samples.product()
    hidden["published"] = False
    hidden["visibility"] = "hidden"
    catalog.upsert_product(hidden)
    assert Product.objects.get().is_active  # oculto en TN no es inactivo en el catálogo
    assert Variant.objects.filter(is_active=True).count() == 2


def test_new_product_hidden_in_tiendanube_starts_inactive_and_reactivates_when_visible():
    hidden = tn_samples.product()
    hidden["visibility"] = "hidden"
    catalog.upsert_product(hidden)
    assert not Product.objects.get().is_active
    catalog.upsert_product(tn_samples.product())
    assert Product.objects.get().is_active
