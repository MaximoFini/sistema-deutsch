"""Cuentas e invitaciones de los clientes mayoristas ya cargados (M9-03 / DDEV-58).

Dos pasos separados:

1. **Preparar** (`prepare`): por cada `Customer` mayorista con email y CUIT válidos crea el usuario (con
   contraseña inutilizable), la `CustomerAccount` aprobada (sin cuenta corriente) y una `Invitation` «sin
   enviar». No manda nada. Es idempotente. Los que no se pueden incluir quedan en un informe con el motivo.
2. **Enviar** (`send_invitations`): genera un enlace de un solo uso por cuenta y lo encola en
   `OutboundEmail`. Está apagado por defecto (`STORE_INVITATIONS_ENABLED`), exige `manage_customers`,
   respeta el límite por hora y el modo ensayo (`STORE_EMAIL_DRY_RUN`).

Del enlace solo se guarda el hash. El token nunca se escribe en el log ni en la auditoría (solo viaja en
el email encolado).
"""

import hashlib
import logging
import re
import secrets
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.customers.models import Customer

from . import accounts, mail
from .accounts import AccountError
from .models import CustomerAccount, Invitation, OutboundEmail

logger = logging.getLogger(__name__)

DISABLED_MESSAGE = (
    "Todavía no se habilitó el envío de invitaciones. Se activa el día del lanzamiento "
    "(interruptor STORE_INVITATIONS_ENABLED)."
)
REQUEST_COOLDOWN = timedelta(minutes=15)  # entre un enlace y otro pedido por el propio cliente

NO_EMAIL = "no_email"
BAD_EMAIL = "bad_email"
BAD_DOCUMENT = "bad_document"
DUP_EMAIL = "dup_email"
DUP_CUIT = "dup_cuit"
REASONS = {
    NO_EMAIL: "Sin email cargado",
    BAD_EMAIL: "Email inválido",
    BAD_DOCUMENT: "CUIT o documento inválido",
    DUP_EMAIL: "Email repetido",
    DUP_CUIT: "CUIT repetido",
}

CREATE, LINK, EXISTING = "create", "link", "existing"


class InvitationsDisabled(AccountError):
    """El interruptor de envío está apagado."""


def _require(user, perm="wholesale.manage_customers"):
    if user is None or not user.has_perm(perm):
        raise PermissionDenied


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── 1. Preparar ──────────────────────────────────────────────────────────────


@dataclass
class Decision:
    customer: Customer
    action: str | None = None  # CREATE | LINK | EXISTING | None (excluido)
    reason: str | None = None
    detail: str = ""
    email: str = ""
    cuit: str = ""
    account: CustomerAccount | None = None  # la cuenta existente (LINK, EXISTING)

    @property
    def reason_label(self) -> str:
        return REASONS.get(self.reason or "", "")

    @property
    def excluded(self) -> bool:
        return self.reason is not None


def candidates():
    return (
        Customer.objects.filter(kind=Customer.Kind.WHOLESALE, is_active=True)
        .select_related("store_account")
        .order_by("id")
    )


def _clean_email(raw: str) -> tuple[str, str | None]:
    """(email normalizado, motivo de exclusión o None)."""
    email = (raw or "").strip().lower()
    if not email:
        return "", NO_EMAIL
    try:
        validate_email(email)
    except ValidationError:
        return email, BAD_EMAIL
    return email, None


