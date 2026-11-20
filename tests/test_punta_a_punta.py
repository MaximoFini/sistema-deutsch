# ruff: noqa: F811
"""M9 · Prueba punta a punta (DDEV-57, US-2 / R2.3): recorre los circuitos completos con canales simulados.

Cada test cubre UN circuito de principio a fin (como lo haría una persona en las pantallas) y al final
comprueba que no quedaron avisos ni emails de más. Los canales (Tiendanube, Mercado Libre) son respx y el
correo es locmem: nada sale a la red. Las letras (a–h) son las del guion `docs/runbooks/prueba-punta-a-punta.md`.
"""

import io
import json
import re
from collections import Counter
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from django.contrib.auth import authenticate, get_user_model
from django.core import mail as djmail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import ADMIN, DEPOSITO, VENDEDOR
from apps.alerts.models import Alert
from apps.audit.models import AuditLog
from apps.catalog.models import Product, Variant
from apps.conversations import tasks as conversation_tasks
from apps.customers.models import Customer
from apps.fulfillment.models import Carrier
from apps.integrations.adapters.mercadolibre import claims as ml_claims
from apps.integrations.adapters.mercadolibre import orders as ml_orders
from apps.integrations.adapters.mercadolibre import shipments as ml_shipments
from apps.integrations.adapters.mercadolibre.client import MLClient
from apps.inventory.models import StockLevel, StockMovement
from apps.pricing.models import PriceListItem
from apps.sales import states, tasks
from apps.sales.models import Payment, SalesDocument, SalesLine, Shipment
from apps.sales.tasks import orders_watch
from apps.wholesale import mail, payments
from apps.wholesale.models import (
    Cart,
    CartItem,
    CustomerAccount,
    CustomerBalance,
    Invitation,
    OutboundEmail,
    PaymentReceipt,
    Shortage,
    StoreSettings,
    WholesaleOrder,
)
from tests import ml_samples as S
from tests import tn_samples
from tests.punta_a_punta import (  # noqa: F401  (los fixtures se usan por nombre)
    PNG,
    alert_codes,
    assert_only,
    catalog_writes,
    clear_cache,
    golden_rule,
    login,
    malla,
    ml,
    ml_notify,
    non_get_calls,
    on_hand,
    reserved,
    run_pending_events,
    stub_ml_order,
    tn,
)
from tests.test_historicos import make_doc
from tests.test_invitaciones import TOKEN_IN_LINK, make_customer
from tests.test_mayorista import PASSWORD, registration_data
from tests.test_tiendanube import post_hook, run_jobs

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def low_min(db):
    row = StoreSettings.load()
    row.min_order_amount = Decimal("1000")
    row.save()
    return row


@pytest.fixture
def capture(django_capture_on_commit_callbacks):
    """Los pedidos y los avisos se completan al terminar la transacción (on_commit): acá se ejecutan."""

    def run():
        return django_capture_on_commit_callbacks(execute=True)

    return run


def run_events(connector, capture) -> int:
    """El worker procesa los webhooks recibidos (y se completan los avisos que quedan para el final)."""
    with capture():
        return run_pending_events(connector)


def web_register_and_approve(client, admin, capture, **over):
    """El cliente se registra en la tienda y un administrador lo aprueba desde el panel."""
    data = registration_data(**over)
    with capture():
        response = client.post(reverse("store:register"), data)
    assert response.url == reverse("store:register_done")
    account = CustomerAccount.objects.get(cuit=data["cuit"])
    assert account.status == CustomerAccount.Status.PENDING
    with capture():
        login(admin).post(reverse("wholesale_customers:action", args=[account.pk]), {"action": "approve"})
    account.refresh_from_db()
    assert account.status == CustomerAccount.Status.APPROVED
    return account, data


def web_checkout(customer_client, variants_qty, *, delivery, payment, carrier=""):
    """Del catálogo a «Confirmar pedido» en las pantallas de la tienda. Devuelve el pedido creado."""
    product_id = next(iter(variants_qty)).product_id
    page = customer_client.get(reverse("store:home"))
    assert page.status_code == 200
    assert customer_client.get(reverse("store:product", args=[product_id])).status_code == 200
    customer_client.post(
        reverse("store:add_to_cart", args=[product_id]),
        {f"qty-{v.pk}": str(q) for v, q in variants_qty.items()},
    )
    cart = customer_client.get(reverse("store:cart"))
    assert cart.status_code == 200 and cart.context["summary"].lines
    form = customer_client.get(reverse("store:checkout"))
    assert form.status_code == 200
    response = customer_client.post(
        reverse("store:checkout"),
        {"delivery": delivery, "carrier": carrier, "payment": payment, "snapshot": form.context["form"].initial["snapshot"]},
    )  # fmt: skip
    doc = SalesDocument.objects.filter(channel__code="mayorista").order_by("-pk").first()
    assert response.url == reverse("store:order_done", args=[doc.number])
    return doc


def customer_session(account, password=PASSWORD):
    """Ingreso real por la pantalla de la tienda (no `force_login`)."""
    client = Client()
    response = client.post(reverse("store:login"), {"username": account.user.email, "password": password})
    assert response.status_code == 302 and response.url == reverse("store:home")
    return client


# ── a) Mayorista por transferencia ───────────────────────────────────────────


