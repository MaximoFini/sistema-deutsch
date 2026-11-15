"""M7 · Reportes: datos nuevos, backfills, consultas, pantallas, Excel y permisos (design §7)."""

import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import ADMIN, DEPOSITO, VENDEDOR, VENTAS
from apps.audit import services as audit
from apps.catalog.models import Product, Variant
from apps.conversations.models import Question
from apps.customers.models import Customer
from apps.integrations import credentials, ratelimit
from apps.integrations.adapters.mercadolibre import orders as ml_orders
from apps.integrations.adapters.mercadolibre import shipments as ml_shipments
from apps.integrations.adapters.mercadolibre.client import MLClient
from apps.integrations.models import Channel
from apps.inventory import services as inventory
from apps.inventory.models import StockLevel, StockMovement
from apps.reports import backfill, filters, queries, tasks
from apps.reports.aggregates import Percentile
from apps.reports.filters import Filters
from apps.sales import manual, states
from apps.sales.models import Payment, ReturnInfo, SalesDocument, SalesLine, Shipment
from tests import ml_samples as S

pytestmark = pytest.mark.django_db
AR = ZoneInfo("America/Argentina/Buenos_Aires")
API = "https://api.mercadolibre.com"
OCT = Filters(date(2026, 10, 1), date(2026, 10, 31))  # anterior: 31/08 al 30/09


def at(month, day, hour=12, minute=0, year=2026):
    return datetime(year, month, day, hour, minute, tzinfo=AR)


def make_order(channel="tiendanube", issued=None, total="1000", status=states.NEW, lines=(), **kw):
    doc = SalesDocument.objects.create(
        channel=Channel.objects.get(code=channel),
        status=status,
        issued_at=issued or at(10, 10),
        total=Decimal(total),
        channel_reference=kw.pop("ref", f"{channel} {SalesDocument.objects.count() + 1}"),
        **kw,
    )
    for variant, qty, price, fee in lines:
        SalesLine.objects.create(
            document=doc,
            variant=variant,
            sku_snapshot=variant.sku if variant else "ML-SKU-RARO",
            description_snapshot="Producto",
            quantity=Decimal(qty),
            unit_price=Decimal(price),
            channel_fee=None if fee is None else Decimal(fee),
        )
    return doc


@pytest.fixture
def variants(db):
    buzo = Product.objects.create(name="Buzo Canguro")
    remera = Product.objects.create(name="Remera Lisa")
    return {
        "buzo_m": Variant.objects.create(
            product=buzo, sku="BUZ-M", attributes={"Talle": "M", "Color": "Negro"}
        ),
        "buzo_l": Variant.objects.create(
            product=buzo, sku="BUZ-L", attributes={"talle": "L", "color": "Negro"}
        ),
        "remera": Variant.objects.create(product=remera, sku="REM-U", attributes={"Color": "Blanco"}),
    }


# ── T1 · permiso y campos ────────────────────────────────────────────────


def test_permission_only_for_admin(roles):
    holders = Group.objects.filter(
        permissions__codename="view_reports", permissions__content_type__app_label="reports"
    )
    assert list(holders.values_list("name", flat=True)) == [ADMIN]


def test_roles_sync_on_last_project_app():
    from apps.accounts.roles import _last_project_app_label

    assert _last_project_app_label() == "reports"


def test_new_fields_default_empty(variants):
    doc = make_order(lines=[(variants["buzo_m"], 1, 1000, None)])
    line = doc.lines.get()
    assert doc.ready_at is None and doc.dispatched_at is None and doc.net_pending is False
    assert line.channel_fee is None
    assert Shipment.objects.create(document=doc, method="carrier").seller_cost is None


# ── T2 · llenado hacia adelante ──────────────────────────────────────────


def test_change_status_sets_ready_and_dispatched_first_time_only(users_by_role):
    doc = make_order(channel="manual", status=states.AWAITING_PAYMENT)
    Shipment.objects.create(document=doc, method=Shipment.Method.PICKUP)
    states.change_status(doc, states.NEW, system=True)
    doc.refresh_from_db()
    first_ready = doc.ready_at
    assert first_ready is not None
    dep = users_by_role[DEPOSITO]
    for to in (states.PREPARING, states.NEW, states.PREPARING, states.READY, states.READY_FOR_PICKUP):
        states.change_status(doc, to, user=dep)
    doc.refresh_from_db()
    assert doc.ready_at == first_ready  # volver a Nuevo no la cambia
    first_out = doc.dispatched_at
    assert first_out is not None
    states.change_status(doc, states.READY, user=dep)
    states.change_status(doc, states.READY_FOR_PICKUP, user=dep)
    states.change_status(doc, states.DELIVERED, user=dep)
    doc.refresh_from_db()
    assert doc.dispatched_at == first_out


def test_system_dispatch_uses_channel_shipped_date():
    doc = make_order(channel="mercadolibre", issued=timezone.now() - timedelta(days=3))
    shipped = timezone.now() - timedelta(days=2)
    Shipment.objects.create(document=doc, method=Shipment.Method.ME_FLEX, shipped_at=shipped)
    states.change_status(doc, states.DISPATCHED, system=True)
    doc.refresh_from_db()
    assert doc.dispatched_at == shipped


def test_delivered_without_dispatch_data_stays_empty():
    doc = make_order(channel="mercadolibre")
    Shipment.objects.create(document=doc, method=Shipment.Method.ME_FLEX)
    states.change_status(doc, states.DELIVERED, system=True)
    doc.refresh_from_db()
    assert doc.dispatched_at is None


