# ruff: noqa: F811 — las fixtures se importan de test_mayorista_operacion y pytest las inyecta por nombre
"""Correcciones de la auditoría M8a de la tienda mayorista (docs/auditoria-m8a.md): T1 a T4."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail as djmail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.roles import ADMIN
from apps.alerts.models import Alert, AlertType
from apps.audit.models import AuditLog
from apps.sales import states
from apps.sales.models import Payment, SalesDocument
from apps.sales.tasks import check_manual_pending
from apps.wholesale import mail, payments
from apps.wholesale.models import CustomerBalance, OutboundEmail, WholesaleOrder
from tests.test_mayorista_operacion import (  # noqa: F401 - fixtures
    _clear_cache,
    customer,
    login,
    malla,
    move,
    order_for,
    other_customer,
    reserved,
    staff,
)

pytestmark = pytest.mark.django_db

GROSS_2 = Decimal("24200.00")  # 2 × 10.000 neto + IVA


# ── T1: pedido pagado entero con saldo a favor ───────────────────────────────


def _alerts(code, doc):
    return Alert.objects.filter(alert_type__code=code, link_url=f"/pedidos/{doc.pk}/")


def test_t1_transfer_fully_paid_with_balance_goes_to_new(
    customer, malla, staff, django_capture_on_commit_callbacks
):
    _, variants = malla
    CustomerBalance.objects.create(customer=customer.customer, amount=Decimal("30000"))
    with django_capture_on_commit_callbacks(execute=True):
        doc = order_for(customer, malla)
    doc.refresh_from_db()
    order = WholesaleOrder.objects.get(document=doc)
    assert doc.total == 0 and doc.discount_total == GROSS_2
    assert doc.status == states.NEW and doc.ready_at is not None
    assert order.expires_at is None and order.paid_with_balance
    payment = doc.payments.get()
    assert payment.method == Payment.Method.BALANCE and payment.status == Payment.Status.CONFIRMED
    assert payment.amount == GROSS_2 and payment.paid_at and payment.external_reference == "mayorista"
    # Le queda el resto del saldo y la reserva es la de siempre.
    assert CustomerBalance.balance_for(customer.customer) == Decimal("30000") - GROSS_2
    assert reserved(variants[("S", "Azul")]) == 2
    # Pasó por change_status (historial) y avisó a Depósito como un pedido nuevo.
    change = AuditLog.objects.get(action="order.status_changed", object_id=str(doc.pk))
    assert change.after == {"estado": states.NEW} and change.before == {"estado": states.AWAITING_PAYMENT}
    assert _alerts("orders.new", doc).count() == 1
    # Email sin datos para transferir.
    email = OutboundEmail.objects.get(template_code="order_received")
    assert "saldo a favor" in email.body_text and "Datos para transferir" not in email.body_text


def test_t1_no_expiry_reminder_or_receipt_for_zero_order(customer, malla, staff):
    CustomerBalance.objects.create(customer=customer.customer, amount=Decimal("30000"))
    doc = order_for(customer, malla)
    later = timezone.now() + timedelta(days=10)
    assert payments.send_reminders(now=timezone.now() + timedelta(days=2, hours=12)) == 0
    assert payments.expire_orders(now=later) == {"expired": 0, "with_receipt": 0}
    doc.refresh_from_db()
    assert doc.status == states.NEW
    upload = SimpleUploadedFile("c.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, content_type="image/png")
    with pytest.raises(payments.PaymentError):
        payments.upload_receipt(doc, upload, user=customer.user)


def test_t1_confirmation_and_account_pages_explain_it(customer, malla, staff):
    CustomerBalance.objects.create(customer=customer.customer, amount=Decimal("30000"))
    doc = order_for(customer, malla)
    client = login(customer.user)
    for name in ("store:order_done", "store:order_detail"):
        page = client.get(reverse(name, args=[doc.number])).content.decode()
        assert "Pagado con saldo a favor" in page
        assert "no tenés que transferir ni subir comprobante" in page
        assert "Subí el comprobante" not in page and 'name="file"' not in page
    panel = login(staff[ADMIN]).get(reverse("sales:detail", args=[doc.pk])).content.decode()
    assert "Pagado entero con saldo a favor" in panel and "Confirmar pago" not in panel


def test_t1_cash_fully_paid_with_balance(customer, malla, staff, django_capture_on_commit_callbacks):
    CustomerBalance.objects.create(customer=customer.customer, amount=Decimal("30000"))
    with django_capture_on_commit_callbacks(execute=True):
        doc = order_for(customer, malla, payment="cash", delivery="pickup", carrier="")
    doc.refresh_from_db()
    assert doc.status == states.NEW and doc.total == 0
    assert payments.cash_pending(doc) is None  # no hay que cobrar nada en el local
    assert doc.payments.get().method == Payment.Method.BALANCE
    assert _alerts("orders.new", doc).count() == 1
    assert not AuditLog.objects.filter(action="order.status_changed", object_id=str(doc.pk)).exists()


def test_t1_partial_balance_still_awaits_transfer(customer, malla, staff):
    CustomerBalance.objects.create(customer=customer.customer, amount=Decimal("1000"))
    doc = order_for(customer, malla)
    order = WholesaleOrder.objects.get(document=doc)
    assert doc.status == states.AWAITING_PAYMENT and order.expires_at and not order.paid_with_balance
    payment = doc.payments.get()
    assert payment.method == Payment.Method.TRANSFER and payment.status == Payment.Status.PENDING


# ── T2: emails viejos en la cola ─────────────────────────────────────────────


def _queued(code, hours_ago):
    email = OutboundEmail.objects.create(
        to="cliente@test.local", template_code=code, subject=code, body_text="x", body_html="<p>x</p>"
    )
    OutboundEmail.objects.filter(pk=email.pk).update(created_at=timezone.now() - timedelta(hours=hours_ago))
    email.refresh_from_db()
    return email


def test_t2_old_emails_expire_instead_of_sending(settings):
    settings.STORE_EMAILS_ENABLED = True
    old = _queued("payment_reminder", 100)
    approved = _queued("registration_approved", 500)
    rejected = _queued("registration_rejected", 500)
    fresh = _queued("dispatched", 2)
    assert mail.send_pending() == 3
    for email in (old, approved, rejected, fresh):
        email.refresh_from_db()
    assert old.status == OutboundEmail.Status.EXPIRED and old.attempts == 0
    assert "72 h" in old.last_error
    assert {approved.status, rejected.status, fresh.status} == {OutboundEmail.Status.SENT}
    assert sorted(m.subject for m in djmail.outbox) == [
        "dispatched",
        "registration_approved",
        "registration_rejected",
    ]


def test_t2_send_single_email_checks_age_and_setting(settings):
    settings.STORE_EMAIL_MAX_AGE_HOURS = 1
    email = _queued("order_received", 2)
    assert mail.send(email) is False
    email.refresh_from_db()
    assert email.status == OutboundEmail.Status.EXPIRED and not djmail.outbox
    assert mail.send(_queued("order_received", 0)) is True


def test_t2_panel_shows_expired_count(staff, settings):
    settings.STORE_EMAILS_ENABLED = True
    _queued("payment_reminder", 100)
    _queued("dispatched", 80)
    mail.send_pending()
    client = login(staff[ADMIN])
    page = client.get(reverse("store_admin:outbound_emails")).content.decode()
    assert "Vencido, no enviado (2)" in page
    assert "2 emails no se mandaron" in page
    expired = client.get(reverse("store_admin:outbound_emails") + "?estado=expired")
    assert len(expired.context["emails"]) == 2


# ── T3: reserva sin facturar ─────────────────────────────────────────────────


def _age(doc, hours):
    when = timezone.now() - timedelta(hours=hours)
    SalesDocument.objects.filter(pk=doc.pk).update(issued_at=when, ready_at=when)


def _pending_alerts(doc):
    return Alert.objects.filter(
        alert_type__code="orders.manual_pending", dedupe_key__startswith=f"manual:{doc.pk}:"
    )


def test_t3_manual_pending_includes_confirmed_wholesale(customer, other_customer, malla, staff):
    _, variants = malla
    cash = order_for(customer, malla, payment="cash", delivery="pickup", carrier="")
    awaiting = order_for(other_customer, malla, items={variants[("M", "Azul")]: 1})
    cancelled = order_for(other_customer, malla, items={variants[("M", "Negro")]: 1}, payment="cash",
                          delivery="pickup", carrier="")  # fmt: skip
    move(cancelled, states.CANCELLED)
    for doc in (cash, awaiting, cancelled):
        _age(doc, 30)
    assert check_manual_pending() == 2  # el de efectivo: sin cobrar y sin facturar
    assert check_manual_pending() == 0  # sin duplicar
    titles = set(_pending_alerts(cash).values_list("title", flat=True))
    assert titles == {
        f"{cash.channel_reference} sin cobrar",
        f"{cash.channel_reference} sin facturar en Contabilium",
    }
    assert cash.channel_reference.startswith("Mayorista #")
    body = _pending_alerts(cash).get(dedupe_key=f"manual:{cash.pk}:factura").body
    assert body.startswith("Pedido mayorista confirmado el") and "sigue reservada" in body
    assert not _pending_alerts(awaiting).exists() and not _pending_alerts(cancelled).exists()
    assert AlertType.objects.get(code="orders.manual_pending").name == (
        "Pedido manual o mayorista sin cobrar o sin facturar"
    )


def test_t3_account_orders_do_not_alert_unpaid(customer, malla, staff):
    """La cuenta corriente se cobra después: solo avisa "sin facturar", nunca "sin cobrar"."""
    customer.credit_enabled = True
    customer.save(update_fields=["credit_enabled"])
    doc = order_for(customer, malla, payment="account")
    _age(doc, 30)
    assert check_manual_pending() == 1
    assert _pending_alerts(doc).get().dedupe_key == f"manual:{doc.pk}:factura"


def test_t3_wholesale_counts_from_confirmation(customer, malla, staff):
    doc = order_for(customer, malla)  # transferencia: esperando pago
    SalesDocument.objects.filter(pk=doc.pk).update(issued_at=timezone.now() - timedelta(days=3))
    payments.confirm_payment(doc, user=staff[ADMIN])  # recién confirmado: entra en Nuevo ahora
    assert check_manual_pending() == 0
    assert check_manual_pending(now=timezone.now() + timedelta(hours=25)) == 1  # pagado, sin facturar
    assert _pending_alerts(doc).get().dedupe_key == f"manual:{doc.pk}:factura"


def test_t3_manual_pending_query_stays_single(customer, malla, staff, django_assert_max_num_queries):
    _, variants = malla
    docs = [
        order_for(customer, malla, items={v: 1}, payment="cash", delivery="pickup", carrier="")
        for v in variants.values()
    ]
    for doc in docs:
        _age(doc, 30)
        payments.mark_cash_collected(doc, user=staff[ADMIN])
    SalesDocument.objects.filter(pk__in=[d.pk for d in docs]).update(invoiced_in_contabilium=True)
    with django_assert_max_num_queries(1):  # cobrados y facturados: se filtran en la consulta
        assert check_manual_pending() == 0


def test_t3_report_shows_units_reserved_without_invoice(customer, other_customer, malla, staff):
    _, variants = malla
    invoiced = order_for(customer, malla, payment="cash", delivery="pickup", carrier="")  # 2 unidades
    pending = order_for(customer, malla, items={variants[("M", "Azul")]: 3}, payment="cash",
                        delivery="pickup", carrier="")  # fmt: skip
    awaiting = order_for(other_customer, malla, items={variants[("M", "Negro")]: 1})
    cancelled = order_for(other_customer, malla, items={variants[("S", "Negro")]: 4})
    move(cancelled, states.CANCELLED)
    payments.on_cancelled(cancelled)
    SalesDocument.objects.filter(pk=invoiced.pk).update(invoiced_in_contabilium=True)
    payments.on_invoiced(invoiced)
    admin = login(staff[ADMIN])
    response = admin.get(reverse("reports:wholesale"))
    data = response.context["data"]
    assert data["reserved_units"] == 4
    assert {r["pedido"]: r["unidades"] for r in data["reserved"]} == {
        pending.channel_reference: 3,
        awaiting.channel_reference: 1,
    }
    assert "Stock reservado sin facturar" in response.content.decode()
    wb = load_workbook(io.BytesIO(admin.get(reverse("reports:wholesale_excel")).content), read_only=True)
    rows = list(wb["Reservado sin facturar"].iter_rows(values_only=True))
    assert any(r and r[0] == "Total" and r[5] == 4 for r in rows)


# ── T4: producto inexistente ─────────────────────────────────────────────────


def test_t4_add_to_cart_missing_product_is_store_404(customer):
    client = login(customer.user)
    response = client.post(reverse("store:add_to_cart", args=[999999]), {"qty-1": "2"})
    assert response.status_code == 404
    assert "store/404.html" in [t.name for t in response.templates]
    empty = client.post(reverse("store:add_to_cart", args=[999999]), {})
    assert empty.status_code == 404