def test_a_circuito_mayorista_transferencia_registro_a_facturado_libera_la_reserva(
    client, malla, users_by_role, low_min, golden_rule, capture
):
    _, v = malla
    admin, deposito = users_by_role[ADMIN], users_by_role[DEPOSITO]
    Carrier.objects.create(name="Expreso Rosario")

    # Registro y aprobación (panel).
    account, _ = web_register_and_approve(client, admin, capture)
    customer = customer_session(account)

    # Catálogo, carrito y checkout; el pedido queda esperando la transferencia y reserva el stock.
    with capture():
        doc = web_checkout(
            customer,
            {v["M"]: 3, v["L"]: 2},
            delivery="carrier",
            carrier="Expreso Rosario",
            payment="transfer",
        )
    assert doc.status == states.AWAITING_PAYMENT and doc.ready_at is None
    assert doc.subtotal == Decimal("50000.00") and doc.total == Decimal("60500.00")
    assert (reserved(v["M"]), reserved(v["L"])) == (3, 2) and on_hand(v["M"]) == 5
    assert (
        "subí el comprobante" in customer.get(reverse("store:order_done", args=[doc.number])).content.decode()
    )

    # El cliente sube el comprobante; avisa a administración. El depósito todavía no lo ve para preparar.
    with capture():
        customer.post(
            reverse("store:receipt_upload", args=[doc.number]),
            {"file": SimpleUploadedFile("transferencia.png", PNG, content_type="image/png")},
        )
    assert PaymentReceipt.objects.filter(document=doc).count() == 1
    assert doc.pk not in [o.pk for o in login(deposito).get(reverse("sales:prepare")).context["orders"]]

    # Administración confirma el pago: pasa a Nuevo y avisa a Depósito.
    with capture():
        login(admin).post(reverse("wholesale_orders:confirm_payment", args=[doc.pk]))
    doc.refresh_from_db()
    assert doc.status == states.NEW and doc.payments.get().status == Payment.Status.CONFIRMED
    assert reserved(v["M"]) == 3  # la reserva sigue hasta facturar

    # Depósito: arma la tanda (picking), imprime la hoja, marca Listo y despacha con seguimiento.
    dep = login(deposito)
    assert doc.pk in [o.pk for o in dep.get(reverse("sales:prepare")).context["orders"]]
    response = dep.post(reverse("sales:prepare"), {"doc": [doc.pk]})
    number = int(response.url.rstrip("/").split("/")[-1])
    assert response.url == reverse("sales:batch_detail", args=[number])
    assert dep.get(reverse("sales:batch_pdf", args=[number])).content.startswith(b"%PDF")
    doc.refresh_from_db()
    assert doc.status == states.PREPARING
    dep.post(reverse("sales:dispatch"), {"action": "listo", "doc": [doc.pk]})
    with capture():
        dep.post(
            reverse("sales:dispatch"),
            {"action": "despachar", "doc": [doc.pk], f"tracking_{doc.pk}": "EXP-123"},
        )
    doc.refresh_from_db()
    assert doc.status == states.DISPATCHED and doc.dispatched_at is not None
    assert doc.shipments.get().tracking_number == "EXP-123"
    assert reserved(v["M"]) == 3  # despachado no es facturado: la reserva sigue

    # Administración marca «Facturado en Contabilium»: se libera la reserva (una sola vez).
    admin_client = login(admin)
    admin_client.post(
        reverse("sales:manual_edit", args=[doc.pk, "factura"]),
        {"invoiced": "1", "invoice_number": "A-0001-00001234"},
    )
    doc.refresh_from_db()
    assert doc.invoiced_in_contabilium and doc.invoice_number == "A-0001-00001234"
    assert (reserved(v["M"]), reserved(v["L"])) == (0, 0)
    assert on_hand(v["M"]) == 5  # el físico lo baja Contabilium, no este sistema
    assert WholesaleOrder.objects.get(document=doc).reservation_released_at is not None
    admin_client.post(
        reverse("sales:manual_edit", args=[doc.pk, "factura"]),
        {"invoiced": "1", "invoice_number": "A-0001-00001235"},
    )
    assert (
        StockMovement.objects.filter(reference_id=str(doc.pk), kind="release").count() == 2
    )  # 2 variantes, 1 vez

    assert_only(
        alerts=["wholesale.registration_new", "wholesale.receipt_uploaded", "orders.new"],
        emails=["registration_received", "registration_approved", "order_received", "payment_confirmed", "dispatched"],
    )  # fmt: skip
    assert not AuditLog.objects.filter(action="integration.write_blocked").exists()


def test_a_circuito_mayorista_transferencia_vence_por_falta_de_pago(
    malla, users_by_role, low_min, golden_rule, capture
):
    _, v = malla
    account, _ = web_register_and_approve(Client(), users_by_role[ADMIN], capture)
    customer = customer_session(account)
    CustomerBalance.objects.create(customer=account.customer, amount=Decimal("1000"))
    with capture():
        doc = web_checkout(customer, {v["M"]: 2}, delivery="pickup", payment="transfer")
    order = WholesaleOrder.objects.get(document=doc)
    assert reserved(v["M"]) == 2 and order.expires_at > timezone.now()

    # Un día antes de vencer sale un solo recordatorio con los datos para transferir.
    assert payments.send_reminders(now=order.expires_at - timedelta(hours=20)) == 1
    assert payments.send_reminders(now=order.expires_at - timedelta(hours=10)) == 0

    # Vence: se cancela, se libera la reserva, vuelve el saldo a favor y se avisa al cliente y a administración.
    with capture():
        result = payments.expire_orders(now=order.expires_at + timedelta(minutes=1))
    assert result["expired"] == 1
    doc.refresh_from_db()
    assert doc.status == states.CANCELLED and reserved(v["M"]) == 0
    assert CustomerBalance.balance_for(account.customer) == Decimal("1000")
    assert "Cancelado" in customer.get(reverse("store:order_detail", args=[doc.number])).content.decode()
    assert_only(
        alerts=["wholesale.registration_new", "wholesale.order_expired"],
        emails=["registration_received", "registration_approved", "order_received", "payment_reminder", "order_expired"],
    )  # fmt: skip


# ── b) Mayorista en efectivo y en cuenta corriente ───────────────────────────