def test_manual_order_is_ready_on_create(users_by_role, variants):
    customer = Customer.objects.create(legal_name="Cliente")
    doc = manual.create_manual_order(
        customer=customer,
        lines=[manual.ManualLine(variant=variants["buzo_m"], quantity=1, unit_price=Decimal("1000"))],
        delivery=Shipment.Method.PICKUP,
        user=users_by_role[ADMIN],
    )
    assert doc.ready_at == doc.issued_at


def test_inventory_movements_store_on_hand_after(variants):
    wh = inventory.default_warehouse()
    v = variants["buzo_m"]
    assert inventory.apply_sync_level(v, wh, 5).on_hand_after == 5
    assert inventory.apply_sync_level(v, wh, 2).on_hand_after == 2
    assert inventory.change_reserved(v, wh, 1).on_hand_after is None  # no cambia el físico


def save_cred():
    credentials.save(
        "mercadolibre",
        {
            "access_token": "ACCESS-1",
            "refresh_token": "REFRESH-1",
            "expires_at": (timezone.now() + timedelta(hours=5)).isoformat(),
            "user_id": S.SELLER,
            "scope": "offline_access read write",
        },
    )


@pytest.fixture
def api(db):
    save_cred()
    with respx.mock(base_url=API, assert_all_called=False) as m:
        yield m


@pytest.fixture
def ml_variants(db):
    p = Product.objects.create(name="Buzo")
    return [Variant.objects.create(product=p, sku=s) for s in ("BUZ-001-M-NEG", "BUZ-001-L-NEG")]


def ml_order(sale_fee=5400, quantity=2, **kw):
    data = S.order(**kw)
    data["order_items"][0]["quantity"] = quantity
    if sale_fee is not None:
        data["order_items"][0]["sale_fee"] = sale_fee
    return data


def stub_shipment(api, costs_status=200, cost=3200.5):
    api.get("/shipments/40001").mock(return_value=httpx.Response(200, json=S.shipment()))
    api.get("/shipments/40001/sla").mock(
        return_value=httpx.Response(200, json={"expected_date": "2026-11-13T12:00:00.000-03:00"})
    )
    return api.get("/shipments/40001/costs").mock(
        return_value=httpx.Response(
            costs_status,
            json={"receiver": {"cost": 0}, "senders": [{"user_id": int(S.SELLER), "cost": cost}]},
        )
    )


def test_ml_upsert_saves_fee_per_line_and_pending_until_shipping_cost(api, ml_variants):
    doc, _ = ml_orders.upsert_order(ml_order())
    line = doc.lines.get()
    assert line.channel_fee == Decimal("10800.00")  # 5400 × 2
    doc.refresh_from_db()
    assert doc.net_pending  # el envío 40001 todavía no tiene costo
    assert doc.ready_at == doc.issued_at  # entró pagado
    costs = stub_shipment(api)
    shipment = ml_shipments.refresh(MLClient(sleep=lambda s: None), 40001)
    assert costs.called and shipment.seller_cost == Decimal("3200.50")
    doc.refresh_from_db()
    assert not doc.net_pending
    assert all(call.request.method == "GET" for call in api.calls)  # solo lecturas a ML


def test_ml_without_sale_fee_is_pending(api, ml_variants):
    doc, _ = ml_orders.upsert_order(ml_order(sale_fee=None, shipping_id=None))
    assert doc.lines.get().channel_fee is None
    doc.refresh_from_db()
    assert doc.net_pending


def test_ml_without_shipping_is_complete_with_fee(api, ml_variants):
    doc, _ = ml_orders.upsert_order(ml_order(shipping_id=None))
    doc.refresh_from_db()
    assert not doc.net_pending


def test_ml_costs_failure_does_not_break_sync(api, ml_variants):
    ml_orders.upsert_order(ml_order())
    stub_shipment(api, costs_status=500)
    shipment = ml_shipments.refresh(MLClient(sleep=lambda s: None), 40001)
    assert shipment is not None and shipment.seller_cost is None
    assert SalesDocument.objects.get().net_pending


def test_ml_unpaid_order_ready_when_paid(api, ml_variants):
    data = ml_order(status="payment_required", shipping_id=None)
    data["payments"] = []
    doc, _ = ml_orders.upsert_order(data)
    doc.refresh_from_db()
    assert doc.status == states.AWAITING_PAYMENT and doc.ready_at is None
    states.change_status(doc, states.NEW, system=True)
    doc.refresh_from_db()
    assert doc.ready_at is not None


# ── T3 · backfills ───────────────────────────────────────────────────────


def _audit_status(doc, before, after, when):
    with mock.patch("django.utils.timezone.now", return_value=when):  # la auditoría es inmutable
        audit.record(None, "order.status_changed", doc, before={"estado": before}, after={"estado": after})


