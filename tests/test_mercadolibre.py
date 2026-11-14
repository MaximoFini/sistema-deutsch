import io
import json
import zipfile
from datetime import timedelta
from unittest import mock

import httpx
import pytest
import respx
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import DEPOSITO, VENTAS
from apps.alerts.models import Alert
from apps.audit.models import AuditLog
from apps.catalog.models import Listing, ListingVariation, Product, Variant
from apps.conversations.models import Claim, Message, Question
from apps.integrations import credentials, registry
from apps.integrations.adapters.mercadolibre import (
    auth,
    billing,
    claims,
    listings,
    messages,
    orders,
    questions,
    shipments,
)
from apps.integrations.adapters.mercadolibre.client import MLClient
from apps.integrations.guard import WriteBlocked
from apps.integrations.models import Channel, ChannelCredential, ExternalRef, InboundEvent, SyncRun
from apps.sales.models import Payment, SalesDocument, Shipment
from tests import ml_samples as S

pytestmark = pytest.mark.django_db
API = "https://api.mercadolibre.com"


def save_cred(expires_in=timedelta(hours=5), access="ACCESS-1", refresh="REFRESH-1"):
    credentials.save(
        "mercadolibre",
        {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": (timezone.now() + expires_in).isoformat(),
            "user_id": S.SELLER,
            "scope": "offline_access read write",
        },
    )


@pytest.fixture
def connected(db):
    save_cred()


@pytest.fixture
def api(connected):
    with respx.mock(base_url=API, assert_all_called=False) as m:
        yield m


@pytest.fixture
def ml(connected):
    return MLClient(sleep=lambda s: None)


@pytest.fixture
def catalog_variants(db):
    p = Product.objects.create(name="Buzo")
    return [Variant.objects.create(product=p, sku=s) for s in ("BUZ-001-M-NEG", "BUZ-001-L-NEG", "GOR-010")]


def stub_order_related(api, shipment_id=40001, order_id=2000001, logistic="self_service"):
    api.get(f"/shipments/{shipment_id}").mock(
        return_value=httpx.Response(200, json=S.shipment(shipment_id, order_id, logistic))
    )
    api.get(f"/shipments/{shipment_id}/sla").mock(
        return_value=httpx.Response(200, json={"expected_date": "2026-11-13T12:00:00.000-03:00"})
    )
    api.get(f"/orders/{order_id}/billing_info").mock(return_value=httpx.Response(200, json=S.billing("CF")))


# ── Token ────────────────────────────────────────────────────────────────


def test_valid_token_is_used_without_refresh(api):
    route = api.post("/oauth/token")
    assert auth.get_access_token() == "ACCESS-1"
    assert route.call_count == 0


def test_refresh_saves_new_refresh_token(db):
    save_cred(expires_in=timedelta(minutes=10))
    with respx.mock(base_url=API, assert_all_called=False) as m:
        route = m.post("/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "ACCESS-2",
                    "refresh_token": "REFRESH-2",
                    "expires_in": 21600,
                    "user_id": int(S.SELLER),
                },
            )
        )
        assert auth.get_access_token() == "ACCESS-2"
    body = route.calls[0].request.content.decode()
    assert "grant_type=refresh_token" in body and "refresh_token=REFRESH-1" in body
    assert credentials.get("mercadolibre")["refresh_token"] == "REFRESH-2"


def test_refresh_skipped_if_another_worker_already_refreshed(db):
    save_cred(expires_in=timedelta(minutes=10), access="ACCESS-OLD")
    save_cred(access="ACCESS-NEW")  # otro worker renovó
    with respx.mock(base_url=API, assert_all_called=False) as m:
        route = m.post("/oauth/token")
        assert auth.force_refresh("ACCESS-OLD") == "ACCESS-NEW"
        assert route.call_count == 0


def test_invalid_grant_disconnects_and_alerts(db, users_by_role):
    save_cred(expires_in=timedelta(minutes=1))
    with respx.mock(base_url=API, assert_all_called=False) as m:
        m.post("/oauth/token").mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
        with pytest.raises(auth.TokenRevoked):
            auth.get_access_token()
    assert not ChannelCredential.objects.exists()
    assert Alert.objects.filter(alert_type__code="integration.disconnected").exists()


