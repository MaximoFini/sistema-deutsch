"""M8a · Tienda mayorista, etapa A (T9–T13): pagos y vencimiento, pedidos en nombre de clientes, Mi cuenta,
faltantes y reportes mayoristas. Más las correcciones de la revisión en el navegador del lote 1."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.roles import ADMIN, DEPOSITO, VENDEDOR, VENTAS
from apps.alerts.models import Alert
from apps.audit.models import AuditLog
from apps.fulfillment import batches, dispatch
from apps.inventory.models import StockLevel, StockMovement
from apps.sales import manual, states
from apps.sales.models import Payment, SalesDocument, Shipment
from apps.wholesale import accounts, acting, checkout, payments, shortages
from apps.wholesale import cart as cart_service
from apps.wholesale.access import ACTING_SESSION_KEY, Shopper
from apps.wholesale.models import (
    Cart,
    CartItem,
    CustomerBalance,
    OutboundEmail,
    PaymentReceipt,
    Shortage,
    StoreSettings,
    WholesaleOrder,
)
from apps.wholesale.tasks import payment_deadlines
from tests.test_mayorista import (
    PASSWORD,
    _place,
    fill_cart,
    make_cuit,
    registration_data,
    set_stock,
    set_wholesale,
)

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture(autouse=True)
def _clear_cache():
    """Las opciones de filtro del catálogo se guardan en caché: cada test arranca limpio."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def malla(db):
    """Malla con 2 talles × 2 colores: precio mayorista 10.000 neto y stock 5 por variante."""
    from apps.catalog.models import Product, Variant

    product = Product.objects.create(
        name="Malla Entrenamiento",
        brand="Deutsch",
        categories=["Mallas"],
        images=[{"url": "https://cdn.test/malla.jpg", "position": 1}],
    )
    variants = {}
    for size in ("S", "M"):
        for color in ("Azul", "Negro"):
            v = Variant.objects.create(
                product=product,
                sku=f"MAL-{size}-{color[:3].upper()}",
                attributes={"Talle": size, "Color": color},
            )
            set_wholesale(v, Decimal("10000"))
            set_stock(v, 5)
            variants[(size, color)] = v
    return product, variants


@pytest.fixture
def staff(users_by_role):
    return users_by_role


@pytest.fixture
def customer(staff):
    """Cliente aprobado con mínimo de compra bajo."""
    account = accounts.register(data=registration_data(), password=PASSWORD)
    accounts.approve(account, user=staff[ADMIN])
    account.refresh_from_db()
    row = StoreSettings.load()
    row.min_order_amount = Decimal("1000")
    row.save()
    return account


@pytest.fixture
def other_customer(staff):
    account = accounts.register(
        data=registration_data(
            cuit=make_cuit("20", "44444444"),
            email="otro@cliente.test",
            legal_name="Club Otro SA",
            trade_name="Club Otro",
        ),
        password=PASSWORD,
    )
    accounts.approve(account, user=staff[ADMIN])
    account.refresh_from_db()
    return account


def login(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def order_for(account, malla, items=None, **kw):
    _, variants = malla
    fill_cart(account, items or {variants[("S", "Azul")]: 2})
    return _place(account, **kw)


def move(doc, *targets):
    for to in targets:
        states.change_status(doc, to, system=True)
    doc.refresh_from_db()
    return doc


def reserved(variant) -> Decimal:
    return StockLevel.objects.get(variant=variant).reserved


def receipt_file(name="comprobante.png", content=PNG, content_type="image/png"):
    return SimpleUploadedFile(name, content, content_type=content_type)


# ── T9: comprobantes ─────────────────────────────────────────────────────────


def test_t9_upload_receipt_valid_private_and_alerts(customer, malla, django_capture_on_commit_callbacks):
    doc = order_for(customer, malla)
    client = login(customer.user)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("store:receipt_upload", args=[doc.number]), {"file": receipt_file()}, follow=True
        )
    assert "Recibimos el comprobante" in response.content.decode()
    receipt = PaymentReceipt.objects.get(document=doc)
    assert receipt.original_name == "comprobante.png" and receipt.size == len(PNG)
    assert receipt.file.name.startswith("comprobantes/") and receipt.file.name.endswith(".png")
    assert receipt.file.storage.__class__.__name__ == "InMemoryStorage"  # el privado de tests, no MEDIA
    assert Alert.objects.filter(alert_type__code="wholesale.receipt_uploaded").exists()
    assert AuditLog.objects.filter(action="wholesale.receipt_uploaded", object_id=str(doc.pk)).exists()


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("comprobante.pdf", b"esto no es un pdf", "No pudimos leer el archivo"),
        ("comprobante.png", PDF, "No pudimos leer el archivo"),  # extensión y contenido no coinciden
        ("comprobante.exe", PNG, "foto (JPG, PNG o WEBP) o un PDF"),
        ("vacio.pdf", b"", "vacío"),
    ],
)
def test_t9_upload_receipt_invalid(customer, malla, name, content, message):
    doc = order_for(customer, malla)
    response = login(customer.user).post(
        reverse("store:receipt_upload", args=[doc.number]),
        {"file": SimpleUploadedFile(name, content)},
        follow=True,
    )
    assert message in response.content.decode()
    assert not PaymentReceipt.objects.exists()