def test_backfill_timestamps_from_audit_and_fallbacks():
    paid_later = make_order(status=states.DISPATCHED, issued=at(10, 1, 9))
    _audit_status(paid_later, states.AWAITING_PAYMENT, states.NEW, at(10, 1, 15))
    _audit_status(paid_later, states.NEW, states.PREPARING, at(10, 2, 9))
    _audit_status(paid_later, states.PREPARING, states.NEW, at(10, 2, 10))  # volvió a Nuevo: no cuenta
    _audit_status(paid_later, states.READY, states.DISPATCHED, at(10, 3, 11))
    no_audit = make_order(
        status=states.READY_FOR_PICKUP, issued=at(10, 5, 9), status_changed_at=at(10, 6, 18)
    )
    back_to_new = make_order(status=states.NEW, issued=at(10, 7, 9))
    _audit_status(back_to_new, states.PREPARING, states.NEW, at(10, 8, 9))
    never_paid = make_order(status=states.CANCELLED, issued=at(10, 9, 9))
    _audit_status(never_paid, states.NEW, states.AWAITING_PAYMENT, at(10, 9, 9))
    delivered = make_order(channel="mercadolibre", status=states.DELIVERED, issued=at(10, 10, 9))
    Shipment.objects.create(document=delivered, method="me_flex", shipped_at=at(10, 11, 8))
    already = make_order(status=states.NEW, issued=at(10, 12, 9), ready_at=at(10, 12, 10))

    stats = backfill.backfill_timestamps()
    for d in (paid_later, no_audit, back_to_new, never_paid, delivered, already):
        d.refresh_from_db()
    assert paid_later.ready_at == at(10, 1, 15) and paid_later.dispatched_at == at(10, 3, 11)
    assert no_audit.ready_at == at(10, 5, 9) and no_audit.dispatched_at == at(10, 6, 18)
    assert back_to_new.ready_at == at(10, 7, 9)
    assert never_paid.ready_at is None and never_paid.dispatched_at is None
    assert delivered.dispatched_at == at(10, 11, 8)
    assert already.ready_at == at(10, 12, 10)  # no pisa lo que ya estaba
    assert stats == {"ready_at": 4, "dispatched_at": 3}
    assert backfill.backfill_timestamps() == {"ready_at": 0, "dispatched_at": 0}  # idempotente


def test_backfill_stock_rebuilds_backwards(variants):
    wh = inventory.default_warehouse()
    v = variants["buzo_m"]
    for qty in (5, 0, 3, 0, 4):
        inventory.apply_sync_level(v, wh, qty)
    inventory.change_reserved(v, wh, 2)
    StockMovement.objects.update(on_hand_after=None)
    assert backfill.backfill_stock() == 5
    afters = list(
        StockMovement.objects.filter(affects="on_hand")
        .order_by("created_at", "id")
        .values_list("on_hand_after", flat=True)
    )
    assert afters == [5, 0, 3, 0, 4]
    assert StockMovement.objects.get(affects="reserved").on_hand_after is None
    assert backfill.backfill_stock() == 0  # segunda corrida: nada que cambiar


def _pending_ml_doc(api, ml_variants):
    """Una venta de ML importada antes de M7: sin comisión y sin costo de envío."""
    doc, _ = ml_orders.upsert_order(ml_order(sale_fee=None))
    Shipment.objects.create(document=doc, external_id="40001", method="me_flex", status="ready_to_ship")
    doc.refresh_from_db()
    assert doc.net_pending
    return doc


def test_backfill_ml_fees_completes_and_respects_rate_limit(api, ml_variants):
    doc = _pending_ml_doc(api, ml_variants)
    api.get("/orders/2000001").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json=ml_order())]
    )
    api.get("/shipments/40001/costs").mock(
        return_value=httpx.Response(200, json={"senders": [{"cost": 1500}]})
    )
    sleeps = []
    with mock.patch("apps.integrations.http.ratelimit.acquire", wraps=ratelimit.acquire) as acquire:
        stats = backfill.backfill_ml_fees(MLClient(sleep=sleeps.append), batch_size=50)
    assert stats["completed"] == 1 and not stats["errors"]
    assert sleeps == [1.0]  # el 429 se respetó con Retry-After
    assert acquire.call_count == 3 and {c.args[0] for c in acquire.call_args_list} == {"mercadolibre"}
    doc.refresh_from_db()
    assert not doc.net_pending
    assert doc.lines.get().channel_fee == Decimal("10800.00")
    assert doc.shipments.get().seller_cost == Decimal("1500.00")
    assert all(call.request.method == "GET" for call in api.calls)
    assert backfill.backfill_ml_fees(MLClient(sleep=sleeps.append))["completed"] == 0  # nada pendiente


def test_backfill_ml_fees_error_keeps_pending_and_continues(api, ml_variants):
    doc = _pending_ml_doc(api, ml_variants)
    api.get("/orders/2000001").mock(return_value=httpx.Response(404, json={"message": "not found"}))
    stats = backfill.backfill_ml_fees(MLClient(sleep=lambda s: None))
    assert stats["completed"] == 0 and len(stats["errors"]) == 1
    doc.refresh_from_db()
    assert doc.net_pending


def test_backfill_ml_fees_stops_when_disconnected(api, ml_variants):
    _pending_ml_doc(api, ml_variants)
    from apps.integrations.adapters.mercadolibre import auth

    with mock.patch.object(auth, "get_access_token", side_effect=auth.TokenRevoked("revocado")):
        stats = backfill.backfill_ml_fees(MLClient(sleep=lambda s: None))
    assert stats["stopped"].startswith("TokenRevoked")


def test_ml_fees_task_skips_when_not_connected(db):
    assert tasks.run_ml_fees() is None


