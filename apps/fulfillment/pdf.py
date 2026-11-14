"""Documentos imprimibles de preparación (US-2, US-3), generados en el servidor con reportlab.

- `checklist_pdf`: hoja A4 de doble control de una tanda (picking por producto y armado por pedido).
- `carrier_label_pdf`: rótulo propio 10×15 para envíos por transporte, una página por bulto.
"""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone
from reportlab.graphics.barcode import code128
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.sales.templatetags.orders import address_text, ship_label

from .batches import PickingList, PickRow, order_ref, qty_text, variant_description

FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"  # cubren acentos y ñ (Latin-1)
LABEL_SIZE = (100 * mm, 150 * mm)
MISSING_ADDRESS = "Domicilio: completar a mano"

_base = ParagraphStyle("base", fontName=FONT, fontSize=8.5, leading=10.5)
_small = ParagraphStyle("small", parent=_base, fontSize=7.5, leading=9)
_h1 = ParagraphStyle("h1", parent=_base, fontName=FONT_BOLD, fontSize=13, leading=16, spaceAfter=4)
_h2 = ParagraphStyle("h2", parent=_base, fontName=FONT_BOLD, fontSize=10, leading=13, spaceAfter=3)
_th = ParagraphStyle("th", parent=_base, fontName=FONT_BOLD, fontSize=7.5, leading=9)


def _p(text, style=_base) -> Paragraph:
    return Paragraph(escape(str(text or "")), style)


class Box(Flowable):
    """Casilla vacía para tildar a mano (no depende de que la fuente tenga ☐)."""

    def __init__(self, size=6 * mm):
        super().__init__()
        self.size = size
        self.width = self.height = size

    def draw(self):
        self.canv.setLineWidth(0.8)
        self.canv.rect(0, 0, self.size, self.size)


class _NumberedCanvas(rl_canvas.Canvas):
    """Canvas que conoce el total de páginas para escribir "Página 1 de 3"."""

    header = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):  # noqa: N802 (API de reportlab)
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._draw_header(total)
            super().showPage()
        super().save()

    def _draw_header(self, total):
        width, height = self._pagesize
        self.setFont(FONT_BOLD, 9)
        self.drawString(12 * mm, height - 9 * mm, self.header)
        self.setFont(FONT, 8)
        self.drawRightString(width - 12 * mm, height - 9 * mm, f"Página {self._pageNumber} de {total}")
        self.setLineWidth(0.4)
        self.line(12 * mm, height - 10.5 * mm, width - 12 * mm, height - 10.5 * mm)


def _deadline_text(doc) -> str:
    deadline = getattr(doc, "deadline", None)
    if not deadline:
        return ""
    return f"despachar antes de {timezone.localtime(deadline):%d/%m %H:%M}"


def _boxes_table(header: list[str], rows: list[list], widths: list[float]) -> Table:
    data = [[_p(h, _th) for h in header], *rows]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (1, -1), "CENTER"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7e5e4")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#a8a29e")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _pick_rows(rows: list[PickRow]) -> list[list]:
    return [
        [Box(), Box(), _p(r.sku), _p(r.description), _p(qty_text(r.total)), _p(r.destinations_text, _small)]
        for r in rows
    ]


def checklist_pdf(batch, picking: PickingList, *, user=None) -> bytes:
    """Hoja A4 de doble control: parte 1 picking por producto, parte 2 armado por pedido."""
    buffer = io.BytesIO()
    margin = 12 * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin + 4 * mm,
        bottomMargin=margin,
        title=f"Tanda {batch.number}",
        author="Sistema Deutsch",
    )
    who = user or batch.created_by
    who_name = (who.get_short_name() if hasattr(who, "get_short_name") else str(who)) or str(who)
    header = (
        f"Tanda {batch.number} · {timezone.localtime():%d/%m/%Y %H:%M} · {who_name} · "
        f"{len(picking.orders)} pedidos · {qty_text(picking.units)} unidades"
    )
    usable = A4[0] - 2 * margin
    box_w = 15 * mm

    story = [_p("Parte 1 · Picking por producto", _h1)]
    widths = [box_w, box_w + 3 * mm, 32 * mm, 60 * mm, 11 * mm]
    widths.append(usable - sum(widths))
    header_row = ["Juntado", "Verificado", "SKU", "Descripción", "Cant.", "Pedidos"]
    if picking.rows:
        story.append(_boxes_table(header_row, _pick_rows(picking.rows), widths))
    else:
        story.append(_p("No hay productos del catálogo en esta tanda."))
    if picking.unknown:
        story += [
            Spacer(1, 4 * mm),
            _p("No está en el catálogo (SKU y descripción tal como vinieron del canal)", _h2),
            _boxes_table(header_row, _pick_rows(picking.unknown), widths),
        ]

    story += [Spacer(1, 6 * mm), _p("Parte 2 · Armado por pedido", _h1)]
    line_widths = [box_w, box_w + 3 * mm, 32 * mm, 0, 11 * mm]
    line_widths[3] = usable - sum(line_widths)
    for order in picking.orders:
        shipment_method = getattr(order, "ship_method", "") or ""
        title = " · ".join(
            part
            for part in (
                order_ref(order),
                str(order.customer) if order.customer_id else "",
                ship_label(shipment_method) if shipment_method else "",
                _deadline_text(order),
            )
            if part
        )
        rows = [
            [
                Box(),
                Box(),
                _p(line.variant.sku if line.variant_id else (line.sku_snapshot or "—")),
                _p(
                    # Misma descripción que la parte 1 (catálogo); la del canal puede traer otro talle.
                    variant_description(line.variant)
                    if line.variant_id
                    else line.description_snapshot + "  (no está en el catálogo)"
                ),
                _p(qty_text(line.quantity)),
            ]
            for line in order.lines.all()
        ]
        block = [
            _p(title, _h2),
            _boxes_table(["Armado", "Controlado", "SKU", "Descripción", "Cant."], rows, line_widths),
            Spacer(1, 2 * mm),
            _p("Armó: ____________________        Controló: ____________________"),
            Spacer(1, 5 * mm),
        ]
        story.append(KeepTogether(block))

    canvas_cls = type("_Canvas", (_NumberedCanvas,), {"header": header})
    doc.build(story, canvasmaker=canvas_cls)
    return buffer.getvalue()