def test_t9_upload_receipt_too_big(customer, malla):
    doc = order_for(customer, malla)
    big = SimpleUploadedFile("grande.pdf", PDF + b"0" * (payments.MAX_RECEIPT_BYTES + 1))
    with pytest.raises(payments.PaymentError, match="10 MB"):
        payments.upload_receipt(doc, big, user=customer.user)
    assert not PaymentReceipt.objects.exists()


def test_t9_receipt_only_for_owner_and_payment_confirmers(customer, other_customer, malla, staff):
    doc = order_for(customer, malla)
    receipt = payments.upload_receipt(doc, receipt_file(), user=customer.user)
    store_url = reverse("store:receipt", args=[doc.number, receipt.pk])
    response = login(customer.user).get(store_url)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PNG
    assert response["Content-Type"] == "image/png" and response["X-Content-Type-Options"] == "nosniff"
    assert login(other_customer.user).get(store_url).status_code == 404
    # Un vendedor comprando «en nombre de» el cliente no ve los comprobantes.
    seller = login(staff[VENDEDOR])
    session = seller.session
    session[ACTING_SESSION_KEY] = customer.customer_id
    session.save()
    assert seller.get(store_url).status_code == 404
    panel_url = reverse("wholesale_orders:receipt", args=[doc.pk, receipt.pk])
    assert login(staff[ADMIN]).get(panel_url).status_code == 200
    for role in (VENTAS, DEPOSITO, VENDEDOR):
        assert login(staff[role]).get(panel_url).status_code == 403
    assert login(customer.user).get(panel_url).status_code == 302  # un cliente nunca entra al panel


def test_t9_upload_only_while_awaiting_payment(customer, malla, staff):
    doc = order_for(customer, malla)
    payments.confirm_payment(doc, user=staff[ADMIN])
    with pytest.raises(payments.PaymentError, match="ya no está esperando el pago"):
        payments.upload_receipt(doc, receipt_file(), user=customer.user)


# ── T9: confirmar pago, reserva y M4 ────────────────────────────────────────


def test_t9_confirm_payment_from_order_page(customer, malla, staff, django_capture_on_commit_callbacks):
    _, variants = malla
    doc = order_for(customer, malla)
    payments.upload_receipt(doc, receipt_file(), user=customer.user)
    admin = login(staff[ADMIN])
    page = admin.get(reverse("sales:detail", args=[doc.pk])).content.decode()
    assert "Pago por transferencia" in page and "Confirmar pago" in page and "comprobante.png" in page
    assert 'value="new"' not in page  # no se saltea la confirmación con «Pasar a Nuevo»
    with django_capture_on_commit_callbacks(execute=True):
        response = admin.post(reverse("wholesale_orders:confirm_payment", args=[doc.pk]))
    assert response.status_code == 302
    doc.refresh_from_db()
    assert doc.status == states.NEW and doc.ready_at is not None
    payment = doc.payments.get()
    assert payment.status == Payment.Status.CONFIRMED and payment.paid_at and payment.amount == doc.total
    assert reserved(variants[("S", "Azul")]) == 2  # la reserva sigue hasta facturar
    assert OutboundEmail.objects.filter(template_code="payment_confirmed", to=customer.user.email).exists()
    assert Alert.objects.filter(alert_type__code="orders.new", dedupe_key=f"new:{doc.pk}").exists()
    log = AuditLog.objects.get(action="order.status_changed", object_id=str(doc.pk))
    assert log.actor == staff[ADMIN]
    assert AuditLog.objects.filter(action="payment.confirmed", actor=staff[ADMIN]).exists()
    # Dos veces no: ya no espera el pago.
    with pytest.raises(payments.PaymentError):
        payments.confirm_payment(doc, user=staff[ADMIN])


def test_t9_confirm_payment_permission(customer, malla, staff):
    doc = order_for(customer, malla)
    for role in (VENTAS, DEPOSITO, VENDEDOR):
        response = login(staff[role]).post(reverse("wholesale_orders:confirm_payment", args=[doc.pk]))
        assert response.status_code == 403
    doc.refresh_from_db()
    assert doc.status == states.AWAITING_PAYMENT


def test_t9_invoice_releases_reservation_once(customer, malla, staff):
    _, variants = malla
    a = variants[("S", "Azul")]
    doc = order_for(customer, malla)
    payments.confirm_payment(doc, user=staff[ADMIN])
    admin = login(staff[ADMIN])
    url = reverse("sales:manual_edit", args=[doc.pk, "factura"])
    admin.post(url, {"invoiced": "1", "invoice_number": "A-0001-00001234"})
    doc.refresh_from_db()
    assert doc.invoiced_in_contabilium and doc.invoice_number == "A-0001-00001234"
    assert reserved(a) == 0
    order = WholesaleOrder.objects.get(document=doc)
    assert order.reservation_released_at is not None
    admin.post(url, {"invoiced": "1", "invoice_number": "A-0001-00001235"})  # de nuevo: no libera otra vez
    assert StockMovement.objects.filter(reference_id=str(doc.pk), kind="release").count() == 1
    assert reserved(a) == 0