def test_ml_fees_enqueued_after_migrate(api, ml_variants, in_memory_queue):
    _pending_ml_doc(api, ml_variants)
    backfill.enqueue_ml_fees_after_migrate(sender=None)
    assert [j["task_name"] for j in in_memory_queue.jobs.values()] == ["apps.reports.tasks.reports_ml_fees"]
    backfill.enqueue_ml_fees_after_migrate(sender=None)  # el queueing_lock evita duplicados
    assert len(in_memory_queue.jobs) == 1


def test_ml_fees_task_is_daily():
    from procrastinate.contrib.django import app

    periodic = [
        t for t in app.periodic_registry.periodic_tasks.values() if t.task.name.endswith("reports_ml_fees")
    ]
    assert periodic and periodic[0].cron == "30 5 * * *"


def test_backfill_command_modes(variants):
    make_order(status=states.NEW, issued=at(10, 1))
    out = io.StringIO()
    call_command("reports_backfill", "timestamps", stdout=out)
    assert "1 pedidos" in out.getvalue()
    call_command("reports_backfill", "stock", stdout=out)
    assert "movimientos de stock" in out.getvalue()
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="no está conectado"):
        call_command("reports_backfill", "ml_fees", stdout=out)


# ── T4 · filtros, indicadores y series ───────────────────────────────────


def test_filters_presets_and_previous_period():
    today = date(2026, 11, 14)
    f = filters.from_request(QueryDict(""), today=today)
    assert (f.start, f.end, f.preset) == (date(2026, 10, 16), today, "30d")
    f = filters.from_request(QueryDict("periodo=mes_anterior"), today=today)
    assert (f.start, f.end) == (date(2026, 10, 1), date(2026, 10, 31))
    assert (f.previous().start, f.previous().end) == (date(2026, 8, 31), date(2026, 9, 30))
    assert filters.from_request(QueryDict("periodo=hoy"), today=today).days == 1
    assert filters.from_request(QueryDict("periodo=7d"), today=today).start == date(2026, 11, 8)
    assert filters.from_request(QueryDict("periodo=mes"), today=today).start == date(2026, 11, 1)


def test_filters_invalid_values_are_fixed_and_warned():
    today = date(2026, 11, 14)
    f = filters.from_request(
        QueryDict("periodo=rango&desde=2026-10-31&hasta=2026-10-01&canal=xx"), today=today
    )
    assert (f.start, f.end, f.channel) == (date(2026, 10, 1), date(2026, 10, 31), "")
    assert len(f.warnings) == 2
    f = filters.from_request(QueryDict("desde=2020-01-01&hasta=2026-11-14"), today=today)
    assert f.days == 730 and "2 años" in f.warnings[0]
    f = filters.from_request(QueryDict("periodo=rango&desde=basura"), today=today)
    assert f.preset == "30d" and f.warnings
    assert filters.from_request(QueryDict("periodo=xyz"), today=today).warnings


def test_kpis_exact_with_previous_period(variants):
    v = variants["buzo_m"]
    # Período (octubre)
    make_order("tiendanube", at(10, 5), "10000", lines=[(v, 2, 5000, None)])
    ml = make_order("mercadolibre", at(10, 6), "20000", lines=[(v, 1, 20000, "2400")], net_pending=False)
    Shipment.objects.create(document=ml, method="me_flex", seller_cost=Decimal("1600"))
    make_order("mercadolibre", at(10, 7), "5000", lines=[(v, 1, 5000, None)], net_pending=True)
    make_order("tiendanube", at(10, 8), "99999", status=states.CANCELLED, lines=[(v, 9, 11111, None)])
    make_order("manual", at(10, 9), "5", status=states.CANCELLED)
    make_order("manual", at(9, 9), "5", status=states.CANCELLED)
    # Período anterior
    make_order("manual", at(9, 15), "7000", lines=[(v, 1, 7000, None)])
    make_order("manual", at(8, 30), "1", lines=[(v, 1, 1, None)])  # antes del período anterior
    ret = SalesDocument.objects.create(
        channel=Channel.objects.get(code="tiendanube"), doc_type="return", issued_at=at(10, 9), total=0
    )
    ReturnInfo.objects.create(document=ret, source="manual", received_at=at(10, 10))

    k = queries.kpis(OCT)["by_key"]
    assert k["gross"]["value"] == Decimal("35000.00") and k["gross"]["previous"] == Decimal("7000.00")
    assert k["net"]["value"] == Decimal("31000.00")  # 35000 − 2400 − 1600
    assert k["orders"]["value"] == 3 and k["orders"]["previous"] == 1
    assert k["units"]["value"] == 4  # el cancelado no suma
    assert k["ticket"]["value"] == Decimal("11666.67")
    assert k["cancelled"]["value"] == 2 and k["cancelled"]["change"] == 100.0
    assert k["cancelled"]["good"] is False  # más cancelados es malo: rojo
    assert k["returns"]["value"] == 1
    assert k["gross"]["change"] == 400.0 and k["gross"]["good"] is True
    assert queries.kpis(OCT)["net_pending"] == 1
    tn_only = queries.kpis(Filters(OCT.start, OCT.end, "tiendanube"))["by_key"]
    assert tn_only["gross"]["value"] == Decimal("10000.00") and tn_only["net"]["value"] == Decimal("10000.00")


