"""M5 · Preparación y despacho de pedidos: tandas, picking, PDF, etiquetas, despacho y pantallas."""

import io
import time
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

from apps.accounts.roles import ADMIN, DEPOSITO, VENDEDOR, VENTAS
from apps.audit.models import AuditLog
from apps.catalog.models import Product, Variant
from apps.customers.models import Customer
from apps.fulfillment import batches, dispatch, labels, pdf
from apps.fulfillment.models import Carrier, PickBatch, PickBatchOrder
from apps.integrations import credentials
from apps.integrations.adapters.tiendanube import orders as tn_orders
from apps.integrations.models import Channel
from apps.sales import states
from apps.sales.models import SalesDocument, SalesLine, Shipment
from apps.sales.signals import order_status_changed
from tests import tn_samples

pytestmark = pytest.mark.django_db
ML_API = "https://api.mercadolibre.com"
M = Shipment.Method


def make_order(
    channel="manual",
    status=states.NEW,
    method=M.CARRIER,
    lines=(),
    deadline=None,
    ref=None,
    customer=None,
    address=None,
    external_id="",
    issued_at=None,
):
    doc = SalesDocument.objects.create(
        channel=Channel.objects.get(code=channel),
        status=status,
        issued_at=issued_at or timezone.now(),
        channel_reference=ref or "",
        customer=customer,
    )
    if ref is None:
        doc.channel_reference = f"{channel[:2].upper()} #{doc.number}"
        doc.save(update_fields=["channel_reference"])
    Shipment.objects.create(
        document=doc, method=method, dispatch_deadline=deadline, address=address, external_id=external_id
    )
    for variant, qty in lines:
        if isinstance(variant, Variant):
            SalesLine.objects.create(
                document=doc,
                variant=variant,
                sku_snapshot=variant.sku,
                description_snapshot=variant.product.name,
                quantity=qty,
                unit_price=1000,
            )
        else:  # (sku, descripción) sin catálogo
            SalesLine.objects.create(
                document=doc,
                sku_snapshot=variant[0],
                description_snapshot=variant[1],
                quantity=qty,
                unit_price=1,
            )
    return doc


@pytest.fixture
def variants(db):
    p = Product.objects.create(name="Buzo Canguro")
    gorra = Product.objects.create(name="Gorra")
    return {
        "m": Variant.objects.create(
            product=p, sku="BUZ-001-M-NEG", attributes={"talle": "M", "color": "Negro"}
        ),
        "l": Variant.objects.create(
            product=p, sku="BUZ-001-L-NEG", attributes={"talle": "L", "color": "Negro"}
        ),
        "g": Variant.objects.create(product=gorra, sku="GOR-010"),
    }


@pytest.fixture
def dep(users_by_role):
    return users_by_role[DEPOSITO]


def run_on_commit(django_capture_on_commit_callbacks, fn, *args, **kwargs):
    with django_capture_on_commit_callbacks(execute=True):
        return fn(*args, **kwargs)


# ── T1 · Modelos y permisos ──────────────────────────────────────────────


def test_roles_have_fulfillment_permissions(users_by_role):
    assert users_by_role[ADMIN].has_perm("fulfillment.manage_carriers")
    assert users_by_role[ADMIN].has_perm("fulfillment.view_pickbatch")
    assert users_by_role[DEPOSITO].has_perm("fulfillment.view_pickbatch")
    assert not users_by_role[DEPOSITO].has_perm("fulfillment.manage_carriers")
    assert users_by_role[VENTAS].has_perm("fulfillment.view_pickbatch")
    assert not users_by_role[VENDEDOR].has_perm("fulfillment.view_pickbatch")


def test_one_active_batch_per_order(dep):
    doc = make_order()
    b1 = PickBatch.objects.create(number=901, created_by=dep)
    b2 = PickBatch.objects.create(number=902, created_by=dep)
    PickBatchOrder.objects.create(batch=b1, document=doc)
    with pytest.raises(IntegrityError), transaction.atomic():
        PickBatchOrder.objects.create(batch=b2, document=doc)
    PickBatchOrder.objects.filter(batch=b1).update(removed_at=timezone.now())
    PickBatchOrder.objects.create(batch=b2, document=doc)  # sacado de la primera: puede ir a otra


