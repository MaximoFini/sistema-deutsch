"""Etiquetas de envío (US-3): Mercado Libre en lote (reusa M2) y rótulo propio de transporte.

Las etiquetas de ML se piden de a una (con el caché de M2): si un envío no está listo, se saltea y
se imprime el resto. El lote nativo de ML rechaza todo si uno solo falla.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit import services as audit
from apps.integrations.errors import friendly
from apps.sales.models import SalesDocument, Shipment

from . import pdf
from .batches import order_ref

logger = logging.getLogger(__name__)
MAX_PACKAGES = 50
KIND_ML, KIND_CARRIER = "ml", "rotulo"


class LabelError(Exception):
    """Error que se le muestra tal cual a Depósito."""


@dataclass
class LabelBundle:
    content: bytes | None
    fmt: str  # "pdf" | "zpl2"
    printed: list[Shipment] = field(default_factory=list)
    skipped: list[tuple[SalesDocument, str]] = field(default_factory=list)

    @property
    def extension(self) -> str:
        return "zpl" if self.fmt == "zpl2" else "pdf"

    @property
    def content_type(self) -> str:
        return "text/plain; charset=utf-8" if self.fmt == "zpl2" else "application/pdf"

    def skipped_text(self) -> str:
        return "; ".join(f"{order_ref(doc)} ({reason})" for doc, reason in self.skipped)


def _ml_methods():
    from apps.integrations.adapters.mercadolibre.shipments import LABEL_METHODS

    return LABEL_METHODS


def label_shipment(document: SalesDocument, shipments=None) -> Shipment | None:
    """El envío que lleva etiqueta: el de ML con etiqueta si hay; si no, el primero."""
    items = list(shipments if shipments is not None else document.shipments.all())
    items.sort(key=lambda s: s.pk)
    methods = _ml_methods()
    for s in items:
        if s.method in methods:
            return s
    return items[0] if items else None


def label_kind(shipment: Shipment | None) -> str:
    """Qué se imprime para este envío: "ml", "rotulo", "envio_nube" o ""."""
    if shipment is None:
        return ""
    if shipment.method in _ml_methods():
        return KIND_ML
    if shipment.method == Shipment.Method.CARRIER:
        return KIND_CARRIER
    if shipment.method == Shipment.Method.ENVIO_NUBE:
        return "envio_nube"
    return ""


def tn_admin_url(document: SalesDocument) -> str:
    template = settings.TN_ADMIN_ORDER_URL
    if not template or document.channel.code != "tiendanube":
        return ""
    from apps.integrations.models import ExternalRef

    external_id = (
        ExternalRef.objects.filter(
            channel__code="tiendanube", content_type__model="salesdocument", object_id=document.pk
        )
        .values_list("external_id", flat=True)
        .first()
    )
    return template.replace("{id}", external_id) if external_id else ""


def _not_ready_reason(shipment: Shipment, message: str) -> str:
    """Motivo en castellano claro (ML responde en inglés, p. ej. "Shipment not ready to print")."""
    text = (message or "").lower()
    if shipment.status == "cancelled" or "cancel" in text:
        return "el envío se canceló en Mercado Libre"
    if "pay" in text:
        return "Mercado Libre todavía no habilita la etiqueta: la venta no está pagada"
    return "Mercado Libre todavía no habilita la etiqueta: el envío no está listo para imprimir"


def ml_labels(shipments, *, fmt: str | None = None) -> LabelBundle:
    """Junta en un solo archivo las etiquetas de ML de estos envíos; saltea las que no están listas."""
    from apps.integrations.adapters.mercadolibre import shipments as ml_shipments
    from apps.integrations.adapters.mercadolibre.client import MLClient

    fmt = fmt or settings.ML_LABEL_FORMAT
    bundle = LabelBundle(content=None, fmt=fmt)
    parts: list[bytes] = []
    client = None
    for shipment in shipments:
        doc = shipment.document
        if shipment.method not in ml_shipments.LABEL_METHODS:
            bundle.skipped.append((doc, "esta forma de envío no usa etiqueta de Mercado Libre"))
            continue
        if client is None:
            client = MLClient()
        try:
            content = ml_shipments.get_label(client, shipment, fmt)
        except ml_shipments.LabelNotReady as exc:
            bundle.skipped.append((doc, _not_ready_reason(shipment, str(exc))))
            continue
        except Exception as exc:  # noqa: BLE001 — token vencido, red, etc.: mensaje claro, sin 500
            logger.warning("Etiqueta ML %s: %s", shipment.external_id, exc)
            bundle.skipped.append((doc, friendly(exc)))
            continue
        parts.append(content)
        bundle.printed.append(shipment)
    if parts:
        bundle.content = _merge(parts, fmt)
    return bundle


def _merge(parts: list[bytes], fmt: str) -> bytes:
    if fmt == "zpl2":
        return b"\n".join(p.strip() for p in parts) + b"\n"
    if len(parts) == 1:
        return parts[0]
    from pypdf import PdfWriter

    writer = PdfWriter()
    for part in parts:
        writer.append(io.BytesIO(part))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def mark_printed(shipments, *, user, request=None, kind: str, **metadata) -> None:
    """Anota que se imprimió (para mostrar "ya impresa") y lo audita en el pedido."""
    now = timezone.now()
    with transaction.atomic():
        for shipment in shipments:
            Shipment.objects.filter(pk=shipment.pk).update(
                label_printed_at=now, label_print_count=F("label_print_count") + 1, updated_at=now
            )
            shipment.refresh_from_db(fields=["label_printed_at", "label_print_count"])
            audit.record(
                user,
                "shipment.label_printed",
                shipment.document,
                request=request,
                tipo="Mercado Libre" if kind == KIND_ML else "Rótulo de transporte",
                veces=shipment.label_print_count,
                **metadata,
            )


def parse_packages(value) -> int:
    try:
        packages = int(str(value).strip())
    except (TypeError, ValueError):
        raise LabelError("Indicá la cantidad de bultos con un número (por ejemplo, 1).") from None
    if packages < 1 or packages > MAX_PACKAGES:
        raise LabelError(f"La cantidad de bultos tiene que estar entre 1 y {MAX_PACKAGES}.")
    return packages


def carrier_label(shipment: Shipment, *, carrier: str, packages, user, request=None) -> bytes:
    """Guarda expreso y bultos en el envío y devuelve el rótulo (una página por bulto)."""
    carrier = (carrier or "").strip()[:100]
    if not carrier:
        raise LabelError("Elegí el expreso o escribí cuál es.")
    packages = parse_packages(packages)
    with transaction.atomic():
        shipment.carrier_name = carrier
        shipment.packages = packages
        shipment.save(update_fields=["carrier_name", "packages", "updated_at"])
        content = pdf.carrier_label_pdf(shipment.document, shipment, carrier=carrier, packages=packages)
        mark_printed(
            [shipment], user=user, request=request, kind=KIND_CARRIER, expreso=carrier, bultos=packages
        )
    return content
