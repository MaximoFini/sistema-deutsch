"""Panel de calidad de datos del catálogo. Se calcula al momento (con ~720 variantes es rápido)."""

import io
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.urls import reverse

from . import channel_view
from .contabilium_import import last_duplicate_codes
from .models import ListingVariation, Variant

CRITICAL, WARNING = "critical", "warning"

LABELS = {
    "no_sku": "Sin SKU",
    "dup_sku": "SKU o código repetido",
    "no_barcode": "Sin código de barras",
    "no_photo": "Sin foto",
    "price_zero": "Precio $0",
    "price_suspicious": "Precio sospechoso",
    "no_weight": "Sin peso",
    "no_dimensions": "Sin medidas",
    "missing_in_ml": "En Tiendanube y no en Mercado Libre",
    "unlinked": "Publicación o código sin vincular",
    "stock_diff": "Stock distinto entre canales",
}
SEVERITY = {
    "no_sku": CRITICAL,
    "dup_sku": CRITICAL,
    "price_zero": CRITICAL,
    "stock_diff": CRITICAL,
}


@dataclass
class Issue:
    code: str
    sku: str
    product: str
    detail: str
    url: str

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.code, WARNING)

    @property
    def title(self) -> str:
        return LABELS[self.code]


def find_issues() -> list[Issue]:
    issues: list[Issue] = []
    variants = Variant.objects.filter(is_active=True).select_related("product")
    rows = channel_view.build_rows(variants)
    min_price = Decimal(settings.CATALOG_SUSPICIOUS_PRICE_MIN)
    pct = Decimal(settings.CATALOG_PRICE_DIFF_PCT) / 100
    dup_codes = set(last_duplicate_codes())
    unlinked_url = reverse("catalog:unlinked")

    for row in rows:
        v = row.variant
        url = reverse("catalog:detail", args=[v.pk])

        def add(code, detail="", v=v, url=url):
            issues.append(Issue(code, v.sku, v.product.name, detail, url))

        notes = v.review_notes or ""
        if "Sin SKU" in notes:
            add("no_sku", notes)
        if "repetido" in notes or v.sku in dup_codes:
            add("dup_sku", notes or "Código repetido en el último archivo de Contabilium")
        if not v.barcode:
            add("no_barcode")
        if not v.product.images:
            add("no_photo")
        if v.weight_g is None:
            add("no_weight")
        if None in (v.width_mm, v.height_mm, v.length_mm):
            add("no_dimensions")
        retail = row.price["minorista"]
        if retail is not None:
            if retail <= 0:
                add("price_zero")
            elif retail < min_price:
                add("price_suspicious", f"Precio minorista ${retail} menor a ${min_price}")
            else:
                for channel_name, price in (
                    ("Tiendanube", row.price["tiendanube"]),
                    *[("ML " + i, p) for i, p in row.ml_prices],
                ):
                    if price is not None and abs(price - retail) / retail > pct:
                        add("price_suspicious", f"{channel_name}: ${price} vs minorista ${retail}")
        if (
            row.stock["tiendanube"] is not None
            and row.stock["ml_own"] is None
            and row.stock["ml_full"] is None
        ):
            add("missing_in_ml")
        if row.stock_diff:
            detail = ", ".join(
                f"{k}: {row.stock[k]}"
                for k in ("contabilium", "tiendanube", "ml_own")
                if row.stock[k] is not None
            )
            add("stock_diff", detail)

    for lv in (
        ListingVariation.objects.filter(variant__isnull=True)
        .exclude(link_source="manual")
        .exclude(listing__status__in=["closed", "missing"])
        .select_related("listing__channel")
    ):
        code = "no_sku" if (not lv.sku and lv.listing.channel.code == "mercadolibre") else "unlinked"
        issues.append(
            Issue(
                code,
                lv.sku or "—",
                lv.listing.title,
                f"{lv.listing.channel.name} {lv.listing.external_id}:{lv.external_id or '-'}",
                unlinked_url,
            )
        )

    order = {CRITICAL: 0, WARNING: 1}
    issues.sort(key=lambda i: (order[i.severity], i.code, i.sku))
    return issues


def export_xlsx(issues: list[Issue], base_url: str = "") -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Calidad de datos"
    ws.append(["Severidad", "Problema", "SKU", "Producto", "Detalle", "Link"])
    for i in issues:
        ws.append(
            [
                "Crítico" if i.severity == CRITICAL else "Aviso",
                i.title,
                i.sku,
                i.product,
                i.detail,
                base_url + i.url,
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