def test_network_error_on_refresh_is_transient(db):
    save_cred(expires_in=timedelta(minutes=1))
    with respx.mock(base_url=API, assert_all_called=False) as m:
        m.post("/oauth/token").mock(side_effect=httpx.ConnectError("caído"))
        with pytest.raises(auth.TokenRefreshError):
            auth.get_access_token()
    assert ChannelCredential.objects.exists()


def test_401_refreshes_and_retries_once(api, ml):
    calls = api.get("/users/me").mock(
        side_effect=[httpx.Response(401, json={}), httpx.Response(200, json={"id": 1})]
    )
    api.post("/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ACCESS-2",
                "refresh_token": "REFRESH-2",
                "expires_in": 21600,
                "user_id": int(S.SELLER),
            },
        )
    )
    assert ml.get("/users/me") == {"id": 1}
    assert calls.calls[1].request.headers["Authorization"] == "Bearer ACCESS-2"


def test_periodic_refresh_only_when_close_to_expiry(db):
    save_cred(expires_in=timedelta(hours=3))
    assert auth.refresh_if_needed() is False


# ── Conexión ─────────────────────────────────────────────────────────────


def test_connect_redirect_and_paste_url_flow(admin_client, in_memory_queue):
    response = admin_client.post(reverse("mercadolibre:connect"))
    state = admin_client.session["ml_oauth_state"]
    assert response["Location"].startswith("https://auth.mercadolibre.com.ar/authorization?")
    assert f"state={state}" in response["Location"]
    with respx.mock(base_url=API, assert_all_called=False) as m:
        m.post("/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "A",
                    "refresh_token": "R",
                    "expires_in": 21600,
                    "user_id": int(S.SELLER),
                    "scope": "x",
                },
            )
        )
        admin_client.post(
            reverse("mercadolibre:paste_url"),
            {"return_url": f"https://example.com/ml-callback?code=TG-abc&state={state}"},
        )
    assert credentials.get("mercadolibre")["user_id"] == S.SELLER
    assert b'"A"' not in bytes(ChannelCredential.objects.get().data_encrypted)
    assert AuditLog.objects.filter(action="integration.connected").exists()
    names = sorted(j["task_name"].rsplit(".", 1)[-1] for j in in_memory_queue.jobs.values())
    assert names == ["ml_import_listings", "ml_import_orders"]


def test_paste_url_with_bad_state_is_rejected(admin_client):
    admin_client.post(reverse("mercadolibre:connect"))
    admin_client.post(
        reverse("mercadolibre:paste_url"), {"return_url": "https://example.com/?code=x&state=otro"}
    )
    assert not ChannelCredential.objects.exists()


def test_paste_url_without_code():
    with pytest.raises(auth.OAuthError):
        auth.parse_return_url("https://example.com/?state=x")


def test_connect_forbidden_for_ventas(ml, users_by_role, django_user_model):
    from django.test import Client

    c = Client()
    c.force_login(users_by_role[VENTAS])
    assert c.post(reverse("mercadolibre:connect")).status_code == 403


# ── Notificaciones ───────────────────────────────────────────────────────


def notify(c, payload):
    return c.post("/hooks/mercadolibre/", data=json.dumps(payload), content_type="application/json")


def test_notification_from_other_app_or_seller_ignored(connected):
    from django.test import Client

    c = Client()
    base = {"resource": "/orders/1", "topic": "orders_v2", "application_id": 5555, "user_id": int(S.SELLER)}
    assert notify(c, {**base, "application_id": 1}).status_code == 403
    assert notify(c, {**base, "user_id": 1}).status_code == 403
    assert notify(c, base).status_code == 200
    assert InboundEvent.objects.count() == 1


def test_notification_dedupe_by_minute(connected):
    from django.test import Client

    c = Client()
    payload = {
        "resource": "/orders/1",
        "topic": "orders_v2",
        "application_id": 5555,
        "user_id": int(S.SELLER),
    }
    t0 = timezone.now().replace(second=1)
    with mock.patch("django.utils.timezone.now", return_value=t0):
        notify(c, payload)
        notify(c, payload)
    assert InboundEvent.objects.count() == 1


