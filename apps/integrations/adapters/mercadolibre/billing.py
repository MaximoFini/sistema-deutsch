"""Datos de facturación del comprador de Mercado Libre → Customer (datos fiscales) y pedido."""

import logging

from django.db import transaction

from apps.customers.models import Address, Customer
from apps.integrations.http import ChannelHTTPError

logger = logging.getLogger(__name__)

VAT = {
    "responsable inscripto": Customer.VatCondition.RI,
    "iva responsable inscripto": Customer.VatCondition.RI,
    "monotributo": Customer.VatCondition.MONOTRIBUTO,
    "monotributista": Customer.VatCondition.MONOTRIBUTO,
    "iva exento": Customer.VatCondition.EXENTO,
    "exento": Customer.VatCondition.EXENTO,
    "consumidor final": Customer.VatCondition.CF,
}


def _additional(info: dict) -> dict:
    return {a.get("type"): a.get("value") for a in info.get("additional_info") or [] if a.get("type")}


def parse(data: dict) -> dict | None:
    """Normaliza la respuesta (versión vieja con additional_info, o nueva con objetos)."""
    if not data:
        return None
    info = data.get("billing_info", data)
    extra = _additional(info)
    identification = info.get("identification") or {}
    doc_type = (info.get("doc_type") or identification.get("type") or "").upper()
    doc_number = str(info.get("doc_number") or identification.get("number") or "").strip()
    taxpayer = (
        extra.get("TAXPAYER_TYPE_ID")
        or extra.get("TAXPAYER_TYPE")
        or ((info.get("taxes") or {}).get("taxpayer_type") or {}).get("description")
        or ""
    )
    name = (
        extra.get("BUSINESS_NAME")
        or " ".join(x for x in (extra.get("FIRST_NAME"), extra.get("LAST_NAME")) if x)
        or " ".join(x for x in (info.get("name"), info.get("last_name")) if x)
        or ""
    ).strip()
    address = info.get("address") or {}
    street = extra.get("STREET_NAME") or address.get("street_name") or ""
    if not (doc_number or name):
        return None
    return {
        "doc_type": doc_type,
        "doc_number": doc_number,
        "taxpayer_type": taxpayer,
        "vat_condition": VAT.get(taxpayer.strip().lower(), Customer.VatCondition.CF),
        "name": name,
        "address": {
            "street": street,
            "number": str(extra.get("STREET_NUMBER") or address.get("street_number") or ""),
            "city": extra.get("CITY_NAME") or address.get("city_name") or "",
            "province": extra.get("STATE_NAME") or address.get("state_name") or "",
            "postal_code": str(extra.get("ZIP_CODE") or address.get("zip_code") or ""),
        }
        if street
        else None,
    }


def fetch(client, order_id) -> dict | None:
    try:
        return client.get(f"/orders/{order_id}/billing_info")
    except ChannelHTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None
        raise


@transaction.atomic
def apply(document, parsed: dict | None) -> None:
    customer = document.customer
    if parsed is None or customer is None:
        return
    changed = []
    digits = "".join(ch for ch in parsed["doc_number"] if ch.isdigit())
    if digits and not customer.tax_id:
        customer.tax_id = digits
        customer.tax_id_type = (
            Customer.TaxIdType.CUIT
            if parsed["doc_type"] in ("CUIT", "CUIL") or len(digits) == 11
            else Customer.TaxIdType.DNI
        )
        changed += ["tax_id", "tax_id_type"]
    if (
        parsed["vat_condition"] != Customer.VatCondition.CF
        and customer.vat_condition == Customer.VatCondition.CF
    ):
        customer.vat_condition = parsed["vat_condition"]
        changed.append("vat_condition")
    if parsed["name"] and (
        not customer.legal_name
        or customer.legal_name == customer.trade_name
        or customer.legal_name.startswith("Comprador ML")
    ):
        customer.legal_name = parsed["name"][:255]
        changed.append("legal_name")
    if changed:
        customer.save(update_fields=[*changed, "updated_at"])
    addr = parsed.get("address")
    if addr and not customer.addresses.filter(kind=Address.Kind.FISCAL).exists():
        Address.objects.create(
            customer=customer,
            kind=Address.Kind.FISCAL,
            street=addr["street"][:255],
            number=addr["number"][:20],
            city=addr["city"][:100],
            province=addr["province"][:100],
            postal_code=addr["postal_code"][:10],
        )
    document.fiscal = {**(document.fiscal or {}), "buyer": parsed}
    document.save(update_fields=["fiscal", "updated_at"])


def refresh(client, order_id, document) -> None:
    apply(document, parse(fetch(client, order_id)))
