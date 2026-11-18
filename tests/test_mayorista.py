"""M8a · Tienda mayorista, etapa A (T1–T8): base, marca, accesos, registro, emails, catálogo, carrito y checkout."""

import re
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from django.conf import settings as dj_settings
from django.contrib.auth.models import Group
from django.core import mail as djmail
from django.test import Client, override_settings
from django.urls import reverse

from apps.accounts.roles import ADMIN, DEPOSITO, VENDEDOR, VENTAS
from apps.alerts.models import Alert, AlertType
from apps.audit.models import AuditLog
from apps.catalog.models import Product, Variant
from apps.customers.models import Customer
from apps.fulfillment.models import Carrier
from apps.inventory.models import StockLevel, StockMovement
from apps.inventory.services import apply_sync_level, change_reserved, default_warehouse
from apps.pricing.models import PriceList, PriceListItem
from apps.sales import states
from apps.sales.models import Payment, SalesDocument, Shipment
from apps.wholesale import accounts, catalog, checkout, mail
from apps.wholesale import cart as cart_service
from apps.wholesale.access import Shopper
from apps.wholesale.models import (
    CartItem,
    CustomerAccount,
    CustomerBalance,
    EmailTemplate,
    OutboundEmail,
    PaymentReceipt,
    StoreSettings,
    WholesaleOrder,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Natacion-Mayorista-2026"


@pytest.fixture(autouse=True)
def _clear_cache():
    """Las opciones de filtro del catálogo se guardan 5 minutos en caché: cada test arranca limpio."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def make_cuit(prefix="30", body="71234567") -> str:
    """CUIT válido (calcula el dígito verificador). Cambia el cuerpo si el dígito daría 10."""
    while True:
        digits = prefix + body
        total = sum(int(d) * w for d, w in zip(digits, accounts.CUIT_WEIGHTS, strict=True))
        check = 11 - total % 11
        if check == 11:
            check = 0
        if check != 10:
            return digits + str(check)
        body = str(int(body) + 1).zfill(8)


def registration_data(**over):
    data = {
        "cuit": make_cuit(),
        "legal_name": "Natatorio Ejemplo SRL",
        "trade_name": "Natatorio Ejemplo",
        "vat_condition": "RI",
        "street": "Av. Siempreviva",
        "number": "742",
        "city": "Rosario",
        "province": "Santa Fe",
        "postal_code": "2000",
        "phone": "341 555-1234",
        "email": "compras@natatorio.test",
        "password1": PASSWORD,
        "password2": PASSWORD,
        "accept_terms": "on",
        "website": "",
    }
    data.update(over)
    return data


# ── Datos de catálogo ────────────────────────────────────────────────────────


def set_wholesale(variant, price):
    PriceListItem.objects.create(
        price_list=PriceList.objects.get(code="MAYORISTA"), variant=variant, price=price
    )


def set_stock(variant, on_hand):
    apply_sync_level(variant, default_warehouse(), on_hand)


@pytest.fixture
def malla(db):
    """Malla con 2 talles × 2 colores: precio mayorista 10.000 neto y stock 5 por variante."""
    product = Product.objects.create(
        name="Malla Entrenamiento",
        brand="Deutsch",
        categories=["Mallas", "Mujer"],
        images=[{"url": "https://cdn.test/malla.jpg", "position": 1}],
        description="<p>Malla <b>resistente</b> al cloro</p>",
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
def approved(admin_user):
    """Cliente aprobado (registrado por la tienda y aprobado por un administrador)."""
    data = registration_data()
    account = accounts.register(data=data, password=PASSWORD)
    accounts.approve(account, user=admin_user)
    account.refresh_from_db()
    return account


@pytest.fixture
def customer_client(approved):
    client = Client()
    client.force_login(approved.user)
    return client


def shopper_for(account, user=None, acting=False):
    return Shopper(account=account, user=user or account.user, acting=acting)


def fill_cart(account, items: dict):
    cart = shopper_for(account).cart()
    for variant, qty in items.items():
        CartItem.objects.update_or_create(cart=cart, variant=variant, defaults={"quantity": qty})
    return cart


@pytest.fixture
def low_min(db):
    row = StoreSettings.load()
    row.min_order_amount = Decimal("1000")
    row.save()
    return row


# ── T1: base ─────────────────────────────────────────────────────────────────


def test_t1_settings_templates_and_alerts_seeded():
    row = StoreSettings.load()
    assert row.min_order_amount == Decimal("300000") and row.transfer_expiry_days == 3
    assert row.safety_margin_units == 0 and not row.min_order_includes_vat
    codes = set(EmailTemplate.objects.values_list("code", flat=True))
    assert codes == {
        "registration_received",
        "registration_approved",
        "registration_rejected",
        "order_received",
        "payment_confirmed",
        "payment_reminder",
        "order_expired",
        "shortage_query",
        "dispatched",
        "ready_for_pickup",
        "invitation",
    }
    for code in [
        "wholesale.registration_new",
        "wholesale.receipt_uploaded",
        "wholesale.order_expired",
        "wholesale.shortage_reported",
        "wholesale.contabilium_correction",
    ]:
        alert_type = AlertType.objects.get(code=code)
        assert list(alert_type.roles.values_list("name", flat=True)) == [ADMIN]


@pytest.mark.parametrize(
    ("perm", "expected"),
    [
        ("wholesale.view_customeraccount", {ADMIN, VENTAS, VENDEDOR}),
        ("wholesale.manage_customers", {ADMIN}),
        ("wholesale.confirm_payment", {ADMIN}),
        ("wholesale.order_on_behalf", {ADMIN, VENDEDOR}),
        ("wholesale.report_shortage", {ADMIN, VENTAS, DEPOSITO}),
        ("wholesale.resolve_shortage", {ADMIN}),
        ("wholesale.manage_store", {ADMIN}),
    ],
)
def test_t1_permissions_by_role(users_by_role, perm, expected):
    assert {role for role, user in users_by_role.items() if user.has_perm(perm)} == expected


def test_t1_permission_labels_in_spanish():
    from apps.accounts.roles import PERMISSION_LABELS, ROLE_PERMISSIONS

    used = {p for perms in ROLE_PERMISSIONS.values() for p in perms if p.startswith("wholesale.")}
    assert used and all(p in PERMISSION_LABELS for p in used)


def test_t1_receipts_use_private_storage_outside_media():
    from apps.wholesale.storage import private_storage

    field = PaymentReceipt._meta.get_field("file")
    storage = field.storage
    assert storage is not None and storage == private_storage() or callable(field._storage_callable)
    media = Path(dj_settings.MEDIA_ROOT).resolve()
    private = Path(dj_settings.PRIVATE_MEDIA_ROOT).resolve()
    assert media not in private.parents and private != media


# ── T2: marca ────────────────────────────────────────────────────────────────

STATIC = Path(dj_settings.BASE_DIR) / "static"


def _hex_to_lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = sorted([_hex_to_lum(a), _hex_to_lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_t2_brand_assets_and_tokens():
    for name in ["deutsch-logo.svg", "deutsch-logo-negativo.svg", "deutsch-isotipo.svg", "tokens.css"]:
        assert (STATIC / "brand" / name).exists(), name
    svg = (STATIC / "brand" / "deutsch-logo.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and "#007DC5" in svg and "<path" in svg
    tokens = dict(
        re.findall(r"--(brand-[\w-]+):\s*(#[0-9a-fA-F]{6})", (STATIC / "brand" / "tokens.css").read_text())
    )
    assert tokens["brand-blue"].lower() == "#007dc5" and tokens["brand-ink"].lower() == "#231f20"
    # WCAG AA (4,5:1) para texto normal y botones.
    white = "#ffffff"
    pairs = [
        (tokens["brand-ink"], white),
        (tokens["brand-blue-text"], white),
        (white, tokens["brand-blue-text"]),
        (tokens["brand-ink"], tokens["brand-water"]),
        (tokens["brand-blue-text"], tokens["brand-water-50"]),
        (tokens["brand-gray-600"], white),
        (tokens["brand-gray-600"], tokens["brand-water-50"]),
        (tokens["brand-success"], tokens["brand-success-bg"]),
        (tokens["brand-warning"], tokens["brand-warning-bg"]),
        (tokens["brand-danger"], tokens["brand-danger-bg"]),
    ]
    for fg, bg in pairs:
        assert contrast(fg, bg) >= 4.5, (fg, bg, contrast(fg, bg))


def test_t2_store_base_has_brand(client):
    html = client.get(reverse("store:login")).content.decode()
    assert "Source+Sans+3" in html and "brand/deutsch-logo.svg" in html
    assert "Pasión por la natación" in html and "DEUTSCH" not in html


def test_t2_style_page_only_for_internal_users(client, admin_user, approved):
    url = reverse("store:style")
    response = client.get(url)
    assert response.status_code == 302 and reverse("accounts:login") in response.url
    client.force_login(approved.user)
    assert client.get(url).url == reverse("store:home")
    client.force_login(admin_user)
    response = client.get(url)
    assert response.status_code == 200 and "Sistema de diseño" in response.content.decode()


# ── T3: rutas y accesos ──────────────────────────────────────────────────────


def test_t3_anonymous_sees_only_public_pages(client, malla):
    product, _ = malla
    for name, args in [
        ("store:home", []),
        ("store:product", [product.pk]),
        ("store:cart", []),
        ("store:checkout", []),
    ]:
        response = client.get(reverse(name, args=args))
        assert response.status_code == 302 and response.url.startswith(reverse("store:login")), name
    for name in ["store:login", "store:register", "store:password_reset", "store:terms", "store:privacy"]:
        assert client.get(reverse(name)).status_code == 200, name


def test_t3_customer_never_enters_panel(customer_client):
    for name in ["core:home", "sales:list", "alerts:list", "wholesale_customers:list"]:
        response = customer_client.get(reverse(name))
        assert response.status_code == 302 and response.url == reverse("store:home"), name


def test_t3_customer_login_on_panel_goes_to_store(approved):
    client = Client()
    response = client.post(reverse("accounts:login"), {"username": approved.user.email, "password": PASSWORD})
    assert response.status_code == 302
    assert client.get(response.url).url == reverse("store:home")


def test_t3_internal_user_does_not_buy_as_customer(client, users_by_role, malla):
    client.force_login(users_by_role[VENTAS])
    response = client.get(reverse("store:home"))
    assert response.status_code == 403
    assert "Los usuarios internos no compran como clientes" in response.content.decode()


def test_t3_store_login_and_logout(client, approved):
    response = client.post(reverse("store:login"), {"username": approved.user.email, "password": "otra"})
    assert "El email o la contraseña no son correctos" in response.content.decode()
    response = client.post(reverse("store:login"), {"username": approved.user.email, "password": PASSWORD})
    assert response.status_code == 302 and response.url == reverse("store:home")
    assert client.post(reverse("store:logout")).url == reverse("store:login")


def test_t3_pending_and_suspended(client, admin_user):
    account = accounts.register(data=registration_data(), password=PASSWORD)
    client.force_login(account.user)
    assert client.get(reverse("store:home")).url == reverse("store:pending")
    assert "pendiente de aprobación" in client.get(reverse("store:pending")).content.decode()
    accounts.approve(account, user=admin_user)
    assert client.get(reverse("store:home")).status_code == 200
    accounts.set_suspended(account, suspended=True, user=admin_user)
    response = client.get(reverse("store:home"), follow=True)
    assert "Tu cuenta está suspendida, escribinos" in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_t3_lockout_uses_store_template(approved, settings):
    with override_settings(AXES_ENABLED=True):
        client = Client()
        response = None
        for _ in range(settings.AXES_FAILURE_LIMIT + 1):
            response = client.post(
                reverse("store:login"), {"username": approved.user.email, "password": "mala-123"}
            )
    content = response.content.decode()
    assert response.status_code in (403, 429)
    assert "Ingreso bloqueado por un rato" in content and "st-body" in content


def test_t3_password_reset_with_store_templates(client, approved):
    response = client.post(reverse("store:password_reset"), {"email": approved.user.email})
    assert response.url == reverse("store:password_reset_done")
    assert len(djmail.outbox) == 1
    body = djmail.outbox[0].body
    assert "/mayorista/recuperar/" in body and "Deutsch" in body


def test_t3_legal_pages_from_settings(client):
    row = StoreSettings.load()
    row.terms_text = "Pedido mínimo y condiciones de venta."
    row.save()
    assert "Pedido mínimo y condiciones" in client.get(reverse("store:terms")).content.decode()
    assert "terminando de redactar" in client.get(reverse("store:privacy")).content.decode()


@override_settings(
    WHOLESALE_HOST="mayoristas.deutsch.test", ALLOWED_HOSTS=["mayoristas.deutsch.test", "testserver"]
)
def test_t3_own_host_serves_store_at_root(client, approved):
    response = client.get("/ingresar/", HTTP_HOST="mayoristas.deutsch.test")
    assert response.status_code == 200 and 'action="/salir/"' not in response.content.decode()
    assert client.get("/pedidos/", HTTP_HOST="mayoristas.deutsch.test").status_code == 404
    client.force_login(approved.user)
    response = client.get("/", HTTP_HOST="mayoristas.deutsch.test")
    assert response.status_code == 200 and 'action="/salir/"' in response.content.decode()


# ── T4: registro y aprobación ────────────────────────────────────────────────


@pytest.mark.parametrize("cuit", ["20-12345678-0", "2012345678", "99-12345678-1", "abc", "30-71234567-2"])
def test_t4_invalid_cuit(cuit):
    assert make_cuit() == "30712345671"  # el válido; "…-2" cambia solo el dígito verificador
    with pytest.raises(ValueError, match="El CUIT no es válido: revisá los 11 números"):
        accounts.validate_cuit(cuit)


def test_t4_valid_cuit_normalized():
    raw = make_cuit("20", "12345678")
    formatted = f"{raw[:2]}-{raw[2:10]}-{raw[10]}"
    assert accounts.validate_cuit(formatted) == raw
    assert accounts.validate_cuit("20-17254359-7") == "20172543597"  # CUIT real de ejemplo con DV conocido


def test_t4_register_creates_pending_account(client, roles, admin_user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse("store:register"), registration_data(), follow=True)
    assert "Te avisamos por email cuando aprobemos tu cuenta" in response.content.decode()
    account = CustomerAccount.objects.get()
    assert account.status == "pending" and account.customer is None
    assert account.registration["city"] == "Rosario" and account.user.check_password(PASSWORD)
    assert not account.user.groups.exists() and not account.user.is_staff
    assert Alert.objects.filter(alert_type__code="wholesale.registration_new").exists()
    email = OutboundEmail.objects.get(template_code="registration_received")
    assert email.status == "pending" and email.to == "compras@natatorio.test"
    assert AuditLog.objects.filter(action="client.registered").exists()


def test_t4_register_invalid_cuit_and_duplicate(client, approved):
    response = client.post(
        reverse("store:register"), registration_data(cuit="20-12345678-0", email="otro@x.test")
    )
    assert "El CUIT no es válido: revisá los 11 números" in response.content.decode()
    response = client.post(reverse("store:register"), registration_data(email="otro@x.test"))
    content = response.content.decode()
    assert "Ese CUIT ya tiene una cuenta" in content and reverse("store:password_reset") in content
    assert CustomerAccount.objects.count() == 1


def test_t4_honeypot_creates_nothing(client):
    response = client.post(reverse("store:register"), registration_data(website="http://spam.test"))
    assert response.url == reverse("store:register_done")
    assert not CustomerAccount.objects.exists()


def test_t4_rate_limit_per_ip(client, settings):
    settings.WHOLESALE_REGISTRATIONS_PER_IP_HOUR = 2
    for i in range(2):
        data = registration_data(cuit=make_cuit("20", f"3000000{i}"), email=f"c{i}@x.test")
        assert client.post(reverse("store:register"), data).status_code == 302
    data = registration_data(cuit=make_cuit("20", "30000009"), email="c9@x.test")
    response = client.post(reverse("store:register"), data)
    assert response.status_code == 200 and "muchos registros seguidos" in response.content.decode()
    assert CustomerAccount.objects.count() == 2


def test_t4_approve_links_existing_customer(admin_user):
    data = registration_data()
    existing = Customer.objects.create(legal_name="Natatorio (manual)", tax_id=data["cuit"], phone="")
    account = accounts.register(data=data, password=PASSWORD)
    customer = accounts.approve(account, user=admin_user)
    assert customer.pk == existing.pk and Customer.objects.filter(tax_id=data["cuit"]).count() == 1
    customer.refresh_from_db()
    assert customer.kind == Customer.Kind.WHOLESALE and customer.legal_name == "Natatorio (manual)"
    assert customer.phone == "341 555-1234"  # completa lo vacío, no pisa lo que había
    assert customer.price_list.code == "MAYORISTA"
    assert OutboundEmail.objects.filter(template_code="registration_approved").exists()
    log = AuditLog.objects.get(action="client.approved")
    assert log.after["vinculado_a_existente"] is True


def test_t4_approve_creates_customer_with_address(admin_user):
    account = accounts.register(data=registration_data(), password=PASSWORD)
    customer = accounts.approve(account, user=admin_user)
    assert customer.kind == Customer.Kind.WHOLESALE and customer.tax_id_type == "CUIT"
    assert customer.addresses.get(kind="fiscal").city == "Rosario"


def test_t4_reject_requires_reason_and_emails(admin_user):
    account = accounts.register(data=registration_data(), password=PASSWORD)
    with pytest.raises(accounts.AccountError):
        accounts.reject(account, reason=" ", user=admin_user)
    accounts.reject(account, reason="El CUIT no corresponde a un comercio", user=admin_user)
    account.refresh_from_db()
    assert account.status == "rejected"
    email = OutboundEmail.objects.get(template_code="registration_rejected")
    assert "El CUIT no corresponde a un comercio" in email.body_text


def test_t4_panel_queue_and_permissions(client, users_by_role):
    account = accounts.register(data=registration_data(), password=PASSWORD)
    client.force_login(users_by_role[VENDEDOR])
    response = client.get(reverse("wholesale_customers:list"))
    assert response.status_code == 200 and "Natatorio Ejemplo" in response.content.decode()
    assert client.get(reverse("wholesale_customers:detail", args=[account.pk])).status_code == 200
    action = reverse("wholesale_customers:action", args=[account.pk])
    assert client.post(action, {"action": "approve"}).status_code == 403
    client.force_login(users_by_role[DEPOSITO])
    assert client.get(reverse("wholesale_customers:list")).status_code == 403
    client.force_login(users_by_role[ADMIN])
    client.post(
        reverse("wholesale_customers:detail", args=[account.pk]),
        {**registration_data(), "cuit": account.cuit, "city": "Funes"},
    )
    account.refresh_from_db()
    assert account.registration["city"] == "Funes"
    client.post(action, {"action": "approve"})
    client.post(action, {"action": "credit_on"})
    account.refresh_from_db()
    assert account.status == "approved" and account.credit_enabled and account.customer.credit_enabled
    assert account.customer.addresses.get(kind="fiscal").city == "Funes"


# ── T5: cola de emails ───────────────────────────────────────────────────────


def test_t5_queue_without_smtp_stays_pending():
    email = mail.enqueue("payment_confirmed", "c@x.test", {"cliente": "Club", "pedido": "Mayorista #7"})
    assert email.status == "pending" and "Mayorista #7" in email.subject
    assert "<html" in email.body_html and "Pasión por la natación" in email.body_html
    assert mail.send_pending() == 0 and not djmail.outbox


def test_t5_queue_with_smtp_sends(settings):
    settings.STORE_EMAILS_ENABLED = True
    mail.enqueue("payment_confirmed", "c@x.test", {"cliente": "Club", "pedido": "Mayorista #7"})
    assert mail.send_pending() == 1
    message = djmail.outbox[0]
    assert message.to == ["c@x.test"] and message.alternatives[0][1] == "text/html"
    assert OutboundEmail.objects.get().status == "sent"


def test_t5_retries_then_alerts(settings, roles):
    settings.STORE_EMAILS_ENABLED = True
    mail.enqueue("payment_confirmed", "c@x.test", {"cliente": "Club"})
    with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("SMTP caído")):
        for _ in range(mail.MAX_ATTEMPTS):
            mail.send_pending()
    email = OutboundEmail.objects.get()
    assert email.status == "failed" and email.attempts == 5 and "SMTP caído" in email.last_error
    assert Alert.objects.filter(alert_type__code="wholesale.email_failed").count() == 1


def test_t5_template_variables_are_safe():
    assert mail.render_text("Hola {cliente} {cliente.__class__} {nada}", {"cliente": "Ana"}) == (
        "Hola Ana {cliente.__class__} {nada}"
    )
    html = mail.render("registration_rejected", {"cliente": "<script>x</script>", "motivo": "m"})[2]
    assert "<script>x" not in html


def test_t5_panel_templates_and_queue(client, users_by_role):
    client.force_login(users_by_role[ADMIN])
    url = reverse("store_admin:email_template_edit", args=["payment_confirmed"])
    assert client.get(url).status_code == 200
    client.post(url, {"subject": "Pago OK {pedido}", "body": "Gracias {cliente}"})
    assert EmailTemplate.objects.get(code="payment_confirmed").subject == "Pago OK {pedido}"
    assert AuditLog.objects.filter(action="wholesale.email_template_changed").exists()
    mail.enqueue("payment_confirmed", "c@x.test", {"cliente": "Club", "pedido": "#1"})
    response = client.get(reverse("store_admin:outbound_emails"))
    assert "Pago OK #1" in response.content.decode() and "pendiente de envío" in response.content.decode()
    response = client.post(
        reverse("store_admin:settings"),
        {
            "min_order_amount": "250000",
            "transfer_expiry_days": "3",
            "safety_margin_units": "1",
            "bank_details": "CBU 0",
        },
    )
    assert response.status_code == 302 and StoreSettings.load().min_order_amount == Decimal("250000")
    client.force_login(users_by_role[VENDEDOR])
    assert client.get(reverse("store_admin:outbound_emails")).status_code == 403


# ── T6: catálogo ─────────────────────────────────────────────────────────────


def test_t6_only_products_with_wholesale_price(customer_client, malla):
    sin_precio = Product.objects.create(name="Gorra sin precio")
    v = Variant.objects.create(product=sin_precio, sku="GOR-0")
    set_wholesale(v, Decimal("0"))
    set_stock(v, 10)
    inactivo = Product.objects.create(name="Antiparras viejas", is_active=False)
    v2 = Variant.objects.create(product=inactivo, sku="ANT-0")
    set_wholesale(v2, Decimal("500"))
    response = customer_client.get(reverse("store:home"))
    names = [p.name for p in response.context["products"]]
    assert names == ["Malla Entrenamiento"]
    content = response.content.decode()
    assert "$ 10.000,00" in content and "+ IVA 21 %" in content and "https://cdn.test/malla.jpg" in content


def test_t6_net_price_when_list_includes_vat(settings, malla):
    _, variants = malla
    v = variants[("S", "Azul")]
    settings.CONTABILIUM_WHOLESALE_INCLUDES_VAT = True
    set_wholesale(v, Decimal("12100"))
    assert catalog.net_price(v) == Decimal("10000.00")
    settings.CONTABILIUM_WHOLESALE_INCLUDES_VAT = False
    assert catalog.net_price(v) == Decimal("12100.00")


def test_t6_availability_with_reservations_and_margin(malla):
    _, variants = malla
    v = variants[("S", "Azul")]
    change_reserved(v, default_warehouse(), 3)
    assert catalog.available(v) == 2
    row = StoreSettings.load()
    row.safety_margin_units = 2
    row.save()
    assert catalog.available(v) == 0
    assert catalog.available(variants[("M", "Negro")]) == 3


def test_t6_sold_out_products_go_last(customer_client, malla):
    agotado = Product.objects.create(name="Aaa Antiparras")  # primero por nombre, pero agotado
    v = Variant.objects.create(product=agotado, sku="ANT-1")
    set_wholesale(v, Decimal("100"))
    set_stock(v, 0)
    response = customer_client.get(reverse("store:home"))
    products = list(response.context["products"])
    assert [p.name for p in products] == ["Malla Entrenamiento", "Aaa Antiparras"]
    assert products[1].has_available is False and "Agotado" in response.content.decode()


def test_t6_filters_and_search(customer_client, malla):
    otro = Product.objects.create(name="Gorro silicona", brand="Otra", categories=["Accesorios"])
    v = Variant.objects.create(product=otro, sku="GSI-1", attributes={"Talle": "U"})
    set_wholesale(v, Decimal("100"))
    set_stock(v, 3)
    url = reverse("store:home")

    def names(params):
        return [p.name for p in customer_client.get(url, params).context["products"]]

    assert names({"q": "MAL-S"}) == ["Malla Entrenamiento"]
    assert names({"q": "silicona"}) == ["Gorro silicona"]
    assert names({"categoria": "Accesorios"}) == ["Gorro silicona"]
    assert names({"marca": "Deutsch"}) == ["Malla Entrenamiento"]
    assert names({"talle": "M"}) == ["Malla Entrenamiento"]
    options = customer_client.get(url).context["options"]
    assert options["sizes"] == ["S", "M", "U"] and "Mallas" in options["categories"]


def test_t6_pagination(customer_client):
    for i in range(catalog.PAGE_SIZE + 2):
        p = Product.objects.create(name=f"Producto {i:02d}")
        v = Variant.objects.create(product=p, sku=f"P-{i}")
        set_wholesale(v, Decimal("10"))
        set_stock(v, 1)
    response = customer_client.get(reverse("store:home"))
    assert len(response.context["products"]) == catalog.PAGE_SIZE
    assert len(customer_client.get(reverse("store:home"), {"page": 2}).context["products"]) == 2


def test_t6_product_detail_grid(customer_client, malla):
    product, variants = malla
    set_stock(variants[("M", "Negro")], 0)
    response = customer_client.get(reverse("store:product", args=[product.pk]))
    grid = response.context["grid"]
    assert grid.sizes == ["S", "M"] and grid.colors == ["Azul", "Negro"]
    content = response.content.decode()
    sold_out = re.search(rf'name="qty-{variants[("M", "Negro")].pk}"[^>]*>', content).group(0)
    assert "disabled" in sold_out
    assert "<b>" not in content and "resistente" in content  # descripción de TN como texto
    assert 'max="5"' in content


# ── T7: grilla y carrito ─────────────────────────────────────────────────────


def test_t7_add_to_cart_limits_to_available(customer_client, malla, approved):
    product, variants = malla
    a, b = variants[("S", "Azul")], variants[("S", "Negro")]
    response = customer_client.post(
        reverse("store:add_to_cart", args=[product.pk]), {f"qty-{a.pk}": "8", f"qty-{b.pk}": "2"}, follow=True
    )
    assert "Solo podés pedir hasta 5 de Malla Entrenamiento S / Azul." in response.content.decode()
    assert cart_service.quantities_in_cart(shopper_for(approved).cart()) == {a.pk: 5, b.pk: 2}
    # 0 quita la variante; otra variante ajena al producto no se agrega.
    otro = Variant.objects.create(product=Product.objects.create(name="X"), sku="X-1")
    set_wholesale(otro, Decimal("1"))
    customer_client.post(
        reverse("store:add_to_cart", args=[product.pk]), {f"qty-{a.pk}": "0", f"qty-{otro.pk}": "1"}
    )
    assert cart_service.quantities_in_cart(shopper_for(approved).cart()) == {b.pk: 2}


def test_t7_invalid_quantity_message(customer_client, malla):
    product, variants = malla
    response = customer_client.post(
        reverse("store:add_to_cart", args=[product.pk]),
        {f"qty-{variants[('S', 'Azul')].pk}": "-1"},
        follow=True,
    )
    assert "no pueden ser negativas" in response.content.decode()


def test_t7_cart_persists_between_sessions(malla, approved):
    _, variants = malla
    fill_cart(approved, {variants[("S", "Azul")]: 3})
    other = Client()
    other.force_login(approved.user)
    summary = other.get(reverse("store:cart")).context["summary"]
    assert summary.units == 3 and summary.subtotal == Decimal("30000.00")
    assert summary.vat == Decimal("6300.00") and summary.total == Decimal("36300.00")


def test_t7_minimum_with_and_without_vat(customer_client, malla, approved):
    _, variants = malla
    fill_cart(approved, {variants[("S", "Azul")]: 5, variants[("S", "Negro")]: 5, variants[("M", "Azul")]: 5})
    row = StoreSettings.load()
    row.min_order_amount = Decimal("170000")
    row.save()
    response = customer_client.get(reverse("store:cart"))
    summary = response.context["summary"]
    assert summary.subtotal == Decimal("150000.00") and not summary.can_checkout
    assert "Te faltan $ 20.000,00 para llegar al mínimo" in response.content.decode()
    assert customer_client.get(reverse("store:checkout")).url == reverse("store:cart")
    row.min_order_includes_vat = True
    row.save()
    summary = customer_client.get(reverse("store:cart")).context["summary"]
    assert summary.gross == Decimal("181500.00") and summary.can_checkout


def test_t7_cart_shows_balance(customer_client, malla, approved):
    _, variants = malla
    fill_cart(approved, {variants[("S", "Azul")]: 1})
    CustomerBalance.objects.create(customer=approved.customer, amount=Decimal("2000"))
    summary = customer_client.get(reverse("store:cart")).context["summary"]
    assert summary.balance_applied == Decimal("2000") and summary.total == Decimal("10100.00")


def test_t7_cart_update_and_remove(customer_client, malla, approved):
    _, variants = malla
    a, b = variants[("S", "Azul")], variants[("M", "Azul")]
    fill_cart(approved, {a: 1, b: 1})
    customer_client.post(reverse("store:cart_update"), {f"qty-{a.pk}": "4", f"qty-{b.pk}": "1"})
    customer_client.post(reverse("store:cart_update"), {"remove": str(b.pk)})
    assert cart_service.quantities_in_cart(shopper_for(approved).cart()) == {a.pk: 4}


# ── T8: checkout y reserva ───────────────────────────────────────────────────


def _snapshot(account):
    return checkout.sign_snapshot(cart_service.summarize(shopper_for(account).cart()))


def _place(account, payment="transfer", delivery="carrier", carrier="Expreso Rosario", **kw):
    shopper = kw.pop("shopper", None) or shopper_for(account)
    return checkout.place_order(
        shopper,
        delivery=checkout.Delivery(method=delivery, carrier_name=carrier),
        payment_method=payment,
        snapshot=kw.pop("snapshot", None) or _snapshot(account),
        **kw,
    )


def test_t8_transfer_order_frozen_prices_and_reservation(
    malla, approved, low_min, django_capture_on_commit_callbacks
):
    _, variants = malla
    a = variants[("S", "Azul")]
    fill_cart(approved, {a: 3, variants[("M", "Negro")]: 2})
    with django_capture_on_commit_callbacks(execute=True):
        doc = _place(approved)
    assert doc.channel.code == "mayorista" and doc.status == states.AWAITING_PAYMENT and doc.ready_at is None
    assert doc.subtotal == Decimal("50000.00") and doc.tax_total == Decimal("10500.00")
    assert doc.total == Decimal("60500.00") and doc.customer == approved.customer
    line = doc.lines.get(variant=a)
    assert line.unit_price == Decimal("10000.00") and line.vat_rate == Decimal("21")
    set_wholesale(a, Decimal("99999"))  # el precio queda congelado en el pedido
    line.refresh_from_db()
    assert line.unit_price == Decimal("10000.00")
    assert StockLevel.objects.get(variant=a).reserved == 3
    assert StockMovement.objects.filter(kind="reservation", reference_id=str(doc.pk)).count() == 2
    order = WholesaleOrder.objects.get(document=doc)
    assert order.payment_method == "transfer" and order.expires_at and order.placed_by == approved.user
    assert not order.on_behalf
    payment = doc.payments.get()
    assert (
        payment.method == Payment.Method.TRANSFER
        and payment.status == "pending"
        and payment.amount == doc.total
    )
    shipment = doc.shipments.get()
    assert shipment.method == Shipment.Method.CARRIER and shipment.carrier_name == "Expreso Rosario"
    assert shipment.address["city"] == "Rosario"
    assert not CartItem.objects.filter(cart__customer=approved.customer).exists()
    assert AuditLog.objects.filter(action="wholesale.order_placed", object_id=str(doc.pk)).exists()
    assert OutboundEmail.objects.filter(template_code="order_received", to=approved.user.email).exists()
    assert not Alert.objects.filter(alert_type__code="orders.new").exists()  # recién al confirmar el pago


def test_t8_cash_only_with_pickup_and_goes_to_new(
    malla, approved, low_min, django_capture_on_commit_callbacks
):
    _, variants = malla
    fill_cart(approved, {variants[("S", "Azul")]: 1})
    with pytest.raises(checkout.CheckoutError, match="solo para retirar"):
        _place(approved, payment="cash", delivery="carrier")
    with django_capture_on_commit_callbacks(execute=True):
        doc = _place(approved, payment="cash", delivery="pickup", carrier="")
    assert doc.status == states.NEW and doc.ready_at is not None
    assert doc.shipments.get().method == Shipment.Method.PICKUP
    assert doc.payments.get().status == "pending"  # pendiente de cobro hasta que se cobre al retirar
    assert Alert.objects.filter(alert_type__code="orders.new", dedupe_key=f"new:{doc.pk}").exists()


def test_t8_current_account_only_if_enabled(malla, approved, low_min, admin_user):
    _, variants = malla
    fill_cart(approved, {variants[("S", "Azul")]: 1})
    with pytest.raises(checkout.CheckoutError):
        _place(approved, payment="account")
    accounts.set_credit(approved, enabled=True, user=admin_user)
    approved.refresh_from_db()
    doc = _place(approved, payment="account")
    assert doc.status == states.NEW and doc.payments.get().method == Payment.Method.CURRENT_ACCOUNT


def test_t8_price_change_asks_to_confirm_again(malla, approved, low_min):
    _, variants = malla
    a = variants[("S", "Azul")]
    fill_cart(approved, {a: 2})
    seen = _snapshot(approved)
    set_wholesale(a, Decimal("11000"))
    with pytest.raises(checkout.CartChanged) as exc:
        _place(approved, snapshot=seen)
    assert "subió de $ 10.000,00 a $ 11.000,00" in exc.value.changes[0]
    assert not SalesDocument.objects.filter(channel__code="mayorista").exists()
    doc = _place(approved)  # con lo que vio ahora, confirma
    assert doc.lines.get().unit_price == Decimal("11000.00")


def test_t8_race_for_last_unit(malla, approved, admin_user, low_min):
    _, variants = malla
    a = variants[("S", "Azul")]
    set_stock(a, 1)
    other = accounts.register(
        data=registration_data(cuit=make_cuit("20", "22222222"), email="otro@x.test"), password=PASSWORD
    )
    accounts.approve(other, user=admin_user)
    other.refresh_from_db()
    fill_cart(approved, {a: 1})
    fill_cart(other, {a: 1})
    seen_first, seen_second = _snapshot(approved), _snapshot(other)  # los dos ven 1 disponible
    _place(approved, snapshot=seen_first)
    with pytest.raises(checkout.CartChanged) as exc:
        _place(other, snapshot=seen_second)
    assert "se agotó" in exc.value.changes[0]
    assert not CartItem.objects.filter(cart__customer=other.customer).exists()  # carrito ajustado
    assert StockLevel.objects.get(variant=a).reserved == 1
    assert SalesDocument.objects.filter(channel__code="mayorista").count() == 1


def test_t8_balance_applied(malla, approved, low_min):
    _, variants = malla
    fill_cart(approved, {variants[("S", "Azul")]: 1})
    CustomerBalance.objects.create(customer=approved.customer, amount=Decimal("5000"))
    doc = _place(approved)
    assert doc.discount_total == Decimal("5000") and doc.total == Decimal("7100.00")
    assert WholesaleOrder.objects.get(document=doc).balance_applied == Decimal("5000")
    assert CustomerBalance.balance_for(approved.customer) == 0
    assert CustomerBalance.objects.get(document=doc).amount == Decimal("-5000")


def test_t8_minimum_enforced_for_customer(malla, approved):
    _, variants = malla
    fill_cart(approved, {variants[("S", "Azul")]: 1})
    with pytest.raises(checkout.CheckoutError, match="mínimo de compra"):
        _place(approved)


def test_t8_checkout_view_end_to_end(customer_client, malla, approved, low_min):
    _, variants = malla
    Carrier.objects.create(name="Expreso Rosario")
    fill_cart(approved, {variants[("S", "Azul")]: 2})
    response = customer_client.get(reverse("store:checkout"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Expreso Rosario" in content and "Cuenta corriente" not in content
    snapshot = response.context["form"].initial["snapshot"]
    response = customer_client.post(
        reverse("store:checkout"),
        {"delivery": "carrier", "carrier": "Expreso Rosario", "payment": "transfer", "snapshot": snapshot},
    )
    doc = SalesDocument.objects.get(channel__code="mayorista")
    assert response.url == reverse("store:order_done", args=[doc.number])
    page = customer_client.get(response.url).content.decode()
    assert doc.channel_reference in page and "subí el comprobante" in page


def test_t8_checkout_view_shows_changes(customer_client, malla, approved, low_min):
    _, variants = malla
    a = variants[("S", "Azul")]
    fill_cart(approved, {a: 4})
    snapshot = customer_client.get(reverse("store:checkout")).context["form"].initial["snapshot"]
    set_stock(a, 2)
    response = customer_client.post(
        reverse("store:checkout"), {"delivery": "pickup", "payment": "cash", "snapshot": snapshot}
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "Algo cambió desde que armaste el carrito" in content and "quedan 2" in content
    assert CartItem.objects.get(cart__customer=approved.customer).quantity == 2


def test_t8_order_done_only_for_owner(client, customer_client, malla, approved, admin_user, low_min):
    _, variants = malla
    fill_cart(approved, {variants[("S", "Azul")]: 1})
    doc = _place(approved)
    other = accounts.register(
        data=registration_data(cuit=make_cuit("20", "33333333"), email="o@x.test"), password=PASSWORD
    )
    accounts.approve(other, user=admin_user)
    client.force_login(other.user)
    assert client.get(reverse("store:order_done", args=[doc.number])).status_code == 404
    assert customer_client.get(reverse("store:order_done", args=[doc.number])).status_code == 200


def test_t8_on_behalf_has_no_minimum_and_records_seller(malla, approved, make_user):
    """La compra «en nombre de» (pantalla en T10) ya la soporta place_order: sin mínimo y placed_by."""
    _, variants = malla
    seller = make_user("vendedor@test.local", VENDEDOR)
    fill_cart(approved, {variants[("S", "Azul")]: 1})
    shopper = Shopper(account=approved, user=seller, acting=True)
    snapshot = checkout.sign_snapshot(cart_service.summarize(shopper.cart(), apply_min=False))
    doc = checkout.place_order(
        shopper, delivery=checkout.Delivery("pickup"), payment_method="transfer", snapshot=snapshot
    )
    order = WholesaleOrder.objects.get(document=doc)
    assert order.placed_by == seller and order.on_behalf
    assert AuditLog.objects.get(action="wholesale.order_placed").actor == seller


def test_t8_recalculate_totals_unchanged_for_other_channels(db):
    from django.utils import timezone

    from apps.integrations.models import Channel
    from apps.sales.models import SalesLine

    doc = SalesDocument.objects.create(channel=Channel.objects.get(code="manual"), issued_at=timezone.now())
    SalesLine.objects.create(
        document=doc, sku_snapshot="X", description_snapshot="X", quantity=2, unit_price=100
    )
    doc.recalculate_totals()
    assert doc.total == Decimal("200") and doc.tax_total == 0


def test_golden_rule_no_channel_writes(malla, approved, low_min):
    """La tienda nunca escribe stock ni precios en los canales: el checkout no encola tareas de canal."""
    _, variants = malla
    fill_cart(approved, {variants[("S", "Azul")]: 1})
    with mock.patch(
        "apps.integrations.guard.ensure_write_allowed", side_effect=AssertionError("escritura")
    ) as guard:
        _place(approved)
    assert not guard.called


def test_group_names_unchanged(roles):
    assert set(Group.objects.values_list("name", flat=True)) >= {ADMIN, DEPOSITO, VENTAS, VENDEDOR}
