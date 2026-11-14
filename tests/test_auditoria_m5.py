"""Auditoría M4–M5 (docs/auditoria-m4-m5.md): correcciones L1–L8 y M1–M2."""

from datetime import timedelta

import httpx
import pytest
import respx
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import DEPOSITO
from apps.alerts.models import Alert
from apps.audit.models import AuditLog
from apps.catalog.models import Product, Variant
from apps.fulfillment import batches, dispatch, labels
from apps.fulfillment import views as fviews
from apps.fulfillment.models import PickBatch
from apps.integrations import credentials
from apps.integrations.adapters.mercadolibre import orders as ml_orders
from apps.integrations.adapters.mercadolibre import shipments as ml_shipments
from apps.integrations.adapters.mercadolibre.client import MLClient
from apps.integrations.adapters.tiendanube import orders as tn_orders
from apps.integrations.models import Channel
from apps.sales import states, sync, tasks
from apps.sales.models import SalesDocument, Shipment
from tests import ml_samples as S
from tests import tn_samples

pytestmark = pytest.mark.django_db
API = "https://api.mercadolibre.com"
M = Shipment.Method


@pytest.fixture
def dep(users_by_role):
    return users_by_role[DEPOSITO]


def make_order(
    channel="manual", status=states.NEW, method=M.CARRIER, ref=None, ship_status="pending", **shipment
):
    doc = SalesDocument.objects.create(
        channel=Channel.objects.get(code=channel), status=status, issued_at=timezone.now()
    )
    doc.channel_reference = ref or f"{channel[:2].upper()} #{doc.number}"
    doc.save(update_fields=["channel_reference"])
    Shipment.objects.create(document=doc, method=method, status=ship_status, **shipment)
    return doc


def tn_jobs(queue):
    return [j for j in queue.jobs.values() if j["task_name"].endswith("tn_fulfillment_update")]


# ── Mercado Libre: cliente y envío simulado ──────────────────────────────


@pytest.fixture
def ml_api(db):
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
    p = Product.objects.create(name="Buzo")
    for sku in ("BUZ-001-M-NEG", "BUZ-001-L-NEG", "GOR-010"):
        Variant.objects.create(product=p, sku=sku)
    with respx.mock(base_url=API, assert_all_called=False) as m:
        yield m


@pytest.fixture
def ml(ml_api):
    return MLClient(sleep=lambda s: None)


@pytest.fixture
def ml_shipment(ml_api):
    """Envío 40001 cuyo contenido se cambia en el test (estado, domicilio, logística, seguimiento)."""
    data = S.shipment()
    ml_api.get("/shipments/40001").mock(side_effect=lambda request: httpx.Response(200, json=data))
    ml_api.get("/shipments/40001/sla").mock(
        return_value=httpx.Response(200, json={"expected_date": "2026-11-13T12:00:00.000-03:00"})
    )
    ml_api.get("/orders/2000001/billing_info").mock(return_value=httpx.Response(200, json=S.billing("CF")))
    return data


def ml_flex_order(ml, ml_shipment):
    doc, _ = ml_orders.upsert_order(S.order())
    ml_shipments.refresh(ml, 40001)
    doc.refresh_from_db()
    assert doc.status == states.NEW and doc.shipments.get().method == M.ME_FLEX
    return doc


# ── L1: despachado por el canal ──────────────────────────────────────────


def test_l1_ml_flex_shipped_while_ready_is_dispatched_and_closes_batch(
    ml, ml_shipment, dep, django_capture_on_commit_callbacks
):
    doc = ml_flex_order(ml, ml_shipment)
    with django_capture_on_commit_callbacks(execute=True):
        batch, _ = batches.create_batch([doc.pk], user=dep)
        states.change_status(doc, states.READY, user=dep)
    ml_shipment["status"] = "shipped"
    with django_capture_on_commit_callbacks(execute=True):
        ml_shipments.refresh(ml, 40001)
    doc.refresh_from_db()
    assert doc.status == states.DISPATCHED
    item = batch.items.get()
    batch.refresh_from_db()
    assert item.resolved_at is not None and batch.status == PickBatch.Status.CLOSED


def test_l1_reason_and_no_oscillation(ml, ml_shipment):
    doc = ml_flex_order(ml, ml_shipment)
    ml_shipment["status"] = "shipped"
    for _ in range(3):  # sincronizaciones repetidas
        ml_shipments.refresh(ml, 40001)
    doc.refresh_from_db()
    assert doc.status == states.DISPATCHED
    logs = AuditLog.objects.filter(action="order.status_changed", object_id=str(doc.pk))
    assert logs.count() == 1 and logs.get().metadata["motivo"] == "Despachado según Mercado Libre"
    assert sync.sync_internal_status(doc) is None