# ── T2 · Señal order_status_changed ──────────────────────────────────────


def test_signal_sent_once_per_real_change(dep, django_capture_on_commit_callbacks):
    received = []

    def handler(sender, document, old, new, system, **kwargs):
        received.append((document.pk, old, new, system))

    order_status_changed.connect(handler)
    try:
        doc = make_order()
        with django_capture_on_commit_callbacks(execute=True):
            states.change_status(doc, states.PREPARING, user=dep)
            states.change_status(doc, states.PREPARING, user=dep)  # no cambia: no hay señal
        with django_capture_on_commit_callbacks(execute=True):
            states.change_status(doc, states.CANCELLED, system=True, reason="Cancelado en el canal")
    finally:
        order_status_changed.disconnect(handler)
    assert received == [(doc.pk, "new", "preparing", False), (doc.pk, "preparing", "cancelled", True)]


# ── T3 · Preparables y crear tanda ───────────────────────────────────────


def test_preparable_orders_filters_and_order(dep):
    now = timezone.now()
    old_manual = make_order(issued_at=now - timedelta(days=2))
    new_manual = make_order(issued_at=now - timedelta(hours=1))
    flex_late = make_order("mercadolibre", method=M.ME_FLEX, deadline=now + timedelta(hours=5))
    flex_soon = make_order("mercadolibre", method=M.ME_FLEX, deadline=now + timedelta(hours=1))
    make_order("mercadolibre", method=M.ME_FULL)  # Full: no se prepara
    make_order(status=states.PREPARING)
    make_order(status=states.AWAITING_PAYMENT)
    in_batch = make_order()
    PickBatchOrder.objects.create(
        batch=PickBatch.objects.create(number=950, created_by=dep), document=in_batch
    )
    assert list(batches.preparable_orders()) == [flex_soon, flex_late, old_manual, new_manual]


def test_create_batch_moves_to_preparing_and_audits(dep, variants):
    a = make_order(lines=[(variants["m"], 1)])
    b = make_order("tiendanube", method=M.ENVIO_NUBE, lines=[(variants["m"], 2)])
    batch, excluded = batches.create_batch([a.pk, b.pk], user=dep)
    assert excluded == []
    assert batch.status == PickBatch.Status.OPEN and batch.created_by == dep
    assert set(batch.items.values_list("document_id", flat=True)) == {a.pk, b.pk}
    for doc in (a, b):
        doc.refresh_from_db()
        assert doc.status == states.PREPARING
    log = AuditLog.objects.filter(action="order.status_changed", object_id=str(a.pk)).get()
    assert log.actor == dep and log.metadata["motivo"] == f"Tanda {batch.number}"
    created = AuditLog.objects.get(action="fulfillment.batch_created")
    assert created.actor == dep and len(created.metadata["pedidos"]) == 2


def test_create_batch_exclusions(dep):
    ok = make_order()
    taken = make_order(status=states.PREPARING)
    full = make_order("mercadolibre", method=M.ME_FULL)
    first, _ = batches.create_batch([make_order().pk], user=dep)
    other = first.items.get().document
    batch, excluded = batches.create_batch([ok.pk, taken.pk, full.pk, other.pk], user=dep)
    assert list(batch.items.values_list("document_id", flat=True)) == [ok.pk]
    reasons = {e.document.pk: e.reason for e in excluded}
    assert reasons[taken.pk] == "ya no está Nuevo (ahora: «En preparación»)"
    assert reasons[full.pk] == "es Full: lo despacha Mercado Libre"
    assert reasons[other.pk] == f"ya está en la tanda {first.number}"