def test_timezone_midnight_boundary():
    make_order(issued=at(10, 31, 23, 30), total="100")  # 02:30 UTC del 1/11: es octubre en Argentina
    make_order(issued=at(11, 1, 0, 30), total="200")  # ya es noviembre
    make_order(issued=at(10, 1, 0, 10), total="400")
    assert queries.kpis(OCT)["by_key"]["gross"]["value"] == Decimal("500.00")
    by_day = queries.sales_by_day(OCT)
    tn = by_day["series"][0]
    assert by_day["bucket"] == "day" and len(by_day["labels"]) == 31
    assert tn["values"][0] == 400.0 and tn["values"][30] == 100.0
    heat = queries.heatmap(OCT)["matrix"]
    assert heat[5][23] == 1  # 31/10/2026 es sábado, 23 h
    assert heat[3][0] == 1  # 1/10/2026 es jueves, 0 h


def test_sales_by_day_buckets_share_and_empty():
    long = Filters(date(2025, 1, 1), date(2026, 10, 31))
    assert queries.bucket_for(long) == "month" and len(queries.sales_by_day(long)["labels"]) == 22
    assert queries.bucket_for(Filters(date(2026, 1, 1), date(2026, 10, 31))) == "week"
    assert queries.sales_by_day(OCT)["empty"] and queries.channel_share(OCT) == []
    make_order("tiendanube", at(10, 2), "300")
    make_order("mercadolibre", at(10, 2), "100")
    share = queries.channel_share(OCT)
    assert [(s["code"], s["pct"]) for s in share] == [("tiendanube", 75.0), ("mercadolibre", 25.0)]
    assert share[0]["color"] == queries.CHANNEL_COLORS["tiendanube"]


# ── T5 · tabla de ventas y productos ─────────────────────────────────────


@pytest.fixture
def sales_data(variants):
    v = variants
    a = make_order(
        "tiendanube",
        at(10, 1, 10),
        "10500",
        lines=[(v["buzo_m"], 2, 3000, None), (v["remera"], 1, 4000, None)],
    )
    b = make_order("mercadolibre", at(10, 8, 10), "9000", lines=[(v["buzo_l"], 1, 9000, "1000")])
    Shipment.objects.create(document=b, method="me_flex", seller_cost=Decimal("500"))
    c = make_order("mercadolibre", at(10, 20, 10), "2000", lines=[(None, 1, 2000, "200")])
    make_order("manual", at(10, 21), "5000", status=states.CANCELLED, lines=[(v["buzo_m"], 5, 1000, None)])
    return a, b, c


def test_sales_table_by_channel_uses_order_totals(sales_data):
    t = queries.sales_table(OCT, "canal")
    rows = {r["clave"]: r for r in t["rows"]}
    assert rows["Tiendanube"]["bruto"] == Decimal("10500.00") and rows["Tiendanube"]["unidades"] == 3
    assert rows["Mercado Libre"]["bruto"] == Decimal("11000.00")
    assert rows["Mercado Libre"]["neto"] == Decimal("9300.00")  # 11000 − 1000 − 200 − 500
    assert rows["Mercado Libre"]["precio"] == Decimal("5500.00")
    assert t["totals"]["pedidos"] == 3 and t["totals"]["bruto"] == Decimal("21500.00")
    assert [r["clave"] for r in t["rows"]] == ["Mercado Libre", "Tiendanube"]  # por bruto, de mayor a menor


def test_sales_table_by_product_variant_size_color(sales_data):
    prod = {r["clave"]: r for r in queries.sales_table(OCT, "producto")["rows"]}
    assert prod["Buzo Canguro"]["unidades"] == 3 and prod["Buzo Canguro"]["bruto"] == Decimal("15000.00")
    assert prod["Buzo Canguro"]["neto"] == Decimal("14000.00")  # solo comisión; el envío no se reparte
    assert prod["Sin vincular (ML-SKU-RARO)"]["bruto"] == Decimal("2000.00")
    var = {r["clave"]: r for r in queries.sales_table(OCT, "variante")["rows"]}
    assert var["BUZ-M"]["talle"] == "M" and var["BUZ-M"]["color"] == "Negro" and var["BUZ-M"]["unidades"] == 2
    assert "Sin vincular (ML-SKU-RARO)" in var
    talle = {r["clave"]: r["unidades"] for r in queries.sales_table(OCT, "talle")["rows"]}
    assert talle == {"M": 2, "L": 1, "Sin talle": 1, "Sin vincular (ML-SKU-RARO)": 1}
    color = {r["clave"]: r["unidades"] for r in queries.sales_table(OCT, "color")["rows"]}
    assert color == {"Negro": 3, "Blanco": 1, "Sin vincular (ML-SKU-RARO)": 1}
    t = queries.sales_table(OCT, "producto")
    assert t["totals"]["pedidos"] == 3  # un pedido con dos productos cuenta una vez
    assert t["totals"]["bruto"] == Decimal("21000.00")  # suma de líneas (sin envío)


def test_sales_table_time_groups_and_sorting(sales_data):
    days = queries.sales_table(OCT, "dia")
    assert [r["clave"] for r in days["rows"]] == ["01/10/2026", "08/10/2026", "20/10/2026"]
    weeks = queries.sales_table(OCT, "semana")
    assert weeks["rows"][0]["clave"] == "Semana del 28/09/2026"
    months = queries.sales_table(OCT, "mes")
    assert months["rows"][0]["clave"] == "Octubre 2026" and months["rows"][0]["pedidos"] == 3
    asc = queries.sales_table(OCT, "variante", "unidades")["rows"]
    assert asc[-1]["clave"] == "BUZ-M"
    assert queries.sales_table(OCT, "variante", "-precio")["rows"][0]["clave"] == "BUZ-L"
    assert queries.sales_table(OCT, "nada", "cualquiera")["group_by"] == "canal"