def plan() -> list[Decision]:
    """Decide qué pasa con cada cliente mayorista sin tocar nada (sirve para el informe y para `--dry-run`)."""
    User = get_user_model()
    rows: list[Decision] = []
    for customer in candidates():
        account = getattr(customer, "store_account", None)
        if account is not None:
            rows.append(Decision(customer, EXISTING, account=account, cuit=account.cuit))
            continue
        email, bad = _clean_email(customer.email)
        decision = Decision(customer, email=email)
        if bad:
            decision.reason = bad
            decision.detail = customer.email or ""
        elif customer.tax_id_type != Customer.TaxIdType.CUIT:
            decision.reason = BAD_DOCUMENT
            decision.detail = f"Tipo de documento: {customer.get_tax_id_type_display()}"
        else:
            try:
                decision.cuit = accounts.validate_cuit(customer.tax_id)
            except ValueError:
                decision.reason = BAD_DOCUMENT
                decision.detail = f"CUIT cargado: {customer.tax_id or '(vacío)'}"
        rows.append(decision)

    # Repetidos entre los candidatos: no se sabe de quién es, así que ninguno entra hasta corregirlo.
    emails = Counter(d.email for d in rows if d.action is None and not d.reason)
    cuits = Counter(d.cuit for d in rows if d.action is None and not d.reason)
    for d in rows:
        if d.action is not None or d.reason:
            continue
        if emails[d.email] > 1:
            d.reason, d.detail = DUP_EMAIL, f"Lo comparte con otro cliente: {d.email}"
        elif cuits[d.cuit] > 1:
            d.reason, d.detail = DUP_CUIT, f"Lo comparte con otro cliente: {accounts.format_cuit(d.cuit)}"

    # Contra lo que ya existe en la base (cuentas de tienda y usuarios).
    pending = [d for d in rows if d.action is None and not d.reason]
    by_cuit = {a.cuit: a for a in CustomerAccount.objects.filter(cuit__in=[d.cuit for d in pending])}
    users = {email.lower() for email in User.objects.values_list("email", flat=True)}
    for d in pending:
        account = by_cuit.get(d.cuit)
        if account is not None:
            if account.customer_id is None:
                d.action, d.account = LINK, account  # se registró sola con ese CUIT: se aprueba y vincula
            else:
                d.reason, d.detail = DUP_CUIT, "Ese CUIT ya tiene una cuenta de otro cliente"
        elif d.email in users:
            d.reason = DUP_EMAIL
            d.detail = "Ese email ya lo usa otro usuario del sistema"
        else:
            d.action = CREATE
    return rows


@dataclass
class PrepareReport:
    dry_run: bool = False
    created: int = 0
    linked: int = 0
    already: int = 0
    excluded: list[Decision] = field(default_factory=list)

    @property
    def by_reason(self) -> dict[str, int]:
        counts = Counter(d.reason for d in self.excluded)
        return {code: counts[code] for code in REASONS if counts[code]}


def _create_account(decision: Decision) -> CustomerAccount:
    User = get_user_model()
    customer = decision.customer
    user = User.objects.create_user(email=decision.email, full_name=str(customer)[:150])
    user.set_unusable_password()  # nunca una contraseña real: entra recién al aceptar la invitación
    user.save(update_fields=["password"])
    registration = {
        "legal_name": customer.legal_name,
        "trade_name": customer.trade_name,
        "vat_condition": customer.vat_condition,
        "phone": customer.phone,
        "email": decision.email,
        "origen": "importado de los clientes cargados",
    }
    account = CustomerAccount.objects.create(
        user=user,
        customer=customer,
        cuit=decision.cuit,
        status=CustomerAccount.Status.APPROVED,
        credit_enabled=False,  # la cuenta corriente la habilita Deutsch aparte
        registration=registration,
        reviewed_at=timezone.now(),
        accepted_terms_at=None,
    )
    return account


def _ensure_invitation(account: CustomerAccount) -> bool:
    """Crea la invitación «sin enviar» si la cuenta todavía no tiene contraseña. True si creó una."""
    if account.status != CustomerAccount.Status.APPROVED or account.user.has_usable_password():
        return False
    _, created = Invitation.objects.get_or_create(account=account)
    return created


def prepare(*, dry_run: bool = False) -> PrepareReport:
    """Crea las cuentas y las invitaciones «sin enviar». No manda nada. Se puede repetir."""
    report = PrepareReport(dry_run=dry_run)
    for decision in plan():
        if decision.excluded:
            report.excluded.append(decision)
            continue
        if dry_run:
            if decision.action == CREATE:
                report.created += 1
            elif decision.action == LINK:
                report.linked += 1
            else:
                report.already += 1
            continue
        try:
            with transaction.atomic():
                if decision.action == CREATE:
                    account = _create_account(decision)
                    _ensure_invitation(account)
                    audit.record(
                        None,
                        "client.imported",
                        account,
                        after={"cliente_id": decision.customer.pk, "cuit": account.cuit},
                    )
                    report.created += 1
                elif decision.action == LINK:
                    _link_existing(decision)
                    report.linked += 1
                else:
                    _ensure_invitation(decision.account)  # la cuenta ya estaba: solo se completa
                    report.already += 1
        except IntegrityError:
            decision.reason = DUP_CUIT if decision.action == CREATE else DUP_EMAIL
            decision.detail = "Otro proceso la creó al mismo tiempo: volvé a correr «preparar»"
            report.excluded.append(decision)
    if not dry_run:
        audit.record(
            None,
            "invitation.prepared",
            None,
            after={
                "creadas": report.created,
                "vinculadas": report.linked,
                "ya_estaban": report.already,
                "no_incluidos": report.by_reason,
            },
        )
    return report


