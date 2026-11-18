"""M9-03 · Cuentas e invitaciones de los mayoristas ya cargados (DDEV-58).

Ningún test manda un email real: el backend es locmem y `STORE_EMAILS_ENABLED` está apagado, así que lo
más que pasa es que quedan filas en `OutboundEmail` (que se comprueban, o se comprueba que no hay).
"""

import logging
import re
from datetime import timedelta

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core import mail as djmail
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import ADMIN, DEPOSITO, VENTAS
from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.wholesale import accounts, invitations, mail
from apps.wholesale.models import CustomerAccount, Invitation, OutboundEmail
from tests.test_mayorista import make_cuit

pytestmark = pytest.mark.django_db

User = get_user_model()
GOOD_PASSWORD = "Natacion-Mayorista-2026"
TOKEN_IN_LINK = re.compile(r"/invitacion/([-\w]+)/")


def make_customer(n=1, *, email=None, tax_id=None, tax_id_type="CUIT", **extra) -> Customer:
    return Customer.objects.create(
        kind=Customer.Kind.WHOLESALE,
        legal_name=f"Natatorio {n} SRL",
        tax_id_type=tax_id_type,
        tax_id=tax_id if tax_id is not None else make_cuit("30", str(70000000 + n)),
        email=f"compras{n}@natatorio.test" if email is None else email,
        **extra,
    )


@pytest.fixture
def three():
    return [make_customer(i) for i in (1, 2, 3)]


@pytest.fixture
def enabled(settings):
    settings.STORE_INVITATIONS_ENABLED = True
    return settings


def token_of(email: OutboundEmail) -> str:
    return TOKEN_IN_LINK.search(email.body_text).group(1)


def send_one(account, admin_user) -> str:
    """Envía (encola) la invitación de una cuenta y devuelve el token del enlace."""
    invitations.send_invitations([account], admin_user)
    return token_of(Invitation.objects.get(account=account).last_email)


# ── Preparar ─────────────────────────────────────────────────────────────────


def test_prepare_creates_approved_accounts_that_cannot_log_in(three):
    report = invitations.prepare()
    assert (report.created, report.linked, report.already, len(report.excluded)) == (3, 0, 0, 0)
    for customer in three:
        account = CustomerAccount.objects.get(customer=customer)
        assert account.status == CustomerAccount.Status.APPROVED
        assert account.credit_enabled is False
        assert account.accepted_terms_at is None
        assert account.cuit == customer.tax_id
        assert not account.user.has_usable_password()
        assert account.user.email == customer.email
        assert account.invitation.status == Invitation.Status.UNSENT
        assert account.invitation.token_hash == ""
    assert AuditLog.objects.filter(action="client.imported").count() == 3


def test_prepare_is_idempotent(three):
    invitations.prepare()
    users, accounts_n, invs = (
        User.objects.count(),
        CustomerAccount.objects.count(),
        Invitation.objects.count(),
    )
    again = invitations.prepare()
    assert (again.created, again.linked, again.already) == (0, 0, 3)
    assert (User.objects.count(), CustomerAccount.objects.count(), Invitation.objects.count()) == (
        users,
        accounts_n,
        invs,
    )


def test_prepare_does_not_touch_suspended_or_credit(three):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    account.status = CustomerAccount.Status.SUSPENDED
    account.credit_enabled = True
    account.save()
    invitations.prepare()
    account.refresh_from_db()
    assert account.status == CustomerAccount.Status.SUSPENDED and account.credit_enabled is True


def test_prepare_dry_run_creates_nothing(three):
    report = invitations.prepare(dry_run=True)
    assert report.created == 3 and report.dry_run
    assert not CustomerAccount.objects.exists()
    assert not Invitation.objects.exists()
    assert not User.objects.filter(email="compras1@natatorio.test").exists()


def test_prepare_never_queues_emails(three):
    invitations.prepare()
    invitations.prepare()
    assert OutboundEmail.objects.count() == 0
    assert djmail.outbox == []


