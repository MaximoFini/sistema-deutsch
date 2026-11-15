"""Pagos de los pedidos mayoristas, reserva de stock y vencimiento (US-5, §5 y §6).

- **Comprobantes:** imagen (jpg, png, webp) o PDF de hasta 10 MB. Se valida el contenido (los primeros
  bytes del archivo) además de la extensión. Van al almacenamiento privado y se descargan solo por una
  vista con permiso (el cliente dueño o quien puede confirmar pagos).
- **Confirmar pago:** Esperando pago → Nuevo (por `change_status`), pago confirmado, email.
- **Efectivo:** el pedido queda pendiente de cobro hasta que Despacho marca que lo cobró al entregar.
- **Reserva:** se libera al facturar en Contabilium, al cancelar o (la diferencia) al ajustar por
  faltante; nunca dos veces (`WholesaleOrder.reservation_released_at`).
- **Vencimiento:** a los N días sin pago se cancela, se libera la reserva y se devuelve el saldo a favor
  usado. Un día antes se le recuerda al cliente que suba el comprobante.

Regla de oro: la reserva es interna; nada de esto escribe stock ni precios en los canales.
"""

import logging
import os
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone

from apps.accounts.mixins import is_store_customer
from apps.alerts import services as alerts
from apps.audit import services as audit
from apps.inventory import services as inventory
from apps.inventory.models import StockMovement
from apps.sales import states
from apps.sales.models import Payment, SalesDocument

from . import catalog, mail
from .accounts import store_url
from .models import CustomerBalance, PaymentReceipt, StoreSettings, WholesaleOrder

logger = logging.getLogger(__name__)

MAX_RECEIPT_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "pdf": "pdf"}
CONTENT_TYPES = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf"}
FILE_EXTENSION = {"jpeg": "jpg", "png": "png", "webp": "webp", "pdf": "pdf"}
BANK_DETAILS_MISSING = (
    "Todavía no cargamos los datos para transferir: te los pasamos por email o WhatsApp en cuanto "
    "confirmemos tu pedido."
)
REMINDER_BEFORE = timedelta(hours=24)


class PaymentError(Exception):
    """Algo que la persona tiene que corregir (mensaje para mostrar tal cual)."""


# ── Utilidades ───────────────────────────────────────────────────────────────


def is_wholesale(doc: SalesDocument) -> bool:
    return doc.channel.code == "mayorista"


def order_of(doc: SalesDocument) -> WholesaleOrder | None:
    try:
        return doc.wholesale
    except WholesaleOrder.DoesNotExist:
        return None


def customer_email(doc: SalesDocument) -> str:
    customer = doc.customer
    if customer is None:
        return ""
    account = getattr(customer, "store_account", None)
    if account is not None and account.user.email:
        return account.user.email
    return customer.email or ""


def bank_details_text(store: StoreSettings | None = None) -> str:
    store = store or StoreSettings.load()
    return store.bank_details.strip() or BANK_DETAILS_MISSING


def money(value) -> str:
    return catalog.format_money(value)


def local_text(value) -> str:
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if value else ""


def _move_status(doc, to, *, user, reason="", request=None):
    """Cambio de estado como parte de una acción propia de la tienda (confirmar un pago, marcar o resolver
    un faltante). Esa acción ya validó su permiso; el historial registra a la persona."""
    return states.change_status(doc, to, user=user, system=True, reason=reason, request=request)


# ── Comprobantes ─────────────────────────────────────────────────────────────