def _link_existing(decision: Decision) -> None:
    """Un cliente que ya se había registrado solo con ese CUIT: se aprueba esa cuenta y no se crea otra."""
    account = CustomerAccount.objects.select_for_update().select_related("user").get(pk=decision.account.pk)
    account.customer = decision.customer
    if account.status in (CustomerAccount.Status.PENDING, CustomerAccount.Status.REJECTED):
        account.status = CustomerAccount.Status.APPROVED
        account.reviewed_at = timezone.now()
        account.rejection_reason = ""
    account.save()
    if not account.user.is_active:
        account.user.is_active = True
        account.user.save(update_fields=["is_active"])
    _ensure_invitation(account)
    audit.record(
        None,
        "client.imported",
        account,
        after={"cliente_id": decision.customer.pk, "cuit": account.cuit, "vinculada_a_registro": True},
    )


# ── 2. Estados y seguimiento ─────────────────────────────────────────────────


def sync_states(now=None) -> None:
    """Refleja en el estado lo que pasó solo: el email falló (rebotada) o el enlace venció."""
    now = now or timezone.now()
    Invitation.objects.filter(
        status=Invitation.Status.SENT, last_email__status=OutboundEmail.Status.FAILED
    ).update(status=Invitation.Status.BOUNCED, updated_at=now)
    Invitation.objects.filter(status=Invitation.Status.SENT, expires_at__lte=now).update(
        status=Invitation.Status.EXPIRED, updated_at=now
    )


def totals() -> dict:
    sync_states()
    counts = Counter(Invitation.objects.values_list("status", flat=True))
    return {
        "invited": sum(counts.values()),
        "unsent": counts[Invitation.Status.UNSENT],
        "sent": counts[Invitation.Status.SENT],
        "accepted": counts[Invitation.Status.ACCEPTED],
        "expired": counts[Invitation.Status.EXPIRED],
        "bounced": counts[Invitation.Status.BOUNCED],
    }


def exclusions() -> list[Decision]:
    return [d for d in plan() if d.excluded]


def accounts_for(scope: str):
    """Cuentas a invitar: «unsent» (todavía no se mandó) o «not_entered» (se mandó y no entraron)."""
    S = Invitation.Status
    statuses = {"unsent": [S.UNSENT], "not_entered": [S.SENT, S.EXPIRED, S.BOUNCED]}[scope]
    return CustomerAccount.objects.filter(invitation__status__in=statuses)


def mask_token(text: str) -> str:
    """Oculta el enlace personal en los textos que se muestran en el panel."""
    return re.sub(r"(/invitacion/)[-\w]{20,}", r"\1«enlace personal oculto»", text or "")


# ── 3. Enviar ────────────────────────────────────────────────────────────────


@dataclass
class SendResult:
    dry_run: bool = False
    queued: int = 0
    would_send: int = 0
    deferred: int = 0  # quedaron para la próxima por el límite por hora
    skipped: list[tuple[CustomerAccount, str]] = field(default_factory=list)


def hourly_budget(now=None) -> int:
    now = now or timezone.now()
    used = Invitation.objects.filter(sent_at__gt=now - timedelta(hours=1)).count()
    return max(0, settings.STORE_INVITATIONS_PER_HOUR - used)


def _deliver(invitation: Invitation, now) -> OutboundEmail:
    """Genera un enlace nuevo (el anterior deja de servir) y encola el email. Dentro de una transacción."""
    account = invitation.account
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(days=settings.STORE_INVITATION_DAYS)
    email = mail.enqueue(
        "invitation",
        account.user.email,
        {
            "cliente": account.display_name,
            "enlace": accounts.store_url("store:invitation", token),
            "vence": timezone.localtime(expires).strftime("%d/%m/%Y"),
        },
    )
    if email is None:
        raise AccountError("No se pudo armar el email de invitación: falta la plantilla «invitation».")
    invitation.token_hash = hash_token(token)
    invitation.status = Invitation.Status.SENT
    invitation.sent_to = account.user.email
    invitation.sent_at = now
    invitation.sent_count += 1
    invitation.expires_at = expires
    invitation.last_email = email
    invitation.save()
    return email