def test_simulated_race_second_batch_gets_it_excluded(dep, users_by_role):
    doc = make_order()
    b1, _ = batches.create_batch([doc.pk], user=dep)
    b2, excluded = batches.create_batch([doc.pk], user=users_by_role[VENTAS])
    assert b2 is None and excluded[0].reason == f"ya está en la tanda {b1.number}"


def test_empty_batch_not_created(dep):
    taken = make_order(status=states.READY)
    count = PickBatch.objects.count()
    batch, excluded = batches.create_batch([taken.pk], user=dep)
    assert batch is None and len(excluded) == 1 and PickBatch.objects.count() == count


def test_batch_limit(dep, settings):
    settings.FULFILLMENT_MAX_BATCH = 2
    ids = [make_order().pk for _ in range(3)]
    with pytest.raises(batches.BatchError, match="hasta 2 pedidos"):
        batches.create_batch(ids, user=dep)
    assert not PickBatch.objects.exists()


def test_vendedor_cannot_create_batch(users_by_role):
    with pytest.raises(batches.BatchError, match="permiso"):
        batches.create_batch([make_order().pk], user=users_by_role[VENDEDOR])


def test_batch_numbers_are_sequential(dep):
    b1, _ = batches.create_batch([make_order().pk], user=dep)
    b2, _ = batches.create_batch([make_order().pk], user=dep)
    assert b2.number == b1.number + 1


# ── T4 · Picking, sacar pedido y cierre automático ───────────────────────


def test_picking_grouped_by_sku(dep, variants):
    a = make_order(ref="TN #1234", lines=[(variants["m"], 1), (variants["g"], 1)])
    b = make_order(ref="ML pack 555", lines=[(variants["m"], 2), (("XX-9", "Remera vieja"), 1)])
    batch, _ = batches.create_batch([a.pk, b.pk], user=dep)
    picking = batches.picking_list(batch)
    assert [r.sku for r in picking.rows] == ["BUZ-001-M-NEG", "GOR-010"]
    buzo = picking.rows[0]
    assert buzo.total == 3 and batches.qty_text(buzo.total) == "3"
    assert buzo.description == "Buzo Canguro (M / Negro)"
    assert buzo.destinations_text == "TN #1234 (1), ML pack 555 (2)"
    assert len(picking.unknown) == 1
    assert picking.unknown[0].sku == "XX-9" and not picking.unknown[0].in_catalog
    assert picking.units == 5


def test_qty_text():
    assert batches.qty_text(Decimal("10.000")) == "10"
    assert batches.qty_text(Decimal("1.500")) == "1.5"


def test_remove_order_returns_to_new(dep, django_capture_on_commit_callbacks):
    a, b = make_order(), make_order()
    batch, _ = batches.create_batch([a.pk, b.pk], user=dep)
    assert run_on_commit(django_capture_on_commit_callbacks, batches.remove_order, batch, a, user=dep)
    a.refresh_from_db()
    assert a.status == states.NEW
    item = batch.items.get(document=a)
    assert item.removed_at and item.removed_by == dep
    assert AuditLog.objects.filter(action="fulfillment.order_removed").exists()
    batch.refresh_from_db()
    assert batch.status == PickBatch.Status.OPEN
    assert a in batches.preparable_orders()  # vuelve a la pantalla Preparar


@pytest.mark.parametrize(
    "path,pickup",
    [
        ([states.READY, states.DISPATCHED], False),
        ([states.READY, states.READY_FOR_PICKUP], True),
    ],
)
def test_batch_closes_when_all_resolved(dep, django_capture_on_commit_callbacks, path, pickup):
    method = M.PICKUP if pickup else M.CARRIER
    a, b = make_order(method=method), make_order(method=method)
    batch, _ = batches.create_batch([a.pk, b.pk], user=dep)
    for doc in (a, b):
        with django_capture_on_commit_callbacks(execute=True):
            for to in path:
                states.change_status(doc, to, user=dep)
        batch.refresh_from_db()
        assert batch.items.get(document=doc).resolved_at is not None
    assert batch.status == PickBatch.Status.CLOSED and batch.closed_at
    assert AuditLog.objects.filter(action="fulfillment.batch_closed").count() == 1