def test_b_circuito_mayorista_efectivo_y_cuenta_corriente_sin_falsos_sin_cobrar(
    malla, users_by_role, low_min, golden_rule, capture
):
    _, v = malla
    admin, deposito = users_by_role[ADMIN], users_by_role[DEPOSITO]
    Carrier.objects.create(name="Expreso Rosario")
    account, _ = web_register_and_approve(Client(), admin, capture)
    customer = customer_session(account)

    # Sin cuenta corriente habilitada la tienda no la ofrece; la habilita un administrador desde el panel.
    assert "Cuenta corriente" not in customer.get(reverse("store:checkout")).content.decode()
    with capture():
        login(admin).post(reverse("wholesale_customers:action", args=[account.pk]), {"action": "credit_on"})
    account.refresh_from_db()
    assert account.credit_enabled

    # Efectivo: solo con retiro en el local; entra directo en Nuevo y se cobra al entregar.
    with capture():
        cash = web_checkout(customer, {v["M"]: 1}, delivery="pickup", payment="cash")
    assert cash.status == states.NEW and cash.payments.get().method == Payment.Method.CASH
    # Cuenta corriente: entra directo en Nuevo, con el pago «pendiente» por definición.
    with capture():
        on_account = web_checkout(
            customer, {v["L"]: 2}, delivery="carrier", carrier="Expreso Rosario", payment="account"
        )
    assert on_account.status == states.NEW
    assert on_account.payments.get().method == Payment.Method.CURRENT_ACCOUNT
    assert (
        WholesaleOrder.objects.get(document=on_account).expires_at is None
    )  # no vence: no hay transferencia

    # Pasadas 48 h sin cobrar ni facturar: el efectivo avisa «sin cobrar» y «sin facturar»;
    # la cuenta corriente SOLO «sin facturar» (se cobra después, avisar «sin cobrar» sería ruido).
    later = timezone.now() + timedelta(hours=48)
    with capture():
        assert tasks.check_manual_pending(now=later) == 3
    keys = set(
        Alert.objects.filter(alert_type__code="orders.manual_pending").values_list("dedupe_key", flat=True)
    )
    assert keys == {f"manual:{cash.pk}:pago", f"manual:{cash.pk}:factura", f"manual:{on_account.pk}:factura"}
    assert tasks.check_manual_pending(now=later) == 0  # no repite

    # El efectivo se entrega recién cuando se tilda «Cobré».
    dep = login(deposito)
    dep.post(reverse("sales:prepare"), {"doc": [cash.pk]})
    dep.post(reverse("sales:dispatch"), {"action": "listo", "doc": [cash.pk]})
    with capture():
        dep.post(reverse("sales:dispatch"), {"action": "despachar", "doc": [cash.pk]})
    cash.refresh_from_db()
    assert cash.status == states.READY_FOR_PICKUP
    dep.post(reverse("sales:dispatch"), {"action": "entregar", "doc": [cash.pk]})
    cash.refresh_from_db()
    assert cash.status == states.READY_FOR_PICKUP  # sin «Cobré» no sale
    dep.post(reverse("sales:dispatch"), {"action": "entregar", "doc": [cash.pk], "cash": [cash.pk]})
    cash.refresh_from_db()
    assert cash.status == states.DELIVERED and cash.payments.get().status == Payment.Status.CONFIRMED

    # Facturados los dos, se libera la reserva de cada uno.
    for doc in (cash, on_account):
        login(admin).post(
            reverse("sales:manual_edit", args=[doc.pk, "factura"]),
            {"invoiced": "1", "invoice_number": f"A-0001-{doc.number:08d}"},
        )
    assert (reserved(v["M"]), reserved(v["L"])) == (0, 0)
    assert_only(
        alerts=["wholesale.registration_new", "orders.new", "orders.new", "orders.manual_pending"] + ["orders.manual_pending"] * 2,
        emails=["registration_received", "registration_approved", "order_received", "order_received", "ready_for_pickup"],
    )  # fmt: skip


# ── c) Faltante, crédito por faltante y devolución recibida ─────────────────