def test_exclusion_reasons():
    make_customer(1, email="")  # sin email
    make_customer(2, email="esto-no-es-un-email")  # email inválido
    make_customer(3, tax_id="12345678", tax_id_type="DNI")  # no es CUIT
    make_customer(4, tax_id="30712345670")  # CUIT con dígito verificador malo
    make_customer(5, email="repetido@natatorio.test")  # email repetido x2
    make_customer(6, email="repetido@natatorio.test")
    shared = make_cuit("30", "70000077")
    make_customer(7, tax_id=shared)  # CUIT repetido x2
    make_customer(8, tax_id=shared)
    User.objects.create_user(email="interno@deutsch.test", full_name="Interno", password="x" * 12)
    make_customer(9, email="Interno@Deutsch.test")  # el email es de un usuario interno
    ok = make_customer(10)
    Customer.objects.create(kind=Customer.Kind.RETAIL, legal_name="Minorista", email="m@x.test")

    report = invitations.prepare()
    assert report.created == 1 and CustomerAccount.objects.get().customer == ok
    assert report.by_reason == {
        invitations.NO_EMAIL: 1,
        invitations.BAD_EMAIL: 1,
        invitations.BAD_DOCUMENT: 2,
        invitations.DUP_EMAIL: 3,
        invitations.DUP_CUIT: 2,
    }
    assert {d.customer.legal_name for d in report.excluded} >= {"Natatorio 1 SRL", "Natatorio 9 SRL"}
    assert len(invitations.exclusions()) == 9  # lo mismo que ve la pantalla de seguimiento


def test_cuit_already_used_by_another_customers_account_is_excluded():
    first = make_customer(1)
    invitations.prepare()
    other = make_customer(2, tax_id=first.tax_id)  # mismo CUIT que una cuenta ya vinculada
    report = invitations.prepare()
    assert [(d.customer, d.reason) for d in report.excluded] == [(other, invitations.DUP_CUIT)]


def test_self_registered_account_is_approved_and_linked_not_duplicated():
    customer = make_customer(1)
    user = User.objects.create_user(
        email="otro-mail@natatorio.test", full_name="Se registró solo", password=GOOD_PASSWORD
    )
    own = CustomerAccount.objects.create(
        user=user,
        cuit=customer.tax_id,
        registration={"legal_name": "Natatorio 1 SRL"},
        accepted_terms_at=timezone.now(),
    )
    report = invitations.prepare()
    assert (report.created, report.linked) == (0, 1)
    own.refresh_from_db()
    assert own.status == CustomerAccount.Status.APPROVED and own.customer == customer
    assert CustomerAccount.objects.count() == 1 and User.objects.count() == 1
    assert own.user.has_usable_password() and not Invitation.objects.exists()  # ya tiene contraseña
    assert OutboundEmail.objects.count() == 0  # no se manda el «aprobamos tu cuenta» del flujo normal


# ── Ingreso bloqueado antes de aceptar ───────────────────────────────────────


def test_invited_customer_cannot_log_in_before_accepting(client, three):
    invitations.prepare()
    email = three[0].email
    for password in ("", "x", GOOD_PASSWORD, "!", "!unusable"):
        assert authenticate(username=email, password=password) is None
        response = client.post(reverse("store:login"), {"username": email, "password": password})
        assert response.status_code == 200 and "_auth_user_id" not in client.session
    # Tampoco sirve «recuperar contraseña» para saltearse la invitación: no se manda nada.
    client.post(reverse("store:password_reset"), {"email": email})
    assert djmail.outbox == []


# ── Enviar: apagado por defecto ──────────────────────────────────────────────


def test_sending_is_off_by_default(three, admin_user):
    invitations.prepare()
    with pytest.raises(invitations.InvitationsDisabled) as exc:
        invitations.send_invitations(invitations.accounts_for("unsent"), admin_user)
    assert "Todavía no se habilitó" in str(exc.value)
    assert OutboundEmail.objects.count() == 0
    assert not Invitation.objects.exclude(status=Invitation.Status.UNSENT).exists()
    assert not Invitation.objects.exclude(token_hash="").exists()
    assert djmail.outbox == []