def test_order_notification_flow(api, in_memory_queue, catalog_variants):
    from django.test import Client

    from apps.integrations.tasks import process_event

    api.get("/orders/2000001").mock(return_value=httpx.Response(200, json=S.order()))
    stub_order_related(api)
    notify(
        Client(),
        {
            "resource": "/orders/2000001",
            "topic": "orders_v2",
            "application_id": 5555,
            "user_id": int(S.SELLER),
        },
    )
    for job in list(in_memory_queue.jobs.values()):
        process_event(**job["args"])
    assert InboundEvent.objects.get().status == "done"
    assert SalesDocument.objects.count() == 1


# ── Publicaciones ────────────────────────────────────────────────────────


def test_item_with_variations_links_by_sku(catalog_variants):
    listing = listings.upsert_item(S.item())
    assert listing.logistic_type == "self_service" and str(listing.health) == "0.85"
    v1 = listing.variations.get(external_id="111")
    v2 = listing.variations.get(external_id="112")
    assert v1.variant.sku == "BUZ-001-M-NEG" and v1.attributes == {"Talle": "M", "Color": "Negro"}
    assert v1.picture_urls == ["https://http2.mlstatic.com/p2.jpg"]
    assert v2.sku == "BUZ-001-L-NEG" and v2.variant is not None  # por seller_custom_field
    assert not listing.needs_review
    assert (
        ExternalRef.objects.filter(channel__code="mercadolibre", content_type__model="variant").count() == 2
    )


def test_item_without_variations(catalog_variants):
    listing = listings.upsert_item(S.item(item_id="MLA2", variations=False))
    row = listing.variations.get()
    assert row.external_id == "" and row.variant.sku == "GOR-010"


def test_missing_and_unknown_sku_flagged(catalog_variants):
    data = S.item()
    data["variations"][0]["attributes"] = []
    data["variations"][1]["seller_custom_field"] = "NO-EXISTE"
    listing = listings.upsert_item(data)
    assert listing.needs_review
    assert "sin SKU" in listing.review_notes and "NO-EXISTE no está en el catálogo" in listing.review_notes


def test_full_listing_and_idempotency(catalog_variants):
    listings.upsert_item(S.item(shipping={"logistic_type": "fulfillment"}))
    listings.upsert_item(S.item(shipping={"logistic_type": "fulfillment"}))
    assert Listing.objects.get().logistic_type == "fulfillment"
    assert ListingVariation.objects.count() == 2


def test_import_all_scan_multiget_and_closed(api, ml, catalog_variants):
    Listing.objects.create(
        channel=Channel.objects.get(code="mercadolibre"),
        external_id="MLA-VIEJA",
        title="Vieja",
        status="active",
    )
    api.get(f"/users/{S.SELLER}/items/search").mock(
        side_effect=[
            httpx.Response(200, json={"results": ["MLA1001", "MLA2"], "scroll_id": "s1"}),
            httpx.Response(200, json={"results": [], "scroll_id": "s1"}),
        ]
    )
    old_closed = S.item(item_id="MLA2", status="closed", last_updated="2025-01-01T00:00:00.000Z")
    api.get("/items").mock(
        return_value=httpx.Response(
            200, json=[{"code": 200, "body": S.item()}, {"code": 200, "body": old_closed}]
        )
    )
    stats = listings.import_all(ml)
    assert stats["listings"] == 1 and stats["skipped_closed"] == 1
    assert Listing.objects.get(external_id="MLA-VIEJA").status == "closed"


def test_import_error_does_not_stop_others(api, ml):
    api.get(f"/users/{S.SELLER}/items/search").mock(
        return_value=httpx.Response(200, json={"results": ["A", "B"]})
    )
    api.get("/items").mock(
        return_value=httpx.Response(
            200, json=[{"code": 200, "body": S.item(item_id="A")}, {"code": 200, "body": S.item(item_id="B")}]
        )
    )
    real = listings.upsert_item
    with mock.patch.object(
        listings,
        "upsert_item",
        side_effect=lambda d: (_ for _ in ()).throw(RuntimeError("x")) if d["id"] == "A" else real(d),
    ):
        stats = listings.import_all(ml)
    assert stats["listings"] == 1 and stats["errors"][0]["id"] == "A"