def test_c_circuito_faltante_credito_y_devolucion_recibida(
    malla, users_by_role, low_min, golden_rule, capture
):
    _, v = malla
    admin, deposito = users_by_role[ADMIN], users_by_role[DEPOSITO]
    Carrier.objects.create(name="Expreso Rosario")
    account, _ = web_register_and_approve(Client(), admin, capture)
    customer = customer_session(account)
    with capture():
        doc = web_checkout(
            customer, {v["M"]: 2}, delivery="carrier", carrier="Expreso Rosario", payment="transfer"
        )
    with capture():
        login(admin).post(reverse("wholesale_orders:confirm_payment", args=[doc.pk]))
    dep = login(deposito)
    dep.post(reverse("sales:prepare"), {"doc": [doc.pk]})
    line = doc.lines.get()

    # Depósito marca que falta 1 unidad: el pedido espera al cliente y se avisa a administración y al cliente.
    with capture():
        dep.post(reverse("wholesale_orders:shortage_report", args=[doc.pk]), {f"missing_{line.pk}": "1"})
    doc.refresh_from_db()
    assert doc.status == states.AWAITING_CUSTOMER
    assert Alert.objects.filter(alert_type__code="wholesale.shortage_reported").exists()
    assert OutboundEmail.objects.filter(template_code="shortage_query").exists()
    assert reserved(v["M"]) == 2

    # Administración lo resuelve con saldo a favor: baja el pedido, libera la diferencia y queda el crédito.
    with capture():
        login(admin).post(
            reverse("wholesale_orders:shortage_resolve", args=[doc.pk]),
            {f"qty_{line.pk}": "1", "difference": "credit"},
        )
    doc.refresh_from_db()
    assert doc.status == states.PREPARING and doc.total == Decimal("12100.00")
    assert reserved(v["M"]) == 1
    assert CustomerBalance.balance_for(account.customer) == Decimal("12100.00")
    assert "$ 12.100,00" in customer.get(reverse("store:account")).content.decode()

    # El crédito paga el pedido siguiente entero: no hay nada que transferir y entra directo en Nuevo.
    with capture():
        next_doc = web_checkout(customer, {v["L"]: 1}, delivery="pickup", payment="transfer")
    assert next_doc.total == Decimal("0.00") and next_doc.status == states.NEW
    assert CustomerBalance.balance_for(account.customer) == Decimal("0.00")

    # El pedido con faltante sigue su camino: Listo, despachado y entregado.
    dep.post(reverse("sales:dispatch"), {"action": "listo", "doc": [doc.pk]})
    with capture():
        dep.post(reverse("sales:dispatch"), {"action": "despachar", "doc": [doc.pk]})
    doc.refresh_from_db()
    assert doc.status == states.DISPATCHED
    states.change_status(doc, states.DELIVERED, user=admin)

    # Devolución: se espera, Depósito la recibe (apta para reventa) y administración ajusta Contabilium.
    stock_before = (on_hand(v["M"]), StockMovement.objects.count())
    created = dep.post(reverse("sales:return_create", args=[doc.pk]), {"receive_now": "1"})
    ret = SalesDocument.objects.get(doc_type=SalesDocument.DocType.RETURN, related_document=doc)
    assert created.url == reverse("sales:return_receive", args=[ret.pk])
    ret_line = ret.lines.get()
    with capture():
        response = dep.post(
            reverse("sales:return_receive", args=[ret.pk]),
            {f"qty_{ret_line.pk}": "1", f"cond_{ret_line.pk}": "resellable", "comment": "Llegó bien"},
        )
    assert response.status_code == 302
    ret.refresh_from_db()
    assert ret.return_info.received_at is not None
    assert Alert.objects.filter(alert_type__code="returns.received_adjust_stock").exists()
    assert (on_hand(v["M"]), StockMovement.objects.count()) == stock_before  # el stock lo ajusta Contabilium
    login(admin).post(reverse("sales:return_adjusted", args=[ret.pk]))
    ret.return_info.refresh_from_db()
    assert ret.return_info.adjusted_in_contabilium

    assert_only(
        alerts=["wholesale.registration_new", "orders.new", "orders.new", "wholesale.shortage_reported", "returns.received_adjust_stock"],
        emails=["registration_received", "registration_approved", "order_received", "order_received", "payment_confirmed", "shortage_query", "dispatched"],
    )  # fmt: skip


# ── d) Mercado Libre Flex y Full ─────────────────────────────────────────────


def ml_shipment(
    shipment_id=40001, order_id=2000001, logistic="self_service", status="ready_to_ship", shipped=False
):
    data = S.shipment(shipment_id, order_id, logistic, status)
    if shipped:
        data["status_history"]["date_shipped"] = "2026-11-13T09:00:00.000-03:00"
    return data


def test_d_circuito_ml_flex_notificacion_etiqueta_despacho_estados_del_canal_y_plazo(
    client, ml, malla, users_by_role, in_memory_queue, golden_rule, capture
):
    deposito = users_by_role[DEPOSITO]
    stub_ml_order(ml)  # Flex (self_service), pagado
    assert ml_notify(client, "/orders/2000001").status_code == 200
    assert run_events(in_memory_queue, capture) == 1
    doc = SalesDocument.objects.get(channel__code="mercadolibre")
    shipment = doc.shipments.get()
    assert doc.status == states.NEW and shipment.method == Shipment.Method.ME_FLEX
    assert shipment.dispatch_deadline is not None and doc.lines.count() == 1
    assert Alert.objects.filter(alert_type__code="orders.new", dedupe_key=f"new:{doc.pk}").exists()

    # Depósito imprime la etiqueta (PDF simulado de ML), arma la tanda y marca Listo.
    ml.get("/shipment_labels").mock(return_value=httpx.Response(200, content=b"%PDF-1.4 etiqueta"))
    dep = login(deposito)
    label = dep.post(reverse("sales:order_label", args=[doc.pk]))
    assert label.status_code == 200 and label.content.startswith(b"%PDF")
    dep.post(reverse("sales:prepare"), {"doc": [doc.pk]})
    dep.post(reverse("sales:dispatch"), {"action": "listo", "doc": [doc.pk]})
    doc.refresh_from_db()
    assert doc.status == states.READY

    # Alerta de plazo: aparece dentro de las 2 h previas al límite, una sola vez, y no antes.
    deadline = shipment.dispatch_deadline
    assert tasks.check_flex_due(now=deadline - timedelta(hours=5)) == 0
    assert tasks.check_flex_due(now=deadline - timedelta(minutes=45)) == 1
    assert tasks.check_flex_due(now=deadline - timedelta(minutes=30)) == 0

    # Despacha Depósito; ML no recibe nada (el repartidor escanea la etiqueta).
    dep.post(reverse("sales:dispatch"), {"action": "despachar", "doc": [doc.pk]})
    doc.refresh_from_db()
    assert doc.status == states.DISPATCHED

    # ML avisa que lo entregó (notificación de envíos): el sistema lo refleja solo.
    ml.get("/shipments/40001").mock(return_value=httpx.Response(200, json=ml_shipment(status="delivered")))
    assert ml_notify(client, "/shipments/40001", topic="shipments").status_code == 200
    assert run_events(in_memory_queue, capture) == 1
    doc.refresh_from_db()
    assert doc.status == states.DELIVERED and doc.channel_status.endswith("delivered")

    # Otro Flex que el repartidor escaneó antes de que Depósito lo marque: pasa a Despachado «según ML».
    stub_ml_order(ml, order_id=2000003, shipment_id=40003, order=S.order(order_id=2000003, shipping_id=40003))
    ml.get("/shipments/40003").mock(
        return_value=httpx.Response(200, json=ml_shipment(40003, 2000003, status="shipped", shipped=True))
    )
    ml_notify(client, "/orders/2000003")
    run_events(in_memory_queue, capture)
    scanned = SalesDocument.objects.get(channel__code="mercadolibre", shipments__external_id="40003")
    assert scanned.status == states.DISPATCHED

    assert non_get_calls(ml) == []  # ML: solo lecturas
    assert_only(alerts=["orders.new", "orders.flex_due"], emails=[])
    assert not AuditLog.objects.filter(action="integration.write_blocked").exists()