def send_invitations(accounts_to_invite, user, *, request=None) -> SendResult:
    """Encola la invitación de cada cuenta. NUNCA manda por sí misma: solo deja filas en `OutboundEmail`.

    Falla si el interruptor está apagado (`InvitationsDisabled`) o si `user` no tiene
    `wholesale.manage_customers`. Con `STORE_EMAIL_DRY_RUN` registra qué mandaría y no toca nada.
    Respeta `STORE_INVITATIONS_PER_HOUR`; lo que no entra queda «sin enviar» o igual que estaba.
    """
    _require(user)
    if not settings.STORE_INVITATIONS_ENABLED:
        raise InvitationsDisabled(DISABLED_MESSAGE)
    now = timezone.now()
    sync_states(now)
    ids = [a.pk if hasattr(a, "pk") else a for a in accounts_to_invite]
    result = SendResult(dry_run=settings.STORE_EMAIL_DRY_RUN)
    invitations = list(
        Invitation.objects.select_related("account__user", "account__customer")
        .filter(account_id__in=ids)
        .order_by("pk")
    )
    sendable = []
    for inv in invitations:
        account = inv.account
        if inv.status == Invitation.Status.ACCEPTED:
            result.skipped.append((account, "Ya creó su contraseña."))
        elif account.status != CustomerAccount.Status.APPROVED or not account.user.is_active:
            result.skipped.append((account, "La cuenta no está activa."))
        else:
            sendable.append(inv)
    budget = hourly_budget(now)
    chosen, result.deferred = sendable[:budget], max(0, len(sendable) - budget)

    if result.dry_run:
        result.would_send = len(chosen)
        logger.info("Ensayo de invitaciones: se mandarían %s (no se encoló nada)", len(chosen))
        audit.record(
            user,
            "invitation.dry_run",
            None,
            request=request,
            cantidad=len(chosen),
            cuentas=[inv.account_id for inv in chosen][:1000],
        )
        return result

    sent_ids = []
    for inv in chosen:
        with transaction.atomic():
            fresh = (
                Invitation.objects.select_for_update(of=("self",))
                .select_related("account__user")
                .get(pk=inv.pk)
            )
            if fresh.status == Invitation.Status.ACCEPTED:
                result.skipped.append((fresh.account, "Ya creó su contraseña."))
                continue
            _deliver(fresh, now)
            sent_ids.append(fresh.account_id)
    result.queued = len(sent_ids)
    if sent_ids:
        audit.record(
            user, "invitation.sent", None, request=request, cantidad=len(sent_ids), cuentas=sent_ids[:1000]
        )
    logger.info(
        "Invitaciones encoladas: %s (quedan %s por el límite por hora)", len(sent_ids), result.deferred
    )
    return result


# ── 4. Aceptar ───────────────────────────────────────────────────────────────


def find_valid(token: str) -> Invitation | None:
    """La invitación que corresponde a ese enlace si sigue sirviendo; si no, None (usado, vencido o inventado)."""
    if not token:
        return None
    return (
        Invitation.objects.select_related("account__user")
        .filter(
            token_hash=hash_token(token),
            status=Invitation.Status.SENT,
            expires_at__gt=timezone.now(),
            account__status=CustomerAccount.Status.APPROVED,
            account__user__is_active=True,
        )
        .first()
    )


@transaction.atomic
def accept(token: str, *, password: str, request=None):
    """El cliente elige su contraseña y acepta los términos. Devuelve el usuario. El enlace queda usado."""
    invitation = find_valid(token)
    if invitation is None:
        raise AccountError("Este enlace ya se usó o venció.")
    invitation = (
        Invitation.objects.select_for_update(of=("self",))
        .select_related("account__user")
        .get(pk=invitation.pk)
    )
    if invitation.status != Invitation.Status.SENT or invitation.token_hash != hash_token(token):
        raise AccountError("Este enlace ya se usó o venció.")  # otro pedido se adelantó
    now = timezone.now()
    account, user = invitation.account, invitation.account.user
    user.set_password(password)
    user.save(update_fields=["password"])
    account.accepted_terms_at = now
    account.save(update_fields=["accepted_terms_at", "updated_at"])
    invitation.status = Invitation.Status.ACCEPTED
    invitation.accepted_at = now
    invitation.token_hash = ""  # el enlace ya no sirve
    invitation.save()
    audit.record(user, "invitation.accepted", account, request=request)
    return user


