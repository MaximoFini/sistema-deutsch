from datetime import timedelta
from decimal import Decimal
from unittest import mock

import httpx
import pytest
import respx
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import ADMIN, DEPOSITO, VENTAS
from apps.alerts.models import Alert
from apps.audit.models import AuditLog
from apps.catalog.models import Product, Variant
from apps.customers.models import Customer
from apps.integrations import credentials
from apps.integrations.adapters.mercadolibre import claims as ml_claims
from apps.integrations.adapters.mercadolibre import orders as ml_orders
from apps.integrations.adapters.tiendanube import orders as tn_orders
from apps.integrations.models import Channel
from apps.inventory import services as inventory
from apps.sales import manual, returns, states, sync
from apps.sales.models import Payment, ReturnInfo, SalesDocument, SalesLine, Shipment
from apps.sales.tasks import check_flex_due, check_manual_pending
from tests import ml_samples, tn_samples

pytestmark = pytest.mark.django_db


def order(
    channel="manual", status=states.NEW, total=Decimal("1000"), method=Shipment.Method.CARRIER, paid=True
):
    doc = SalesDocument.objects.create(
        channel=Channel.objects.get(code=channel),
        status=status,
        issued_at=timezone.now(),
        total=total,
        channel_reference=f"{channel} test",
    )
    Shipment.objects.create(document=doc, method=method)
    if paid:
        Payment.objects.create(document=doc, method="cash", amount=total, status=Payment.Status.CONFIRMED)
    return doc


@pytest.fixture
def variant(db):
    p = Product.objects.create(name="Buzo")
    v = Variant.objects.create(product=p, sku="BUZ-1")
    inventory.apply_sync_level(v, inventory.default_warehouse(), 5)
    return v


# ── Máquina de estados ───────────────────────────────────────────────────


def test_happy_path_audited(users_by_role):
    dep = users_by_role[DEPOSITO]
    doc = order()
    for to in (states.PREPARING, states.READY, states.DISPATCHED, states.DELIVERED):
        assert states.change_status(doc, to, user=dep)
    doc.refresh_from_db()
    assert doc.status == states.DELIVERED
    logs = AuditLog.objects.filter(action="order.status_changed").order_by("id")
    assert [lg.after["estado"] for lg in logs] == ["preparing", "ready", "dispatched", "delivered"]
    assert logs.first().actor == dep


def test_forbidden_transition(users_by_role):
    doc = order()
    with pytest.raises(states.TransitionNotAllowed, match="No se puede pasar"):
        states.change_status(doc, states.DELIVERED, user=users_by_role[ADMIN])


def test_vendedor_cannot_change_status(users_by_role):
    with pytest.raises(states.TransitionNotAllowed, match="permiso"):
        states.change_status(order(), states.PREPARING, user=users_by_role["Vendedor"])


def test_cancel_only_manual_orders(users_by_role):
    tn = order("tiendanube")
    with pytest.raises(states.TransitionNotAllowed, match="se cancelan en el canal"):
        states.change_status(tn, states.CANCELLED, user=users_by_role[ADMIN])
    manual_doc = order("manual")
    with pytest.raises(states.TransitionNotAllowed):
        states.change_status(
            manual_doc, states.CANCELLED, user=users_by_role[DEPOSITO]
        )  # sin permiso de cancelar
    states.change_status(manual_doc, states.CANCELLED, user=users_by_role[VENTAS], reason="Se arrepintió")
    manual_doc.refresh_from_db()
    assert manual_doc.status == states.CANCELLED


def test_pickup_vs_dispatch(users_by_role):
    pickup = order(method=Shipment.Method.PICKUP, status=states.READY)
    ship = order(status=states.READY)
    admin = users_by_role[ADMIN]
    assert states.READY_FOR_PICKUP in states.allowed_transitions(pickup, admin)
    assert states.DISPATCHED not in states.allowed_transitions(pickup, admin)
    assert states.DISPATCHED in states.allowed_transitions(ship, admin)


def test_cancel_in_progress_alerts(users_by_role, django_capture_on_commit_callbacks):
    doc = order(status=states.PREPARING)
    with django_capture_on_commit_callbacks(execute=True):
        states.change_status(doc, states.CANCELLED, user=users_by_role[ADMIN])
    assert Alert.objects.filter(alert_type__code="orders.cancelled_in_progress").exists()


