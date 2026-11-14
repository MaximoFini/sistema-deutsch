"""Importación del archivo de productos que exporta Contabilium (Excel o CSV; no hay API).

Flujo: parse_file → build_preview (no escribe datos) → apply_import (una sola vez).
Los códigos se guardan como Listing/ListingVariation del canal "contabilium".
"""

import csv
import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.integrations.models import Channel
from apps.pricing import services as pricing
from apps.pricing.models import PriceList

from .linking import auto_link
from .models import ContabiliumImport, Listing, ListingVariation, Variant

CHANNEL = "contabilium"
HEADER_SEARCH_ROWS = 10
SYNONYMS = {
    "code": ["codigo", "sku", "cod", "codigo interno", "codigo producto", "cod producto", "codigo articulo"],
    "name": ["nombre", "descripcion", "producto", "concepto", "articulo"],
    "barcode": ["codigo de barras", "cod barras", "codigo barras", "ean", "barcode", "cod de barras"],
    "stock": ["stock", "stock actual", "cantidad", "existencia", "stock disponible"],
    "retail_price": [
        "precio",
        "precio venta",
        "precio final",
        "precio minorista",
        "lista minorista",
        "pvp",
        "precio unitario",
    ],
    "wholesale_price": ["precio mayorista", "mayorista", "lista mayorista", "precio lista mayorista"],
}


class ImportFileError(Exception):
    pass


def normalize_header(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_number(value) -> Decimal | None:
    """Acepta "$ 1.234,56", "1234,56", "1234.56", 1234.56. Vacío → None. Inválido → ValueError."""
    if value is None:
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))
    text = str(value).strip().replace("$", "").replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = (
            text.replace(".", "").replace(",", ".")
            if text.rfind(",") > text.rfind(".")
            else text.replace(",", "")
        )
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"«{value}» no es un número") from exc


def _read_table(filename: str, content: bytes) -> list[list]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise ImportFileError("No se pudo leer el Excel. ¿Es un archivo .xlsx válido?") from exc
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if filename.lower().endswith((".csv", ".txt")):
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        sample = text[:4096]
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    raise ImportFileError("Formato no soportado: subí un Excel (.xlsx) o un CSV.")


def detect_columns(rows: list[list]) -> tuple[int, dict[str, int]]:
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        headers = [normalize_header(c) for c in row]
        mapping = {}
        for field, names in SYNONYMS.items():
            for col, header in enumerate(headers):
                if header in names and col not in mapping.values():
                    mapping[field] = col
                    break
        # "precio mayorista" no debe tomarse como precio minorista
        if "retail_price" in mapping and headers[mapping["retail_price"]] in SYNONYMS["wholesale_price"]:
            mapping.pop("retail_price")
        if "code" in mapping:
            return index, mapping
    found = ", ".join(str(c) for c in (rows[0] if rows else []) if c not in (None, "")) or "ninguna"
    raise ImportFileError(f"No encontré una columna de código (código / SKU). Columnas encontradas: {found}.")


def parse_file(filename: str, content: bytes) -> dict:
    if len(content) > settings.CONTABILIUM_MAX_FILE_MB * 1024 * 1024:
        raise ImportFileError(f"El archivo supera {settings.CONTABILIUM_MAX_FILE_MB} MB.")
    rows = _read_table(filename, content)
    header_index, mapping = detect_columns(rows)
    parsed, errors, duplicates, seen = [], [], [], set()
    for line_no, raw in enumerate(rows[header_index + 1 :], start=header_index + 2):

        def cell(field, raw=raw):
            col = mapping.get(field)
            return raw[col] if col is not None and col < len(raw) else None

        code = str(cell("code") or "").strip()
        if code.endswith(".0") and code[:-2].isdigit():
            code = code[:-2]  # Excel guarda códigos numéricos como 123.0
        if not code:
            continue
        if code in seen:
            duplicates.append({"line": line_no, "code": code})
            continue
        try:
            stock = parse_number(cell("stock"))
            retail = parse_number(cell("retail_price"))
            wholesale = parse_number(cell("wholesale_price"))
        except ValueError as exc:
            errors.append({"line": line_no, "code": code, "error": str(exc)})
            continue
        seen.add(code)
        barcode = str(cell("barcode") or "").strip()
        if barcode.endswith(".0") and barcode[:-2].isdigit():
            barcode = barcode[:-2]
        parsed.append(
            {
                "line": line_no,
                "code": code,
                "name": str(cell("name") or "").strip()[:255],
                "barcode": barcode,
                "stock": str(stock) if stock is not None else None,
                "retail_price": str(retail) if retail is not None else None,
                "wholesale_price": str(wholesale) if wholesale is not None else None,
            }
        )
    columns = {field: str(rows[header_index][col]) for field, col in mapping.items()}
    return {"columns": columns, "rows": parsed, "errors": errors, "duplicates": duplicates}


def _wholesale_net(value: str | None) -> Decimal | None:
    if value is None:
        return None
    price = Decimal(value)
    if settings.CONTABILIUM_WHOLESALE_INCLUDES_VAT:
        price = price / Decimal("1.21")
    return price.quantize(Decimal("0.01"))


