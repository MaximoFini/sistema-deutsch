"""Stock y precio por canal para cada SKU (solo lectura). Pocas consultas, sin N+1."""

import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.integrations.models import ExternalRef
from apps.pricing.models import PriceListItem

from .models import ListingVariation, Variant

STOCK_COLUMNS = ["contabilium", "tiendanube", "ml_own", "ml_full", "mayorista"]
PRICE_COLUMNS = ["minorista", "mayorista", "tiendanube", "mercadolibre"]


@dataclass
class ChannelRow:
    variant: Variant
    stock: dict = field(default_factory=dict)
    price: dict = field(default_factory=dict)
    updated: dict = field(default_factory=dict)
    ml_prices: list = field(default_factory=list)
    stock_diff: bool = False
    price_diff: set = field(default_factory=set)

    @property
    def has_diff(self) -> bool:
        return self.stock_diff or bool(self.price_diff)


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return None


def _current_prices(variant_ids) -> dict[tuple[int, str], Decimal]:
    now = timezone.now()
    latest: dict[tuple[int, str], tuple[datetime, Decimal]] = {}
    items = PriceListItem.objects.filter(
        variant_id__in=variant_ids, valid_from__lte=now, price_list__code__in=["MINORISTA", "MAYORISTA"]
    ).values_list("variant_id", "price_list__code", "valid_from", "price")
    for variant_id, code, valid_from, price in items:
        key = (variant_id, code)
        if key not in latest or valid_from > latest[key][0]:
            latest[key] = (valid_from, price)
    return {k: v[1] for k, v in latest.items()}


def build_rows(variants) -> list[ChannelRow]:
    variants = list(variants.select_related("product"))
    ids = [v.pk for v in variants]
    ct = ContentType.objects.get_for_model(Variant)
    tn_refs = {
        r.object_id: r
        for r in ExternalRef.objects.filter(channel__code="tiendanube", content_type=ct, object_id__in=ids)
    }
    rows_by_variant = defaultdict(list)
    for lv in ListingVariation.objects.filter(variant_id__in=ids).select_related("listing__channel"):
        rows_by_variant[lv.variant_id].append(lv)
    prices = _current_prices(ids)

    result = []
    for v in variants:
        row = ChannelRow(variant=v)
        row.stock = dict.fromkeys(STOCK_COLUMNS)
        row.price = dict.fromkeys(PRICE_COLUMNS)
        row.updated = {}
        row.price["minorista"] = prices.get((v.pk, "MINORISTA"))
        row.price["mayorista"] = prices.get((v.pk, "MAYORISTA"))
        tn = tn_refs.get(v.pk)
        if tn is not None:
            row.stock["tiendanube"] = tn.extra.get("stock")
            promo = _dec(tn.extra.get("promotional_price"))
            row.price["tiendanube"] = promo or _dec(tn.extra.get("price"))
            row.updated["tiendanube"] = parse_datetime(tn.extra.get("updated_at") or "") or tn.updated_at
        ml_own = ml_full = None
        for lv in rows_by_variant.get(v.pk, []):
            listing = lv.listing
            code = listing.channel.code
            if code == "contabilium" and listing.status != "missing":
                row.stock["contabilium"] = lv.available_quantity
                row.updated["contabilium"] = listing.last_synced_at
            elif code == "mercadolibre" and listing.status == "active":
                qty = lv.available_quantity or 0
                if listing.logistic_type == "fulfillment":
                    ml_full = (ml_full or 0) + qty
                else:
                    ml_own = (ml_own or 0) + qty
                price = _dec(lv.price if lv.price is not None else listing.price)
                if price is not None:
                    row.ml_prices.append((listing.external_id, price))
                row.updated["mercadolibre"] = max(
                    filter(None, [row.updated.get("mercadolibre"), listing.last_synced_at]), default=None
                )
        row.stock["ml_own"], row.stock["ml_full"] = ml_own, ml_full
        if row.ml_prices:
            row.price["mercadolibre"] = row.ml_prices[0][1]
        values = {row.stock[k] for k in ("contabilium", "tiendanube", "ml_own") if row.stock[k] is not None}
        row.stock_diff = len(values) > 1
        retail = row.price["minorista"]
        if retail is not None:
            retail = Decimal(retail).quantize(Decimal("0.01"))
            # La lista minorista guarda el precio de lista de TN (la promo se muestra aparte).
            tn_list = _dec(tn.extra.get("price")) if tn is not None else None
            if tn_list is not None and tn_list != retail:
                row.price_diff.add("tiendanube")
            if any(p != retail for _, p in row.ml_prices):
                row.price_diff.add("mercadolibre")
        result.append(row)
    return result


def export_xlsx(rows: list[ChannelRow]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Stock y precios"
    ws.append(
        [
            "SKU",
            "Producto",
            "Stock Contabilium",
            "Stock Tiendanube",
            "Stock ML propio",
            "Stock ML Full",
            "Stock mayorista",
            "Precio minorista",
            "Precio mayorista",
            "Precio Tiendanube",
            "Precio ML",
            "Diferencias",
        ]
    )
    for r in rows:
        diffs = (["stock"] if r.stock_diff else []) + [f"precio {c}" for c in sorted(r.price_diff)]
        ws.append(
            [
                r.variant.sku,
                r.variant.product.name,
                *[r.stock[c] for c in STOCK_COLUMNS],
                *[float(r.price[c]) if r.price[c] is not None else None for c in PRICE_COLUMNS],
                ", ".join(diffs),
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
