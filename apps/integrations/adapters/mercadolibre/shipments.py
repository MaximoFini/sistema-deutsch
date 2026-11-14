"""Envíos de Mercado Libre: modalidad, plazo de despacho, estado y etiquetas (PDF / ZPL)."""

import io
import logging
import zipfile
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.integrations.http import ChannelHTTPError
from apps.sales.models import Shipment

from . import orders
from .common import dt, error_body

logger = logging.getLogger(__name__)
NEW_FORMAT = {"x-format-new": "true"}

LOGISTIC_METHOD = {
    "self_service": Shipment.Method.ME_FLEX,
    "fulfillment": Shipment.Method.ME_FULL,
    "cross_docking": Shipment.Method.ME_COLECTA,
    "drop_off": Shipment.Method.ME_DROP_OFF,
    "xd_drop_off": Shipment.Method.ME_DROP_OFF,
    "default": Shipment.Method.ME_CUSTOM,
    "custom": Shipment.Method.ME_CUSTOM,
    "not_specified": Shipment.Method.ME_CUSTOM,
}
LABEL_METHODS = {Shipment.Method.ME_FLEX, Shipment.Method.ME_COLECTA, Shipment.Method.ME_DROP_OFF}
CLOSED_STATUSES = {"delivered", "cancelled", "not_delivered"}


class LabelNotReady(Exception):
    """La etiqueta todavía no está disponible (p. ej. venta sin pagar o envío no listo)."""


def method_for(logistic_type: str) -> str:
    return LOGISTIC_METHOD.get(logistic_type or "", Shipment.Method.ME_OTHER)


def _deadline(client, shipment_id, data: dict):
    try:
        sla = client.get(f"/shipments/{shipment_id}/sla")
        if sla.get("expected_date"):
            return dt(sla["expected_date"])
    except ChannelHTTPError:
        pass
    limit = ((data.get("shipping_option") or {}).get("estimated_handling_limit") or {}).get("date")
    return dt(limit)


def refresh(client, shipment_id) -> Shipment | None:
    data = client.get(f"/shipments/{shipment_id}", headers=NEW_FORMAT)
    logistic = data.get("logistic_type") or (data.get("logistic") or {}).get("type") or ""
    order_id = data.get("order_id") or (data.get("external_reference") or "")
    document = orders.find_document(order_id) if order_id else None
    if document is None:
        logger.info("Envío ML %s sin pedido todavía (orden %s)", shipment_id, order_id)
        return None
    method = method_for(logistic)
    history = data.get("status_history") or {}
    address = (
        data.get("receiver_address") or ((data.get("destination") or {}).get("shipping_address")) or None
    )
    previous = (
        Shipment.objects.filter(document=document, external_id=str(shipment_id))
        .values("address", "logistic_type", "tracking_number")
        .first()
    )
    shipment, _ = Shipment.objects.update_or_create(
        document=document,
        external_id=str(shipment_id),
        defaults={
            "method": method,
            "logistic_type": logistic[:40],
            "carrier_name": ((data.get("shipping_option") or {}).get("name") or "")[:100],
            "tracking_number": (data.get("tracking_number") or "")[:100],
            "status": data.get("status") or "pending",
            "substatus": (data.get("substatus") or "")[:60],
            "dispatch_deadline": _deadline(client, shipment_id, data) if method in LABEL_METHODS else None,
            "shipped_at": dt(history.get("date_shipped")),
            "address": address,
        },
    )
    if previous is not None and previous != {
        "address": shipment.address,
        "logistic_type": shipment.logistic_type,
        "tracking_number": shipment.tracking_number,
    }:
        _drop_saved_labels(shipment)
    orders.refresh_channel_status(document)
    from apps.sales import sync as order_sync

    order_sync.sync_internal_status(document)
    return shipment


def _drop_saved_labels(shipment: Shipment) -> None:
    """ML cambió el envío (domicilio, logística o seguimiento): la etiqueta guardada ya no sirve.

    Se borran el PDF y el ZPL para que la próxima impresión los pida de nuevo a Mercado Libre.
    """
    fields = [name for name in ("label_file", "label_zpl_file") if getattr(shipment, name)]
    if not fields:
        return
    for name in fields:
        getattr(shipment, name).delete(save=False)
    # La etiqueta impresa quedó vieja: en Despacho vuelve a figurar "Etiqueta sin imprimir".
    shipment.label_printed_at = None
    shipment.save(update_fields=[*fields, "label_printed_at", "updated_at"])
    logger.info("Envío ML %s cambió: se descartó la etiqueta guardada", shipment.external_id)


def refresh_open(client) -> dict:
    stats = {"shipments": 0, "errors": []}
    recent = timezone.now() - timedelta(days=30)
    qs = (
        Shipment.objects.filter(document__channel__code="mercadolibre", created_at__gte=recent)
        .exclude(external_id="")
        .exclude(status__in=CLOSED_STATUSES)
    )
    for shipment in qs:
        try:
            refresh(client, shipment.external_id)
            stats["shipments"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append(
                {"id": shipment.external_id, "error": f"{type(exc).__name__}: {exc}"[:300]}
            )
    return stats


def _unzip(content: bytes) -> bytes:
    if content[:2] != b"PK":
        return content
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = next(n for n in zf.namelist() if not n.endswith("/"))
        return zf.read(name)


def get_label(client, shipment: Shipment, fmt: str | None = None) -> bytes:
    """Devuelve la etiqueta (PDF 10×15 o ZPL). La guarda y la reutiliza si ya existe."""
    fmt = fmt or settings.ML_LABEL_FORMAT
    field = shipment.label_zpl_file if fmt == "zpl2" else shipment.label_file
    if field:
        field.open("rb")
        try:
            return field.read()
        finally:
            field.close()
    if shipment.method not in LABEL_METHODS:
        raise LabelNotReady("Esta modalidad de envío no usa etiqueta de Mercado Libre.")
    try:
        response = client.get_raw(
            "/shipment_labels", params={"shipment_ids": shipment.external_id, "response_type": fmt}
        )
    except ChannelHTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (400, 403, 404, 409, 424):
            message = error_body(exc).get("message", "")
            raise LabelNotReady(
                message or "La etiqueta todavía no está disponible en Mercado Libre."
            ) from exc
        raise
    content = _unzip(response.content)
    ext = "zpl" if fmt == "zpl2" else "pdf"
    target = "label_zpl_file" if fmt == "zpl2" else "label_file"
    getattr(shipment, target).save(f"ml-{shipment.external_id}.{ext}", ContentFile(content), save=False)
    shipment.save(update_fields=[target, "updated_at"])
    return content