def test_d_circuito_ml_full_lo_despacha_mercado_libre_y_no_se_prepara(
    client, ml, malla, users_by_role, in_memory_queue, golden_rule, capture
):
    stub_ml_order(ml, logistic="fulfillment")
    assert ml_notify(client, "/orders/2000001").status_code == 200
    assert run_events(in_memory_queue, capture) == 1
    doc = SalesDocument.objects.get(channel__code="mercadolibre")
    assert doc.shipments.get().method == Shipment.Method.ME_FULL
    # Full: el pedido sale de Mercado Libre; no se prepara, no tiene etiqueta ni plazo, no avisa.
    assert doc.status == states.DISPATCHED
    dep = login(users_by_role[DEPOSITO])
    assert doc.pk not in [o.pk for o in dep.get(reverse("sales:prepare")).context["orders"]]
    assert tasks.check_flex_due(now=timezone.now()) == 0
    assert dep.post(reverse("sales:order_label", args=[doc.pk])).status_code == 302  # «no tiene etiqueta»
    dep.post(reverse("sales:prepare"), {"doc": [doc.pk]})
    doc.refresh_from_db()
    assert doc.status == states.DISPATCHED and not doc.pick_items.exists()
    # ML lo entrega.
    ml.get("/shipments/40001").mock(
        return_value=httpx.Response(200, json=ml_shipment(logistic="fulfillment", status="delivered"))
    )
    ml_notify(client, "/shipments/40001", topic="shipments")
    run_events(in_memory_queue, capture)
    doc.refresh_from_db()
    assert doc.status == states.DELIVERED
    assert non_get_calls(ml) == []
    assert_only(alerts=[], emails=[])


# ── e) Tiendanube: Envío Nube y retiro en el local ───────────────────────────

TN_WRITE_PATH = re.compile(r"^/2025-03/8434848/orders/\d+/fulfillment-orders/[^/]+(/tracking-events)?$")


def assert_tn_only_wrote_shipping_state(router):
    """Lo único que el sistema escribe en Tiendanube es el estado del envío (nunca productos, stock ni precios)."""
    assert catalog_writes(router) == []
    writes = non_get_calls(router)
    assert writes, "se esperaba al menos un aviso de envío a Tiendanube"
    for call in writes:
        assert TN_WRITE_PATH.match(call.request.url.path), call.request.url
        body = json.loads(call.request.content)
        if call.request.method == "PATCH":
            assert set(body) <= {"status", "tracking_info"}
            assert body["status"] in {"PACKED", "DISPATCHED", "READY_FOR_PICKUP"}
        else:
            assert call.request.method == "POST" and body == {"status": "delivered"}
    assert not any(c.request.url.path.endswith(("/products", "/variants")) for c in router.calls)


def test_e_circuito_tn_envio_nube_y_retiro_solo_escribe_el_estado_de_envio(
    client, tn, malla, users_by_role, in_memory_queue, golden_rule, capture
):
    dep = login(users_by_role[DEPOSITO])

    # Envío Nube, pagado: entra por el webhook firmado y queda listo para preparar.
    tn.get("/orders/9001").mock(return_value=httpx.Response(200, json=tn_samples.order()))
    tn.get("/orders/9001/fulfillment-orders").mock(
        return_value=httpx.Response(200, json=tn_samples.fulfillment_orders("UNPACKED"))
    )
    tn.patch("/orders/9001/fulfillment-orders/01HXFO000000000000000000AA").mock(
        return_value=httpx.Response(200, json={})
    )
    assert post_hook(client, {"store_id": 8434848, "event": "order/created", "id": 9001}).status_code == 200
    assert run_events(in_memory_queue, capture) == 1
    nube = SalesDocument.objects.get(channel__code="tiendanube")
    assert nube.status == states.NEW and nube.shipments.get().method == Shipment.Method.ENVIO_NUBE
    assert nube.payments.get().status == Payment.Status.CONFIRMED

    dep.post(reverse("sales:prepare"), {"doc": [nube.pk]})
    with capture():
        dep.post(reverse("sales:dispatch"), {"action": "listo", "doc": [nube.pk]})
        dep.post(
            reverse("sales:dispatch"),
            {"action": "despachar", "doc": [nube.pk], f"tracking_{nube.pk}": "AB123"},
        )
    nube.refresh_from_db()
    assert nube.status == states.DISPATCHED
    assert run_jobs(in_memory_queue, "tn_fulfillment_update") == 2  # empaquetado y despachado

    # Retiro en el local con transferencia: entra «esperando pago»; cuando TN avisa el pago pasa a Nuevo.
    tn.get("/orders/9002").mock(return_value=httpx.Response(200, json=tn_samples.pickup_order()))
    tn.get("/orders/9002/fulfillment-orders").mock(
        return_value=httpx.Response(200, json=tn_samples.fulfillment_orders("UNPACKED", "pickup"))
    )
    tn.patch("/orders/9002/fulfillment-orders/01HXFO000000000000000000AA").mock(
        return_value=httpx.Response(200, json={})
    )
    tn.post("/orders/9002/fulfillment-orders/01HXFO000000000000000000AA/tracking-events").mock(
        return_value=httpx.Response(201, json={})
    )
    post_hook(client, {"store_id": 8434848, "event": "order/created", "id": 9002})
    run_events(in_memory_queue, capture)
    retiro = SalesDocument.objects.get(channel__code="tiendanube", shipments__method=Shipment.Method.PICKUP)
    assert retiro.status == states.AWAITING_PAYMENT
    assert retiro.pk not in [o.pk for o in dep.get(reverse("sales:prepare")).context["orders"]]
    paid = tn_samples.order(
        order_id=9002,
        number=1235,
        shipping_pickup_type="pickup",
        shipping_option="Retiro en el local",
        shipping_option_code="pickup-local",
        gateway="offline",
        gateway_name="Transferencia bancaria",
        payment_status="paid",
        updated_at="2026-11-12T18:00:00+0000",
    )
    tn.get("/orders/9002").mock(return_value=httpx.Response(200, json=paid))
    post_hook(client, {"store_id": 8434848, "event": "order/updated", "id": 9002})
    run_events(in_memory_queue, capture)
    retiro.refresh_from_db()
    assert retiro.status == states.NEW

    dep.post(reverse("sales:prepare"), {"doc": [retiro.pk]})
    with capture():
        dep.post(reverse("sales:dispatch"), {"action": "listo", "doc": [retiro.pk]})
        dep.post(reverse("sales:dispatch"), {"action": "despachar", "doc": [retiro.pk]})
    retiro.refresh_from_db()
    assert retiro.status == states.READY_FOR_PICKUP  # «Listo para retirar», no «Despachado»
    with capture():
        dep.post(reverse("sales:dispatch"), {"action": "entregar", "doc": [retiro.pk]})
    retiro.refresh_from_db()
    assert retiro.status == states.DELIVERED
    assert (
        run_jobs(in_memory_queue, "tn_fulfillment_update") == 3
    )  # empaquetado, listo para retirar y entregado

    assert_tn_only_wrote_shipping_state(tn)
    assert_only(alerts=["orders.new", "orders.new"], emails=[])
    assert not AuditLog.objects.filter(action="integration.write_blocked").exists()