def test_command_send_is_off_by_default(three, admin_user):
    call_command("invitar_mayoristas", "preparar", stdout=_Out())
    with pytest.raises(CommandError, match="Todavía no se habilitó"):
        call_command("invitar_mayoristas", "enviar", usuario=admin_user.email, stdout=_Out())
    assert OutboundEmail.objects.count() == 0


class _Out:
    def __init__(self):
        self.lines = []

    def write(self, text="", *a, **k):
        self.lines.append(text)

    def flush(self):
        pass


def test_command_prepare_reports_and_sends_nothing(three):
    out = _Out()
    call_command("invitar_mayoristas", "preparar", "--dry-run", stdout=out)
    assert not CustomerAccount.objects.exists()
    call_command("invitar_mayoristas", "preparar", stdout=out)
    text = "\n".join(out.lines)
    assert "Cuentas creadas: 3" in text and "No se mandó ningún email." in text
    assert CustomerAccount.objects.count() == 3 and OutboundEmail.objects.count() == 0


def test_send_requires_manage_customers(three, enabled, make_user):
    invitations.prepare()
    seller = make_user("ventas@x.test", VENTAS)
    with pytest.raises(PermissionDenied):
        invitations.send_invitations(invitations.accounts_for("unsent"), seller)
    with pytest.raises(PermissionDenied):
        invitations.send_invitations(invitations.accounts_for("unsent"), None)
    assert OutboundEmail.objects.count() == 0


def test_send_queues_one_email_per_account_without_sending(three, enabled, admin_user, caplog):
    invitations.prepare()
    with caplog.at_level(logging.DEBUG):
        result = invitations.send_invitations(invitations.accounts_for("unsent"), admin_user)
    assert result.queued == 3 and not result.dry_run
    emails = OutboundEmail.objects.filter(template_code="invitation")
    assert emails.count() == 3 and all(e.status == OutboundEmail.Status.PENDING for e in emails)
    assert djmail.outbox == []  # nada salió: solo quedó en la cola
    for inv in Invitation.objects.select_related("last_email"):
        token = token_of(inv.last_email)
        assert inv.status == Invitation.Status.SENT and inv.sent_count == 1
        assert inv.token_hash == invitations.hash_token(token) and token not in inv.token_hash
        assert inv.expires_at - inv.sent_at == timedelta(days=7)
        # El token no queda ni en la auditoría ni en el log.
        assert not AuditLog.objects.filter(metadata__icontains=token).exists()
        assert all(
            token not in str(a.after) + str(a.before) + str(a.metadata) for a in AuditLog.objects.all()
        )
        assert token not in caplog.text
    assert AuditLog.objects.filter(action="invitation.sent").count() == 1


def test_invitation_email_never_expires_in_queue(three, enabled, admin_user):
    invitations.prepare()
    invitations.send_invitations(invitations.accounts_for("unsent"), admin_user)
    OutboundEmail.objects.update(created_at=timezone.now() - timedelta(days=10))
    assert "invitation" in mail.NEVER_EXPIRE
    assert mail.expire_stale() == 0
    assert OutboundEmail.objects.filter(status=OutboundEmail.Status.PENDING).count() == 3


def test_dry_run_registers_but_queues_nothing(three, enabled, admin_user):
    enabled.STORE_EMAIL_DRY_RUN = True
    invitations.prepare()
    result = invitations.send_invitations(invitations.accounts_for("unsent"), admin_user)
    assert result.dry_run and result.would_send == 3 and result.queued == 0
    assert OutboundEmail.objects.count() == 0
    assert Invitation.objects.filter(status=Invitation.Status.UNSENT, token_hash="").count() == 3
    log = AuditLog.objects.get(action="invitation.dry_run")
    assert log.metadata["cantidad"] == 3