def test_write_stock_and_price_blocked(api):
    route = api.put("/items/MLA1001")
    adapter = registry.get("mercadolibre")
    with pytest.raises(WriteBlocked):
        adapter.write_stock("MLA1001", "111", 3)
    with pytest.raises(WriteBlocked):
        adapter.write_price("MLA1001", 100)
    assert route.call_count == 0


# ── Ventas y packs ───────────────────────────────────────────────────────


def test_single_order(catalog_variants):
    listings.upsert_item(S.item())
    doc, changed = orders.upsert_order(S.order())
    assert changed and doc.channel.code == "mercadolibre" and doc.status == "new"
    line = doc.lines.get()
    assert line.variant.sku == "BUZ-001-M-NEG" and line.description_snapshot.endswith("(M)")
    assert str(doc.total) == "45000.00" and doc.shipping_total == 0
    assert doc.payments.get().status == Payment.Status.CONFIRMED
    assert doc.customer.trade_name == "LUCIAG" and doc.customer.legal_name == "Lucía Gómez"
    assert doc.channel_status == "paid"


@pytest.mark.parametrize("order_of_arrival", [(0, 1), (1, 0)])
def test_pack_in_any_order_is_one_document(catalog_variants, order_of_arrival):
    pack = [
        S.order(order_id=3001, pack_id=777),
        S.order(order_id=3002, pack_id=777, variation_id=112, sku="BUZ-001-L-NEG"),
    ]
    for i in order_of_arrival:
        orders.upsert_order(pack[i])
    assert SalesDocument.objects.count() == 1
    doc = SalesDocument.objects.get()
    assert sorted(ln.sku_snapshot for ln in doc.lines.all()) == ["BUZ-001-L-NEG", "BUZ-001-M-NEG"]
    assert str(doc.total) == "90000.00" and doc.payments.count() == 2


def test_partial_cancel_in_pack(catalog_variants):
    orders.upsert_order(S.order(order_id=3001, pack_id=777))
    orders.upsert_order(
        S.order(order_id=3002, pack_id=777, status="cancelled", sku="BUZ-001-L-NEG", variation_id=112)
    )
    assert SalesDocument.objects.get().channel_status == "cancelled,paid"


def test_old_order_does_not_overwrite(catalog_variants):
    orders.upsert_order(S.order(updated="2026-11-12T16:00:00.000-03:00", status="paid"))
    doc, changed = orders.upsert_order(
        S.order(updated="2026-11-12T15:00:00.000-03:00", status="payment_required")
    )
    assert not changed and doc.channel_status == "paid"