def detect_kind(head: bytes) -> str | None:
    """Tipo real del archivo por sus primeros bytes (no por el nombre)."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"%PDF-"):
        return "pdf"
    return None


def validate_receipt(upload) -> str:
    """Devuelve el tipo (jpeg/png/webp/pdf) o lanza PaymentError con un mensaje claro."""
    if upload is None:
        raise PaymentError("Elegí el archivo del comprobante.")
    if upload.size > MAX_RECEIPT_BYTES:
        raise PaymentError("El archivo pesa más de 10 MB. Mandá una foto más liviana o el PDF del banco.")
    if upload.size == 0:
        raise PaymentError("El archivo está vacío. Probá subirlo de nuevo.")
    ext = os.path.splitext(upload.name or "")[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise PaymentError("El comprobante tiene que ser una foto (JPG, PNG o WEBP) o un PDF.")
    upload.seek(0)
    head = upload.read(16)
    upload.seek(0)
    kind = detect_kind(head)
    if kind is None or kind != ALLOWED_EXTENSIONS[ext]:
        raise PaymentError(
            "No pudimos leer el archivo como foto o PDF. Revisá que sea el comprobante y probá de nuevo."
        )
    return kind


@transaction.atomic
def upload_receipt(doc: SalesDocument, upload, *, user, request=None) -> PaymentReceipt:
    doc = (
        SalesDocument.objects.select_for_update(of=("self",))
        .select_related("channel", "customer")
        .get(pk=doc.pk)
    )
    order = order_of(doc)
    if order is None or order.payment_method != WholesaleOrder.PaymentMethod.TRANSFER:
        raise PaymentError("Este pedido no se paga por transferencia.")
    if doc.status != states.AWAITING_PAYMENT:
        raise PaymentError("Este pedido ya no está esperando el pago: no hace falta subir el comprobante.")
    kind = validate_receipt(upload)
    original = os.path.basename(upload.name or "comprobante")[:255]
    receipt = PaymentReceipt(document=doc, uploaded_by=user, original_name=original, size=upload.size)
    receipt.file.save(
        f"pedido-{doc.number}-{uuid.uuid4().hex[:12]}.{FILE_EXTENSION[kind]}", upload, save=False
    )
    receipt.save()
    audit.record(
        user,
        "wholesale.receipt_uploaded",
        doc,
        request=request,
        after={"archivo": original, "tamaño": upload.size},
    )
    ref = doc.channel_reference
    customer = str(doc.customer)
    doc_id = doc.pk
    transaction.on_commit(
        lambda: alerts.emit(
            "wholesale.receipt_uploaded",
            title=f"{customer} subió el comprobante de {ref}",
            body="Revisalo y confirmá el pago desde la ficha del pedido.",
            link_url=f"/pedidos/{doc_id}/",
            dedupe_key=f"receipt:{receipt.pk}",
        )
    )
    return receipt


def content_type_of(receipt: PaymentReceipt) -> str:
    ext = os.path.splitext(receipt.file.name)[1].lower().lstrip(".")
    return CONTENT_TYPES.get(ALLOWED_EXTENSIONS.get(ext, ""), "application/octet-stream")


def can_view_receipts(user, doc: SalesDocument) -> bool:
    """El cliente dueño o quien puede confirmar pagos (US-5). Nadie más, ni siquiera un vendedor."""
    if not getattr(user, "is_authenticated", False):
        return False
    if is_store_customer(user):
        return bool(doc.customer_id) and user.customer_account.customer_id == doc.customer_id
    return user.has_perm("wholesale.confirm_payment")


# ── Confirmar pago y cobro en efectivo ───────────────────────────────────────


@transaction.atomic
def confirm_payment(doc: SalesDocument, *, user, request=None) -> None:
    if not user.has_perm("wholesale.confirm_payment"):
        raise PermissionDenied
    doc = (
        SalesDocument.objects.select_for_update(of=("self",))
        .select_related("channel", "customer")
        .get(pk=doc.pk)
    )
    if not is_wholesale(doc) or order_of(doc) is None:
        raise PaymentError("Solo se confirman así los pagos de pedidos mayoristas.")
    if doc.status != states.AWAITING_PAYMENT:
        raise PaymentError(f"El pedido ya no está esperando el pago (está «{states.label(doc.status)}»).")
    now = timezone.now()
    payment = doc.payments.filter(external_reference="mayorista").first()
    if payment is None:
        payment = Payment(document=doc, method=Payment.Method.TRANSFER, external_reference="mayorista")
    payment.status = Payment.Status.CONFIRMED
    payment.amount = doc.total
    payment.paid_at = now
    payment.save()
    _move_status(doc, states.NEW, user=user, reason="Pago confirmado", request=request)
    audit.record(
        user,
        "payment.confirmed",
        doc,
        request=request,
        after={"monto": str(doc.total), "comprobantes": doc.receipts.count()},
    )
    mail.enqueue(
        "payment_confirmed",
        customer_email(doc),
        {
            "cliente": str(doc.customer),
            "pedido": doc.channel_reference,
            "total": money(doc.total),
            "enlace": store_url("store:order_detail", doc.number),
        },
    )


def cash_pending(doc: SalesDocument) -> Payment | None:
    """El pago en efectivo todavía sin cobrar (o None)."""
    order = order_of(doc)
    if order is None or order.payment_method != WholesaleOrder.PaymentMethod.CASH:
        return None
    return doc.payments.filter(method=Payment.Method.CASH, status=Payment.Status.PENDING).first()


@transaction.atomic
def mark_cash_collected(doc: SalesDocument, *, user, request=None) -> None:
    if not user.has_perm("sales.change_order_status"):
        raise PermissionDenied
    doc = SalesDocument.objects.select_for_update(of=("self",)).select_related("channel").get(pk=doc.pk)
    if doc.status == states.CANCELLED:
        raise PaymentError("El pedido está cancelado.")
    payment = cash_pending(doc)
    if payment is None:
        raise PaymentError("Este pedido no tiene un cobro en efectivo pendiente.")
    payment.status = Payment.Status.CONFIRMED
    payment.amount = doc.total
    payment.paid_at = timezone.now()
    payment.save(update_fields=["status", "amount", "paid_at", "updated_at"])
    audit.record(
        user, "order.payment_updated", doc, request=request, before={"cobrado": False},
        after={"cobrado": True, "medio": "cash", "monto": str(doc.total)},
    )  # fmt: skip


# ── Reserva y saldo a favor ──────────────────────────────────────────────────


def reserved_by_document(doc: SalesDocument) -> dict[int, Decimal]:
    """Lo que este pedido tiene reservado hoy, por variante (suma de sus movimientos de reserva)."""
    ct = ContentType.objects.get_for_model(SalesDocument)
    rows = (
        StockMovement.objects.filter(reference_type=ct, reference_id=str(doc.pk), affects="reserved")
        .values("variant_id")
        .annotate(q=Sum("quantity"))
    )
    return {r["variant_id"]: r["q"] for r in rows if r["q"]}


def change_line_reservation(doc, variant, delta, *, user=None, note="") -> None:
    """Toma (+) o libera (−) reserva de una línea, salvo que la reserva ya se haya liberado."""
    order = order_of(doc)
    if order is None or order.reservation_released_at is not None or not delta or variant is None:
        return
    inventory.change_reserved(
        variant, inventory.default_warehouse(), Decimal(delta), reference=doc, user=user, note=note
    )


@transaction.atomic
def release_reservation(doc: SalesDocument, *, reason: str, user=None) -> bool:
    """Libera todo lo que el pedido tiene reservado. Devuelve False si ya estaba liberada."""
    order = WholesaleOrder.objects.select_for_update().filter(document_id=doc.pk).first()
    if order is None or order.reservation_released_at is not None:
        return False
    warehouse = inventory.default_warehouse()
    ref = doc.channel_reference or str(doc)
    from apps.catalog.models import Variant

    reserved = reserved_by_document(doc)
    variants = Variant.objects.in_bulk(list(reserved))
    for variant_id, quantity in sorted(reserved.items()):
        if quantity > 0:
            inventory.change_reserved(
                variants[variant_id], warehouse, -quantity, reference=doc, user=user,
                note=f"Libera reserva {ref}: {reason}",
            )  # fmt: skip
    order.reservation_released_at = timezone.now()
    order.save(update_fields=["reservation_released_at"])
    return True


@transaction.atomic
def return_balance(doc: SalesDocument, *, user=None) -> Decimal:
    """Devuelve el saldo a favor usado en un pedido que se cancela (una sola vez)."""
    order = WholesaleOrder.objects.select_for_update().filter(document_id=doc.pk).first()
    if order is None or order.balance_returned_at is not None or order.balance_applied <= 0:
        return Decimal(0)
    CustomerBalance.objects.create(
        customer_id=doc.customer_id,
        amount=order.balance_applied,
        document=doc,
        note=f"Devolución del saldo usado en {doc.channel_reference} (cancelado)",
        created_by=user,
    )
    order.balance_returned_at = timezone.now()
    order.save(update_fields=["balance_returned_at"])
    return order.balance_applied


def on_cancelled(doc: SalesDocument, *, user=None, reason="Pedido cancelado") -> None:
    """Efectos de cancelar un pedido mayorista, venga de donde venga (M4, vencimiento…)."""
    if order_of(doc) is None:
        return
    with transaction.atomic():
        release_reservation(doc, reason=reason, user=user)
        return_balance(doc, user=user)


def on_invoiced(doc: SalesDocument, *, user=None) -> None:
    """Facturado en Contabilium: desde ahí el stock lo descuenta Contabilium (§5)."""
    if order_of(doc) is None:
        return
    release_reservation(doc, reason="Facturado en Contabilium", user=user)


# ── Vencimiento y recordatorio ───────────────────────────────────────────────


def _awaiting_transfers():
    return WholesaleOrder.objects.filter(
        payment_method=WholesaleOrder.PaymentMethod.TRANSFER,
        document__status=states.AWAITING_PAYMENT,
        expires_at__isnull=False,
    ).annotate(has_receipt=Exists(PaymentReceipt.objects.filter(document=OuterRef("document"))))


def expire_orders(now=None) -> dict:
    """Cancela los pedidos por transferencia vencidos sin comprobante. Con comprobante sin confirmar, alerta."""
    now = now or timezone.now()
    result = {"expired": 0, "with_receipt": 0}
    due = list(_awaiting_transfers().filter(expires_at__lte=now).select_related("document__customer"))
    for order in due:
        doc = order.document
        if order.has_receipt:
            result["with_receipt"] += 1
            alerts.emit(
                "wholesale.order_expired",
                title=f"{doc.channel_reference} venció con un comprobante sin confirmar",
                body="No lo cancelamos solo: revisá el comprobante y confirmá el pago o cancelá el pedido.",
                link_url=f"/pedidos/{doc.pk}/",
                dedupe_key=f"expired-receipt:{doc.pk}",
            )
            continue
        try:
            with transaction.atomic():
                changed = states.change_status(
                    doc, states.CANCELLED, system=True, reason="Venció el plazo para pagar la transferencia"
                )
                if not changed:
                    continue
                WholesaleOrder.objects.filter(pk=order.pk).update(expired_at=timezone.now())
                on_cancelled(doc, reason="Venció el plazo para pagar")
                mail.enqueue(
                    "order_expired",
                    customer_email(doc),
                    {
                        "cliente": str(doc.customer),
                        "pedido": doc.channel_reference,
                        "total": money(doc.total),
                        "enlace": store_url("store:order_detail", doc.number),
                    },
                )
                ref, doc_id, customer = doc.channel_reference, doc.pk, str(doc.customer)
                transaction.on_commit(
                    lambda ref=ref, doc_id=doc_id, customer=customer: alerts.emit(
                        "wholesale.order_expired",
                        title=f"Se canceló {ref} de {customer}: venció sin pago",
                        body="Liberamos la reserva de stock y le avisamos al cliente.",
                        link_url=f"/pedidos/{doc_id}/",
                        dedupe_key=f"expired:{doc_id}",
                    )
                )
        except states.TransitionNotAllowed:  # cambió de estado mientras tanto
            logger.info("No se pudo vencer %s: cambió de estado", doc.pk)
            continue
        result["expired"] += 1
    return result


def send_reminders(now=None) -> int:
    """Un día antes de vencer, recuerda (una sola vez) que suba el comprobante."""
    now = now or timezone.now()
    store = StoreSettings.load()
    sent = 0
    due = (
        _awaiting_transfers()
        .filter(reminder_sent_at__isnull=True, expires_at__gt=now, expires_at__lte=now + REMINDER_BEFORE)
        .filter(has_receipt=False)
        .select_related("document__customer")
    )
    for order in due:
        with transaction.atomic():
            locked = WholesaleOrder.objects.select_for_update().get(pk=order.pk)
            if locked.reminder_sent_at is not None:
                continue
            doc = order.document
            mail.enqueue(
                "payment_reminder",
                customer_email(doc),
                {
                    "cliente": str(doc.customer),
                    "pedido": doc.channel_reference,
                    "total": money(doc.total),
                    "vence": local_text(order.expires_at),
                    "datos_bancarios": bank_details_text(store),
                    "enlace": store_url("store:order_detail", doc.number),
                },
            )
            locked.reminder_sent_at = now
            locked.save(update_fields=["reminder_sent_at"])
            sent += 1
    return sent