def test_l1_flex_due_alert_stops_once_shipped(ml, ml_shipment):
    doc = ml_flex_order(ml, ml_shipment)
    ml_shipment["status"] = "shipped"
    ml_shipments.refresh(ml, 40001)
    soon = timezone.now() + timedelta(minutes=5)
    Shipment.objects.filter(document=doc).update(dispatch_deadline=soon)
    assert tasks.check_flex_due() == 0
    assert not Alert.objects.filter(alert_type__code="orders.flex_due").exists()


def test_l1_flex_due_alert_still_fires_when_not_shipped(ml, ml_shipment):
    doc = ml_flex_order(ml, ml_shipment)
    Shipment.objects.filter(document=doc).update(dispatch_deadline=timezone.now() + timedelta(minutes=5))
    assert tasks.check_flex_due() == 1


def test_l1_tn_shipped_is_dispatched_without_writing_to_tn(
    in_memory_queue, django_capture_on_commit_callbacks
):
    credentials.save("tiendanube", {"access_token": "T", "store_id": "8434848", "scope": "x"})
    doc = tn_orders.upsert_order(tn_samples.order())
    SalesDocument.objects.filter(pk=doc.pk).update(status=states.READY)
    with django_capture_on_commit_callbacks(execute=True):
        tn_orders.upsert_order(
            tn_samples.order(updated_at="2026-11-13T10:00:00+0000", shipping_status="shipped")
        )
    doc.refresh_from_db()
    assert doc.status == states.DISPATCHED
    assert tn_jobs(in_memory_queue) == []


def test_l1_tn_pickup_goes_to_ready_for_pickup(in_memory_queue, django_capture_on_commit_callbacks):
    credentials.save("tiendanube", {"access_token": "T", "store_id": "8434848", "scope": "x"})
    doc = tn_orders.upsert_order(tn_samples.pickup_order())
    assert doc.shipments.get().method == M.PICKUP
    SalesDocument.objects.filter(pk=doc.pk).update(status=states.PREPARING)
    with django_capture_on_commit_callbacks(execute=True):
        tn_orders.upsert_order(
            tn_samples.pickup_order(updated_at="2026-11-13T10:00:00+0000", shipping_status="shipped")
        )
    doc.refresh_from_db()
    assert doc.status == states.READY_FOR_PICKUP
    assert tn_jobs(in_memory_queue) == []
    assert sync.sync_internal_status(doc) is None  # no vuelve a moverse


@pytest.mark.parametrize("status", [states.NEW, states.PREPARING, states.READY, states.AWAITING_CUSTOMER])
def test_l1_rule_applies_from_every_not_dispatched_state(status):
    doc = make_order("mercadolibre", status=status, method=M.ME_FLEX, ship_status="shipped")
    assert sync.sync_internal_status(doc) == states.DISPATCHED


@pytest.mark.parametrize("status", [states.DISPATCHED, states.READY_FOR_PICKUP, states.DELIVERED])
def test_l1_rule_ignores_other_states(status):
    doc = make_order("mercadolibre", status=status, method=M.ME_FLEX, ship_status="shipped")
    assert sync.sync_internal_status(doc) is None


def test_l1_rule_ignores_unpaid_awaiting_payment():
    doc = make_order("mercadolibre", status=states.AWAITING_PAYMENT, method=M.ME_FLEX, ship_status="shipped")
    f = sync.Facts(cancelled=False, paid=False, delivered=False, full=False, claim_open=False, shipped=True)
    assert sync._target(doc, f, False) == (None, "")


def test_l1_claim_still_wins_over_shipped():
    from apps.conversations.models import Claim

    doc = make_order("mercadolibre", status=states.READY, method=M.ME_FLEX, ship_status="shipped")
    Claim.objects.create(channel=doc.channel, external_id="C9", document=doc, status="opened")
    assert sync.sync_internal_status(doc) == states.CLAIM
    doc.refresh_from_db()
    assert doc.status == states.CLAIM and sync.sync_internal_status(doc) is None


# ── L2: etiqueta de ML vieja ─────────────────────────────────────────────


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _with_saved_labels(shipment):
    shipment.label_file.save("ml-40001.pdf", ContentFile(b"%PDF vieja"), save=False)
    shipment.label_zpl_file.save("ml-40001.zpl", ContentFile(b"^XA vieja ^XZ"), save=False)
    shipment.label_printed_at = timezone.now()
    shipment.save()
    return shipment.label_file.path, shipment.label_zpl_file.path


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(receiver_address={"address_line": "Otra calle 99", "city": {"name": "CABA"}}),
        lambda d: d.update(logistic_type="cross_docking"),
        lambda d: d.update(tracking_number="TRK-NUEVO"),
    ],
    ids=["domicilio", "logistica", "seguimiento"],
)
def test_l2_changed_shipment_drops_saved_labels(ml, ml_shipment, media, change):
    import os

    doc = ml_flex_order(ml, ml_shipment)
    pdf_path, zpl_path = _with_saved_labels(doc.shipments.get())
    change(ml_shipment)
    ml_shipments.refresh(ml, 40001)
    shipment = doc.shipments.get()
    assert not shipment.label_file and not shipment.label_zpl_file
    assert not os.path.exists(pdf_path) and not os.path.exists(zpl_path)
    assert shipment.label_printed_at is None  # vuelve a figurar "Etiqueta sin imprimir"


