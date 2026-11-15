"""Excel de los reportes (M7).

Cada reporte arma una lista de hojas `Sheet(título, encabezados, filas, totales)` y `build` genera el .xlsx.

Por qué no openpyxl: aun en modo `write_only`, openpyxl serializa celda por celda y tardó 12–14 s
para 50.000 filas en la máquina de desarrollo (el requisito es < 10 s). Un .xlsx es un zip con unos
pocos XML: acá se escribe la hoja directamente como texto (≈ 1 s para 50.000 filas), con estilos
mínimos (encabezado en negrita, pesos, fechas) y paneles congelados. Ver "Notas de implementación"
en specs/reportes/design.md. Los tests lo leen de vuelta con openpyxl.
"""

import io
import math
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.utils import timezone

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_EPOCH = datetime(1899, 12, 30)
# Índices de `cellXfs` en styles.xml
NORMAL, BOLD, MONEY, BOLD_MONEY, DATE, DATETIME = range(6)


@dataclass
class Sheet:
    title: str
    headers: list[str]
    rows: list[list] = field(default_factory=list)
    totals: list | None = None
    money_columns: set[int] = field(default_factory=set)  # índices (desde 0) con formato de pesos
    note: str = ""


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _text(value: str) -> str:
    return escape(_ILLEGAL_XML.sub("", value))


def _cell(ref: str, value, style: int) -> str:
    s = f' s="{style}"' if style else ""
    if value is None or value == "":
        return f'<c r="{ref}"{s}/>' if style else ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"{s}><v>{int(value)}</v></c>'
    if isinstance(value, int):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    if isinstance(value, float | Decimal):
        number = float(value)
        if math.isfinite(number):
            return f'<c r="{ref}"{s}><v>{number!r}</v></c>'
        value = str(value)
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value).replace(tzinfo=None)
        serial = (value - _EPOCH).total_seconds() / 86400
        return f'<c r="{ref}" s="{DATETIME}"><v>{serial!r}</v></c>'
    if isinstance(value, date):
        return f'<c r="{ref}" s="{DATE}"><v>{(value - _EPOCH.date()).days}</v></c>'
    text = _text(str(value))
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f'<c r="{ref}" t="inlineStr"{s}><is><t{space}>{text}</t></is></c>'


def _sheet_xml(sheet: Sheet) -> str:
    cols = [_col(i) for i in range(max(len(sheet.headers), 1))]
    out = []
    n = 0
    widest = [1]

    def row(values, bold=False):
        nonlocal n, cols
        n += 1
        if len(values) > len(cols):
            cols = [_col(i) for i in range(len(values))]
        cells = []
        for i, v in enumerate(values):
            money = i in sheet.money_columns and isinstance(v, int | float | Decimal)
            style = (BOLD_MONEY if money else BOLD) if bold else (MONEY if money else NORMAL)
            cells.append(_cell(f"{cols[i]}{n}", v, style))
        out.append(f'<row r="{n}">{"".join(cells)}</row>')
        widest[0] = max(widest[0], len(values))

    if sheet.note:
        row([sheet.note])
    row(sheet.headers, bold=True)
    frozen = n
    for values in sheet.rows:
        row(values)
    if sheet.totals is not None:
        row(sheet.totals, bold=True)
    pane = (
        f'<pane ySplit="{frozen}" topLeftCell="A{frozen + 1}" activePane="bottomLeft" state="frozen"/>'
        f'<selection pane="bottomLeft" activeCell="A{frozen + 1}" sqref="A{frozen + 1}"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{_col(widest[0] - 1)}{max(n, 1)}"/>'
        f'<sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<sheetData>{''.join(out)}</sheetData>"
        "</worksheet>"
    )


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="3"><numFmt numFmtId="164" formatCode="#,##0.00"/>'
    '<numFmt numFmtId="165" formatCode="dd/mm/yyyy"/><numFmt numFmtId="166" formatCode="dd/mm/yyyy hh:mm"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="6">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>'
    '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def _sheet_name(title: str, used: set[str]) -> str:
    name = re.sub(r"[\[\]:*?/\\]", "-", title).strip("'")[:31] or "Hoja"
    base, i = name, 2
    while name.lower() in used:
        suffix = f" ({i})"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name.lower())
    return name


def build(sheets: list[Sheet]) -> bytes:
    used: set[str] = set()
    names = [_sheet_name(s.title, used) for s in sheets]
    n = len(sheets)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, n + 1)
        )
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<bookViews><workbookView/></bookViews><sheets>"
        + "".join(
            f'<sheet name="{escape(name, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(names, start=1)
        )
        + "</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, n + 1)
        )
        + f'<Relationship Id="rId{n + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/styles.xml", STYLES)
        for i, sheet in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheet))
    return buf.getvalue()


def response(sheets: list[Sheet], name: str) -> HttpResponse:
    resp = HttpResponse(build(sheets), content_type=XLSX)
    resp["Content-Disposition"] = f'attachment; filename="{name}-{timezone.localdate():%Y%m%d}.xlsx"'
    return resp