def test_top_products_top_50_with_stock(variants):
    product = Product.objects.create(name="Medias")
    many = Variant.objects.bulk_create([Variant(product=product, sku=f"MED-{i:02d}") for i in range(55)])
    wh = inventory.default_warehouse()
    inventory.apply_sync_level(many[54], wh, 7)
    inventory.change_reserved(many[54], wh, 2)
    lines = [(v, i + 1, 100, None) for i, v in enumerate(many)]
    make_order("tiendanube", at(10, 3), "1", lines=lines)
    top = queries.top_products(OCT)
    assert len(top["variants"]) == 50
    assert top["variants"][0]["clave"] == "MED-54" and top["variants"][0]["stock"] == 5  # 7 − 2 reservadas
    assert top["products"][0]["clave"] == "Medias" and top["products"][0]["stock"] == 5
    assert queries.top_products(OCT, by="bruto")["by"] == "bruto"


def _movement(variant, qty, when):
    m = inventory.apply_sync_level(variant, inventory.default_warehouse(), qty)
    StockMovement.objects.filter(pk=m.pk).update(created_at=when)


def test_stockouts_counts_times_and_days(variants):
    v, other = variants["buzo_m"], variants["buzo_l"]
    _movement(v, 3, at(9, 20))
    _movement(v, 0, at(10, 2, 12))  # 1.ª vez
    _movement(v, 2, at(10, 4, 12))  # 2 días sin stock
    _movement(v, 0, at(10, 10, 12))  # 2.ª vez
    _movement(v, 1, at(10, 11, 0))  # 0,5 días
    _movement(other, 1, at(9, 20))
    _movement(other, 0, at(10, 5))  # una sola vez: no entra con el mínimo de 2
    make_order("tiendanube", at(10, 3), "1", lines=[(v, 4, 100, None)])
    out = queries.stockouts(OCT, min_times=2)
    assert [r["sku"] for r in out["rows"]] == ["BUZ-M"]
    row = out["rows"][0]
    assert row["veces"] == 2 and row["dias_sin_stock"] == 2.5 and row["vendidas"] == 4 and row["stock"] == 1
    assert out["history_since"] == date(2026, 9, 20)
    assert {r["sku"] for r in queries.stockouts(OCT, min_times=1)["rows"]} == {"BUZ-M", "BUZ-L"}


def test_stockouts_ignores_movements_without_history(variants):
    _movement(variants["buzo_m"], 2, at(9, 1))
    _movement(variants["buzo_m"], 0, at(10, 2))
    _movement(variants["buzo_m"], 1, at(10, 3))
    _movement(variants["buzo_m"], 0, at(10, 4))
    StockMovement.objects.update(on_hand_after=None)
    out = queries.stockouts(OCT)
    assert out["rows"] == [] and out["history_since"] is None


# ── T6 · operación ───────────────────────────────────────────────────────


def test_percentile_aggregate():
    ml = Channel.objects.get(code="mercadolibre")
    for i, h in enumerate([1, 2, 3, 4]):
        Question.objects.create(
            channel=ml, external_id=f"p{i}", text="?", asked_at=at(10, 1), answered_at=at(10, 1, 12 + h)
        )
    from django.db.models import F

    from apps.reports.aggregates import Epoch

    agg = Question.objects.annotate(s=Epoch(F("answered_at") - F("asked_at"))).aggregate(
        p50=Percentile("s", 0.5), p90=Percentile("s", 0.9)
    )
    assert agg["p50"] == 2.5 * 3600 and agg["p90"] == pytest.approx(3.7 * 3600)
    with pytest.raises(ValueError):
        Percentile("s", 2)


def test_response_times_overall_and_by_person(make_user):
    ml = Channel.objects.get(code="mercadolibre")
    ana = make_user("ana@test.local", VENTAS)
    minutes = [30, 90, 600, 1200]  # 0,5 h · 1,5 h · 10 h · 20 h
    for i, m in enumerate(minutes):
        Question.objects.create(
            channel=ml,
            external_id=f"r{i}",
            text="?",
            asked_at=at(10, 5, 8),
            answered_at=at(10, 5, 8) + timedelta(minutes=m),
            answered_by=ana if i < 2 else None,
        )
    Question.objects.create(
        channel=ml, external_id="viejo", text="?", asked_at=at(9, 1), answered_at=at(9, 1, 13)
    )
    r = queries.response_times(OCT)
    assert r["overall"] == {"n": 4, "mediana_h": 5.8, "p90_h": 17.0, "pct_1h": 25.0, "pct_12h": 75.0}
    assert r["people"] == [
        {"persona": "Ana", "n": 2, "mediana_h": 1.0, "p90_h": 1.4, "pct_1h": 50.0, "pct_12h": 100.0}
    ]
    assert queries.response_times(Filters(OCT.start, OCT.end, "tiendanube")) == {"available": False}