def test_channel_cancellation_resolves_and_closes(dep, django_capture_on_commit_callbacks):
    doc = make_order("tiendanube", method=M.ENVIO_NUBE)
    batch, _ = batches.create_batch([doc.pk], user=dep)
    with django_capture_on_commit_callbacks(execute=True):
        states.change_status(doc, states.CANCELLED, system=True, reason="Cancelado en Tiendanube")
    batch.refresh_from_db()
    assert batch.status == PickBatch.Status.CLOSED
    assert batch.items.get().resolved_at is not None
    assert batches.picking_list(batch).is_empty  # lo cancelado no se junta


def test_back_to_new_from_order_page_removes_from_batch(dep, django_capture_on_commit_callbacks):
    doc = make_order()
    batch, _ = batches.create_batch([doc.pk], user=dep)
    with django_capture_on_commit_callbacks(execute=True):
        states.change_status(doc, states.NEW, user=dep, reason="Desde la ficha")
    item = batch.items.get()
    assert item.removed_at is not None and item.resolved_at is None
    batch.refresh_from_db()
    assert batch.status == PickBatch.Status.CLOSED


# ── T5 · PDF de doble control ────────────────────────────────────────────


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_checklist_pdf_has_both_parts(dep, variants):
    customer = Customer.objects.create(legal_name="Lucía Gómez")
    a = make_order(ref="TN #1234", customer=customer, lines=[(variants["m"], 2)])
    b = make_order(ref="Manual #45", lines=[(("XX-9", "Remera vieja"), 1)])
    batch, _ = batches.create_batch([a.pk, b.pk], user=dep)
    content = pdf.checklist_pdf(batch, batches.picking_list(batch), user=dep)
    assert content.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(content))
    width, height = reader.pages[0].mediabox.width, reader.pages[0].mediabox.height
    assert (round(float(width)), round(float(height))) == (595, 842)  # A4
    text = _pdf_text(content)
    for expected in (
        f"Tanda {batch.number}",
        "2 pedidos",
        "3 unidades",
        "Página 1 de",
        "Parte 1 · Picking por producto",
        "Juntado",
        "Verificado",
        "BUZ-001-M-NEG",
        "No está en el catálogo",
        "Parte 2 · Armado por pedido",
        "Armado",
        "Controlado",
        "TN #1234 · Lucía Gómez",
        "Armó:",
        "Controló:",
    ):
        assert expected in text, expected


def test_checklist_pdf_50_orders_under_3_seconds(dep, variants):
    ids = [
        make_order(lines=[(variants["m"], 1), (variants["l"], 2), (variants["g"], 1)]).pk for _ in range(50)
    ]
    batch, _ = batches.create_batch(ids, user=dep)
    start = time.perf_counter()
    content = pdf.checklist_pdf(batch, batches.picking_list(batch), user=dep)
    assert time.perf_counter() - start < 3
    assert "Página 1 de" in _pdf_text(content)


# ── T6 · Etiquetas de Mercado Libre ──────────────────────────────────────


def fake_label_pdf(text="etiqueta") -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(100 * mm, 150 * mm))
    c.drawString(20, 200, text)
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def ml_connected(db):
    credentials.save(
        "mercadolibre",
        {
            "access_token": "ACCESS-1",
            "refresh_token": "REFRESH-1",
            "expires_at": (timezone.now() + timedelta(hours=5)).isoformat(),
            "user_id": "123",
            "scope": "offline_access read write",
        },
    )


@pytest.fixture
def ml_api(ml_connected):
    with respx.mock(base_url=ML_API, assert_all_called=False) as m:
        yield m


def ml_order(shipment_id, method=M.ME_FLEX):
    return make_order("mercadolibre", method=method, external_id=str(shipment_id))