# ── f) Alertas ───────────────────────────────────────────────────────────────


def test_f_alertas_sin_cobrar_sin_facturar_plazo_flex_y_reclamos_y_el_historico_no_avisa(
    ml, malla, users_by_role, capture
):
    now = timezone.now()
    # 1. Pedidos históricos de todo tipo, con todo lo que haría avisar a uno vivo: ningún aviso.
    for status in (states.NEW, states.PREPARING, states.READY, states.AWAITING_PAYMENT, states.DISPATCHED):
        make_doc("manual", status=status, issued=now - timedelta(days=3))
        make_doc("mayorista", status=status, issued=now - timedelta(days=3))
        flex = make_doc("mercadolibre", status=status)
        Shipment.objects.create(
            document=flex, method=Shipment.Method.ME_FLEX, dispatch_deadline=now + timedelta(minutes=10)
        )
    with capture():
        orders_watch(timestamp=0)
    assert Alert.objects.count() == 0 and OutboundEmail.objects.count() == 0

    # 2. Un pedido manual vivo sin cobrar ni facturar hace más de 24 h: dos avisos, y no se repiten.
    make_doc("manual", historical=False, issued=now - timedelta(hours=30), total="5000")
    with capture():
        assert tasks.check_manual_pending(now=now) == 2
        assert tasks.check_manual_pending(now=now) == 0
    manual_keys = Alert.objects.filter(alert_type__code="orders.manual_pending")
    assert {a.dedupe_key.rsplit(":", 1)[1] for a in manual_keys} == {"pago", "factura"}

    # 3. Flex vivo cerca del plazo: avisa. El histórico de arriba (también cerca del plazo) no avisó.
    stub_ml_order(ml)
    client = MLClient(sleep=lambda s: None)
    live, _ = ml_orders.upsert_order(S.order())
    shipment = ml_shipments.refresh(client, 40001)
    with capture():
        assert tasks.check_flex_due(now=shipment.dispatch_deadline - timedelta(minutes=40)) == 1
    flex_alert = Alert.objects.get(alert_type__code="orders.flex_due")
    assert flex_alert.link_url == f"/pedidos/{live.pk}/"

    # 4. Reclamo de ML: aviso de reclamo nuevo, y aviso de plazo a 4 h del vencimiento (una vez).
    claim = ml_claims.upsert_claim(client, S.claim())
    assert claim.document == live and claim.due_date is not None
    with capture():
        assert conversation_tasks.check_claims_due(now=claim.due_date - timedelta(hours=3)) == 1
        assert conversation_tasks.check_claims_due(now=claim.due_date - timedelta(hours=2)) == 0
    live.refresh_from_db()
    assert live.status == states.CLAIM

    codes = alert_codes()
    assert codes["orders.manual_pending"] == 2 and codes["orders.flex_due"] == 1
    assert codes["ml.claim_opened"] == 1 and codes["ml.claim_due"] == 1
    # Nada más que lo esperado, y ninguno apunta a un pedido histórico.
    assert set(codes) <= {
        "orders.manual_pending",
        "orders.flex_due",
        "ml.claim_opened",
        "ml.claim_due",
        "orders.new",
    }
    historical = {
        f"/pedidos/{pk}/"
        for pk in SalesDocument.objects.filter(is_historical=True).values_list("pk", flat=True)
    }
    assert not Alert.objects.filter(link_url__in=historical).exists()


# ── g) Invitación de un cliente mayorista ────────────────────────────────────