def test_update_keeps_internal_status(catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    SalesDocument.objects.filter(pk=doc.pk).update(status="preparing")
    # Una actualización sin hechos nuevos (sigue pagada) no toca el estado interno.
    # (Las cancelaciones sí lo mueven: lo cubre test_centro_pedidos.)
    orders.upsert_order(S.order(updated="2026-11-13T10:00:00.000-03:00", status="paid"))
    doc.refresh_from_db()
    assert doc.status == "preparing" and doc.channel_status.startswith("paid")


def test_unknown_sku_alert(users_by_role):
    doc, _ = orders.upsert_order(S.order(sku="NO-EXISTE"))
    assert doc.lines.get().variant is None
    assert Alert.objects.filter(alert_type__code="catalog.unknown_sku", dedupe_key="NO-EXISTE").exists()


def test_sync_orders_window_48h_and_pagination(api, ml, catalog_variants):
    route = api.get("/orders/search").mock(
        side_effect=[
            httpx.Response(
                200, json={"results": [S.order(order_id=1, shipping_id=None)], "paging": {"total": 2}}
            ),
            httpx.Response(
                200, json={"results": [S.order(order_id=2, shipping_id=None)], "paging": {"total": 2}}
            ),
        ]
    )
    api.get(url__regex=r".*/orders/\d+/billing_info").mock(return_value=httpx.Response(404, json={}))
    stats = orders.sync_orders(ml, updated_since=timezone.now() - timedelta(minutes=5))
    assert stats["orders"] == 2
    sent = route.calls[0].request.url.params["order.date_last_updated.from"]
    assert sent[:13] == (timezone.now() - timedelta(hours=48)).isoformat()[:13]
    assert route.calls[0].request.url.params["seller"] == S.SELLER


def test_initial_import_by_creation_date(api, in_memory_queue):
    from apps.integrations.adapters.mercadolibre.tasks import ml_import_orders

    route = api.get("/orders/search").mock(
        return_value=httpx.Response(200, json={"results": [], "paging": {"total": 0}})
    )
    ml_import_orders(days=30)
    assert "order.date_created.from" in route.calls[0].request.url.params
    assert SyncRun.objects.get(job="orders_initial").status == "ok"


def test_periodic_tasks_skip_when_not_connected(db):
    from apps.integrations.adapters.mercadolibre.tasks import ml_reconcile_orders

    ml_reconcile_orders(timestamp=0)
    assert not SyncRun.objects.exists()


# ── Envíos y etiquetas ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "logistic,method,has_deadline",
    [
        ("self_service", Shipment.Method.ME_FLEX, True),
        ("fulfillment", Shipment.Method.ME_FULL, False),
        ("cross_docking", Shipment.Method.ME_COLECTA, True),
        ("drop_off", Shipment.Method.ME_DROP_OFF, True),
        ("custom", Shipment.Method.ME_CUSTOM, False),
        ("rarísimo", Shipment.Method.ME_OTHER, False),
    ],
)
def test_shipment_modes(api, ml, catalog_variants, logistic, method, has_deadline):
    orders.upsert_order(S.order())
    stub_order_related(api, logistic=logistic)
    shipment = shipments.refresh(ml, 40001)
    assert shipment.method == method and shipment.logistic_type == logistic
    assert (shipment.dispatch_deadline is not None) == has_deadline
    assert SalesDocument.objects.get().channel_status == "paid/ready_to_ship"


def test_shipment_without_order_yet_is_ignored(api, ml):
    stub_order_related(api, order_id=999)
    assert shipments.refresh(ml, 40001) is None


@pytest.fixture
def flex_shipment(api, ml, catalog_variants):
    orders.upsert_order(S.order())
    stub_order_related(api)
    return shipments.refresh(ml, 40001)


def test_label_pdf_cached(api, ml, flex_shipment):
    route = api.get("/shipment_labels").mock(return_value=httpx.Response(200, content=b"%PDF-1.4 etiqueta"))
    assert shipments.get_label(ml, flex_shipment, "pdf").startswith(b"%PDF")
    flex_shipment.refresh_from_db()
    assert shipments.get_label(ml, flex_shipment, "pdf").startswith(b"%PDF")
    assert route.call_count == 1 and route.calls[0].request.url.params["response_type"] == "pdf"


def test_label_zpl_inside_zip(api, ml, flex_shipment):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Etiqueta de envio.txt", "^XA^FO50,50^FDDeutsch^FS^XZ")
    api.get("/shipment_labels").mock(return_value=httpx.Response(200, content=buf.getvalue()))
    assert shipments.get_label(ml, flex_shipment, "zpl2").startswith(b"^XA")
    flex_shipment.refresh_from_db()
    assert flex_shipment.label_zpl_file.name.endswith(".zpl")


def test_label_not_ready(api, ml, flex_shipment):
    api.get("/shipment_labels").mock(
        return_value=httpx.Response(400, json={"message": "Shipment not ready to print"})
    )
    with pytest.raises(shipments.LabelNotReady, match="not ready"):
        shipments.get_label(ml, flex_shipment, "pdf")


def test_full_has_no_label(api, ml, catalog_variants):
    orders.upsert_order(S.order())
    stub_order_related(api, logistic="fulfillment")
    full = shipments.refresh(ml, 40001)
    with pytest.raises(shipments.LabelNotReady):
        shipments.get_label(ml, full)


# ── Facturación ──────────────────────────────────────────────────────────