def test_dispatch_times_by_channel_and_method_excluding_full():
    def dispatched(channel, method, ready, out, **kw):
        doc = make_order(
            channel, ready, status=states.DISPATCHED, ready_at=kw.pop("ready_at", ready), dispatched_at=out
        )
        Shipment.objects.create(document=doc, method=method)
        return doc

    dispatched("tiendanube", "envio_nube", at(10, 1, 10), at(10, 1, 12))  # 2 h
    dispatched("tiendanube", "carrier", at(10, 2, 10), at(10, 2, 16))  # 6 h
    dispatched("mercadolibre", "me_flex", at(10, 3, 10), at(10, 3, 11))  # 1 h
    dispatched("mercadolibre", "me_full", at(10, 3, 10), at(10, 9, 10))  # Full: no cuenta
    dispatched(
        "manual", "pickup", at(10, 4, 10), at(10, 4, 14), ready_at=None
    )  # sin ready_at: desde la fecha
    d = queries.dispatch_times(OCT)
    assert d["overall"]["n"] == 4 and d["overall"]["mediana_h"] == 3.0
    by_channel = {r["clave"]: (r["n"], r["mediana_h"]) for r in d["by_channel"]}
    assert by_channel == {"Tiendanube": (2, 4.0), "Mercado Libre": (1, 1.0), "Pedido manual": (1, 4.0)}
    by_method = {r["clave"]: r["n"] for r in d["by_method"]}
    assert "Mercado Envíos Full" not in by_method and by_method["Retiro en local"] == 1


def test_flex_on_time_and_late_list():
    def flex(deadline, out, method="me_flex"):
        doc = make_order("mercadolibre", at(10, 1), status=states.DISPATCHED, dispatched_at=out)
        Shipment.objects.create(document=doc, method=method, dispatch_deadline=deadline)
        return doc

    flex(at(10, 2, 14), at(10, 2, 13))
    flex(at(10, 3, 14), at(10, 3, 14))  # justo a la hora: a tiempo
    late = flex(at(10, 4, 14), at(10, 4, 16, 30), method="me_colecta")
    flex(at(9, 4, 14), at(9, 4, 16))  # fuera del período
    r = queries.flex_on_time(OCT)
    assert (r["total"], r["on_time"], r["late_count"], r["pct"]) == (3, 2, 1, 66.7)
    assert r["late"][0]["document_id"] == late.pk and r["late"][0]["demora_h"] == 2.5
    assert r["late"][0]["modalidad"] == "Mercado Envíos Colecta"


def test_manual_pending_list():
    today = date(2026, 11, 14)
    unpaid = make_order("manual", at(11, 4), "1500", invoiced_in_contabilium=True)
    Payment.objects.create(document=unpaid, method="cash", amount=Decimal("1500"), status="pending")
    uninvoiced = make_order("manual", at(11, 10), "800")
    Payment.objects.create(document=uninvoiced, method="cash", amount=Decimal("800"), status="confirmed")
    done = make_order("manual", at(11, 1), "500", invoiced_in_contabilium=True)
    Payment.objects.create(document=done, method="cash", amount=Decimal("500"), status="confirmed")
    make_order("manual", at(11, 1), "900", status=states.CANCELLED)
    make_order("tiendanube", at(11, 1), "900")
    r = queries.manual_pending(today=today)
    assert [(x["document_id"], x["dias"], x["falta"]) for x in r["rows"]] == [
        (unpaid.pk, 10, "Sin cobrar"),
        (uninvoiced.pk, 4, "Sin facturar"),
    ]
    assert r["total"] == Decimal("2300.00")


# ── Pantallas, Excel y permisos ──────────────────────────────────────────

SCREENS = ["reports:summary", "reports:sales", "reports:products", "reports:operations"]
OCT_QS = "?periodo=rango&desde=2026-10-01&hasta=2026-10-31"


@pytest.mark.parametrize("name", SCREENS)
def test_screens_render_for_admin(admin_client, sales_data, name):
    response = admin_client.get(reverse(name) + OCT_QS)
    assert response.status_code == 200
    html = response.content.decode()
    assert "Exportar a Excel" in html and "01/10/2026 al 31/10/2026" in html


def test_summary_shows_charts_notices_and_menu(admin_client, sales_data):
    SalesDocument.objects.filter(channel__code="mercadolibre").update(net_pending=True)
    html = admin_client.get(reverse("reports:summary") + OCT_QS).content.decode()
    assert "cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js" in html
    assert 'id="chart-data"' in html and "Ventas en neto" in html
    assert "2 ventas de Mercado Libre con neto pendiente" in html
    assert "sin comisiones del canal" in html
    assert reverse("reports:summary") in html  # ítem del menú


def test_summary_empty_period(admin_client):
    html = admin_client.get(reverse("reports:summary") + OCT_QS).content.decode()
    assert "No hay ventas en este período" in html


@pytest.mark.parametrize(
    "query",
    [
        "?periodo=rango&desde=nada&hasta=2026-99-99",
        "?periodo=rango&desde=2020-01-01&hasta=2026-10-31",
        "?canal=otro&agrupar=zzz&orden=--x&page=abc&por=y&veces=-3",
        "?veces=texto",
    ],
)
@pytest.mark.parametrize("name", SCREENS)
def test_bad_parameters_never_fail(admin_client, sales_data, name, query):
    assert admin_client.get(reverse(name) + query).status_code == 200


@pytest.mark.parametrize("group", list(queries.GROUPS))
def test_sales_screen_each_group(admin_client, sales_data, group):
    response = admin_client.get(reverse("reports:sales") + OCT_QS + f"&agrupar={group}")
    assert response.status_code == 200 and response.context["table"]["group_by"] == group