def label_router(api, ready: dict):
    def respond(request):
        sid = request.url.params["shipment_ids"]
        if sid not in ready:
            return httpx.Response(400, json={"message": "Shipment not ready to print"})
        return httpx.Response(200, content=ready[sid])

    return api.get("/shipment_labels").mock(side_effect=respond)


def test_ml_labels_skips_not_ready_and_merges(ml_api):
    docs = [ml_order(1), ml_order(2), ml_order(3)]
    label_router(ml_api, {"1": fake_label_pdf("uno"), "3": fake_label_pdf("tres")})
    shipments = [d.shipments.get() for d in docs]
    bundle = labels.ml_labels(shipments, fmt="pdf")
    assert len(PdfReader(io.BytesIO(bundle.content)).pages) == 2
    assert [s.external_id for s in bundle.printed] == ["1", "3"]
    assert len(bundle.skipped) == 1
    doc, reason = bundle.skipped[0]
    assert doc == docs[1] and "no está listo para imprimir" in reason


def test_ml_labels_zpl_concatenated(ml_api):
    docs = [ml_order(1), ml_order(2)]
    label_router(ml_api, {"1": b"^XA^FDuno^FS^XZ", "2": b"^XA^FDdos^FS^XZ"})
    bundle = labels.ml_labels([d.shipments.get() for d in docs], fmt="zpl2")
    assert bundle.content.count(b"^XA") == 2 and bundle.extension == "zpl"


def test_ml_labels_expired_token_is_friendly(ml_api):
    doc = ml_order(1)
    # 401 y la renovación del token rechazada: hay que reconectar ML (sin error 500).
    ml_api.post("/oauth/token").mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    ml_api.get("/shipment_labels").mock(return_value=httpx.Response(401, json={"message": "invalid token"}))
    bundle = labels.ml_labels([doc.shipments.get()], fmt="pdf")
    assert bundle.content is None
    assert "reconectar" in bundle.skipped[0][1]


def test_mark_printed_counts_and_audits(dep):
    doc = ml_order(1)
    shipment = doc.shipments.get()
    labels.mark_printed([shipment], user=dep, kind=labels.KIND_ML)
    labels.mark_printed([shipment], user=dep, kind=labels.KIND_ML)
    shipment.refresh_from_db()
    assert shipment.label_print_count == 2 and shipment.label_printed_at
    logs = AuditLog.objects.filter(action="shipment.label_printed", object_id=str(doc.pk))
    assert logs.count() == 2 and logs.first().actor == dep


def test_order_label_view_downloads_and_marks(client, dep, ml_api):
    doc = ml_order(7)
    label_router(ml_api, {"7": fake_label_pdf()})
    client.force_login(dep)
    response = client.post(reverse("sales:order_label", args=[doc.pk]))
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert doc.shipments.get().label_print_count == 1


def test_batch_labels_view_not_ready_message(client, dep, ml_api):
    ready, not_ready = ml_order(1), ml_order(2)
    batch, _ = batches.create_batch([ready.pk, not_ready.pk], user=dep)
    label_router(ml_api, {"1": fake_label_pdf()})
    client.force_login(dep)
    response = client.post(reverse("sales:batch_labels", args=[batch.number]))
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    page = client.get(reverse("sales:batch_detail", args=[batch.number]))
    assert "no está listo para imprimir" in page.content.decode()


def test_envio_nube_shows_tiendanube_notice(client, dep, settings):
    settings.TN_ADMIN_ORDER_URL = "https://tienda.example/admin/orders/{id}"
    credentials.save("tiendanube", {"access_token": "T", "store_id": "8434848", "scope": "x"})
    doc = tn_orders.upsert_order(tn_samples.order())
    Shipment.objects.filter(document=doc).update(method=M.ENVIO_NUBE)
    if not doc.shipments.exists():
        Shipment.objects.create(document=doc, method=M.ENVIO_NUBE)
    client.force_login(dep)
    html = client.get(reverse("sales:detail", args=[doc.pk])).content.decode()
    assert "La etiqueta se imprime desde Tiendanube" in html
    assert "https://tienda.example/admin/orders/9001" in html