def test_l2_unchanged_shipment_keeps_labels(ml, ml_shipment, media):
    doc = ml_flex_order(ml, ml_shipment)
    _with_saved_labels(doc.shipments.get())
    ml_shipment["substatus"] = "printed"  # cambia algo que no afecta la etiqueta
    ml_shipments.refresh(ml, 40001)
    shipment = doc.shipments.get()
    assert shipment.label_file and shipment.label_zpl_file


def test_l2_new_label_is_requested_after_change(ml, ml_api, ml_shipment, media):
    doc = ml_flex_order(ml, ml_shipment)
    route = ml_api.get("/shipment_labels").mock(return_value=httpx.Response(200, content=b"%PDF nueva"))
    assert ml_shipments.get_label(ml, doc.shipments.get(), "pdf") == b"%PDF nueva"
    ml_shipment["tracking_number"] = "TRK-NUEVO"
    ml_shipments.refresh(ml, 40001)
    assert ml_shipments.get_label(ml, doc.shipments.get(), "pdf") == b"%PDF nueva"
    assert route.call_count == 2


# ── L3 / L8: botones que se traban al enviar y tope de la tanda ──────────


def test_l3_l8_prepare_page_guards(client, dep, settings):
    make_order()
    client.force_login(dep)
    html = client.get(reverse("sales:prepare")).content.decode()
    assert "Armando…" in html
    assert f'data-max="{settings.FULFILLMENT_MAX_BATCH}"' in html
    assert f"Máximo {settings.FULFILLMENT_MAX_BATCH} por tanda" in html


def test_l3_dispatch_batch_and_carrier_pages_guard_double_submit(client, dep):
    doc = make_order(status=states.NEW)
    batch, _ = batches.create_batch([doc.pk], user=dep)
    client.force_login(dep)
    assert "Guardando…" in client.get(reverse("sales:dispatch")).content.decode()
    detail = client.get(reverse("sales:batch_detail", args=[batch.number])).content.decode()
    assert "Sacando…" in detail and "remove-form" in detail
    assert "Generando…" in client.get(reverse("sales:carrier_label", args=[doc.pk])).content.decode()


# ── L4: rótulo propio solo para Transporte u Otro ────────────────────────


@pytest.mark.parametrize("method", [M.CARRIER, M.OTHER])
def test_l4_carrier_label_allowed(client, dep, method):
    doc = make_order(method=method)
    client.force_login(dep)
    response = client.post(
        reverse("sales:carrier_label", args=[doc.pk]), {"carrier": "Expreso X", "packages": "1"}
    )
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert labels.label_kind(doc.shipments.get()) == labels.KIND_CARRIER


@pytest.mark.parametrize(
    "method,text",
    [
        (M.ME_FLEX, "usa la etiqueta de Mercado Libre"),
        (M.ME_FULL, "es Full"),
        (M.ENVIO_NUBE, "desde Tiendanube"),
        (M.PICKUP, "lo retira el cliente"),
        (M.ME_CUSTOM, "lo maneja Mercado Libre"),
    ],
)
def test_l4_carrier_label_rejected_for_other_methods(client, dep, method, text):
    doc = make_order("mercadolibre", method=method, carrier_name="Correo ML")
    client.force_login(dep)
    page = client.get(reverse("sales:carrier_label", args=[doc.pk])).content.decode()
    assert "Este pedido no lleva rótulo propio" in page and text in page
    assert 'name="packages"' not in page
    response = client.post(
        reverse("sales:carrier_label", args=[doc.pk]), {"carrier": "Expreso X", "packages": "1"}, follow=True
    )
    assert "Este pedido no lleva rótulo propio" in response.content.decode()
    shipment = doc.shipments.get()
    assert shipment.carrier_name == "Correo ML" and shipment.label_print_count == 0
    with pytest.raises(labels.LabelError, match="no lleva rótulo propio"):
        labels.carrier_label(shipment, carrier="X", packages=1, user=dep)


def test_l4_order_panel_shows_carrier_button_only_when_allowed(client, dep):
    other = make_order(method=M.OTHER)
    flex = make_order("mercadolibre", method=M.ME_CUSTOM)
    client.force_login(dep)
    assert (
        "Imprimir rótulo de transporte"
        in client.get(reverse("sales:detail", args=[other.pk])).content.decode()
    )
    assert (
        "Imprimir rótulo de transporte"
        not in client.get(reverse("sales:detail", args=[flex.pk])).content.decode()
    )


