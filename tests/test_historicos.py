"""Lanzamiento · US-1 (R1.3): un pedido histórico es de solo lectura, no ensucia la operación y sí cuenta
en los reportes."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.alerts.models import Alert
from apps.catalog.models import Product, Variant
from apps.fulfillment import batches
from apps.integrations.models import Channel
from apps.inventory.models import StockLevel, StockMovement
from apps.inventory.services import default_warehouse
from apps.reports import queries
from apps.reports.filters import Filters
from apps.sales import manual, returns, states, sync, tasks
from apps.sales.models import SalesDocument, SalesLine, Shipment
from apps.wholesale import payments as wholesale_payments
from apps.wholesale.models import WholesaleOrder

pytestmark = pytest.mark.django_db

AR = ZoneInfo("America/Argentina/Buenos_Aires")
OCT = Filters(date(2026, 10, 1), date(2026, 10, 31))
ALL_STATES = list(states.LABELS)


def at(month, day, hour=12, year=2026):
    return datetime(year, month, day, hour, 0, tzinfo=AR)


def make_doc(channel="manual", status=states.NEW, historical=True, issued=None, total="1000", **kw):
    doc = SalesDocument.objects.create(
        channel=Channel.objects.get(code=channel),
        status=status,
        issued_at=issued or timezone.now() - timedelta(days=200),
        total=Decimal(total),
        is_historical=historical,
        **kw,
    )
    doc.channel_reference = f"{channel[:2].upper()} #{doc.number}"
    doc.save(update_fields=["channel_reference"])
    return doc


@pytest.fixture
def variant(db):
    return Variant.objects.create(product=Product.objects.create(name="Buzo"), sku="BUZ-H")


def _alert_count():
    return Alert.objects.count()


# ── Modelo ───────────────────────────────────────────────────────────────


def test_is_historical_defaults_to_false():
    assert make_doc(historical=False).is_historical is False
    assert SalesDocument._meta.get_field("is_historical").db_index is True


# ── Estados ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ALL_STATES)
def test_change_status_rejects_historical(status, admin_user):
    doc = make_doc(status=states.NEW)
    target = states.PREPARING if status == states.NEW else status
    for system in (False, True):
        with pytest.raises(states.TransitionNotAllowed, match="histórico"):
            states.change_status(doc, target, user=admin_user, system=system)
    doc.refresh_from_db()
    assert doc.status == states.NEW and doc.ready_at is None
    assert states.allowed_transitions(doc, admin_user) == []


def test_sync_does_not_touch_historical():
    doc = make_doc("tiendanube", status=states.AWAITING_PAYMENT, channel_status="cancelled/voided/unpacked")
    assert sync.sync_internal_status(doc, created=True) is None
    sync.on_document_created(doc)
    doc.refresh_from_db()
    assert doc.status == states.AWAITING_PAYMENT and doc.ready_at is None
    assert _alert_count() == 0


# ── Alertas ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ALL_STATES)
def test_no_alerts_for_historical_orders(status):
    # Manual sin cobrar ni facturar, de hace meses: un pedido vivo avisaría; un histórico no.
    make_doc("manual", status=status)
    flex = make_doc("mercadolibre", status=status)
    Shipment.objects.create(
        document=flex, method=Shipment.Method.ME_FLEX, dispatch_deadline=timezone.now() + timedelta(minutes=5)
    )
    assert tasks.check_manual_pending() == 0
    assert tasks.check_flex_due() == 0
    assert _alert_count() == 0


def test_same_orders_do_alert_when_not_historical():
    """Control: sin la marca los mismos pedidos sí avisan."""
    make_doc("manual", historical=False)
    flex = make_doc("mercadolibre", historical=False)
    Shipment.objects.create(
        document=flex, method=Shipment.Method.ME_FLEX, dispatch_deadline=timezone.now() + timedelta(minutes=5)
    )
    assert tasks.check_manual_pending() == 2  # sin cobrar y sin facturar
    assert tasks.check_flex_due() == 1


def test_no_new_order_or_stock_alert_for_historical(variant):
    doc = make_doc("tiendanube", status=states.NEW)
    SalesLine.objects.create(
        document=doc,
        variant=variant,
        sku_snapshot="BUZ-H",
        description_snapshot="Buzo",
        quantity=5,
        unit_price=1,
    )
    states.emit_new_order(doc)
    sync.after_created_complete(doc)
    sync.check_stock(doc)
    assert _alert_count() == 0


def test_unpaid_wholesale_historical_does_not_expire_nor_remind(admin_user):
    doc = make_doc("mayorista", status=states.AWAITING_PAYMENT)
    WholesaleOrder.objects.create(
        document=doc,
        placed_by=admin_user,
        payment_method=WholesaleOrder.PaymentMethod.TRANSFER,
        expires_at=timezone.now() - timedelta(days=1),
    )
    assert wholesale_payments.expire_orders() == {"expired": 0, "with_receipt": 0}
    assert wholesale_payments.send_reminders() == 0
    doc.refresh_from_db()
    assert doc.status == states.AWAITING_PAYMENT
    assert _alert_count() == 0


# ── Stock ────────────────────────────────────────────────────────────────


def test_historical_never_reserves_stock(variant, admin_user):
    doc = make_doc("mayorista", status=states.NEW)
    WholesaleOrder.objects.create(
        document=doc, placed_by=admin_user, payment_method=WholesaleOrder.PaymentMethod.CASH
    )
    wholesale_payments.change_line_reservation(doc, variant, 3, user=admin_user)
    assert not StockMovement.objects.exists()
    assert not StockLevel.objects.filter(variant=variant, reserved__gt=0).exists()
    assert default_warehouse() is not None


# ── Lista, colas y acciones ──────────────────────────────────────────────


@pytest.fixture
def pair():
    live = make_doc("manual", historical=False, issued=timezone.now(), channel_reference="")
    old = make_doc("manual", historical=True, issued=timezone.now() - timedelta(days=300))
    Shipment.objects.create(document=live, method=Shipment.Method.CARRIER)
    Shipment.objects.create(document=old, method=Shipment.Method.CARRIER)
    return live, old


def test_order_list_hides_historical_unless_asked(admin_client, pair):
    live, old = pair
    page = admin_client.get(reverse("sales:list")).content.decode()
    assert reverse("sales:detail", args=[live.pk]) in page
    assert reverse("sales:detail", args=[old.pk]) not in page
    assert "Incluir históricos" in page
    page = admin_client.get(reverse("sales:list") + "?historicos=1").content.decode()
    assert reverse("sales:detail", args=[old.pk]) in page and reverse("sales:detail", args=[live.pk]) in page
    assert "histórico" in page


def test_historical_detail_is_read_only(admin_client, pair):
    _, old = pair
    response = admin_client.get(reverse("sales:detail", args=[old.pk]))
    page = response.content.decode()
    assert response.status_code == 200
    assert "Pedido histórico importado de TiendaQuick: solo lectura" in page
    assert response.context["transitions"] == []
    assert reverse("sales:status", args=[old.pk]) not in page
    assert reverse("sales:manual_edit", args=[old.pk, "cobro"]) not in page
    assert reverse("sales:return_create", args=[old.pk]) not in page


def test_historical_actions_are_refused(admin_client, pair):
    _, old = pair
    admin_client.post(reverse("sales:status", args=[old.pk]), {"to": states.PREPARING}, follow=True)
    admin_client.post(
        reverse("sales:manual_edit", args=[old.pk, "cobro"]), {"paid": "1", "payment_method": "cash"}
    )
    admin_client.post(reverse("sales:return_create", args=[old.pk]), {"receive_now": "0"})
    old.refresh_from_db()
    assert old.status == states.NEW and not old.payments.exists() and not old.related_documents.exists()
    with pytest.raises(manual.ManualOrderError):
        manual.update_invoice(old, invoiced=True, number="A-1", user=pair_user(admin_client))
    with pytest.raises(returns.ReturnError):
        returns.create_expected(old, user=pair_user(admin_client))


def pair_user(client):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.get(email="admin@test.local")


def test_historical_not_in_preparation_or_dispatch_queues(admin_client, pair, admin_user):
    live, old = pair
    assert list(batches.preparable_orders()) == [live]
    page = admin_client.get(reverse("sales:prepare")).content.decode()
    assert live.channel_reference in page or str(live.number) in page
    assert old.channel_reference not in page
    # Aunque alguien mande el id a mano, la tanda lo deja afuera y no le cambia el estado.
    batch, excluded = batches.create_batch([old.pk], user=admin_user)
    assert batch is None and "histórico" in excluded[0].reason
    old.refresh_from_db()
    assert old.status == states.NEW
    for status in (states.PREPARING, states.READY, states.READY_FOR_PICKUP):
        SalesDocument.objects.filter(pk=old.pk).update(status=status)
    page = admin_client.get(reverse("sales:dispatch")).content.decode()
    assert old.channel_reference not in page


def test_historical_not_in_return_order_search(admin_client, pair):
    live, old = pair
    SalesDocument.objects.filter(pk=live.pk).update(channel_reference="PEDIDO-VIVO")
    SalesDocument.objects.filter(pk=old.pk).update(channel_reference="PEDIDO-VIEJO")
    page = admin_client.get(reverse("sales:returns") + "?pedido=PEDIDO").content.decode()
    assert "PEDIDO-VIVO" in page and "PEDIDO-VIEJO" not in page


# ── Reportes ─────────────────────────────────────────────────────────────


def test_reports_count_historical_orders(variant):
    live = make_doc("tiendanube", historical=False, issued=at(10, 5), total="1000")
    old = make_doc("tiendanube", historical=True, issued=at(10, 6), total="4000")
    for doc in (live, old):
        SalesLine.objects.create(
            document=doc, variant=variant, sku_snapshot="BUZ-H", description_snapshot="Buzo",
            quantity=2, unit_price=Decimal(doc.total) / 2,
        )  # fmt: skip
    k = queries.kpis(OCT)["by_key"]
    assert k["gross"]["value"] == Decimal("5000.00") and k["orders"]["value"] == 2
    assert k["units"]["value"] == 4
    assert queries.sales(OCT).count() == 2
    assert sum(queries.sales_by_day(OCT)["series"][0]["values"]) == Decimal("5000.00")


def test_reports_screens_load_with_historical(admin_client, variant):
    make_doc("mercadolibre", historical=True, issued=at(10, 6), status=states.AWAITING_PAYMENT)
    qs = "?periodo=rango&desde=2026-10-01&hasta=2026-10-31"
    for name in ("summary", "sales", "products", "operations", "wholesale"):
        assert admin_client.get(reverse(f"reports:{name}") + qs).status_code == 200


def test_operation_reports_ignore_historical():
    """Un histórico sin ready_at/dispatched_at no cuenta como demora ni como pendiente."""
    old = make_doc("mercadolibre", historical=True, issued=at(10, 3), status=states.NEW)
    Shipment.objects.create(document=old, method="me_flex", dispatch_deadline=at(10, 4))
    despachado = make_doc(
        "tiendanube", historical=True, issued=at(10, 3), status=states.DISPATCHED, dispatched_at=at(10, 9)
    )
    Shipment.objects.create(document=despachado, method="carrier")
    make_doc("manual", historical=True, issued=at(10, 3))
    flex = queries.flex_on_time(OCT, now=at(10, 20))
    assert flex["total"] == 0 and flex["late"] == []
    assert queries.dispatch_times(OCT)["overall"]["n"] == 0
    assert queries.manual_pending(today=date(2026, 11, 14))["count"] == 0


def test_year_over_year_comparison(variant):
    make_doc("tiendanube", historical=False, issued=at(10, 5), total="3000")
    make_doc("tiendanube", historical=True, issued=at(10, 5, year=2025), total="1000")
    make_doc("tiendanube", historical=True, issued=at(10, 20, year=2025), total="1000")
    make_doc("tiendanube", historical=True, issued=at(9, 20, year=2025), total="9999")  # fuera del período
    k = queries.kpis(OCT)
    gross = k["by_key"]["gross"]
    assert gross["value"] == Decimal("3000.00") and gross["year_ago"] == Decimal("2000.00")
    assert gross["year_change"] == 50.0 and gross["year_good"] is True
    assert k["by_key"]["orders"]["year_ago"] == 2
    assert k["year"].start == date(2025, 10, 1) and k["year"].end == date(2025, 10, 31)


def test_previous_year_handles_leap_day():
    f = Filters(date(2024, 2, 29), date(2024, 3, 1))
    y = f.previous_year()
    assert (y.start, y.end) == (date(2023, 2, 28), date(2023, 3, 1))


def test_summary_page_shows_year_comparison(admin_client):
    make_doc("tiendanube", historical=True, issued=at(10, 5, year=2025), total="1000")
    page = admin_client.get(
        reverse("reports:summary") + "?periodo=rango&desde=2026-10-01&hasta=2026-10-31"
    ).content.decode()
    assert "año anterior" in page
