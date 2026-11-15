"""Excel de los reportes (M7).

Cada reporte arma una lista de hojas `Sheet(título, encabezados, filas, totales)` y `build` genera el .xlsx
con XlsxWriter en modo `constant_memory` (escribe fila por fila sin guardar todo en memoria: unos 5 s para
50.000 filas; openpyxl tardaba 12–14 s). Encabezado en negrita, pesos con dos decimales, fechas y paneles
congelados. Los tests lo leen de vuelta con openpyxl.
"""

import io
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import xlsxwriter
from django.http import HttpResponse
from django.utils import timezone

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class Sheet:
    title: str
    headers: list[str]
    rows: list[list] = field(default_factory=list)
    totals: list | None = None
    money_columns: set[int] = field(default_factory=set)  # índices (desde 0) con formato de pesos
    note: str = ""


def _sheet_name(title: str, used: set[str]) -> str:
    name = re.sub(r"[\[\]:*?/\\]", "-", title).strip("'")[:31] or "Hoja"
    base, i = name, 2
    while name.lower() in used:
        suffix = f" ({i})"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name.lower())
    return name


class _Writer:
    def __init__(self, workbook):
        self.fmt = {
            "bold": workbook.add_format({"bold": True}),
            "money": workbook.add_format({"num_format": "#,##0.00"}),
            "bold_money": workbook.add_format({"bold": True, "num_format": "#,##0.00"}),
            "date": workbook.add_format({"num_format": "dd/mm/yyyy"}),
            "datetime": workbook.add_format({"num_format": "dd/mm/yyyy hh:mm"}),
        }

    def cell(self, ws, r, c, value, *, money=False, bold=False):
        fmt = self.fmt
        if value is None or value == "":
            return
        if isinstance(value, bool):
            ws.write_boolean(r, c, value, fmt["bold"] if bold else None)
            return
        if isinstance(value, int | float | Decimal):
            number = float(value)
            if math.isfinite(number):
                style = (
                    (fmt["bold_money"] if money else fmt["bold"])
                    if bold
                    else (fmt["money"] if money else None)
                )
                ws.write_number(r, c, number, style)
                return
            value = str(value)
        if isinstance(value, datetime):
            if timezone.is_aware(value):
                value = timezone.localtime(value).replace(tzinfo=None)
            ws.write_datetime(r, c, value, fmt["datetime"])
            return
        if isinstance(value, date):
            ws.write_datetime(r, c, datetime(value.year, value.month, value.day), fmt["date"])
            return
        # Siempre como texto: un valor que empiece con "=" nunca se interpreta como fórmula.
        ws.write_string(r, c, _ILLEGAL_XML.sub("", str(value)), fmt["bold"] if bold else None)


def build(sheets: list[Sheet]) -> bytes:
    buf = io.BytesIO()
    workbook = xlsxwriter.Workbook(
        buf,
        {"in_memory": False, "constant_memory": True, "strings_to_formulas": False, "strings_to_urls": False},
    )
    writer = _Writer(workbook)
    used: set[str] = set()
    for sheet in sheets or [Sheet("Hoja", [])]:
        ws = workbook.add_worksheet(_sheet_name(sheet.title, used))
        r = 0
        if sheet.note:
            writer.cell(ws, r, 0, sheet.note)
            r += 1
        for c, header in enumerate(sheet.headers):
            writer.cell(ws, r, c, header, bold=True)
        ws.freeze_panes(r + 1, 0)
        r += 1
        for values in sheet.rows:
            for c, value in enumerate(values):
                writer.cell(ws, r, c, value, money=c in sheet.money_columns)
            r += 1
        if sheet.totals is not None:
            for c, value in enumerate(sheet.totals):
                writer.cell(ws, r, c, value, money=c in sheet.money_columns, bold=True)
    workbook.close()
    return buf.getvalue()


def response(sheets: list[Sheet], name: str) -> HttpResponse:
    resp = HttpResponse(build(sheets), content_type=XLSX)
    resp["Content-Disposition"] = f'attachment; filename="{name}-{timezone.localdate():%Y%m%d}.xlsx"'
    return resp