# ── L5: pedidos frenados en la tanda ─────────────────────────────────────


@pytest.mark.parametrize("stalled", [states.CLAIM, states.AWAITING_CUSTOMER])
def test_l5_stalled_order_marked_in_batch(client, dep, stalled):
    doc = make_order()
    batch, _ = batches.create_batch([doc.pk], user=dep)
    states.change_status(doc, stalled, system=True)
    client.force_login(dep)
    html = client.get(reverse("sales:batch_detail", args=[batch.number])).content.decode()
    assert f"Frenado: «{states.label(stalled)}»" in html
    assert reverse("sales:batch_remove", args=[batch.number, doc.pk]) in html


# ── L6: aviso de que hay más pedidos que los que se muestran ─────────────


def test_l6_prepare_warns_when_truncated(client, dep, monkeypatch):
    monkeypatch.setattr(fviews, "PREPARE_LIMIT", 2)
    for _ in range(3):
        make_order()
    client.force_login(dep)
    assert (
        "Se muestran los primeros 2 de 3. Usá los filtros."
        in client.get(reverse("sales:prepare")).content.decode()
    )
    monkeypatch.setattr(fviews, "PREPARE_LIMIT", 3)
    assert "Se muestran los primeros" not in client.get(reverse("sales:prepare")).content.decode()


def test_l6_dispatch_warns_when_truncated(client, dep, monkeypatch):
    monkeypatch.setattr(fviews, "DISPATCH_LIMIT", 2)
    for _ in range(3):
        make_order(status=states.READY)
    client.force_login(dep)
    assert "Se muestran los primeros 2 de 3." in client.get(reverse("sales:dispatch")).content.decode()


# ── L7: etiqueta o rótulo sin imprimir en Despacho ───────────────────────


def test_l7_unprinted_marks_in_dispatch(client, dep):
    ml_doc = make_order("mercadolibre", status=states.READY, method=M.ME_FLEX, ref="ML-SIN")
    carrier = make_order(status=states.READY, method=M.CARRIER, ref="TR-SIN")
    printed = make_order(status=states.READY, method=M.CARRIER, ref="TR-OK")
    Shipment.objects.filter(document=printed).update(label_printed_at=timezone.now(), label_print_count=1)
    pickup = make_order(status=states.READY, method=M.PICKUP, ref="RET")
    client.force_login(dep)
    html = client.get(reverse("sales:dispatch")).content.decode()

    def card(ref):
        start = html.index(f"<strong>{ref}</strong>")
        return html[start : html.index("Ver pedido", start) + 300]

    assert "Etiqueta sin imprimir" in card("ML-SIN")
    assert "Rótulo sin imprimir" in card("TR-SIN")
    assert "sin imprimir" not in card("TR-OK")
    assert "sin imprimir" not in card("RET")
    assert ml_doc and carrier and pickup


# ── M1 / M2: mensajes ────────────────────────────────────────────────────


def test_m1_create_batch_translates_transition_error(dep, monkeypatch):
    doc = make_order()

    def fail(*args, **kwargs):
        raise states.TransitionNotAllowed("No se puede pasar de «Nuevo» a «En preparación».")

    monkeypatch.setattr(batches.states, "change_status", fail)
    batch, excluded = batches.create_batch([doc.pk], user=dep)
    assert batch is None
    assert excluded[0].reason == "no se pudo pasar a En preparación"
    assert "No se puede pasar" not in excluded[0].reason


def test_m1_reason_when_status_changed(dep, monkeypatch):
    doc = make_order()

    def fail(document, *args, **kwargs):
        SalesDocument.objects.filter(pk=document.pk).update(status=states.CANCELLED)
        raise states.TransitionNotAllowed("No se puede pasar de «Cancelado» a «En preparación».")

    monkeypatch.setattr(batches.states, "change_status", fail)
    _, excluded = batches.create_batch([doc.pk], user=dep)
    assert excluded[0].reason == "ya no está Nuevo (ahora: «Cancelado»)"


def test_m2_dispatch_hint_on_stale_status(client, dep):
    doc = make_order(status=states.DISPATCHED)
    client.force_login(dep)
    response = client.post(reverse("sales:dispatch"), {"action": "despachar", "doc": [doc.pk]}, follow=True)
    html = response.content.decode()
    assert "ahora está «Despachado»" in html and "Actualizá la página para ver el estado actual." in html


def test_m2_no_hint_for_other_failures(users_by_role):
    from apps.accounts.roles import VENDEDOR

    doc = make_order(status=states.PREPARING)
    result = dispatch.advance([doc.pk], dispatch.LISTO, user=users_by_role[VENDEDOR])
    assert result.failed and result.stale == 0
