"""Clientes de la tienda: CUIT, registro, aprobación, cuenta corriente y suspensión (US-2)."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.alerts import services as alerts
from apps.audit import services as audit
from apps.customers.models import Address, Customer
from apps.integrations.models import RateLimitBucket
from apps.pricing.models import PriceList

from . import mail
from .models import CustomerAccount

CUIT_PREFIXES = {"20", "23", "24", "27", "30", "33", "34"}
CUIT_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
INVALID_CUIT = "El CUIT no es válido: revisá los 11 números"

VAT_CHOICES = [
    (Customer.VatCondition.RI, "Responsable inscripto"),
    (Customer.VatCondition.MONOTRIBUTO, "Monotributo"),
    (Customer.VatCondition.EXENTO, "Exento"),
]
PROVINCES = [
    "Buenos Aires",
    "Ciudad Autónoma de Buenos Aires",
    "Catamarca",
    "Chaco",
    "Chubut",
    "Córdoba",
    "Corrientes",
    "Entre Ríos",
    "Formosa",
    "Jujuy",
    "La Pampa",
    "La Rioja",
    "Mendoza",
    "Misiones",
    "Neuquén",
    "Río Negro",
    "Salta",
    "San Juan",
    "San Luis",
    "Santa Cruz",
    "Santa Fe",
    "Santiago del Estero",
    "Tierra del Fuego",
    "Tucumán",
]
# Datos del registro que el administrador puede corregir (el CUIT solo mientras está pendiente).
DATA_FIELDS = [
    "legal_name",
    "trade_name",
    "vat_condition",
    "street",
    "number",
    "city",
    "province",
    "postal_code",
    "phone",
]


class AccountError(Exception):
    """Error de negocio con un mensaje para mostrar tal cual."""


def normalize_cuit(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def validate_cuit(value: str) -> str:
    """Devuelve el CUIT normalizado (11 dígitos, sin guiones) o lanza ValueError con el mensaje de US-2."""
    digits = normalize_cuit(value)
    if len(digits) != 11 or digits[:2] not in CUIT_PREFIXES:
        raise ValueError(INVALID_CUIT)
    total = sum(int(d) * w for d, w in zip(digits[:10], CUIT_WEIGHTS, strict=True))
    check = 11 - total % 11
    if check == 11:
        check = 0
    elif check == 10:  # combinación inválida: AFIP nunca asigna dígito verificador 10
        raise ValueError(INVALID_CUIT)
    if check != int(digits[10]):
        raise ValueError(INVALID_CUIT)
    return digits


def format_cuit(digits: str) -> str:
    digits = normalize_cuit(digits)
    return f"{digits[:2]}-{digits[2:10]}-{digits[10:]}" if len(digits) == 11 else digits


def cuit_has_account(cuit: str) -> bool:
    return CustomerAccount.objects.filter(cuit=normalize_cuit(cuit)).exists()


def store_url(name: str, *args) -> str:
    path = reverse(name, args=args)
    return (settings.WHOLESALE_BASE_URL.rstrip("/") + path) if settings.WHOLESALE_BASE_URL else path


# ── Límite de registros por IP ────────────────────────────────────────────────


def registration_allowed(ip: str | None) -> bool:
    """Token bucket por IP (mismo `RateLimitBucket` de M0): N registros por hora."""
    if not ip:
        return True
    capacity = float(settings.WHOLESALE_REGISTRATIONS_PER_IP_HOUR)
    refill = capacity / 3600.0
    now = timezone.now()
    with transaction.atomic():
        bucket, _ = RateLimitBucket.objects.select_for_update().get_or_create(
            key=f"store-register:{ip}"[:60],
            defaults={
                "capacity": capacity,
                "refill_per_second": refill,
                "tokens": capacity,
                "updated_at": now,
            },
        )
        elapsed = max(0.0, (now - bucket.updated_at).total_seconds())
        bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_per_second)
        bucket.updated_at = now
        allowed = bucket.tokens >= 1
        if allowed:
            bucket.tokens -= 1
        bucket.save(update_fields=["tokens", "updated_at"])
    return allowed


# ── Registro ─────────────────────────────────────────────────────────────────


@transaction.atomic
def register(*, data: dict, password: str, request=None) -> CustomerAccount:
    """Crea el usuario (sin permisos internos) y la cuenta pendiente. `data` viene validado del formulario."""
    User = get_user_model()
    cuit = validate_cuit(data["cuit"])
    email = data["email"].strip().lower()
    if CustomerAccount.objects.filter(cuit=cuit).exists():
        raise AccountError("Ese CUIT ya tiene una cuenta.")
    if User.objects.filter(email__iexact=email).exists():
        raise AccountError("Ese email ya está registrado.")
    name = (data.get("trade_name") or data["legal_name"]).strip()[:150]
    user = User.objects.create_user(email=email, full_name=name, password=password)
    registration = {k: str(data.get(k, "") or "").strip() for k in DATA_FIELDS}
    registration["email"] = email
    account = CustomerAccount.objects.create(
        user=user,
        cuit=cuit,
        registration=registration,
        accepted_terms_at=timezone.now(),
    )
    audit.record(user, "client.registered", account, request=request, after={"cuit": cuit, **registration})
    account_id = account.pk
    display = account.display_name
    transaction.on_commit(
        lambda: alerts.emit(
            "wholesale.registration_new",
            title=f"Nuevo registro mayorista: {display}",
            body=f"CUIT {format_cuit(cuit)}. Revisá los datos y aprobalo o rechazalo.",
            link_url=f"/clientes-mayoristas/{account_id}/",
            dedupe_key=f"registration:{account_id}",
        )
    )
    mail.enqueue("registration_received", email, {"cliente": display})
    return account


# ── Panel: revisar, aprobar, rechazar, suspender ─────────────────────────────


def _require(user, perm="wholesale.manage_customers"):
    if not user.has_perm(perm):
        raise PermissionDenied


@transaction.atomic
def update_data(account: CustomerAccount, *, data: dict, user, request=None) -> None:
    """El administrador corrige los datos cargados. Si ya hay cliente vinculado, también lo actualiza."""
    _require(user)
    account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
    before = {"cuit": account.cuit, **account.registration}
    new = dict(account.registration)
    for key in DATA_FIELDS:
        if key in data:
            new[key] = str(data[key] or "").strip()
    if "cuit" in data and normalize_cuit(data["cuit"]) != account.cuit:
        if account.status != CustomerAccount.Status.PENDING:
            raise AccountError("El CUIT no se puede cambiar en una cuenta ya revisada.")
        cuit = validate_cuit(data["cuit"])
        if CustomerAccount.objects.filter(cuit=cuit).exclude(pk=account.pk).exists():
            raise AccountError("Ese CUIT ya tiene otra cuenta.")
        account.cuit = cuit
    account.registration = new
    account.save(update_fields=["registration", "cuit", "updated_at"])
    if account.customer_id:
        _fill_customer(account.customer, account, overwrite=True)
    audit.record(
        user, "client.updated", account, request=request, before=before, after={"cuit": account.cuit, **new}
    )


def _fill_customer(customer: Customer, account: CustomerAccount, overwrite: bool) -> None:
    """Copia los datos del registro al cliente. Sin `overwrite`, solo completa lo vacío."""
    data = account.registration
    fields = {
        "legal_name": data.get("legal_name", ""),
        "trade_name": data.get("trade_name", ""),
        "email": account.user.email,
        "phone": data.get("phone", ""),
    }
    for field, value in fields.items():
        if value and (overwrite or not getattr(customer, field)):
            setattr(customer, field, value[:255] if field != "phone" else value[:50])
    vat = data.get("vat_condition")
    if vat and (overwrite or customer.vat_condition == Customer.VatCondition.CF):
        customer.vat_condition = vat
    customer.tax_id = account.cuit
    customer.tax_id_type = Customer.TaxIdType.CUIT
    customer.kind = Customer.Kind.WHOLESALE
    customer.credit_enabled = account.credit_enabled
    if customer.price_list_id is None or overwrite:
        customer.price_list = PriceList.objects.filter(code="MAYORISTA").first()
    customer.save()
    address = customer.addresses.filter(kind=Address.Kind.FISCAL).first()
    if data.get("street") and (address is None or overwrite):
        address = address or Address(customer=customer, kind=Address.Kind.FISCAL)
        address.street = data.get("street", "")[:255]
        address.number = data.get("number", "")[:20]
        address.city = data.get("city", "")[:100]
        address.province = data.get("province", "")[:100]
        address.postal_code = data.get("postal_code", "")[:10]
        address.save()


@transaction.atomic
def approve(account: CustomerAccount, *, user, request=None) -> Customer:
    """Aprueba: vincula el cliente existente con ese CUIT (completando lo vacío) o crea uno mayorista."""
    _require(user)
    account = CustomerAccount.objects.select_for_update().select_related("user").get(pk=account.pk)
    if account.status not in (CustomerAccount.Status.PENDING, CustomerAccount.Status.REJECTED):
        raise AccountError("Esta cuenta ya fue aprobada.")
    customer = account.customer
    linked = False
    if customer is None:
        customer = (
            Customer.objects.select_for_update(of=("self",))
            .filter(tax_id=account.cuit, store_account__isnull=True)
            .order_by("id")
            .first()
        )
        linked = customer is not None
        if customer is None:
            if Customer.objects.filter(tax_id=account.cuit, store_account__isnull=False).exists():
                raise AccountError("Ya hay otra cuenta de la tienda vinculada a un cliente con ese CUIT.")
            customer = Customer(legal_name=account.registration.get("legal_name") or account.cuit)
        _fill_customer(customer, account, overwrite=not linked)
    account.customer = customer
    account.status = CustomerAccount.Status.APPROVED
    account.reviewed_by = user
    account.reviewed_at = timezone.now()
    account.rejection_reason = ""
    account.save()
    if not account.user.is_active:
        account.user.is_active = True
        account.user.save(update_fields=["is_active"])
    audit.record(
        user,
        "client.approved",
        account,
        request=request,
        after={"cliente": str(customer), "cliente_id": customer.pk, "vinculado_a_existente": linked},
    )
    mail.enqueue(
        "registration_approved",
        account.user.email,
        {"cliente": str(customer), "enlace": store_url("store:login")},
    )
    return customer


@transaction.atomic
def reject(account: CustomerAccount, *, reason: str, user, request=None) -> None:
    _require(user)
    reason = (reason or "").strip()
    if not reason:
        raise AccountError("Escribí el motivo del rechazo: se lo mandamos al cliente.")
    account = CustomerAccount.objects.select_for_update().select_related("user").get(pk=account.pk)
    if account.status != CustomerAccount.Status.PENDING:
        raise AccountError(
            "Solo se rechazan registros pendientes. Para cortar el acceso, suspendé la cuenta."
        )
    account.status = CustomerAccount.Status.REJECTED
    account.rejection_reason = reason[:500]
    account.reviewed_by = user
    account.reviewed_at = timezone.now()
    account.save()
    audit.record(user, "client.rejected", account, request=request, after={"motivo": reason})
    mail.enqueue(
        "registration_rejected", account.user.email, {"cliente": account.display_name, "motivo": reason}
    )


@transaction.atomic
def set_suspended(account: CustomerAccount, *, suspended: bool, user, request=None) -> None:
    _require(user)
    account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
    if suspended and account.status != CustomerAccount.Status.APPROVED:
        raise AccountError("Solo se suspenden cuentas aprobadas.")
    if not suspended and account.status != CustomerAccount.Status.SUSPENDED:
        raise AccountError("La cuenta no está suspendida.")
    account.status = CustomerAccount.Status.SUSPENDED if suspended else CustomerAccount.Status.APPROVED
    account.save(update_fields=["status", "updated_at"])
    audit.record(user, "client.suspended" if suspended else "client.reactivated", account, request=request)


@transaction.atomic
def set_credit(account: CustomerAccount, *, enabled: bool, user, request=None) -> None:
    _require(user)
    account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
    before = account.credit_enabled
    account.credit_enabled = enabled
    account.save(update_fields=["credit_enabled", "updated_at"])
    if account.customer_id:
        Customer.objects.filter(pk=account.customer_id).update(credit_enabled=enabled)
    audit.record(
        user,
        "client.credit_changed",
        account,
        request=request,
        before={"cuenta_corriente": before},
        after={"cuenta_corriente": enabled},
    )


def pending_count() -> int:
    return CustomerAccount.objects.filter(status=CustomerAccount.Status.PENDING).count()


@transaction.atomic
def request_change(account: CustomerAccount, *, text: str, user, request=None) -> None:
    """El cliente pide cambiar sus datos (el CUIT no): alerta para los administradores."""
    text = (text or "").strip()[:1000]
    if not text:
        raise AccountError("Contanos qué dato querés cambiar.")
    audit.record(user, "client.change_requested", account, request=request, pedido=text)
    display, account_id = account.display_name, account.pk
    stamp = timezone.now().strftime("%Y%m%d%H%M%S")
    transaction.on_commit(
        lambda: alerts.emit(
            "wholesale.data_change_requested",
            title=f"{display} pidió cambiar sus datos",
            body=text,
            link_url=f"/clientes-mayoristas/{account_id}/",
            dedupe_key=f"change:{account_id}:{stamp}",
        )
    )