# ── T7 · Rótulo 10×15 y expresos ─────────────────────────────────────────


def test_carrier_label_pages_and_size(dep):
    customer = Customer.objects.create(legal_name="Lucía Gómez", tax_id="30111222", phone="11-5555-0000")
    doc = make_order(
        customer=customer,
        address={
            "address": "Av. Siempreviva",
            "number": "742",
            "city": "Springfield",
            "province": "Buenos Aires",
        },
    )
    shipment = doc.shipments.get()
    content = labels.carrier_label(shipment, carrier="Vía Cargo", packages="3", user=dep)
    reader = PdfReader(io.BytesIO(content))
    assert len(reader.pages) == 3
    box = reader.pages[0].mediabox
    assert (round(float(box.width) / 72 * 25.4), round(float(box.height) / 72 * 25.4)) == (100, 150)
    text = _pdf_text(content)
    assert "BULTO 1 DE 3" in text and "BULTO 3 DE 3" in text
    assert "Lucía Gómez" in text and "Vía Cargo" in text and "Av. Siempreviva 742" in text
    assert "DNI 30111222" in text and "Deutsch" in text
    shipment.refresh_from_db()
    assert shipment.carrier_name == "Vía Cargo" and shipment.packages == 3 and shipment.label_print_count == 1


def test_carrier_label_without_address(dep):
    doc = make_order()
    content = labels.carrier_label(doc.shipments.get(), carrier="Expreso X", packages=1, user=dep)
    assert pdf.MISSING_ADDRESS in _pdf_text(content)


def test_carrier_label_sender_from_settings(dep, settings):
    settings.SENDER_NAME = "Deutsch Indumentaria SRL"
    settings.SENDER_ADDRESS = "Calle Falsa 123, CABA"
    doc = make_order()
    text = _pdf_text(labels.carrier_label(doc.shipments.get(), carrier="X", packages=1, user=dep))
    assert "Deutsch Indumentaria SRL" in text and "Calle Falsa 123" in text


@pytest.mark.parametrize("packages", ["0", "abc", "", "51"])
def test_carrier_label_invalid_packages(dep, packages):
    with pytest.raises(labels.LabelError):
        labels.carrier_label(make_order().shipments.get(), carrier="X", packages=packages, user=dep)


def test_carrier_label_view(client, dep):
    Carrier.objects.create(name="Vía Cargo")
    doc = make_order()
    client.force_login(dep)
    url = reverse("sales:carrier_label", args=[doc.pk])
    page = client.get(url).content.decode()
    assert "Vía Cargo" in page and "completar a mano" in page
    bad = client.post(url, {"carrier": "", "packages": "2"})
    assert bad.status_code == 400 and "Elegí el expreso" in bad.content.decode()
    ok = client.post(url, {"carrier": "Vía Cargo", "carrier_other": "Andreani", "packages": "2"})
    assert ok.status_code == 200 and ok["Content-Type"] == "application/pdf"
    assert doc.shipments.get().carrier_name == "Andreani"  # "otro" gana sobre la lista


def test_carriers_screen_add_and_deactivate(admin_client):
    url = reverse("sales:carriers")
    admin_client.post(url, {"op": "add", "name": "  Vía   Cargo "})
    carrier = Carrier.objects.get()
    assert carrier.name == "Vía Cargo" and carrier.is_active
    admin_client.post(url, {"op": "add", "name": "vía cargo"})
    assert Carrier.objects.count() == 1
    admin_client.post(url, {"op": "toggle", "id": carrier.pk})
    carrier.refresh_from_db()
    assert not carrier.is_active
    assert AuditLog.objects.filter(action="fulfillment.carrier_changed").count() == 2


# ── T8 · Despacho en lote ────────────────────────────────────────────────