# ── Rótulo 10×15 ─────────────────────────────────────────────────────────


def recipient_data(document, shipment) -> dict:
    customer = document.customer
    address = shipment.address if isinstance(shipment.address, dict) else {}
    name = (
        (customer.legal_name if customer else "") or address.get("receiver_name") or address.get("name") or ""
    )
    tax = ""
    if customer and customer.tax_id:
        tax = f"{customer.tax_id_type} {customer.tax_id}"
    phone = (
        (customer.phone if customer else "") or address.get("receiver_phone") or address.get("phone") or ""
    )
    return {
        "name": name or "(sin nombre)",
        "tax_id": tax,
        "phone": str(phone or ""),
        "address": address_text(address),
    }


def _ascii(text: str) -> str:
    return "".join(ch for ch in text if 32 <= ord(ch) < 127) or "PEDIDO"


def carrier_label_pdf(document, shipment, *, carrier: str, packages: int) -> bytes:
    """Rótulo propio 100 × 150 mm, una página por bulto ("Bulto 2 de 3")."""
    buffer = io.BytesIO()
    width, height = LABEL_SIZE
    c = rl_canvas.Canvas(buffer, pagesize=LABEL_SIZE)
    c.setTitle(f"Rótulo {order_ref(document)}")
    pad = 5 * mm
    inner = width - 2 * pad
    sender_lines = [
        settings.SENDER_NAME or "Deutsch",
        " · ".join(x for x in (settings.SENDER_TAX_ID, settings.SENDER_PHONE) if x),
        settings.SENDER_ADDRESS,
    ]
    rcpt = recipient_data(document, shipment)
    ref = order_ref(document)

    def section(y, title, lines, size=9, bold_first=False):
        c.setFont(FONT_BOLD, 7)
        c.drawString(pad, y, title)
        y -= 4 * mm
        for i, text in enumerate(line for line in lines if line):
            font = FONT_BOLD if (bold_first and i == 0) else FONT
            for chunk in simpleSplit(str(text), font, size, inner):
                c.setFont(font, size)
                c.drawString(pad, y, chunk)
                y -= size * 0.42 * mm + 1.6 * mm
        return y - 1.5 * mm

    for n in range(1, packages + 1):
        c.setLineWidth(1)
        c.rect(2 * mm, 2 * mm, width - 4 * mm, height - 4 * mm)
        y = height - pad - 2 * mm
        y = section(y, "REMITENTE", sender_lines, size=8)
        c.line(pad, y + 1 * mm, width - pad, y + 1 * mm)
        y -= 2 * mm
        address = rcpt["address"] or MISSING_ADDRESS
        y = section(
            y,
            "DESTINATARIO",
            [rcpt["name"], rcpt["tax_id"], address, f"Tel. {rcpt['phone']}" if rcpt["phone"] else ""],
            size=11,
            bold_first=True,
        )
        c.line(pad, y + 1 * mm, width - pad, y + 1 * mm)
        y -= 2 * mm
        y = section(y, "EXPRESO", [carrier or "—"], size=12, bold_first=True)
        y = section(y, "PEDIDO", [ref], size=12, bold_first=True)
        barcode = code128.Code128(_ascii(ref), barHeight=14 * mm, barWidth=0.38 * mm)
        if barcode.width > inner:  # referencias largas (packs de ML): se angosta para que entre
            barcode = code128.Code128(
                _ascii(ref), barHeight=14 * mm, barWidth=0.38 * mm * inner / barcode.width
            )
        bx = max(pad, (width - barcode.width) / 2)
        barcode.drawOn(c, bx, 22 * mm)
        c.setFont(FONT_BOLD, 18)
        c.drawCentredString(width / 2, 9 * mm, f"BULTO {n} DE {packages}")
        c.showPage()
    c.save()
    return buffer.getvalue()