def test_t9_cancel_from_order_center_releases_and_returns_balance(
    customer, malla, staff, django_capture_on_commit_callbacks
):
    _, variants = malla
    CustomerBalance.objects.create(customer=customer.customer, amount=Decimal("3000"))
    doc = order_for(customer, malla)
    assert CustomerBalance.balance_for(customer.customer) == 0
    admin = login(staff[ADMIN])
    page = admin.get(reverse("sales:detail", args=[doc.pk])).content.decode()
    assert 'value="cancelled"' in page  # M4 cancela pedidos mayoristas como los manuales
    with django_capture_on_commit_callbacks(execute=True):
        admin.post(
            reverse("sales:status", args=[doc.pk]), {"to": "cancelled", "reason": "Lo pidió el cliente"}
        )
    doc.refresh_from_db()
    assert doc.status == states.CANCELLED
    assert reserved(variants[("S", "Azul")]) == 0
    assert CustomerBalance.balance_for(customer.customer) == Decimal("3000")
    order = WholesaleOrder.objects.get(document=doc)
    assert order.reservation_released_at and order.balance_returned_at
    payments.on_cancelled(doc)  # idempotente
    assert CustomerBalance.balance_for(customer.customer) == Decimal("3000")
    assert reserved(variants[("S", "Azul")]) == 0


def test_t9_seller_cannot_cancel_and_tiendanube_still_cannot(customer, malla, staff):
    doc = order_for(customer, malla)
    with pytest.raises(states.TransitionNotAllowed):
        states.change_status(doc, states.CANCELLED, user=staff[VENDEDOR])
    assert states.CANCELLED not in states.allowed_transitions(doc, staff[DEPOSITO])


def test_t9_payment_and_invoice_editable_like_manual(customer, malla, staff):
    doc = order_for(customer, malla)
    with pytest.raises(manual.ManualOrderError, match="confirmá el pago"):
        manual.update_payment(doc, paid=True, method="transfer", user=staff[ADMIN])
    payments.confirm_payment(doc, user=staff[ADMIN])
    doc.refresh_from_db()
    manual.update_payment(doc, paid=False, method="transfer", user=staff[ADMIN])
    assert doc.payments.get().status == Payment.Status.PENDING  # el mismo pago, no uno nuevo
    page = login(staff[ADMIN]).get(reverse("sales:detail", args=[doc.pk])).content.decode()
    assert "Facturación" in page and "Cuenta corriente" in page


# ── T9: vencimiento y recordatorio ──────────────────────────────────────────


def test_t9_expiry_cancels_releases_and_notifies(customer, malla, django_capture_on_commit_callbacks):
    _, variants = malla
    CustomerBalance.objects.create(customer=customer.customer, amount=Decimal("1000"))
    doc = order_for(customer, malla)
    order = WholesaleOrder.objects.get(document=doc)
    assert reserved(variants[("S", "Azul")]) == 2
    with django_capture_on_commit_callbacks(execute=True):
        assert payments.expire_orders(now=order.expires_at - timedelta(minutes=1)) == {
            "expired": 0,
            "with_receipt": 0,
        }
        result = payments.expire_orders(now=order.expires_at + timedelta(minutes=1))
    assert result["expired"] == 1
    assert WholesaleOrder.objects.get(document=doc).expired_at is not None
    doc.refresh_from_db()
    assert doc.status == states.CANCELLED
    assert reserved(variants[("S", "Azul")]) == 0
    assert CustomerBalance.balance_for(customer.customer) == Decimal("1000")
    assert OutboundEmail.objects.filter(template_code="order_expired", to=customer.user.email).exists()
    assert Alert.objects.filter(
        alert_type__code="wholesale.order_expired", dedupe_key=f"expired:{doc.pk}"
    ).exists()
    log = AuditLog.objects.get(action="order.status_changed", object_id=str(doc.pk))
    assert log.actor is None and "Venció" in log.metadata["motivo"]


def test_t9_expiry_with_receipt_only_alerts(customer, malla):
    doc = order_for(customer, malla)
    payments.upload_receipt(doc, receipt_file(), user=customer.user)
    order = WholesaleOrder.objects.get(document=doc)
    result = payments.expire_orders(now=order.expires_at + timedelta(hours=1))
    assert result == {"expired": 0, "with_receipt": 1}
    doc.refresh_from_db()
    assert doc.status == states.AWAITING_PAYMENT
    assert Alert.objects.filter(dedupe_key=f"expired-receipt:{doc.pk}").exists()


def test_t9_reminder_once_a_day_before(customer, malla):
    doc = order_for(customer, malla)
    order = WholesaleOrder.objects.get(document=doc)
    assert payments.send_reminders(now=order.expires_at - timedelta(hours=30)) == 0
    assert payments.send_reminders(now=order.expires_at - timedelta(hours=20)) == 1
    assert payments.send_reminders(now=order.expires_at - timedelta(hours=10)) == 0
    email = OutboundEmail.objects.get(template_code="payment_reminder")
    assert doc.channel_reference in email.body_text
    assert payments.BANK_DETAILS_MISSING in email.body_text  # sin datos bancarios, el aviso claro


def test_t9_no_reminder_if_receipt_uploaded(customer, malla):
    doc = order_for(customer, malla)
    payments.upload_receipt(doc, receipt_file(), user=customer.user)
    order = WholesaleOrder.objects.get(document=doc)
    assert payments.send_reminders(now=order.expires_at - timedelta(hours=2)) == 0


def test_t9_periodic_task_runs(customer, malla):
    order_for(customer, malla)
    assert payment_deadlines(timestamp=0) == {"reminders": 0, "expired": 0, "with_receipt": 0}


# ── T9: efectivo y despacho ──────────────────────────────────────────────────


