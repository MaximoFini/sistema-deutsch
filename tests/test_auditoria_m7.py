"""Auditoría M7 (docs/auditoria-m7.md): R1 Flex/Colecta a tiempo por fecha límite y R2 aclaración de netos."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.reports import queries
from apps.sales import states
from apps.sales.models import SalesLine, Shipment
from tests.test_reportes import OCT, OCT_QS, _xlsx, at, make_order

pytestmark = pytest.mark.django_db


# ── R1 · Flex y Colecta: período por fecha límite y vencidos sin despachar ────────────


def _flex(deadline, out=None, status=None, method="me_flex"):
    status = status or (states.DISPATCHED if out else states.NEW)
    doc = make_order("mercadolibre", at(10, 1), status=status, dispatched_at=out)
    Shipment.objects.create(document=doc, method=method, dispatch_deadline=deadline)
    return doc


@pytest.fixture
def flex_data():
    return {
        "on_time": _flex(at(10, 2, 14), at(10, 2, 13)),
        "late": _flex(at(10, 4, 14), at(10, 4, 16, 30), method="me_colecta"),
        "overdue": _flex(at(10, 10, 12)),  # venció y sigue sin despachar
        "future": _flex(at(10, 25, 12)),  # todavía está a tiempo: no cuenta
        "cancelled": _flex(at(10, 5, 12), status=states.CANCELLED),
    }


def test_flex_counts_overdue_undispatched_as_late(flex_data):
    r = queries.flex_on_time(OCT, now=at(10, 20, 12))
    assert (r["total"], r["on_time"], r["late_count"], r["pending_count"], r["pct"]) == (3, 1, 2, 1, 33.3)
    late = {x["document_id"]: x for x in r["late"]}
    assert set(late) == {flex_data["late"].pk, flex_data["overdue"].pk}
    overdue = late[flex_data["overdue"].pk]
    assert overdue["sin_despachar"] and overdue["despachado"] is None
    assert overdue["demora_h"] == 240.0  # del 10/10 12:00 hasta "ahora" (20/10 12:00)
    assert late[flex_data["late"].pk]["demora_h"] == 2.5 and not late[flex_data["late"].pk]["sin_despachar"]
    assert r["late"][0]["document_id"] == flex_data["overdue"].pk  # fecha límite más reciente primero


def test_flex_period_is_by_deadline_not_dispatch_date():
    _flex(at(9, 30, 12), at(10, 2, 12))  # fecha límite en septiembre, salió en octubre: no es de octubre
    inside = _flex(at(10, 31, 20), at(11, 1, 9))  # fecha límite en octubre, salió en noviembre: tarde
    r = queries.flex_on_time(OCT, now=at(11, 5))
    assert (r["total"], r["late_count"]) == (1, 1) and r["late"][0]["document_id"] == inside.pk


def test_flex_page_and_excel_mark_undispatched(admin_client, flex_data):
    # Octubre ya pasó: las dos fechas límite vencidas sin despacho cuentan como tarde.
    response = admin_client.get(reverse("reports:operations") + OCT_QS)
    html = response.content.decode()
    assert response.context["flex"]["pending_count"] == 2
    assert "Todavía sin despachar" in html and "(2 todavía sin despachar)" in html
    ws = _xlsx(admin_client.get(reverse("reports:operations_excel") + OCT_QS))["Flex y Colecta tarde"]
    rows = list(ws.values)
    assert "vencieron y siguen sin despachar" in rows[0][0]
    by_order = {r[0]: r for r in rows[2:]}
    assert by_order[flex_data["overdue"].channel_reference][3] == "Todavía sin despachar"
    assert by_order[flex_data["late"].channel_reference][4] == 2.5


# ── R2 · neto por producto vs neto del resumen ─────────────────────────────────────


@pytest.fixture
def ml_sale(db):
    from apps.catalog.models import Product, Variant

    variant = Variant.objects.create(
        product=Product.objects.create(name="Buzo"), sku="BUZ-M", attributes={"Talle": "M", "Color": "Negro"}
    )
    doc = make_order("mercadolibre", at(10, 8), "4000", lines=[(variant, 1, 4000, "690")])
    Shipment.objects.create(document=doc, method="me_flex", seller_cost=Decimal("500"))
    assert SalesLine.objects.get(document=doc).line_total == Decimal("4000.00")
    return doc


FOOTER = (
    "Neto sin descontar envíos de Mercado Libre ($ 500,00). El neto del resumen, con envíos, es $ 2.810,00."
)


@pytest.mark.parametrize("group_by", ["producto", "variante", "talle", "color"])
def test_line_groupings_explain_net_difference(admin_client, ml_sale, group_by):
    t = queries.add_net_summary(OCT, queries.sales_table(OCT, group_by))
    assert t["totals"]["neto"] == Decimal("3310.00")  # sin descontar el envío
    assert t["totals"]["envio"] == Decimal("500.00")
    assert t["totals"]["neto_resumen"] == Decimal("2810.00")
    assert queries.kpis(OCT)["by_key"]["net"]["value"] == t["totals"]["neto_resumen"]
    html = admin_client.get(reverse("reports:sales") + OCT_QS + f"&agrupar={group_by}").content.decode()
    assert FOOTER in html
    ws = _xlsx(admin_client.get(reverse("reports:sales_excel") + OCT_QS + f"&agrupar={group_by}"))["Ventas"]
    assert FOOTER in next(ws.values)[0]


@pytest.mark.parametrize("group_by", ["canal", "mes"])
def test_doc_groupings_have_no_footer(admin_client, ml_sale, group_by):
    t = queries.add_net_summary(OCT, queries.sales_table(OCT, group_by))
    assert "neto_resumen" not in t["totals"] and t["totals"]["neto"] == Decimal("2810.00")
    html = admin_client.get(reverse("reports:sales") + OCT_QS + f"&agrupar={group_by}").content.decode()
    assert "Neto sin descontar envíos" not in html