def test_advance_partial_success(dep):
    ok = make_order(status=states.PREPARING)
    moved = make_order(status=states.NEW)
    result = dispatch.advance([ok.pk, moved.pk], dispatch.LISTO, user=dep)
    assert [d.pk for d, _ in result.done] == [ok.pk]
    assert result.failed[0][0].pk == moved.pk and "Nuevo" in result.failed[0][1]
    ok.refresh_from_db()
    assert ok.status == states.READY


def test_advance_dispatch_vs_pickup_and_tracking(dep):
    ship = make_order(status=states.READY, method=M.CARRIER)
    pickup = make_order(status=states.READY, method=M.PICKUP)
    result = dispatch.advance(
        [ship.pk, pickup.pk], dispatch.DESPACHAR, user=dep, tracking={ship.pk: "GUIA-99"}
    )
    assert dict((d.pk, to) for d, to in result.done) == {
        ship.pk: states.DISPATCHED,
        pickup.pk: states.READY_FOR_PICKUP,
    }
    assert ship.shipments.get().tracking_number == "GUIA-99"
    log = AuditLog.objects.filter(action="order.status_changed", object_id=str(ship.pk)).get()
    assert log.metadata["seguimiento"] == "GUIA-99" and log.actor == dep
    result = dispatch.advance([pickup.pk], dispatch.ENTREGAR, user=dep)
    assert result.done[0][1] == states.DELIVERED


def test_advance_tiendanube_enqueues_notice(dep, in_memory_queue, django_capture_on_commit_callbacks):
    credentials.save("tiendanube", {"access_token": "T", "store_id": "8434848", "scope": "x"})
    doc = tn_orders.upsert_order(tn_samples.order())
    SalesDocument.objects.filter(pk=doc.pk).update(status=states.READY)
    with django_capture_on_commit_callbacks(execute=True):
        result = dispatch.advance([doc.pk], dispatch.DESPACHAR, user=dep, tracking={doc.pk: "AB1"})
    assert result.done
    jobs = [j for j in in_memory_queue.jobs.values() if j["task_name"].endswith("tn_fulfillment_update")]
    assert len(jobs) == 1 and jobs[0]["args"]["action"] == "dispatched"
    assert jobs[0]["args"]["tracking_code"] == "AB1"


def test_advance_without_permission_fails_each(users_by_role):
    doc = make_order(status=states.PREPARING)
    result = dispatch.advance([doc.pk], dispatch.LISTO, user=users_by_role[VENDEDOR])
    assert not result.done and "permiso" in result.failed[0][1]


def test_dispatch_view_batch_action(client, dep):
    a = make_order(status=states.PREPARING)
    b = make_order(status=states.READY)
    client.force_login(dep)
    response = client.post(reverse("sales:dispatch"), {"action": "listo", "doc": [a.pk, b.pk]}, follow=True)
    html = response.content.decode()
    assert "1 pedido pasó a «Listo»" in html and "No se pudieron avanzar 1" in html
    a.refresh_from_db()
    assert a.status == states.READY


# ── T9/T10 · Pantallas ───────────────────────────────────────────────────


def test_prepare_screen_creates_batch_and_reports_excluded(client, dep, variants):
    a = make_order(ref="Manual #1", lines=[(variants["m"], 1)])
    b = make_order(ref="Manual #2", status=states.READY)
    client.force_login(dep)
    page = client.get(reverse("sales:prepare")).content.decode()
    assert "Manual #1" in page and "Manual #2" not in page
    response = client.post(reverse("sales:prepare"), {"doc": [a.pk, b.pk]}, follow=True)
    html = response.content.decode()
    batch = PickBatch.objects.get()
    assert f"Se armó la tanda {batch.number} con 1 pedido." in html
    assert "Quedaron afuera 1: Manual #2" in html
    assert "BUZ-001-M-NEG" in html  # lista de picking en pantalla