def test_t9_cash_pickup_collected_at_delivery(customer, malla, staff):
    doc = order_for(customer, malla, payment="cash", delivery="pickup", carrier="")
    move(doc, states.PREPARING, states.READY, states.READY_FOR_PICKUP)
    deposito = login(staff[DEPOSITO])
    page = deposito.get(reverse("sales:dispatch")).content.decode()
    assert "Cobrar $" in page and "en efectivo" in page and f'name="cash" value="{doc.pk}"' in page
    deposito.post(reverse("sales:dispatch"), {"action": "entregar", "doc": [doc.pk]})
    doc.refresh_from_db()
    assert doc.status == states.READY_FOR_PICKUP  # sin tildar «Cobré» no se entrega
    deposito.post(reverse("sales:dispatch"), {"action": "entregar", "doc": [doc.pk], "cash": [doc.pk]})
    doc.refresh_from_db()
    assert doc.status == states.DELIVERED
    assert doc.payments.get().status == Payment.Status.CONFIRMED


def test_t9_cash_collected_from_order_page(customer, malla, staff):
    doc = order_for(customer, malla, payment="cash", delivery="pickup", carrier="")
    admin = login(staff[ADMIN])
    assert "Cobrar $" in admin.get(reverse("sales:detail", args=[doc.pk])).content.decode()
    assert (
        login(staff[VENDEDOR]).post(reverse("wholesale_orders:cash_collected", args=[doc.pk])).status_code
        == 403
    )
    admin.post(reverse("wholesale_orders:cash_collected", args=[doc.pk]))
    assert doc.payments.get().status == Payment.Status.CONFIRMED
    result = dispatch.advance([doc.pk], dispatch.LISTO, user=staff[ADMIN])
    assert result.failed  # sigue en Nuevo: no está En preparación


def test_t9_wholesale_orders_in_center_and_preparation(customer, malla, staff):
    doc = order_for(customer, malla, payment="cash", delivery="pickup", carrier="")
    admin = login(staff[ADMIN])
    listing = admin.get(reverse("sales:list"), {"canal": "mayorista"}).content.decode()
    assert doc.channel_reference in listing and 'value="mayorista"' in listing and "#7c3aed" in listing
    assert doc in batches.preparable_orders()
    batch, excluded = batches.create_batch([doc.pk], user=staff[ADMIN])
    assert batch is not None and not excluded


# ── Correcciones de la revisión del lote 1 ───────────────────────────────────


def test_fix_bank_details_fallback_in_store_and_panel(customer, malla, staff):
    _, variants = malla
    fill_cart(customer, {variants[("S", "Azul")]: 1})
    client = login(customer.user)
    checkout_page = client.get(reverse("store:checkout")).content.decode()
    assert payments.BANK_DETAILS_MISSING in checkout_page
    doc = _place(customer)
    done = client.get(reverse("store:order_done", args=[doc.number])).content.decode()
    assert payments.BANK_DETAILS_MISSING in done and "Transferí el total" not in done
    assert (
        payments.BANK_DETAILS_MISSING in OutboundEmail.objects.get(template_code="order_received").body_text
    )
    admin = login(staff[ADMIN])
    assert (
        "Faltan los datos bancarios de la tienda"
        in admin.get(reverse("store_admin:settings")).content.decode()
    )
    assert (
        "Faltan los datos bancarios de la tienda"
        in admin.get(reverse("sales:detail", args=[doc.pk])).content.decode()
    )
    row = StoreSettings.load()
    row.bank_details = "CBU 0000003100000000000001\nAlias DEUTSCH.MAYORISTA"
    row.save()
    done = client.get(reverse("store:order_done", args=[doc.number])).content.decode()
    assert "DEUTSCH.MAYORISTA" in done and payments.BANK_DETAILS_MISSING not in done
    assert "Faltan los datos bancarios" not in admin.get(reverse("store_admin:settings")).content.decode()
    assert (
        "Faltan los datos bancarios" not in admin.get(reverse("sales:detail", args=[doc.pk])).content.decode()
    )


def test_fix_broken_images_fall_back_to_placeholder(customer, malla):
    product, _ = malla
    client = login(customer.user)
    catalog_page = client.get(reverse("store:home")).content.decode()
    assert 'onerror="this.hidden=true;this.nextElementSibling.hidden=false"' in catalog_page
    assert ">Sin foto</div>" in catalog_page  # el reemplazo ya está en la tarjeta, oculto
    detail = client.get(reverse("store:product", args=[product.pk])).content.decode()
    assert "onerror=" in detail and "Sin foto" in detail


# ── T10: pedidos en nombre de clientes ──────────────────────────────────────