def test_g_invitacion_de_punta_a_punta_en_ensayo_y_con_envio_simulado(
    client, users_by_role, settings, capture
):
    customer = make_customer(1)
    call_command("invitar_mayoristas", "preparar", stdout=io.StringIO())
    account = CustomerAccount.objects.get(customer=customer)
    admin = login(users_by_role[ADMIN])
    send = reverse("wholesale_customers:invitations_send")

    # Apagado por defecto: el botón de enviar no manda nada.
    page = admin.post(send, {"scope": "unsent"}, follow=True)
    assert "Todavía no se habilitó" in page.content.decode()
    assert OutboundEmail.objects.count() == 0

    # Un administrador habilita el envío (sigue sin mandarse nada) y se ensaya con el modo «ensayo».
    admin.post(reverse("wholesale_customers:invitations_switch"), {"enabled": "1"})
    settings.STORE_EMAIL_DRY_RUN = True
    page = admin.post(send, {"scope": "unsent"}, follow=True)
    assert "Ensayo: se mandarían 1 invitaciones" in page.content.decode()
    assert OutboundEmail.objects.count() == 0 and djmail.outbox == []
    assert Invitation.objects.get(account=account).status == Invitation.Status.UNSENT
    assert AuditLog.objects.filter(action="invitation.dry_run").count() == 1

    # Envío real simulado: la invitación queda en la cola; con el correo apagado no sale; encendido, sale una.
    settings.STORE_EMAIL_DRY_RUN = False
    with capture():
        admin.post(send, {"scope": "unsent"})
    email = OutboundEmail.objects.get(template_code="invitation")
    assert email.status == OutboundEmail.Status.PENDING and email.to == customer.email
    assert mail.send_pending() == 0 and djmail.outbox == []  # STORE_EMAILS_ENABLED apagado
    settings.STORE_EMAILS_ENABLED = True
    assert mail.send_pending() == 1
    assert len(djmail.outbox) == 1 and djmail.outbox[0].to == [customer.email]
    link = TOKEN_IN_LINK.search(djmail.outbox[0].body)
    assert link, "el email tiene que traer el enlace de la invitación"
    url = reverse("store:invitation", args=[link.group(1)])

    # El cliente abre el enlace, elige su contraseña, acepta los términos y queda adentro.
    assert "Creá tu contraseña" in client.get(url).content.decode()
    done = client.post(url, {"password1": PASSWORD, "password2": PASSWORD, "accept_terms": "on"})
    assert done.status_code == 302 and done.url == reverse("store:home")
    assert client.get(reverse("store:home")).status_code == 200
    assert client.post(reverse("store:logout")).status_code == 302
    assert authenticate(username=customer.email, password=PASSWORD) is not None

    # El token quedó usado: el mismo enlace ya no sirve (misma pantalla que uno inventado) y no sale otro email.
    again = Client().post(
        url, {"password1": "Otra-Clave-2026", "password2": "Otra-Clave-2026", "accept_terms": "on"}
    )
    assert again.status_code == 200 and "_auth_user_id" not in again.client.session
    invitation = Invitation.objects.get(account=account)
    assert invitation.status == Invitation.Status.ACCEPTED and invitation.token_hash == ""
    assert authenticate(username=customer.email, password="Otra-Clave-2026") is None
    assert len(djmail.outbox) == 1
    assert_only(alerts=[], emails=["invitation"])
    # Y ya puede comprar: entra al catálogo con su cuenta.
    assert customer_session(account).get(reverse("store:home")).status_code == 200


# ── h) Datos de ensayo: seguros, idempotentes y que se limpian ───────────────

COUNTED = [
    Product, Variant, Customer, CustomerAccount, Invitation, SalesDocument, SalesLine, Payment,
    Shipment, StockLevel, StockMovement, PriceListItem, Carrier, OutboundEmail, Alert, Cart, CartItem,
    WholesaleOrder, CustomerBalance, Shortage,
]  # fmt: skip


def counts() -> dict:
    """Cuántas filas hay de cada cosa. Los usuarios se cuentan aparte: la auditoría no se borra, así que un
    usuario de ensayo que figura en ella queda desactivado en lugar de borrarse."""
    data = {model.__name__: model.objects.count() for model in COUNTED}
    data["Usuarios reales o activos"] = User.objects.exclude(
        email__endswith="@ensayo.invalid", is_active=False
    ).count()
    return data


