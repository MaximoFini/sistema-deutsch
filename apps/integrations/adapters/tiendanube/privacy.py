"""Webhooks obligatorios de privacidad de Tiendanube."""

from django.db import transaction
from django.db.models import Q

from apps.alerts import services as alerts
from apps.audit import services as audit
from apps.customers.models import Customer
from apps.integrations.models import ChannelCredential, ExternalRef
from apps.sales.models import Shipment

from .client import CHANNEL

ANON_NAME = "Cliente anonimizado"


def _tn_customer_ids() -> list[int]:
    return list(
        ExternalRef.objects.filter(channel__code=CHANNEL, content_type__model="customer").values_list(
            "object_id", flat=True
        )
    )


@transaction.atomic
def anonymize(customer: Customer) -> None:
    before = {"legal_name": customer.legal_name, "email": customer.email}
    customer.legal_name = ANON_NAME
    customer.trade_name = ""
    customer.email = ""
    customer.phone = ""
    customer.tax_id = ""
    customer.tax_id_type = Customer.TaxIdType.CF
    customer.save()
    customer.addresses.all().delete()
    Shipment.objects.filter(document__customer=customer).update(address=None)
    # Los documentos de venta (totales y líneas) se conservan: son registros comerciales.
    audit.record(
        None,
        "privacy.customer_redacted",
        customer,
        before={"redacted": True, **{k: bool(v) for k, v in before.items()}},
    )


def find_customer(payload_customer: dict) -> Customer | None:
    tn_id = payload_customer.get("id")
    if tn_id:
        ref = ExternalRef.objects.filter(
            channel__code=CHANNEL, content_type__model="customer", external_id=str(tn_id)
        ).first()
        if ref:
            return Customer.objects.filter(pk=ref.object_id).first()
    email = (payload_customer.get("email") or "").strip()
    if email:
        return Customer.objects.filter(email__iexact=email).first()
    return None


def handle(kind: str, payload: dict) -> str:
    if kind == "customers_redact":
        customer = find_customer(payload.get("customer") or {})
        if customer is None:
            return "sin cliente"
        anonymize(customer)
        return "anonimizado"
    if kind == "store_redact":
        for customer in Customer.objects.filter(Q(pk__in=_tn_customer_ids())):
            anonymize(customer)
        ChannelCredential.objects.filter(channel__code=CHANNEL).delete()
        return "tienda anonimizada"
    if kind == "customers_data_request":
        customer_data = payload.get("customer") or {}
        alerts.emit(
            "privacy.data_request",
            title="Tiendanube pide los datos personales de un cliente",
            body=(
                f"Cliente TN {customer_data.get('id')} ({customer_data.get('email') or 'sin email'}). "
                "Hay que responder el pedido a mano con los datos que guarda el sistema."
            ),
            dedupe_key=f"tn-data-request:{(payload.get('data_request') or {}).get('id') or customer_data.get('id')}",
        )
        return "alerta emitida"
    raise ValueError(f"Tipo de webhook de privacidad desconocido: {kind}")