def test_billing_ri_sets_fiscal_data(api, ml, catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    api.get("/orders/2000001/billing_info").mock(return_value=httpx.Response(200, json=S.billing("RI")))
    billing.refresh(ml, 2000001, doc)
    c = doc.customer
    c.refresh_from_db()
    assert (c.tax_id, c.tax_id_type, c.vat_condition) == ("30712345678", "CUIT", "RI")
    assert c.legal_name == "Lucía Gómez"  # el nombre real ya estaba: no se pisa
    assert c.addresses.get(kind="fiscal").city == "CABA"
    doc.refresh_from_db()
    assert doc.fiscal["buyer"]["taxpayer_type"] == "IVA Responsable Inscripto"


def test_billing_cf_and_missing(api, ml, catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    api.get("/orders/2000001/billing_info").mock(return_value=httpx.Response(200, json=S.billing("CF")))
    billing.refresh(ml, 2000001, doc)
    doc.customer.refresh_from_db()
    assert doc.customer.vat_condition == "CF" and doc.customer.tax_id == "30111222"
    assert billing.parse({}) is None


def test_billing_does_not_overwrite_manual_data(api, ml, catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    doc.customer.tax_id = "20999999990"
    doc.customer.save()
    api.get("/orders/2000001/billing_info").mock(return_value=httpx.Response(200, json=S.billing("RI")))
    billing.refresh(ml, 2000001, doc)
    doc.customer.refresh_from_db()
    assert doc.customer.tax_id == "20999999990"


# ── Preguntas ────────────────────────────────────────────────────────────


def test_question_saved_and_linked(catalog_variants):
    listings.upsert_item(S.item())
    q = questions.upsert_question(S.question())
    assert q.status == Question.Status.UNANSWERED and q.listing.external_id == "MLA1001"


def test_answer_ok_audited(api, ml, users_by_role):
    q = questions.upsert_question(S.question())
    route = api.post("/answers").mock(return_value=httpx.Response(200, json={}))
    questions.answer(ml, q, "Sí, hay XL", user=users_by_role[VENTAS])
    assert json.loads(route.calls[0].request.content) == {"question_id": 9001, "text": "Sí, hay XL"}
    q.refresh_from_db()
    assert (
        q.status == Question.Status.ANSWERED
        and q.answered_by == users_by_role[VENTAS]
        and q.draft_answer == ""
    )
    assert AuditLog.objects.filter(action="ml.question_answered").exists()


@pytest.mark.parametrize(
    "error,status",
    [
        ({"error": "not_found", "message": "Question deleted"}, Question.Status.DELETED),
        ({"error": "forbidden", "message": "User is banned"}, Question.Status.BANNED),
        ({"error": "bad_request", "message": "Question already answered"}, Question.Status.ANSWERED),
        ({"error": "bad_request", "message": "Invalid text"}, Question.Status.ERROR),
    ],
)
def test_answer_rejected_keeps_draft(api, ml, users_by_role, error, status):
    q = questions.upsert_question(S.question())
    api.post("/answers").mock(return_value=httpx.Response(400, json=error))
    with pytest.raises(questions.AnswerRejected):
        questions.answer(ml, q, "Mi respuesta", user=users_by_role[VENTAS])
    q.refresh_from_db()
    assert q.status == status and q.draft_answer == "Mi respuesta" and q.answer_error


def test_answer_requires_permission(ml, users_by_role):
    q = questions.upsert_question(S.question())
    with pytest.raises(PermissionDenied):
        questions.answer(ml, q, "x", user=users_by_role[DEPOSITO])


def test_sync_unanswered_refreshes_stale(api, ml):
    questions.upsert_question(S.question(qid=1))
    api.get("/questions/search").mock(
        return_value=httpx.Response(
            200, json={"questions": [S.question(qid=2)], "total": 1, "paging": {"total": 1}}
        )
    )
    api.get("/questions/1").mock(
        return_value=httpx.Response(
            200,
            json=S.question(
                qid=1,
                status="ANSWERED",
                answer={"text": "ok", "date_created": "2026-11-12T11:00:00.000-03:00"},
            ),
        )
    )
    questions.sync_unanswered(ml)
    assert Question.objects.get(external_id="1").status == Question.Status.ANSWERED
    assert Question.objects.get(external_id="2").status == Question.Status.UNANSWERED


# ── Mensajes ─────────────────────────────────────────────────────────────


def test_message_in_and_out_linked_to_document(catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    m_in = messages.upsert_message(S.message(), S.SELLER)
    m_out = messages.upsert_message(S.message(mid="msg-2", from_seller=True, text="Mañana"), S.SELLER)
    assert m_in.direction == "in" and m_out.direction == "out" and m_in.document == doc


def test_send_message_ok(api, ml, users_by_role, catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    route = api.post(f"/messages/packs/2000001/sellers/{S.SELLER}").mock(
        return_value=httpx.Response(201, json={"id": "out-1"})
    )
    msg = messages.send(ml, doc, "Te llega mañana", user=users_by_role[VENTAS])
    body = json.loads(route.calls[0].request.content)
    assert body["to"]["user_id"] == S.BUYER and body["text"] == "Te llega mañana"
    assert msg.external_id == "out-1" and AuditLog.objects.filter(action="ml.message_sent").exists()


def test_send_message_too_long(ml, users_by_role, catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    with pytest.raises(messages.MessagingBlocked, match="350"):
        messages.send(ml, doc, "x" * 351, user=users_by_role[VENTAS])


def test_send_message_blocked_by_ml(api, ml, users_by_role, catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    api.post(f"/messages/packs/2000001/sellers/{S.SELLER}").mock(
        return_value=httpx.Response(403, json={"message": "blocked_conversation"})
    )
    with pytest.raises(messages.MessagingBlocked, match="blocked_conversation"):
        messages.send(ml, doc, "hola", user=users_by_role[VENTAS])
    assert not Message.objects.exists()


def test_sync_unread(api, ml, catalog_variants):
    orders.upsert_order(S.order(pack_id=777))
    api.get("/messages/unread").mock(
        return_value=httpx.Response(
            200, json={"results": [{"resource": f"/packs/777/sellers/{S.SELLER}", "count": 1}]}
        )
    )
    thread = api.get(f"/messages/packs/777/sellers/{S.SELLER}").mock(
        return_value=httpx.Response(200, json={"messages": [S.message(pack_id=777)]})
    )
    stats = messages.sync_unread(ml)
    assert stats["messages"] == 1 and thread.calls[0].request.url.params["mark_as_read"] == "false"
    assert Message.objects.get().document is not None


# ── Reclamos ─────────────────────────────────────────────────────────────


def test_claim_due_date_and_alert_once(api, ml, users_by_role, catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    claims.upsert_claim(ml, S.claim())
    claims.upsert_claim(ml, S.claim())
    claim = Claim.objects.get()
    assert claim.document == doc and claim.action_required and claim.due_date is not None
    assert Alert.objects.filter(alert_type__code="ml.claim_opened").count() == 1


@pytest.mark.parametrize("ret_status", ["shipped", "delivered"])
def test_claim_with_return(api, ml, catalog_variants, ret_status):
    orders.upsert_order(S.order())
    api.get("/post-purchase/v2/claims/5001/returns").mock(
        return_value=httpx.Response(200, json={"status": "opened", "shipments": [{"status": ret_status}]})
    )
    claim = claims.upsert_claim(ml, S.claim(with_return=True))
    assert claim.return_status == ret_status


def test_closed_claim_requires_no_action(api, ml, catalog_variants):
    claim = claims.upsert_claim(ml, S.claim(status="closed"))
    assert not claim.action_required


# ── Panel ────────────────────────────────────────────────────────────────


def test_panel_card(admin_client, connected):
    content = admin_client.get(reverse("integrations:status")).content.decode()
    assert "Vendedor" in content and S.SELLER in content and "Importar publicaciones" in content


def test_import_buttons(admin_client, connected, in_memory_queue):
    admin_client.post(reverse("mercadolibre:import", args=["publicaciones"]))
    admin_client.post(reverse("mercadolibre:import", args=["ventas"]))
    assert len(in_memory_queue.jobs) == 2
