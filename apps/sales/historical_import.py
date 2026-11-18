"""Historial de pedidos de TiendaQuick → `SalesDocument` histórico (M9-01).

Lee los Excel "Pedidos con detalle" que exporta el admin de TiendaQuick (uno por mes). Los pedidos se
crean por ORM, sin pasar por `change_status`: no hay señales, reservas de stock ni emails, y quedan con
`is_historical=True` (solo lectura, cuentan en los reportes). Es idempotente por la referencia
`TQ-<número>`. Nunca llama a ningún canal.
"""

import io
import re
import unicodedata
import zipfile
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from django.db import transaction
from openpyxl import load_workbook

from apps.catalog.models import Variant
from apps.customers.models import Customer
from apps.integrations.models import Channel

from . import states
from .models import Payment, SalesDocument, SalesLine

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
VAT = Decimal("1.21")
CENT = Decimal("0.01")


def _sheet(path: Path):
    """Algunos Excel de TiendaQuick traen márgenes de página vacíos que rompen a openpyxl: se quitan en memoria."""
    buf = io.BytesIO()
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/"):
                data = re.sub(rb"<pageMargins[^>]*/>", b"", data)
            zout.writestr(item, data)
    buf.seek(0)
    return load_workbook(buf, read_only=True, data_only=True).worksheets[0]


def read_orders(folder: Path) -> list[dict]:
    """Pedidos de todos los `pedidos_detalle_*.xlsx`, sin repetidos y del más viejo al más nuevo."""
    orders = {}
    for path in sorted(folder.glob("pedidos_detalle_*.xlsx")):
        current = None
        for i, row in enumerate(_sheet(path).iter_rows(values_only=True)):
            if i == 0:
                continue
            if row[0] == "-":  # línea del pedido anterior
                if current is not None and row[10]:
                    current["lines"].append(
                        {
                            "name": str(row[10]),
                            "code": str(row[11] or ""),
                            "price": Decimal(str(row[12] or 0)),
                            "qty": Decimal(str(row[14] or 1)),
                        }
                    )
                continue
            try:
                issued = datetime.strptime(str(row[2]), "%d/%m/%Y %H:%M").replace(tzinfo=TZ)
                number = int(row[0])
            except (ValueError, TypeError):
                current = None  # fila de totales u otra cosa: no es un pedido
                continue
            if number in orders:  # el mismo pedido en dos meses (borde del rango)
                current = None
                continue
            current = orders[number] = {
                "number": number,
                "customer": str(row[1] or "").strip(),
                "issued": issued,
                "status": str(row[3] or ""),
                "origin": str(row[5] or ""),
                "price_list": str(row[6] or ""),
                "total": Decimal(str(row[7] or 0)),
                "paid": Decimal(str(row[8] or 0)),
                "lines": [],
            }
    return sorted(orders.values(), key=lambda o: (o["issued"], o["number"]))


def _key(code: str) -> str:
    """Los SKU de Contabilium van en mayúsculas, sin acentos y con guiones ("45-VIOLETA-OSCURO");
    TiendaQuick los muestra como "45 - Violeta Oscuro"."""
    text = unicodedata.normalize("NFKD", code).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[\s/-]+", "-", text.strip())


def _find_variant(code: str, variants: dict[str, Variant]) -> Variant | None:
    return variants.get(_key(code))


def import_orders(folder: Path) -> dict:
    orders = read_orders(folder)
    channels = {c.code: c for c in Channel.objects.all()}
    variants = {_key(v.sku): v for v in Variant.objects.all()}
    customers = {}
    for customer in Customer.objects.filter(kind=Customer.Kind.WHOLESALE):
        for name in (customer.legal_name, customer.trade_name):
            if name:
                customers.setdefault(name.strip().lower(), customer)
    existing = set(
        SalesDocument.objects.filter(is_historical=True).values_list("channel_reference", flat=True)
    )
    stats = {
        "leidos": len(orders),
        "creados": 0,
        "ya_estaban": 0,
        "lineas": 0,
        "lineas_sin_variante": 0,
        "con_cliente": 0,
    }
    for order in orders:
        reference = f"TQ-{order['number']}"
        if reference in existing:
            stats["ya_estaban"] += 1
            continue
        with transaction.atomic():
            _create_order(order, reference, channels, variants, customers, stats)
    return stats


def _create_order(o, reference, channels, variants, customers, stats):
    is_ml = o["origin"] == "Mercado Libre"
    wholesale = "mayorista" in o["price_list"].lower()
    channel = (
        channels["mercadolibre"] if is_ml else channels["mayorista"] if wholesale else channels["tiendanube"]
    )
    paid = o["paid"] > 0 and o["paid"] >= o["total"] - Decimal("0.05")
    pending = not paid and "pendiente" in o["status"].lower()
    customer = None if is_ml else customers.get(o["customer"].lower())
    doc = SalesDocument(
        doc_type=SalesDocument.DocType.ORDER,
        channel=channel,
        customer=customer,
        status=states.AWAITING_PAYMENT if pending else states.DELIVERED,
        channel_reference=reference,
        channel_status=("paid" if is_ml and paid else o["status"])[:60],
        issued_at=o["issued"],
        status_changed_at=o["issued"],
        notes=f"Histórico importado de TiendaQuick (pedido {o['number']}). Cliente: {o['customer']}",
        is_historical=True,
        net_pending=is_ml,  # no tenemos la comisión ni el costo de envío de ML de ese período
    )
    doc.save()
    for line in o["lines"]:
        variant = _find_variant(line["code"], variants)
        stats["lineas_sin_variante"] += variant is None
        # TiendaQuick informa precios con IVA. En la mayorista el sistema guarda neto + IVA aparte.
        price = (line["price"] / VAT).quantize(CENT, ROUND_HALF_UP) if wholesale else line["price"]
        SalesLine(
            document=doc,
            variant=variant,
            sku_snapshot=(line["code"] or "-")[:64],
            description_snapshot=line["name"][:300],
            quantity=line["qty"],
            unit_price=price,
            vat_rate=21,
        ).save()
        stats["lineas"] += 1
    doc.recalculate_totals(save=False)
    # Lo que TiendaQuick cobró de más o de menos que las líneas es envío (o descuento).
    gap = o["total"] - (doc.subtotal + doc.tax_total)
    doc.shipping_total = max(gap, Decimal(0))
    doc.discount_total = max(-gap, Decimal(0))
    doc.total = o["total"]
    doc.save()
    if paid:
        mercadopago = is_ml or "mercadopago" in o["status"].lower()
        Payment.objects.create(
            document=doc,
            method=Payment.Method.MERCADOPAGO if mercadopago else Payment.Method.OTHER,
            amount=o["total"],
            status=Payment.Status.CONFIRMED,
            paid_at=o["issued"],
        )
    stats["creados"] += 1
    stats["con_cliente"] += customer is not None