def run_seed(*args) -> str:
    out = io.StringIO()
    call_command("seed_demo_launch", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def real_data(db):
    """Datos «reales» que el ensayo jamás puede tocar: un producto, un cliente y un pedido histórico."""
    product = Product.objects.create(name="Buzo Real")
    Variant.objects.create(product=product, sku="REAL-001")
    historical = make_doc("tiendanube", historical=True)
    SalesDocument.objects.filter(pk=historical.pk).update(
        channel_reference="ENSAYO mal puesto en un histórico"
    )
    return {
        "customer": make_customer(7),
        "historical": historical,
        "products": set(Product.objects.values_list("pk", flat=True)),
        "customers": set(Customer.objects.values_list("pk", flat=True)),
        "users": set(User.objects.values_list("pk", flat=True)),
    }


def test_h_ensayo_se_niega_en_produccion_y_sin_confirmar(settings):
    before = counts()
    for name in ("production", "prod", "Production"):
        settings.ENVIRONMENT_NAME = name
        with pytest.raises(CommandError, match="producción"):
            call_command("seed_demo_launch", "--yes", stdout=io.StringIO())
        with pytest.raises(CommandError, match="producción"):
            call_command("seed_demo_launch", "--yes", "--limpiar", stdout=io.StringIO())
    settings.ENVIRONMENT_NAME = "staging"
    with pytest.raises(CommandError, match="--yes"):
        call_command("seed_demo_launch", stdout=io.StringIO())
    with pytest.raises(CommandError, match="--yes"):
        call_command("seed_demo_launch", "--limpiar", stdout=io.StringIO())
    assert counts() == before


def test_h_ensayo_arma_datos_marcados_sin_emails_sin_avisos_y_sin_tocar_canales(
    real_data, in_memory_queue, settings
):
    settings.ENVIRONMENT_NAME = "staging"
    before = counts()
    with respx.mock(assert_all_called=False) as net:  # cualquier llamada a un canal rompería el test
        out = run_seed("--yes")
    assert not net.calls
    assert OutboundEmail.objects.count() == 0 and Alert.objects.count() == 0 and not in_memory_queue.jobs
    assert djmail.outbox == []
    # Todo lo que creó lleva la marca de ensayo.
    assert (
        not Product.objects.exclude(name__startswith="ENSAYO").exclude(pk__in=real_data["products"]).exists()
    )
    assert Variant.objects.filter(sku__startswith="ENS-").count() == 7
    new_customers = Customer.objects.exclude(pk__in=real_data["customers"])
    assert new_customers.count() == 4 and all(
        c.legal_name.startswith("ENSAYO") and c.email.endswith("@ensayo.invalid") for c in new_customers
    )
    new_users = User.objects.exclude(pk__in=real_data["users"])
    assert new_users.count() == 4 and all(u.email.endswith("@ensayo.invalid") for u in new_users)
    docs = SalesDocument.objects.filter(is_historical=False)
    assert {d.channel.code for d in docs} == {"mercadolibre", "tiendanube", "mayorista"}
    assert docs.filter(channel__code="mayorista").count() == 4
    assert (
        docs.filter(channel__code="mercadolibre").count() == 4
        and docs.filter(channel__code="tiendanube").count() == 3
    )
    assert set(docs.values_list("status", flat=True)) >= {
        states.NEW, states.PREPARING, states.DISPATCHED, states.DELIVERED, states.AWAITING_PAYMENT
    }  # fmt: skip
    # Las contraseñas salen UNA vez en la consola y sirven; la tercera cuenta no tiene (es para invitar).
    passwords = dict(re.findall(r"^\s+(\S+@ensayo\.invalid)\s+→\s+(\S+)$", out, flags=re.M))
    assert set(passwords) == {
        "vendedor@ensayo.invalid", "cliente.uno@ensayo.invalid", "cliente.dos@ensayo.invalid"
    }  # fmt: skip
    for email, password in passwords.items():
        assert len(password) >= 12 and authenticate(username=email, password=password) is not None
        assert password not in str(list(AuditLog.objects.values_list("metadata", "after", "before")))
    tres = User.objects.get(email="cliente.tres@ensayo.invalid")
    assert not tres.has_usable_password() and tres.customer_account.invitation.status == "unsent"
    # La cuenta con cuenta corriente la tiene; la otra no. El vendedor es Vendedor.
    assert CustomerAccount.objects.get(user__email="cliente.dos@ensayo.invalid").credit_enabled
    assert not CustomerAccount.objects.get(user__email="cliente.uno@ensayo.invalid").credit_enabled
    assert User.objects.get(email="vendedor@ensayo.invalid").groups.filter(name=VENDEDOR).exists()
    # Un cliente de ensayo entra a la tienda y ve los productos de ensayo, no más.
    shop = Client()
    shop.post(
        reverse("store:login"),
        {"username": "cliente.uno@ensayo.invalid", "password": passwords["cliente.uno@ensayo.invalid"]},
    )
    html = shop.get(reverse("store:home")).content.decode()
    assert "ENSAYO Malla Entrenamiento" in html and "Buzo Real" not in html
    assert counts() != before


def test_h_ensayo_es_idempotente_y_la_limpieza_deja_todo_como_estaba(real_data, settings):
    settings.ENVIRONMENT_NAME = "staging"
    before = counts()
    first = run_seed("--yes")
    after_first = counts()
    assert "Contraseñas de prueba" in first
    second = run_seed("--yes")
    assert counts() == after_first  # correrlo de nuevo no duplica nada
    assert "Contraseñas de prueba" not in second and "ya existían" in second
    assert "ya estaban" in second  # los pedidos no se arman dos veces
    assert not re.search(r"→\s+\S+", second)  # y no se vuelve a imprimir ninguna clave
    renewed = run_seed("--yes", "--nuevas-claves")
    assert re.search(r"→\s+\S+", renewed) and counts() == after_first

    cleaned = run_seed("--yes", "--limpiar")
    assert "Datos de ensayo borrados" in cleaned
    assert counts() == before  # exactamente lo que había antes
    leftovers = User.objects.filter(email__endswith="@ensayo.invalid")
    assert leftovers.exists() and all(not u.is_active and not u.has_usable_password() for u in leftovers)
    assert set(User.objects.exclude(pk__in=leftovers).values_list("pk", flat=True)) == real_data["users"]
    # Lo real y lo histórico quedaron intactos, aunque el histórico tenga «ENSAYO» en la referencia.
    assert Customer.objects.filter(pk=real_data["customer"].pk).exists()
    assert SalesDocument.objects.filter(pk=real_data["historical"].pk, is_historical=True).exists()
    assert Variant.objects.filter(sku="REAL-001").exists()
    # Y se puede volver a armar y volver a borrar.
    run_seed("--yes")
    assert counts() == after_first
    run_seed("--yes", "--limpiar")
    assert counts() == before


def test_h_ensayo_la_limpieza_no_borra_nada_si_algo_real_depende_de_un_dato_de_ensayo(real_data, settings):
    settings.ENVIRONMENT_NAME = "staging"
    run_seed("--yes")
    variant = Variant.objects.filter(sku__startswith="ENS-").first()
    historical = real_data["historical"]
    SalesLine.objects.create(
        document=historical,
        variant=variant,
        sku_snapshot=variant.sku,
        description_snapshot="x",
        quantity=1,
        unit_price=1,
    )  # un histórico real usa un producto de ensayo
    seeded = counts()
    with pytest.raises(CommandError, match="No se borró nada"):
        run_seed("--yes", "--limpiar")
    assert counts() == seeded
    assert SalesDocument.objects.filter(pk=historical.pk).exists()


def test_h_los_datos_de_ensayo_disparan_solo_el_aviso_de_plazo_flex_esperado(settings, capture):
    settings.ENVIRONMENT_NAME = "staging"
    run_seed("--yes")
    assert Alert.objects.count() == 0
    with capture():
        orders_watch(timestamp=0)
    # Un Flex vence en 1 h (avisa); el otro, en 26 h (todavía no). Nada sin cobrar: los pedidos son de hoy.
    assert alert_codes() == Counter({"orders.flex_due": 1})
    assert "ENSAYO ML Flex 1" in Alert.objects.get().title