def test_hourly_rate_limit_defers_the_rest(three, enabled, admin_user):
    enabled.STORE_INVITATIONS_PER_HOUR = 2
    invitations.prepare()
    first = invitations.send_invitations(invitations.accounts_for("unsent"), admin_user)
    assert (first.queued, first.deferred) == (2, 1)
    second = invitations.send_invitations(invitations.accounts_for("unsent"), admin_user)
    assert (second.queued, second.deferred) == (0, 1)  # la hora no pasó
    Invitation.objects.update(sent_at=timezone.now() - timedelta(hours=2))
    third = invitations.send_invitations(invitations.accounts_for("unsent"), admin_user)
    assert third.queued == 1 and Invitation.objects.filter(status=Invitation.Status.UNSENT).count() == 0


def test_resend_replaces_the_previous_link(three, enabled, admin_user):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    old = send_one(account, admin_user)
    assert invitations.accounts_for("not_entered").get() == account
    new = send_one(account, admin_user)
    assert old != new and invitations.find_valid(old) is None and invitations.find_valid(new) is not None
    assert Invitation.objects.get(account=account).sent_count == 2


# ── Aceptar ──────────────────────────────────────────────────────────────────


def test_accept_happy_path(client, three, enabled, admin_user, caplog):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    token = send_one(account, admin_user)
    url = reverse("store:invitation", args=[token])

    page = client.get(url)
    assert page.status_code == 200 and "Creá tu contraseña" in page.content.decode()
    assert "no-store" in page.headers["Cache-Control"]

    weak = client.post(url, {"password1": "12345678", "password2": "12345678", "accept_terms": "on"})
    assert weak.status_code == 200 and "_auth_user_id" not in client.session
    no_terms = client.post(url, {"password1": GOOD_PASSWORD, "password2": GOOD_PASSWORD})
    assert no_terms.status_code == 200 and "tenés que aceptar los términos" in no_terms.content.decode()
    mismatch = client.post(
        url, {"password1": GOOD_PASSWORD, "password2": GOOD_PASSWORD + "x", "accept_terms": "on"}
    )
    assert "no coinciden" in mismatch.content.decode()
    account.refresh_from_db()
    assert account.accepted_terms_at is None and not account.user.has_usable_password()

    with caplog.at_level(logging.DEBUG):
        done = client.post(
            url, {"password1": GOOD_PASSWORD, "password2": GOOD_PASSWORD, "accept_terms": "on"}
        )
    assert done.status_code == 302 and done.url == reverse("store:home")
    assert client.session["_auth_user_id"] == str(account.user_id)  # quedó con sesión iniciada
    account.refresh_from_db()
    assert account.accepted_terms_at is not None and account.user.check_password(GOOD_PASSWORD)
    invitation = Invitation.objects.get(account=account)
    assert invitation.status == Invitation.Status.ACCEPTED and invitation.token_hash == ""
    assert token not in caplog.text
    log = AuditLog.objects.get(action="invitation.accepted")
    assert token not in str(log.after) + str(log.metadata) and log.actor_id == account.user_id
    assert djmail.outbox == []
    # Y ahora sí entra a la tienda con su contraseña.
    client.post(reverse("store:logout"))
    assert authenticate(username=account.user.email, password=GOOD_PASSWORD) is not None
    assert client.get(reverse("store:home")).status_code == 302  # sin sesión: va al ingreso


def test_used_token_cannot_be_reused(client, three, enabled, admin_user):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    token = send_one(account, admin_user)
    url = reverse("store:invitation", args=[token])
    client.post(url, {"password1": GOOD_PASSWORD, "password2": GOOD_PASSWORD, "accept_terms": "on"})
    client.post(reverse("store:logout"))
    page = client.get(url)
    assert "ya se usó o venció" in page.content.decode() and "Pedir un enlace nuevo" in page.content.decode()
    other = client.post(
        url, {"password1": "Otra-Clave-2026-xyz", "password2": "Otra-Clave-2026-xyz", "accept_terms": "on"}
    )
    assert "ya se usó o venció" in other.content.decode()
    account.refresh_from_db()
    assert account.user.check_password(GOOD_PASSWORD)  # la segunda contraseña no se aplicó