def test_sales_screen_sort_links_keep_filters(admin_client, sales_data):
    response = admin_client.get(reverse("reports:sales") + OCT_QS + "&agrupar=producto&orden=unidades")
    headers = {h["field"]: h for h in response.context["headers"]}
    assert headers["unidades"]["arrow"] == "▲" and "orden=-unidades" in headers["unidades"]["url"]
    assert "desde=2026-10-01" in headers["bruto"]["url"] and "agrupar=producto" in headers["bruto"]["url"]


def _xlsx(response):
    from openpyxl import load_workbook

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    return load_workbook(
        io.BytesIO(b"".join(response.streaming_content) if response.streaming else response.content)
    )


def test_sales_excel_columns_and_totals(admin_client, sales_data):
    wb = _xlsx(
        admin_client.get(reverse("reports:sales_excel") + OCT_QS + "&agrupar=variante&orden=-unidades")
    )
    ws = wb["Ventas"]
    rows = list(ws.values)
    assert rows[1] == (
        "Variante (SKU)", "Producto", "Talle", "Color", "Unidades", "Pedidos", "Bruto", "Neto", "Precio prom. por unidad"
    )  # fmt: skip
    assert rows[2][0] == "BUZ-M" and rows[2][4] == 2
    assert rows[-1][0] == "Total" and rows[-1][6] == 21000 and rows[-1][5] == 3


@pytest.mark.parametrize(
    "name,sheets",
    [
        ("reports:summary_excel", ["Indicadores", "Ventas por día", "Días y horas"]),
        ("reports:products_excel", ["Productos más vendidos", "Variantes más vendidas", "Se agotan seguido"]),
        (
            "reports:operations_excel",
            ["Respuesta a preguntas", "Tiempo de despacho", "Flex y Colecta tarde", "Manuales pendientes"],
        ),
    ],
)
def test_other_excels(admin_client, sales_data, name, sheets):
    wb = _xlsx(admin_client.get(reverse(name) + OCT_QS))
    assert wb.sheetnames == sheets


def test_summary_excel_values(admin_client, sales_data):
    ws = _xlsx(admin_client.get(reverse("reports:summary_excel") + OCT_QS))["Indicadores"]
    rows = {r[0]: r for r in ws.values}
    assert rows["Ventas en bruto"][1] == 21500 and rows["Pedidos"][1] == 3


@pytest.mark.parametrize("role", [DEPOSITO, VENTAS, VENDEDOR])
@pytest.mark.parametrize("name", SCREENS + ["reports:sales_excel", "reports:operations_excel"])
def test_other_roles_get_403(client, users_by_role, role, name):
    client.force_login(users_by_role[role])
    assert client.get(reverse(name)).status_code == 403


def test_menu_hidden_for_other_roles(client, users_by_role):
    client.force_login(users_by_role[VENTAS])
    assert reverse("reports:summary") not in client.get(reverse("core:home")).content.decode()


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("reports:summary"))
    assert response.status_code == 302 and reverse("accounts:login") in response["Location"]


def test_reports_never_write(admin_client, sales_data, django_assert_max_num_queries):
    """Solo lectura: ninguna pantalla ni Excel escribe en la base."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    admin_client.get(reverse("reports:summary"))  # calienta la sesión
    for name in SCREENS + ["reports:summary_excel", "reports:sales_excel"]:
        with CaptureQueriesContext(connection) as ctx:
            admin_client.get(reverse(name) + OCT_QS)
        writes = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            and "django_session" not in q["sql"]
        ]
        assert not writes, (name, writes)


def test_stock_levels_untouched_by_reports(admin_client, variants):
    inventory.apply_sync_level(variants["buzo_m"], inventory.default_warehouse(), 3)
    before = list(StockLevel.objects.values_list("on_hand", "reserved"))
    for name in SCREENS:
        admin_client.get(reverse(name))
    assert list(StockLevel.objects.values_list("on_hand", "reserved")) == before


def test_excel_writer_types_and_escaping():
    from openpyxl import load_workbook

    from apps.reports.excel import Sheet, build

    content = build(
        [
            Sheet(
                "Prueba: [rara]/hoja con un nombre muy largo de más de 31",
                ["Texto", "Pesos", "Fecha", "Fecha y hora", "Entero"],
                [
                    ["<A & B> \x01 ok ", Decimal("1234.5"), date(2026, 10, 1), at(10, 1, 9, 30), 7],
                    [None, None, "", "", 0],
                ],
                totals=["Total", Decimal("1234.5"), "", "", 7],
                money_columns={1},
                note="Nota",
            ),
            Sheet("Prueba: [rara]/hoja con un nombre muy largo de más de 31", ["x"]),
        ]
    )
    wb = load_workbook(io.BytesIO(content))
    assert len(wb.sheetnames) == 2 and all(len(n) <= 31 for n in wb.sheetnames)
    ws = wb.worksheets[0]
    assert ws["A1"].value == "Nota" and ws["A2"].font.b
    assert (
        ws["A3"].value == "<A & B>  ok " and ws["B3"].value == 1234.5 and ws["B3"].number_format == "#,##0.00"
    )
    assert ws["C3"].value == datetime(2026, 10, 1) and ws["D3"].value == datetime(2026, 10, 1, 9, 30)
    assert ws["E3"].value == 7 and ws["E4"].value == 0
    assert ws["A5"].value == "Total" and ws["B5"].font.b
    assert ws.freeze_panes == "A3"