def _match(row: dict) -> Variant | None:
    variant = Variant.objects.filter(sku=row["code"]).first()
    if variant is None and row.get("barcode"):
        variant = Variant.objects.filter(barcode=row["barcode"]).first()
    return variant


def build_preview(parsed: dict) -> dict:
    """Resumen sin escribir datos."""
    mayorista = PriceList.objects.get(code="MAYORISTA")
    matched, unmatched, price_changes = [], [], []
    for row in parsed["rows"]:
        variant = _match(row)
        if variant is None:
            unmatched.append(row)
            continue
        matched.append({**row, "sku": variant.sku})
        new_price = _wholesale_net(row["wholesale_price"])
        if new_price is not None:
            current = pricing.current_price(mayorista, variant)
            if current is None or current.price != new_price:
                price_changes.append(
                    {
                        "sku": variant.sku,
                        "before": str(current.price) if current else None,
                        "after": str(new_price),
                    }
                )
    return {
        "total": len(parsed["rows"]),
        "matched": len(matched),
        "unmatched": len(unmatched),
        "duplicates": len(parsed["duplicates"]),
        "errors": len(parsed["errors"]),
        "wholesale_changes": len(price_changes),
        "has_wholesale": "wholesale_price" in parsed["columns"],
        "examples": {
            "matched": matched[:50],
            "unmatched": unmatched[:50],
            "duplicates": parsed["duplicates"][:50],
            "errors": parsed["errors"][:50],
            "wholesale_changes": price_changes[:50],
        },
        "duplicate_codes": [d["code"] for d in parsed["duplicates"]],
    }


def create_preview(*, filename: str, content: bytes, user) -> ContabiliumImport:
    parsed = parse_file(filename, content)
    return ContabiliumImport.objects.create(
        uploaded_by=user,
        filename=filename[:255],
        columns=parsed["columns"],
        rows=parsed["rows"],
        summary=build_preview(parsed)
        | {"error_rows": parsed["errors"][:200], "duplicate_rows": parsed["duplicates"][:200]},
    )


class ImportNotApplicable(Exception):
    pass


@transaction.atomic
def apply_import(imp: ContabiliumImport, *, user, request=None) -> dict:
    imp = ContabiliumImport.objects.select_for_update().get(pk=imp.pk)
    if imp.status != ContabiliumImport.Status.PREVIEW:
        raise ImportNotApplicable("Esta importación ya fue aplicada o descartada.")
    channel = Channel.objects.get(code=CHANNEL)
    mayorista = PriceList.objects.get(code="MAYORISTA")
    stats = {"linked": 0, "unlinked": 0, "wholesale_updated": 0, "missing": 0}
    seen = []
    now = timezone.now()
    for row in imp.rows:
        retail = Decimal(row["retail_price"]) if row["retail_price"] is not None else None
        stock = int(Decimal(row["stock"])) if row["stock"] is not None else None
        listing, _ = Listing.objects.update_or_create(
            channel=channel,
            external_id=row["code"],
            defaults={
                "title": row["name"] or row["code"],
                "status": "active",
                "price": retail,
                "available_quantity": stock,
                "last_synced_at": now,
                "data": {
                    "barcode": row["barcode"],
                    "wholesale_price": row["wholesale_price"],
                    "import_id": imp.pk,
                },
            },
        )
        variation, _ = ListingVariation.objects.update_or_create(
            listing=listing,
            external_id="",
            defaults={"sku": row["code"][:64], "price": retail, "available_quantity": stock},
        )
        seen.append(row["code"])
        if auto_link(variation, barcode=row["barcode"]):
            stats["linked"] += 1
        else:
            stats["unlinked"] += 1
        variant = variation.variant
        wholesale = _wholesale_net(row["wholesale_price"])
        if variant is not None and wholesale is not None:
            if pricing.set_price(mayorista, variant, wholesale, valid_from=now) is not None:
                stats["wholesale_updated"] += 1
    stats["missing"] = (
        Listing.objects.filter(channel=channel)
        .exclude(external_id__in=seen)
        .exclude(status="missing")
        .update(status="missing")
    )
    # El stock de Contabilium queda como dato del canal: no toca StockLevel mientras
    # STOCK_FEED_CHANNEL no sea "contabilium" (decisión de M1/M3).
    imp.status = ContabiliumImport.Status.APPLIED
    imp.applied_at = now
    imp.applied_by = user
    imp.summary = {**imp.summary, "applied": stats}
    imp.save(update_fields=["status", "applied_at", "applied_by", "summary"])
    audit.record(
        user, "catalog.contabilium_imported", imp, after={"archivo": imp.filename, **stats}, request=request
    )
    return stats


def discard(imp: ContabiliumImport) -> None:
    if imp.status == ContabiliumImport.Status.PREVIEW:
        imp.status = ContabiliumImport.Status.DISCARDED
        imp.save(update_fields=["status"])


def last_duplicate_codes() -> list[str]:
    last = ContabiliumImport.objects.filter(status=ContabiliumImport.Status.APPLIED).first()
    return (last.summary or {}).get("duplicate_codes", []) if last else []