def test_expired_and_invented_tokens_show_the_same_message(client, three, enabled, admin_user):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    token = send_one(account, admin_user)
    Invitation.objects.filter(account=account).update(expires_at=timezone.now() - timedelta(minutes=1))
    expired = client.get(reverse("store:invitation", args=[token]))
    invented = client.get(reverse("store:invitation", args=["x" * 43]))
    assert expired.status_code == invented.status_code == 200
    assert "ya se usó o venció" in expired.content.decode()
    assert "ya se usó o venció" in invented.content.decode()
    post = client.post(
        reverse("store:invitation", args=[token]),
        {"password1": GOOD_PASSWORD, "password2": GOOD_PASSWORD, "accept_terms": "on"},
    )
    assert "_auth_user_id" not in client.session and "ya se usó o venció" in post.content.decode()
    invitations.sync_states()
    assert Invitation.objects.get(account=account).status == Invitation.Status.EXPIRED
    assert invitations.totals()["expired"] == 1


# ── Pedir otro enlace desde el ingreso ───────────────────────────────────────


def _request(client, cuit, email, **extra):
    return client.post(reverse("store:invitation_request"), {"cuit": cuit, "email": email, **extra})


def test_request_new_link_is_generic_and_does_not_reveal_accounts(client, three, enabled, admin_user):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    send_one(account, admin_user)
    Invitation.objects.update(
        expires_at=timezone.now() - timedelta(days=1), sent_at=timezone.now() - timedelta(days=8)
    )
    before = OutboundEmail.objects.count()

    unknown = _request(client, make_cuit("30", "79999999"), "nadie@x.test")
    wrong_email = _request(client, account.cuit, "otro@x.test")
    right = _request(client, accounts.format_cuit(account.cuit), account.user.email.upper())
    assert unknown.status_code == wrong_email.status_code == right.status_code == 302
    assert unknown.url == wrong_email.url == right.url == reverse("store:invitation_request_done")
    assert OutboundEmail.objects.count() == before + 1  # solo el que coincidía
    new = Invitation.objects.get(account=account).last_email
    assert new.to == account.user.email and invitations.find_valid(token_of(new)) is not None
    # Un segundo pedido enseguida no manda otro (evita llenarle la casilla a alguien).
    _request(client, account.cuit, account.user.email)
    assert OutboundEmail.objects.count() == before + 1
    assert djmail.outbox == []


def test_request_new_link_does_nothing_while_sending_is_off(client, three, admin_user, settings):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    response = _request(client, account.cuit, account.user.email)
    assert response.url == reverse("store:invitation_request_done")
    assert OutboundEmail.objects.count() == 0 and Invitation.objects.get(account=account).token_hash == ""


def test_request_new_link_ignores_bots_and_is_rate_limited(client, three, enabled, admin_user):
    enabled.STORE_INVITATION_REQUESTS_PER_IP_HOUR = 2
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    bot = _request(client, account.cuit, account.user.email, website="http://spam")
    assert bot.url == reverse("store:invitation_request_done") and OutboundEmail.objects.count() == 0
    for _ in range(2):  # gastan el cupo con datos que no coinciden
        _request(client, "30000000000", "no@x.test")
    limited = _request(client, account.cuit, account.user.email)
    assert limited.url == reverse("store:invitation_request_done")  # misma respuesta, pero no manda
    assert OutboundEmail.objects.count() == 0


def test_accepted_customer_cannot_get_another_invitation(client, three, enabled, admin_user):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    token = send_one(account, admin_user)
    client.post(
        reverse("store:invitation", args=[token]),
        {"password1": GOOD_PASSWORD, "password2": GOOD_PASSWORD, "accept_terms": "on"},
    )
    client.post(reverse("store:logout"))
    count = OutboundEmail.objects.count()
    _request(client, account.cuit, account.user.email)
    assert OutboundEmail.objects.count() == count