def test_t10_seller_orders_on_behalf_without_minimum(
    customer, malla, staff, django_capture_on_commit_callbacks
):
    _, variants = malla
    row = StoreSettings.load()
    row.min_order_amount = Decimal("999999")
    row.save()
    fill_cart(customer, {variants[("M", "Negro")]: 1})  # el cliente ya tenía algo
    seller = login(staff[VENDEDOR])
    page = seller.get(reverse("store:acting"), {"q": customer.cuit[:6]}).content.decode()
    assert "Natatorio Ejemplo" in page
    response = seller.post(reverse("store:acting"), {"account": customer.pk}, follow=True)
    content = response.content.decode()
    assert (
        "Estás armando un pedido para" in content and "ya tenía 1 unidad" in content and "Terminar" in content
    )
    cart = Cart.objects.get(customer=customer.customer)
    assert cart.acting_user == staff[VENDEDOR]
    # El cliente ve el aviso de carrito compartido.
    assert (
        "también lo está editando Deutsch" in login(customer.user).get(reverse("store:cart")).content.decode()
    )
    seller.post(
        reverse("store:add_to_cart", args=[variants[("S", "Azul")].product_id]),
        {f"qty-{variants[('S', 'Azul')].pk}": "1"},
    )
    cart_page = seller.get(reverse("store:cart"))
    assert cart_page.context["summary"].min_applies is False
    snapshot = seller.get(reverse("store:checkout")).context["form"].initial["snapshot"]
    with django_capture_on_commit_callbacks(execute=True):
        response = seller.post(
            reverse("store:checkout"), {"delivery": "pickup", "payment": "cash", "snapshot": snapshot}
        )
    doc = SalesDocument.objects.get(channel__code="mayorista")
    order = WholesaleOrder.objects.get(document=doc)
    assert order.placed_by == staff[VENDEDOR] and order.on_behalf
    assert AuditLog.objects.get(action="wholesale.order_placed").actor == staff[VENDEDOR]
    # El cliente lo ve como «Cargado por Deutsch».
    account_page = login(customer.user).get(reverse("store:account")).content.decode()
    assert doc.channel_reference in account_page and "Cargado por Deutsch" in account_page
    seller.post(reverse("store:acting_stop"))
    assert ACTING_SESSION_KEY not in seller.session
    cart.refresh_from_db()
    assert cart.acting_user is None
    assert seller.get(reverse("store:home")).status_code == 403  # ya no compra en nombre de nadie


def test_t10_only_sellers_and_admins(customer, staff):
    for role in (DEPOSITO, VENTAS):
        assert login(staff[role]).get(reverse("store:acting")).status_code == 403
    assert login(customer.user).get(reverse("store:acting")).status_code == 302  # cliente → tienda
    assert login(staff[ADMIN]).get(reverse("store:acting")).status_code == 200
    pending = accounts.register(
        data=registration_data(cuit=make_cuit("27", "55555555"), email="p@x.test"), password=PASSWORD
    )
    response = login(staff[VENDEDOR]).post(reverse("store:acting"), {"account": pending.pk}, follow=True)
    assert "no tiene la cuenta aprobada" in response.content.decode()


def test_t10_manual_order_for_wholesale_customer_redirects(customer, malla, staff):
    _, variants = malla
    data = {
        "customer_id": customer.customer_id,
        "variant_id": [variants[("S", "Azul")].pk],
        "quantity": ["1"],
        "price": [""],
        "delivery": "pickup",
    }
    response = login(staff[ADMIN]).post(reverse("sales:manual_create"), data)
    assert response.status_code == 302 and response.url.startswith(reverse("store:acting"))
    response = login(staff[VENTAS]).post(reverse("sales:manual_create"), data)
    assert response.status_code == 400 and "vendedor" in response.content.decode()


def test_t10_seller_sees_wholesale_customers_and_orders(customer, malla, staff):
    doc = order_for(customer, malla)
    seller = login(staff[VENDEDOR])
    detail = seller.get(reverse("wholesale_customers:detail", args=[customer.pk])).content.decode()
    assert doc.channel_reference in detail and "Armar un pedido en su nombre" in detail
    assert seller.get(reverse("sales:detail", args=[doc.pk])).status_code == 200


# ── T11: Mi cuenta ───────────────────────────────────────────────────────────


def test_t11_account_history_with_client_statuses(customer, malla, staff):
    awaiting = order_for(customer, malla)
    preparing = move(
        order_for(customer, malla, payment="cash", delivery="pickup", carrier=""), states.PREPARING
    )
    CustomerBalance.objects.create(
        customer=customer.customer, amount=Decimal("2500"), note="Saldo por faltante"
    )
    page = login(customer.user).get(reverse("store:account")).content.decode()
    assert awaiting.channel_reference in page and preparing.channel_reference in page
    assert "Esperando tu pago" in page and "En preparación" in page
    assert "$ 2.500,00" in page and "Saldo por faltante" in page
    assert customer.cuit[:2] in page and "Pedir un cambio de datos" in page


def test_t11_order_detail_invoice_tracking_and_isolation(customer, other_customer, malla, staff):
    doc = order_for(customer, malla)
    payments.confirm_payment(doc, user=staff[ADMIN])
    manual.update_invoice(doc, invoiced=True, number="A-0001-00000077", user=staff[ADMIN])
    Shipment.objects.filter(document=doc).update(tracking_number="VC-123456")
    client = login(customer.user)
    page = client.get(reverse("store:order_detail", args=[doc.number])).content.decode()
    assert "A-0001-00000077" in page and "La factura te llega por email desde Contabilium" in page
    assert "VC-123456" in page and "En preparación" in page
    assert login(other_customer.user).get(reverse("store:order_detail", args=[doc.number])).status_code == 404


def test_t11_order_detail_lets_upload_while_awaiting(customer, malla):
    doc = order_for(customer, malla)
    page = login(customer.user).get(reverse("store:order_detail", args=[doc.number])).content.decode()
    assert "Subí el comprobante de la transferencia" in page and payments.BANK_DETAILS_MISSING in page