# ── 5. Pedir otro enlace desde el ingreso ────────────────────────────────────


def request_new(cuit: str, email: str, *, request=None) -> bool:
    """«Mandame otra invitación». El que llama responde SIEMPRE lo mismo: no se revela si la cuenta existe.

    Solo manda si el interruptor está prendido, el CUIT y el email son de una cuenta con invitación sin
    aceptar, y pasaron `REQUEST_COOLDOWN` desde el último enlace. Devuelve True si encoló un email.
    """
    digits = accounts.normalize_cuit(cuit)
    email = (email or "").strip().lower()
    if not digits or not email or not settings.STORE_INVITATIONS_ENABLED:
        return False
    account = (
        CustomerAccount.objects.select_related("user")
        .filter(cuit=digits, user__email__iexact=email, status=CustomerAccount.Status.APPROVED)
        .first()
    )
    if account is None or not account.user.is_active:
        return False
    now = timezone.now()
    with transaction.atomic():
        invitation = Invitation.objects.select_for_update().filter(account=account).first()
        if invitation is None or invitation.status == Invitation.Status.ACCEPTED:
            return False
        if invitation.sent_at and invitation.sent_at > now - REQUEST_COOLDOWN:
            return False
        if settings.STORE_EMAIL_DRY_RUN:
            logger.info("Ensayo: la cuenta %s pidió otra invitación (no se encoló nada)", account.pk)
            return False
        invitation = Invitation.objects.select_related("account__user").get(pk=invitation.pk)
        _deliver(invitation, now)
        audit.record(None, "invitation.requested", account, request=request)
    return True


# ── 6. Corregir el email antes de enviar ─────────────────────────────────────


@transaction.atomic
def change_email(account: CustomerAccount, new_email: str, *, user, request=None) -> None:
    """El administrador corrige el email de acceso. Si ya se había mandado un enlace, deja de servir."""
    _require(user)
    User = get_user_model()
    email, bad = _clean_email(new_email)
    if bad:
        raise AccountError("Escribí un email válido.")
    account = (
        CustomerAccount.objects.select_for_update(of=("self",))
        .select_related("user", "customer")
        .get(pk=account.pk)
    )
    invitation = Invitation.objects.select_for_update().filter(account=account).first()
    if invitation is not None and invitation.status == Invitation.Status.ACCEPTED:
        raise AccountError("Este cliente ya creó su contraseña: el email de acceso no se cambia desde acá.")
    if account.user.email.lower() == email:
        raise AccountError("Ese ya es el email de este cliente.")
    if User.objects.filter(email__iexact=email).exclude(pk=account.user_id).exists():
        raise AccountError("Ese email ya lo usa otro usuario.")
    before = account.user.email
    account.user.email = email
    account.user.save(update_fields=["email"])
    account.registration = {**(account.registration or {}), "email": email}
    account.save(update_fields=["registration", "updated_at"])
    if account.customer_id:
        Customer.objects.filter(pk=account.customer_id).update(email=email)
    if invitation is not None and invitation.status != Invitation.Status.UNSENT:
        # El enlace anterior fue a la dirección equivocada: se anula y la invitación vuelve a «sin enviar».
        if invitation.last_email_id:
            OutboundEmail.objects.filter(
                pk=invitation.last_email_id, status=OutboundEmail.Status.PENDING
            ).update(status=OutboundEmail.Status.EXPIRED, last_error="Email corregido: no se manda.")
        invitation.token_hash = ""
        invitation.status = Invitation.Status.UNSENT
        invitation.expires_at = None
        invitation.sent_to = ""
        invitation.last_email = None
        invitation.save()
    audit.record(
        user,
        "invitation.email_corrected",
        account,
        request=request,
        before={"email": before},
        after={"email": email},
    )