@pytest.fixture
def tn_doc(db):
    credentials.save("tiendanube", {"access_token": "T", "store_id": "8434848", "scope": "x"})
    doc = tn_orders.upsert_order(tn_samples.order())
    return doc


def test_user_dispatch_marks_tiendanube(
    tn_doc, users_by_role, in_memory_queue, django_capture_on_commit_callbacks
):
    SalesDocument.objects.filter(pk=tn_doc.pk).update(status=states.READY)
    with django_capture_on_commit_callbacks(execute=True):
        states.change_status(tn_doc, states.DISPATCHED, user=users_by_role[DEPOSITO], tracking_code="AB1")
    jobs = [j for j in in_memory_queue.jobs.values() if j["task_name"].endswith("tn_fulfillment_update")]
    assert (
        len(jobs) == 1
        and jobs[0]["args"]["action"] == "dispatched"
        and jobs[0]["args"]["tracking_code"] == "AB1"
    )


def test_system_changes_never_write_to_tiendanube(
    tn_doc, in_memory_queue, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        tn_orders.upsert_order(tn_samples.order(updated_at="2026-11-13T10:00:00+0000", status="cancelled"))
    tn_doc.refresh_from_db()
    assert tn_doc.status == states.CANCELLED
    assert not [j for j in in_memory_queue.jobs.values() if j["task_name"].endswith("tn_fulfillment_update")]


# ── Sincronización con los canales ───────────────────────────────────────


def test_tn_unpaid_then_paid(db, users_by_role, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        doc = tn_orders.upsert_order(tn_samples.order(payment_status="pending", paid_at=None))
    doc.refresh_from_db()
    assert doc.status == states.AWAITING_PAYMENT
    assert not Alert.objects.filter(alert_type__code="orders.new").exists()
    with django_capture_on_commit_callbacks(execute=True):
        tn_orders.upsert_order(tn_samples.order(updated_at="2026-11-13T10:00:00+0000"))
    doc.refresh_from_db()
    assert doc.status == states.NEW
    assert Alert.objects.filter(alert_type__code="orders.new").count() == 1


def test_tn_new_paid_order_alerts_deposito_once(db, users_by_role, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        tn_orders.upsert_order(tn_samples.order())
        tn_orders.upsert_order(tn_samples.order(updated_at="2026-11-13T10:00:00+0000"))
    alert = Alert.objects.get(alert_type__code="orders.new")
    assert alert.receipts.get().user == users_by_role[DEPOSITO]
    assert not alert.receipts.filter(emailed_at__isnull=False).exists()


def test_tn_delivered(db):
    doc = tn_orders.upsert_order(tn_samples.order())
    tn_orders.upsert_order(
        tn_samples.order(updated_at="2026-11-14T10:00:00+0000", shipping_status="delivered")
    )
    doc.refresh_from_db()
    assert doc.status == states.DELIVERED


@pytest.fixture
def ml_api(db):
    credentials.save(
        "mercadolibre",
        {
            "access_token": "A",
            "refresh_token": "R",
            "expires_at": (timezone.now() + timedelta(hours=5)).isoformat(),
            "user_id": ml_samples.SELLER,
            "scope": "",
        },
    )
    with respx.mock(base_url="https://api.mercadolibre.com", assert_all_called=False) as m:
        yield m


def stub_ml(api, logistic="self_service", order_id=2000001, shipment_status="ready_to_ship"):
    sh = ml_samples.shipment(order_id=order_id, logistic=logistic, status=shipment_status)
    api.get("/shipments/40001").mock(return_value=httpx.Response(200, json=sh))
    api.get("/shipments/40001/sla").mock(
        return_value=httpx.Response(200, json={"expected_date": "2026-11-13T12:00:00.000-03:00"})
    )
    api.get(f"/orders/{order_id}/billing_info").mock(return_value=httpx.Response(404, json={}))


def test_ml_full_goes_to_dispatched_without_new_alert(
    ml_api, users_by_role, django_capture_on_commit_callbacks
):
    from apps.integrations.adapters.mercadolibre.client import MLClient

    stub_ml(ml_api, logistic="fulfillment")
    with django_capture_on_commit_callbacks(execute=True):
        doc = ml_orders.process_order(MLClient(sleep=lambda s: None), ml_samples.order())
    doc.refresh_from_db()
    assert doc.status == states.DISPATCHED
    assert not Alert.objects.filter(alert_type__code__in=["orders.new", "orders.out_of_stock"]).exists()
    log = AuditLog.objects.filter(action="order.status_changed").last()
    assert log.actor is None and "Full" in log.metadata["motivo"]


def test_ml_flex_new_order_and_out_of_stock(ml_api, users_by_role, django_capture_on_commit_callbacks):
    from apps.integrations.adapters.mercadolibre.client import MLClient

    p = Product.objects.create(name="Buzo")
    v = Variant.objects.create(product=p, sku="BUZ-001-M-NEG")
    inventory.apply_sync_level(v, inventory.default_warehouse(), 0)
    inventory.change_reserved(v, inventory.default_warehouse(), 1)  # disponible −1
    stub_ml(ml_api)
    with django_capture_on_commit_callbacks(execute=True):
        doc = ml_orders.process_order(MLClient(sleep=lambda s: None), ml_samples.order())
    doc.refresh_from_db()
    assert doc.status == states.NEW and doc.channel_reference == "ML 2000001"
    assert Alert.objects.filter(alert_type__code="orders.new").exists()
    assert "BUZ-001-M-NEG" in Alert.objects.get(alert_type__code="orders.out_of_stock").body


def test_ml_cancelled_pack(db):
    ml_orders.upsert_order(ml_samples.order(order_id=1, pack_id=9))
    doc, _ = ml_orders.upsert_order(ml_samples.order(order_id=2, pack_id=9, status="cancelled"))
    doc.refresh_from_db()
    assert doc.status == states.NEW  # cancelación parcial: sigue
    ml_orders.upsert_order(
        ml_samples.order(order_id=1, pack_id=9, status="cancelled", updated="2026-11-13T00:00:00.000-03:00")
    )
    doc.refresh_from_db()
    assert doc.status == states.CANCELLED


def test_claim_open_and_close_returns_to_previous(ml_api, users_by_role):
    from apps.integrations.adapters.mercadolibre.client import MLClient

    doc, _ = ml_orders.upsert_order(ml_samples.order())
    states.change_status(doc, states.PREPARING, user=users_by_role[DEPOSITO])
    client = MLClient(sleep=lambda s: None)
    ml_claims.upsert_claim(client, ml_samples.claim())
    doc.refresh_from_db()
    assert doc.status == states.CLAIM and doc.status_before_claim == states.PREPARING
    ml_claims.upsert_claim(client, ml_samples.claim(status="closed"))
    doc.refresh_from_db()
    assert doc.status == states.PREPARING


def test_sync_is_idempotent(db):
    doc = tn_orders.upsert_order(tn_samples.order())
    before = AuditLog.objects.count()
    sync.sync_internal_status(doc)
    sync.sync_internal_status(doc)
    assert AuditLog.objects.count() == before


def test_delivered_not_overwritten_by_cancel(db):
    doc = order("tiendanube", status=states.DELIVERED)
    SalesDocument.objects.filter(pk=doc.pk).update(channel_status="cancelled/refunded/unpacked")
    assert sync.sync_internal_status(doc) is None


# ── Pedidos manuales ─────────────────────────────────────────────────────


def test_manual_order_full(users_by_role, variant, django_capture_on_commit_callbacks):
    from apps.pricing import services as pricing
    from apps.pricing.models import PriceList

    pricing.set_price(PriceList.objects.get(code="MINORISTA"), variant, Decimal("1500"))
    customer = manual.find_or_create_customer(
        legal_name="Ana López", tax_id="20-30111222-3", email="ana@x.com"
    )
    with django_capture_on_commit_callbacks(execute=True):
        doc = manual.create_manual_order(
            customer=customer,
            lines=[manual.ManualLine(variant, Decimal("2"))],
            delivery=Shipment.Method.PICKUP,
            paid=False,
            payment_method=Payment.Method.TRANSFER,
            user=users_by_role[VENTAS],
        )
    assert doc.channel_reference.startswith("Manual #") and doc.total == Decimal("3000.00")
    assert customer.tax_id_type == "CUIT" and doc.payments.get().status == Payment.Status.PENDING
    assert Alert.objects.filter(alert_type__code="orders.new").exists()
    manual.update_payment(doc, paid=True, method=Payment.Method.TRANSFER, user=users_by_role[VENTAS])
    manual.update_invoice(doc, invoiced=True, number="B-0001-00001234", user=users_by_role[VENTAS])
    doc.refresh_from_db()
    assert manual.is_paid(doc) and doc.invoice_number == "B-0001-00001234"
    assert AuditLog.objects.filter(action__in=["order.payment_updated", "order.invoice_updated"]).count() == 2


def test_manual_rejects_wholesale_and_requires_invoice_number(users_by_role, variant):
    wholesale = Customer.objects.create(legal_name="Mayorista SA", kind="wholesale")
    with pytest.raises(manual.WholesaleNotAllowed):
        manual.create_manual_order(
            customer=wholesale,
            lines=[manual.ManualLine(variant, Decimal(1))],
            delivery="pickup",
            user=users_by_role[ADMIN],
        )
    retail = Customer.objects.create(legal_name="Juan")
    with pytest.raises(manual.ManualOrderError, match="comprobante"):
        manual.create_manual_order(
            customer=retail,
            lines=[manual.ManualLine(variant, Decimal(1))],
            delivery="pickup",
            invoiced=True,
            user=users_by_role[ADMIN],
        )


def test_manual_requires_permission(users_by_role, variant):
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        manual.create_manual_order(
            customer=Customer.objects.create(legal_name="X"),
            lines=[manual.ManualLine(variant, Decimal(1))],
            delivery="pickup",
            user=users_by_role[DEPOSITO],
        )


def test_manual_pending_alert_after_24h(users_by_role, variant):
    doc = manual.create_manual_order(
        customer=Customer.objects.create(legal_name="X"),
        lines=[manual.ManualLine(variant, Decimal(1), Decimal("100"))],
        delivery="pickup",
        user=users_by_role[ADMIN],
    )
    assert check_manual_pending() == 0
    later = timezone.now() + timedelta(hours=25)
    assert check_manual_pending(now=later) == 2  # sin cobrar y sin facturar
    assert check_manual_pending(now=later) == 0  # sin duplicar
    assert {a.dedupe_key for a in Alert.objects.filter(alert_type__code="orders.manual_pending")} == {
        f"manual:{doc.pk}:pago",
        f"manual:{doc.pk}:factura",
    }


# ── Devoluciones ─────────────────────────────────────────────────────────


def test_expected_from_ml_claim_once(ml_api):
    from apps.integrations.adapters.mercadolibre.client import MLClient

    doc, _ = ml_orders.upsert_order(ml_samples.order())
    ml_api.get("/post-purchase/v2/claims/5001/returns").mock(
        return_value=httpx.Response(200, json={"status": "opened", "shipments": [{"status": "shipped"}]})
    )
    client = MLClient(sleep=lambda s: None)
    ml_claims.upsert_claim(client, ml_samples.claim(with_return=True))
    ml_claims.upsert_claim(client, ml_samples.claim(with_return=True))
    info = ReturnInfo.objects.get()
    assert info.source == "ml_claim" and info.document.related_document == doc
    assert info.document.lines.count() == 1


def test_receive_and_adjust(users_by_role, variant, django_capture_on_commit_callbacks):
    stock_before = variant.stock_levels.get().on_hand
    o = order()
    SalesLine.objects.create(
        document=o,
        variant=variant,
        sku_snapshot="BUZ-1",
        description_snapshot="Buzo",
        quantity=2,
        unit_price=500,
    )
    ret = returns.create_expected(o, user=users_by_role[VENTAS])
    line = ret.lines.get()
    with django_capture_on_commit_callbacks(execute=True):
        returns.receive(ret, [(line, Decimal(1), "damaged")], "Vino manchado", user=users_by_role[DEPOSITO])
    line.refresh_from_db()
    assert line.quantity == 1 and line.condition == "damaged"
    assert Alert.objects.filter(alert_type__code="returns.received_adjust_stock").exists()
    with pytest.raises(returns.ReturnError):
        returns.receive(ret, [(line, Decimal(1), "damaged")], "", user=users_by_role[DEPOSITO])
    returns.mark_adjusted(ret, user=users_by_role[ADMIN])
    assert ReturnInfo.objects.get(document=ret).adjusted_in_contabilium
    assert variant.stock_levels.get().on_hand == stock_before  # no toca stock


def test_receive_unexpected(users_by_role, variant):
    o = order()
    line = SalesLine.objects.create(
        document=o,
        variant=variant,
        sku_snapshot="BUZ-1",
        description_snapshot="Buzo",
        quantity=1,
        unit_price=500,
    )
    ret = returns.receive_unexpected(o, [(line, Decimal(1), "resellable")], "", user=users_by_role[DEPOSITO])
    assert ret.status == returns.RECEIVED and ret.lines.get().condition == "resellable"


# ── Alertas Flex ─────────────────────────────────────────────────────────


def test_flex_due_alert_once(users_by_role):
    doc = order(method=Shipment.Method.ME_FLEX)
    Shipment.objects.filter(document=doc).update(dispatch_deadline=timezone.now() + timedelta(minutes=90))
    assert check_flex_due() == 1
    assert check_flex_due() == 0
    alert = Alert.objects.get(alert_type__code="orders.flex_due")
    assert alert.receipts.get().user == users_by_role[DEPOSITO]


def test_flex_not_alerted_if_dispatched_or_far(users_by_role):
    far = order(method=Shipment.Method.ME_FLEX)
    Shipment.objects.filter(document=far).update(dispatch_deadline=timezone.now() + timedelta(hours=5))
    done = order(method=Shipment.Method.ME_FLEX, status=states.DISPATCHED)
    Shipment.objects.filter(document=done).update(dispatch_deadline=timezone.now() + timedelta(minutes=10))
    assert check_flex_due() == 0


# ── Pantallas ────────────────────────────────────────────────────────────


@pytest.fixture
def some_orders(db):
    a = order("tiendanube", total=Decimal("100"))
    b = order("manual", status=states.PREPARING, paid=False)
    c = order("mercadolibre", status=states.DELIVERED, method=Shipment.Method.ME_FLEX)
    Shipment.objects.filter(document=b).update(dispatch_deadline=timezone.now() + timedelta(hours=1))
    SalesLine.objects.create(
        document=b, sku_snapshot="ZAP-9", description_snapshot="Zapatilla", quantity=1, unit_price=1
    )
    customer = Customer.objects.create(legal_name="Carla Ruiz")
    SalesDocument.objects.filter(pk=a.pk).update(customer=customer)
    return a, b, c


def ids(response):
    return [o.pk for o in response.context["orders"]]


def test_list_filters_and_order(admin_client, some_orders):
    a, b, c = some_orders
    url = reverse("sales:list")
    assert ids(admin_client.get(url))[0] == b.pk  # con fecha límite primero
    assert ids(admin_client.get(url, {"canal": "tiendanube"})) == [a.pk]
    assert ids(admin_client.get(url, {"estado": "preparing"})) == [b.pk]
    assert set(ids(admin_client.get(url, {"estado": "abiertos"}))) == {a.pk, b.pk}
    assert ids(admin_client.get(url, {"comprador": "carla"})) == [a.pk]
    assert ids(admin_client.get(url, {"sku": "ZAP"})) == [b.pk]
    assert ids(admin_client.get(url, {"cobro": "pendiente"})) == [b.pk]
    assert set(ids(admin_client.get(url, {"cobro": "cobrado"}))) == {a.pk, c.pk}
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    assert ids(admin_client.get(url, {"desde": tomorrow})) == []


def test_list_query_count(admin_client, some_orders):
    admin_client.get(reverse("sales:list"))  # calienta caches de sesión/permisos
    with CaptureQueriesContext(connection) as ctx:
        admin_client.get(reverse("sales:list"))
    assert len(ctx.captured_queries) <= 12


def test_list_visible_to_all_roles(client, users_by_role):
    for user in users_by_role.values():
        client.force_login(user)
        assert client.get(reverse("sales:list")).status_code == 200


def test_list_renders_mobile_cards(admin_client, some_orders):
    content = admin_client.get(reverse("sales:list")).content.decode()
    assert "md:hidden" in content and "Despachar antes de" in content


def test_detail_sections_and_buttons(client, users_by_role, some_orders):
    _, b, _ = some_orders
    client.force_login(users_by_role[DEPOSITO])
    content = client.get(reverse("sales:detail", args=[b.pk])).content.decode()
    for text in (
        "Productos",
        "Comprador",
        "Cobro",
        "Envío",
        "Reclamos y devoluciones",
        "Mensajes",
        "Historial",
    ):
        assert text in content
    assert "Listo" in content and ">Cancelado<" not in content  # Depósito no cancela
    client.force_login(users_by_role["Vendedor"])
    assert "Pasar a:" not in client.get(reverse("sales:detail", args=[b.pk])).content.decode()


def test_status_post_and_invalid(admin_client, some_orders):
    a, _, _ = some_orders
    admin_client.post(reverse("sales:status", args=[a.pk]), {"to": "preparing"})
    a.refresh_from_db()
    assert a.status == states.PREPARING
    response = admin_client.post(reverse("sales:status", args=[a.pk]), {"to": "delivered"}, follow=True)
    assert "No se puede pasar" in response.content.decode()


def test_manual_create_screen(admin_client, variant):
    response = admin_client.post(
        reverse("sales:manual_create"),
        {
            "legal_name": "Pedro Gómez",
            "tax_id": "30111222",
            "vat_condition": "CF",
            "variant_id": [variant.pk],
            "quantity": ["3"],
            "price": ["250,50"],
            "delivery": "carrier",
            "street": "Mitre 100",
            "city": "Córdoba",
            "paid": "1",
            "payment_method": "transfer",
        },
    )
    doc = SalesDocument.objects.get(channel__code="manual")
    assert response["Location"] == reverse("sales:detail", args=[doc.pk])
    assert doc.total == Decimal("751.50") and doc.customer.legal_name == "Pedro Gómez"
    assert doc.shipments.get().address["city"] == "Córdoba"


def test_manual_create_errors_keep_form(admin_client, variant):
    response = admin_client.post(reverse("sales:manual_create"), {"legal_name": "", "delivery": "pickup"})
    assert response.status_code == 400 and "Elegí un cliente" in response.content.decode()


def test_search_fragments(admin_client, variant):
    Customer.objects.create(legal_name="Lucía Pérez", tax_id="27111")
    assert "Lucía Pérez" in admin_client.get(reverse("sales:customer_search"), {"q": "luc"}).content.decode()
    assert "BUZ-1" in admin_client.get(reverse("sales:product_search"), {"q": "buz"}).content.decode()


def test_returns_screens(client, users_by_role, variant):
    o = order()
    SalesLine.objects.create(
        document=o,
        variant=variant,
        sku_snapshot="BUZ-1",
        description_snapshot="Buzo",
        quantity=1,
        unit_price=500,
    )
    client.force_login(users_by_role[DEPOSITO])
    response = client.post(reverse("sales:return_create", args=[o.pk]), {"receive_now": "1"})
    ret = SalesDocument.objects.get(doc_type="return")
    assert response["Location"] == reverse("sales:return_receive", args=[ret.pk])
    line = ret.lines.get()
    client.post(
        reverse("sales:return_receive", args=[ret.pk]),
        {f"qty_{line.pk}": "1", f"cond_{line.pk}": "resellable"},
    )
    assert ReturnInfo.objects.get(document=ret).received_at is not None
    assert "Falta ajustar" in client.get(reverse("sales:returns"), {"vista": "recibidas"}).content.decode()
    assert client.post(reverse("sales:return_adjusted", args=[ret.pk])).status_code == 403  # solo admin
    client.force_login(users_by_role[ADMIN])
    client.post(reverse("sales:return_adjusted", args=[ret.pk]))
    assert ReturnInfo.objects.get(document=ret).adjusted_in_contabilium


def test_orders_watch_task_runs(db):
    from apps.sales.tasks import orders_watch

    with (
        mock.patch("apps.sales.tasks.check_flex_due") as flex,
        mock.patch("apps.sales.tasks.check_manual_pending") as man,
    ):
        orders_watch(timestamp=0)
    assert flex.called and man.called


def test_channel_reference_set_by_integrations(db):
    assert tn_orders.upsert_order(tn_samples.order()).channel_reference == "TN #1234"
    doc, _ = ml_orders.upsert_order(ml_samples.order(order_id=7, pack_id=55))
    assert doc.channel_reference == "ML pack 55"


def test_detail_renders_real_channel_orders(admin_client, ml_api):
    from apps.integrations.adapters.mercadolibre.client import MLClient

    tn_doc = tn_orders.upsert_order(tn_samples.order())
    content = admin_client.get(reverse("sales:detail", args=[tn_doc.pk])).content.decode()
    assert "Av. Corrientes 1234 2B, Balvanera, CABA" in content
    stub_ml(ml_api)
    ml_doc = ml_orders.process_order(MLClient(sleep=lambda s: None), ml_samples.order())
    content = admin_client.get(reverse("sales:detail", args=[ml_doc.pk])).content.decode()
    assert "Av. Corrientes 1234, CABA" in content and "Despachar antes de" in content


def test_lines_summary_quantity_format(admin_client, some_orders):
    content = admin_client.get(reverse("sales:list")).content.decode()
    assert "1× ZAP-9" in content and "1.000×" not in content