# ── Corregir el email ────────────────────────────────────────────────────────


def test_change_email_before_sending(three, admin_user):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    invitations.change_email(account, " Nuevo@Natatorio.test ", user=admin_user)
    account.refresh_from_db()
    assert account.user.email == "nuevo@natatorio.test" and account.customer.email == "nuevo@natatorio.test"
    log = AuditLog.objects.get(action="invitation.email_corrected")
    assert log.before == {"email": "compras1@natatorio.test"} and log.after == {
        "email": "nuevo@natatorio.test"
    }
    assert log.actor == admin_user
    with pytest.raises(accounts.AccountError, match="Escribí un email válido"):
        invitations.change_email(account, "no-es-un-mail", user=admin_user)
    with pytest.raises(accounts.AccountError, match="ya lo usa"):
        invitations.change_email(account, three[1].email, user=admin_user)
    with pytest.raises(accounts.AccountError, match="mismo|ya es el email"):
        invitations.change_email(account, "nuevo@natatorio.test", user=admin_user)


def test_change_email_after_sending_voids_the_old_link(three, enabled, admin_user):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    token = send_one(account, admin_user)
    old_email = Invitation.objects.get(account=account).last_email
    invitations.change_email(account, "bien@natatorio.test", user=admin_user)
    invitation = Invitation.objects.get(account=account)
    assert invitation.status == Invitation.Status.UNSENT and invitation.token_hash == ""
    assert invitations.find_valid(token) is None
    old_email.refresh_from_db()
    assert old_email.status == OutboundEmail.Status.EXPIRED  # el email al correo equivocado no sale
    token2 = send_one(account, admin_user)
    assert invitations.find_valid(token2).account == account
    assert Invitation.objects.get(account=account).last_email.to == "bien@natatorio.test"


def test_change_email_not_allowed_after_accepting_or_without_permission(
    client, three, enabled, admin_user, make_user
):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    token = send_one(account, admin_user)
    with pytest.raises(PermissionDenied):
        invitations.change_email(account, "x@natatorio.test", user=make_user("d@x.test", DEPOSITO))
    client.post(
        reverse("store:invitation", args=[token]),
        {"password1": GOOD_PASSWORD, "password2": GOOD_PASSWORD, "accept_terms": "on"},
    )
    with pytest.raises(accounts.AccountError, match="ya creó su contraseña"):
        invitations.change_email(account, "x@natatorio.test", user=admin_user)


# ── Panel ────────────────────────────────────────────────────────────────────

PANEL_GETS = ["wholesale_customers:invitations"]
PANEL_POSTS = [
    ("wholesale_customers:invitations_send", []),
    ("wholesale_customers:invitation_resend", [1]),
    ("wholesale_customers:invitation_email", [1]),
]


def test_panel_permissions(client, three, users_by_role, enabled):
    invitations.prepare()
    for name in PANEL_GETS:
        assert client.get(reverse(name)).status_code == 302  # sin sesión: al ingreso
    for role in (DEPOSITO, VENTAS):
        client.force_login(users_by_role[role])
        for name in PANEL_GETS:
            assert client.get(reverse(name)).status_code == 403
        for name, args in PANEL_POSTS:
            assert client.post(reverse(name, args=args), {"scope": "unsent"}).status_code == 403
    assert OutboundEmail.objects.count() == 0
    client.force_login(users_by_role[ADMIN])
    assert client.get(reverse("wholesale_customers:invitations")).status_code == 200


def test_store_customer_never_sees_the_panel_screens(client, three, enabled, admin_user):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    token = send_one(account, admin_user)
    client.post(
        reverse("store:invitation", args=[token]),
        {"password1": GOOD_PASSWORD, "password2": GOOD_PASSWORD, "accept_terms": "on"},
    )
    before = OutboundEmail.objects.count()
    response = client.get(reverse("wholesale_customers:invitations"))
    assert response.status_code == 302 and response.url == reverse("store:home")
    for name, args in PANEL_POSTS:
        post = client.post(reverse(name, args=args), {"scope": "unsent"})
        assert post.status_code == 302 and post.url == reverse("store:home")
    assert OutboundEmail.objects.count() == before