def test_t11_repeat_order_uses_current_stock_and_prices(customer, malla):
    _, variants = malla
    a, b = variants[("S", "Azul")], variants[("M", "Negro")]
    doc = order_for(customer, malla, items={a: 2, b: 3})
    set_wholesale(a, Decimal("12000"))
    set_stock(b, 4)  # 3 reservadas por el pedido: queda 1 disponible
    response = login(customer.user).post(reverse("store:repeat", args=[doc.number]), follow=True)
    content = response.content.decode()
    assert "Cargamos el pedido en el carrito" in content and "Solo podés pedir hasta 1" in content
    items = dict(
        CartItem.objects.filter(cart__customer=customer.customer).values_list("variant_id", "quantity")
    )
    assert items == {a.pk: 2, b.pk: 1}
    summary = cart_service.summarize(Cart.objects.get(customer=customer.customer))
    assert {line.net for line in summary.lines} == {Decimal("12000.00"), Decimal("10000.00")}


def test_t11_change_request_alerts_admins(customer, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        login(customer.user).post(reverse("store:change_request"), {"text": "Nos mudamos a Funes"})
    alert = Alert.objects.get(alert_type__code="wholesale.data_change_requested")
    assert "Nos mudamos a Funes" in alert.body and str(customer.pk) in alert.link_url
    assert AuditLog.objects.filter(action="client.change_requested").exists()


def test_t11_dispatched_and_pickup_emails_by_signal(
    customer, malla, staff, django_capture_on_commit_callbacks
):
    carrier_doc = order_for(customer, malla, payment="cash", delivery="pickup", carrier="")
    move(carrier_doc, states.PREPARING, states.READY)
    with django_capture_on_commit_callbacks(execute=True):
        states.change_status(carrier_doc, states.READY_FOR_PICKUP, system=True)
    email = OutboundEmail.objects.get(template_code="ready_for_pickup")
    assert "en efectivo" in email.body_text and carrier_doc.channel_reference in email.subject
    accounts.set_credit(customer, enabled=True, user=staff[ADMIN])
    customer.refresh_from_db()
    ship_doc = order_for(customer, malla, payment="account", delivery="carrier")
    move(ship_doc, states.PREPARING, states.READY)
    Shipment.objects.filter(document=ship_doc).update(tracking_number="VC-999")
    with django_capture_on_commit_callbacks(execute=True):
        states.change_status(ship_doc, states.DISPATCHED, system=True)
    email = OutboundEmail.objects.get(template_code="dispatched")
    assert "VC-999" in email.body_text and "Expreso Rosario" in email.body_text


# ── T12: faltantes ───────────────────────────────────────────────────────────


def _preparing_paid(customer, malla, staff, items=None):
    doc = order_for(customer, malla, items=items)
    payments.confirm_payment(doc, user=staff[ADMIN])
    return move(doc, states.PREPARING)


def test_t12_report_shortage(customer, malla, staff, django_capture_on_commit_callbacks):
    doc = _preparing_paid(customer, malla, staff)
    line = doc.lines.get()
    deposito = login(staff[DEPOSITO])
    form = deposito.get(reverse("wholesale_orders:shortage_report", args=[doc.pk]))
    assert form.status_code == 200 and line.sku_snapshot in form.content.decode()
    with django_capture_on_commit_callbacks(execute=True):
        deposito.post(reverse("wholesale_orders:shortage_report", args=[doc.pk]), {f"missing_{line.pk}": "1"})
    doc.refresh_from_db()
    assert doc.status == states.AWAITING_CUSTOMER
    shortage = Shortage.objects.get(document=doc)
    assert (
        shortage.missing_quantity == 1
        and shortage.reported_by == staff[DEPOSITO]
        and shortage.sku == line.sku_snapshot
    )
    email = OutboundEmail.objects.get(template_code="shortage_query")
    assert line.sku_snapshot in email.body_text and email.to == customer.user.email
    assert Alert.objects.filter(alert_type__code="wholesale.shortage_reported").exists()
    # No se puede saltear con «Pasar a»: solo cancelar mientras haya un faltante abierto.
    assert states.allowed_transitions(doc, staff[ADMIN]) == [states.CANCELLED]
    assert (
        login(staff[VENDEDOR]).get(reverse("wholesale_orders:shortage_report", args=[doc.pk])).status_code
        == 403
    )


def test_t12_report_only_in_preparation_and_valid_quantity(customer, malla, staff):
    doc = order_for(customer, malla)
    line = doc.lines.get()
    with pytest.raises(shortages.ShortageError, match="En preparación"):
        shortages.report(doc, {line.pk: 1}, user=staff[DEPOSITO])
    payments.confirm_payment(doc, user=staff[ADMIN])
    move(doc, states.PREPARING)
    with pytest.raises(shortages.ShortageError, match="entre 0 y 2"):
        shortages.report(doc, {line.pk: 5}, user=staff[DEPOSITO])
    with pytest.raises(shortages.ShortageError, match="al menos un producto"):
        shortages.report(doc, {}, user=staff[DEPOSITO])


def test_t12_resolve_with_credit_balance(customer, malla, staff):
    _, variants = malla
    a = variants[("S", "Azul")]
    doc = _preparing_paid(customer, malla, staff)  # 2 × 10.000 + IVA = 24.200
    line = doc.lines.get()
    shortages.report(doc, {line.pk: 1}, user=staff[DEPOSITO])
    admin = login(staff[ADMIN])
    page = admin.get(reverse("wholesale_orders:shortage_resolve", args=[doc.pk])).content.decode()
    assert "ya pagado" in page and "Saldo a favor" in page
    url = reverse("wholesale_orders:shortage_resolve", args=[doc.pk])
    response = admin.post(url, {f"qty_{line.pk}": "1"})
    assert response.status_code == 400 and "elegí si queda como saldo a favor" in response.content.decode()
    admin.post(url, {f"qty_{line.pk}": "1", "difference": "credit"})
    doc.refresh_from_db()
    assert doc.status == states.PREPARING and doc.total == Decimal("12100.00")
    assert CustomerBalance.balance_for(customer.customer) == Decimal("12100.00")
    assert reserved(a) == 1  # se liberó solo la diferencia
    shortage = Shortage.objects.get(document=doc)
    assert shortage.resolved_at and shortage.resolution["diferencia"]["tipo"] == "saldo a favor"
    assert AuditLog.objects.filter(action="wholesale.shortage_resolved", actor=staff[ADMIN]).exists()
    # El saldo se descuenta solo en el próximo pedido y se ve en Mi cuenta.
    assert "$ 12.100,00" in login(customer.user).get(reverse("store:account")).content.decode()
    next_doc = order_for(customer, malla, items={variants[("M", "Azul")]: 1})
    assert next_doc.discount_total == Decimal("12100.00") and next_doc.total == Decimal("0.00")


def test_t12_resolve_with_refund_remove_and_replace(customer, malla, staff):
    _, variants = malla
    a, b, c = variants[("S", "Azul")], variants[("M", "Negro")], variants[("M", "Azul")]
    doc = _preparing_paid(customer, malla, staff, items={a: 2, b: 1})
    line_a = doc.lines.get(variant=a)
    line_b = doc.lines.get(variant=b)
    shortages.report(doc, {line_b.pk: 1}, user=staff[DEPOSITO])
    set_wholesale(c, Decimal("5000"))
    result = shortages.resolve(
        doc,
        quantities={line_a.pk: 2, line_b.pk: 0},
        replacements=[shortages.Replacement(c, 1)],
        difference="refund",
        refund_reference="Transferencia 778899",
        user=staff[ADMIN],
    )
    doc.refresh_from_db()
    assert not doc.lines.filter(variant=b).exists()
    new_line = doc.lines.get(variant=c)
    assert new_line.unit_price == Decimal("5000.00")
    assert doc.total == Decimal("30250.00")  # (20.000 + 5.000) × 1,21
    assert (
        result["diferencia"]["tipo"] == "reintegro"
        and result["diferencia"]["referencia"] == "Transferencia 778899"
    )
    assert result["diferencia"]["monto"] == "6050.00"
    assert CustomerBalance.balance_for(customer.customer) == 0
    assert reserved(b) == 0 and reserved(c) == 1 and reserved(a) == 2
    shortage = Shortage.objects.get(document=doc)
    assert shortage.line is None and shortage.sku == line_b.sku_snapshot  # la línea se quitó, el dato queda


def test_t12_resolve_invoiced_marks_contabilium_correction(
    customer, malla, staff, django_capture_on_commit_callbacks
):
    _, variants = malla
    a = variants[("S", "Azul")]
    doc = _preparing_paid(customer, malla, staff)
    manual.update_invoice(doc, invoiced=True, number="A-1", user=staff[ADMIN])
    assert reserved(a) == 0
    line = doc.lines.get()
    shortages.report(doc, {line.pk: 2}, user=staff[DEPOSITO])
    set_wholesale(variants[("M", "Azul")], Decimal("10000"))
    with django_capture_on_commit_callbacks(execute=True):
        shortages.resolve(
            doc,
            quantities={line.pk: 0},
            replacements=[shortages.Replacement(variants[("M", "Azul")], 2)],
            user=staff[ADMIN],
        )
    order = WholesaleOrder.objects.get(document=doc)
    assert order.needs_contabilium_correction
    assert Alert.objects.filter(alert_type__code="wholesale.contabilium_correction").exists()
    assert reserved(a) == 0 and reserved(variants[("M", "Azul")]) == 0  # Contabilium ya descuenta
    page = login(staff[ADMIN]).get(reverse("sales:detail", args=[doc.pk])).content.decode()
    assert "Corregir en Contabilium" in page


def test_t12_resolve_errors(customer, malla, staff):
    _, variants = malla
    doc = _preparing_paid(customer, malla, staff)
    line = doc.lines.get()
    with pytest.raises(shortages.ShortageError, match="no tiene un faltante"):
        shortages.resolve(doc, quantities={line.pk: 1}, user=staff[ADMIN])
    shortages.report(doc, {line.pk: 1}, user=staff[DEPOSITO])
    with pytest.raises(shortages.ShortageError, match="quedaría sin productos"):
        shortages.resolve(doc, quantities={line.pk: 0}, user=staff[ADMIN])
    with pytest.raises(shortages.ShortageError, match="disponibles"):
        shortages.resolve(
            doc, quantities={line.pk: 2}, replacements=[shortages.Replacement(variants[("M", "Negro")], 50)],
            user=staff[ADMIN],
        )  # fmt: skip
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        shortages.resolve(doc, quantities={line.pk: 1}, user=staff[DEPOSITO])
    doc.refresh_from_db()
    assert doc.status == states.AWAITING_CUSTOMER  # nada quedó a medias
    assert doc.lines.get().quantity == 2


def test_t12_shortage_from_batch_and_dispatch(customer, malla, staff):
    doc = order_for(customer, malla, payment="cash", delivery="pickup", carrier="")
    batch, _ = batches.create_batch([doc.pk], user=staff[ADMIN])
    deposito = login(staff[DEPOSITO])
    url = reverse("wholesale_orders:shortage_report", args=[doc.pk])
    assert url in deposito.get(reverse("sales:batch_detail", args=[batch.number])).content.decode()
    assert url in deposito.get(reverse("sales:dispatch")).content.decode()


# ── T13: reportes mayoristas ─────────────────────────────────────────────────


def test_t13_wholesale_report_and_excel(customer, other_customer, malla, staff):
    _, variants = malla
    paid = order_for(customer, malla)  # transferencia del cliente
    payments.confirm_payment(paid, user=staff[ADMIN])
    awaiting = order_for(other_customer, malla, items={variants[("M", "Azul")]: 1})
    expired = order_for(other_customer, malla, items={variants[("M", "Negro")]: 1})
    WholesaleOrder.objects.filter(document=awaiting).update(expires_at=timezone.now() + timedelta(days=30))
    payments.expire_orders(now=WholesaleOrder.objects.get(document=expired).expires_at + timedelta(minutes=5))
    shopper = Shopper(account=customer, user=staff[VENDEDOR], acting=True)
    fill_cart(customer, {variants[("S", "Negro")]: 1})
    on_behalf = _place(
        customer,
        shopper=shopper,
        payment="cash",
        delivery="pickup",
        carrier="",
        snapshot=checkout.sign_snapshot(cart_service.summarize(shopper.cart(), apply_min=False)),
    )
    CustomerBalance.objects.create(customer=customer.customer, amount=Decimal("1500"))
    admin = login(staff[ADMIN])
    response = admin.get(reverse("reports:wholesale"))
    assert response.status_code == 200
    data = response.context["data"]
    by_customer = {r["clave"]: r for r in data["customers"]}
    assert by_customer["Natatorio Ejemplo"]["pedidos"] == 2
    assert by_customer["Club Otro"]["pedidos"] == 1  # sin el vencido (cancelado)
    sellers = {r["clave"]: r["pedidos"] for r in data["sellers"]}
    assert sellers[staff[VENDEDOR].full_name] == 1 and sellers["El cliente (en la tienda)"] == 2
    assert [r["pedido"] for r in data["awaiting"]] == [awaiting.channel_reference]
    assert [r["pedido"] for r in data["expired"]] == [expired.channel_reference]
    assert {r["pedido"] for r in data["not_invoiced"]} == {
        paid.channel_reference,
        on_behalf.channel_reference,
    }
    assert data["balances"] == [{"clave": "Natatorio Ejemplo", "saldo": Decimal("1500.00")}]
    content = response.content.decode()
    assert "Mayorista" in content and "Saldos a favor vigentes" in content
    excel = admin.get(reverse("reports:wholesale_excel"))
    wb = load_workbook(io.BytesIO(excel.content), read_only=True)
    assert wb.sheetnames == [
        "Ventas por cliente",
        "Ventas por quién cargó",
        "Esperando pago",
        "Vencidos",
        "Sin facturar",
        "Saldos a favor",
    ]
    rows = list(wb["Ventas por cliente"].iter_rows(values_only=True))
    assert rows[1][0] == "Cliente" and rows[-1][0] == "Total"


def test_t13_permissions_and_channel_in_existing_reports(customer, malla, staff):
    order_for(customer, malla, payment="cash", delivery="pickup", carrier="")
    for role in (VENDEDOR, DEPOSITO, VENTAS):
        assert login(staff[role]).get(reverse("reports:wholesale")).status_code == 403
    admin = login(staff[ADMIN])
    sales_page = admin.get(reverse("reports:sales"), {"canal": "mayorista"})
    assert sales_page.status_code == 200 and not sales_page.context["f"].warnings
    assert sales_page.context["table"]["totals"]["pedidos"] == 1
    assert 'value="mayorista"' in sales_page.content.decode()


def test_golden_rule_operations_never_write_channels(customer, malla, staff):
    """Confirmar, facturar, faltante y vencer: nada escribe stock ni precios en Tiendanube o ML."""
    from unittest import mock

    with mock.patch(
        "apps.integrations.guard.ensure_write_allowed", side_effect=AssertionError("escritura")
    ) as guard:
        doc = _preparing_paid(customer, malla, staff)
        line = doc.lines.get()
        shortages.report(doc, {line.pk: 1}, user=staff[DEPOSITO])
        shortages.resolve(doc, quantities={line.pk: 1}, difference="credit", user=staff[ADMIN])
        manual.update_invoice(doc, invoiced=True, number="A-9", user=staff[ADMIN])
        other = order_for(customer, malla, items={malla[1][("M", "Azul")]: 1})
        payments.expire_orders(
            now=WholesaleOrder.objects.get(document=other).expires_at + timedelta(minutes=1)
        )
    assert not guard.called


def test_acting_helper_shared_notice_expires(customer, staff):
    cart, _ = Cart.objects.get_or_create(customer=customer.customer)
    cart.acting_user = staff[VENDEDOR]
    cart.acting_since = timezone.now() - acting.SHARED_CART_NOTICE - timedelta(minutes=1)
    cart.save()
    assert not acting.shared_with_deutsch(cart)
    cart.acting_since = timezone.now()
    cart.save()
    assert acting.shared_with_deutsch(cart)