def test_prepare_over_limit_shows_error(client, dep, settings):
    settings.FULFILLMENT_MAX_BATCH = 1
    ids = [make_order().pk, make_order().pk]
    client.force_login(dep)
    html = client.post(reverse("sales:prepare"), {"doc": ids}, follow=True).content.decode()
    assert "Una tanda puede tener hasta 1 pedidos" in html


def test_batch_pdf_view(client, dep):
    batch, _ = batches.create_batch([make_order().pk], user=dep)
    client.force_login(dep)
    response = client.get(reverse("sales:batch_pdf", args=[batch.number]))
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == f'inline; filename="tanda-{batch.number}.pdf"'


def test_batch_remove_view(client, dep):
    doc = make_order()
    batch, _ = batches.create_batch([doc.pk], user=dep)
    client.force_login(dep)
    client.post(reverse("sales:batch_remove", args=[batch.number, doc.pk]))
    doc.refresh_from_db()
    assert doc.status == states.NEW


def test_order_detail_shows_batch_and_printed(client, dep):
    doc = make_order()
    batch, _ = batches.create_batch([doc.pk], user=dep)
    labels.mark_printed([doc.shipments.get()], user=dep, kind=labels.KIND_CARRIER)
    client.force_login(dep)
    html = client.get(reverse("sales:detail", args=[doc.pk])).content.decode()
    assert f"tanda {batch.number}" in html and "Ya impresa (1 vez" in html
    assert reverse("sales:carrier_label", args=[doc.pk]) in html


def test_menu_items_by_role(client, users_by_role):
    client.force_login(users_by_role[DEPOSITO])
    html = client.get(reverse("sales:list")).content.decode()
    assert "Preparar" in html and "Despacho" in html and "Tandas" in html and "Expresos" not in html
    client.force_login(users_by_role[VENDEDOR])
    html = client.get(reverse("sales:list")).content.decode()
    assert "Preparar" not in html and "Tandas" not in html


@pytest.fixture
def screens(dep):
    doc = make_order()
    batch, _ = batches.create_batch([doc.pk], user=dep)
    return {"doc": doc, "batch": batch}


GET_URLS = [
    ("sales:prepare", None, {ADMIN, DEPOSITO, VENTAS}),
    ("sales:dispatch", None, {ADMIN, DEPOSITO, VENTAS}),
    ("sales:batches", None, {ADMIN, DEPOSITO, VENTAS}),
    ("sales:batch_detail", "batch", {ADMIN, DEPOSITO, VENTAS}),
    ("sales:batch_pdf", "batch", {ADMIN, DEPOSITO, VENTAS}),
    ("sales:carrier_label", "doc", {ADMIN, DEPOSITO, VENTAS}),
    ("sales:carriers", None, {ADMIN}),
]
POST_URLS = [
    ("sales:batch_labels", "batch"),
    ("sales:order_label", "doc"),
    ("sales:batch_remove", "batch+doc"),
]


def _args(kind, screens):
    if kind == "batch":
        return [screens["batch"].number]
    if kind == "doc":
        return [screens["doc"].pk]
    if kind == "batch+doc":
        return [screens["batch"].number, screens["doc"].pk]
    return []


@pytest.mark.parametrize("name,kind,allowed", GET_URLS)
def test_get_permissions_by_role(client, users_by_role, screens, name, kind, allowed):
    url = reverse(name, args=_args(kind, screens))
    for role, user in users_by_role.items():
        client.force_login(user)
        assert client.get(url).status_code == (200 if role in allowed else 403), (name, role)
    client.logout()
    assert client.get(url).status_code == 302  # anónimo: al login


@pytest.mark.parametrize("name,kind", POST_URLS)
def test_post_actions_forbidden_for_vendedor(client, users_by_role, screens, name, kind):
    client.force_login(users_by_role[VENDEDOR])
    assert client.post(reverse(name, args=_args(kind, screens))).status_code == 403
    assert client.post(reverse("sales:prepare"), {"doc": [screens["doc"].pk]}).status_code == 403
    assert client.post(reverse("sales:dispatch"), {"action": "listo"}).status_code == 403