def test_tracking_screen_totals_filters_and_disabled_button(admin_client, three, settings):
    make_customer(4, email="")
    invitations.prepare()
    page = admin_client.get(reverse("wholesale_customers:invitations"))
    html = page.content.decode()
    assert page.status_code == 200
    assert "El envío de invitaciones está apagado" in html and "Todavía no se habilitó" in html
    assert re.search(r"<button\s+disabled[^>]*>Enviar invitaciones \(3\)", html)
    assert "Sin email cargado (1)" in html and "No incluidos" in html
    assert "Natatorio 1 SRL" in html
    filtered = admin_client.get(reverse("wholesale_customers:invitations"), {"estado": "accepted"})
    assert "Natatorio 1 SRL" not in filtered.content.decode().split("No incluidos (")[0].split("<tbody")[1]
    searched = admin_client.get(reverse("wholesale_customers:invitations"), {"q": three[1].tax_id})
    assert "compras2@natatorio.test" in searched.content.decode()


def test_panel_send_button_is_refused_while_off(admin_client, three):
    invitations.prepare()
    response = admin_client.post(
        reverse("wholesale_customers:invitations_send"), {"scope": "unsent"}, follow=True
    )
    assert "Todavía no se habilitó" in response.content.decode()
    assert OutboundEmail.objects.count() == 0


def test_panel_send_resend_and_correct_email(admin_client, three, enabled):
    invitations.prepare()
    sent = admin_client.post(
        reverse("wholesale_customers:invitations_send"), {"scope": "unsent"}, follow=True
    )
    assert "Dejamos 3 invitaciones en la cola" in sent.content.decode()
    assert OutboundEmail.objects.filter(template_code="invitation").count() == 3
    account = CustomerAccount.objects.get(customer=three[0])
    admin_client.post(reverse("wholesale_customers:invitation_resend", args=[account.pk]))
    assert Invitation.objects.get(account=account).sent_count == 2
    admin_client.post(
        reverse("wholesale_customers:invitation_email", args=[account.pk]), {"email": "bien@natatorio.test"}
    )
    account.refresh_from_db()
    assert account.user.email == "bien@natatorio.test"
    assert Invitation.objects.get(account=account).status == Invitation.Status.UNSENT
    selected = admin_client.post(
        reverse("wholesale_customers:invitations_send"), {"scope": "selected", "accounts": [account.pk]}
    )
    assert (
        selected.status_code == 302
        and Invitation.objects.get(account=account).status == Invitation.Status.SENT
    )
    assert djmail.outbox == []


def test_panel_dry_run_shows_message_and_queues_nothing(admin_client, three, enabled):
    enabled.STORE_EMAIL_DRY_RUN = True
    invitations.prepare()
    response = admin_client.post(
        reverse("wholesale_customers:invitations_send"), {"scope": "unsent"}, follow=True
    )
    assert "Ensayo: se mandarían 3 invitaciones" in response.content.decode()
    assert OutboundEmail.objects.count() == 0


def test_outbound_email_screen_hides_the_personal_link(admin_client, three, enabled, admin_user):
    invitations.prepare()
    account = CustomerAccount.objects.get(customer=three[0])
    token = send_one(account, admin_user)
    page = admin_client.get(reverse("store_admin:outbound_emails"), {"estado": "pending"})
    html = page.content.decode()
    assert page.status_code == 200 and "Ya podés ingresar" in html
    assert token not in html and "enlace personal oculto" in html


def test_invitation_template_is_editable_and_seeded():
    from apps.wholesale.models import EmailTemplate

    template = EmailTemplate.objects.get(code="invitation")
    assert "{enlace}" in template.body and "{vence}" in template.body and "{cliente}" in template.body
