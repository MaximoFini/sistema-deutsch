"""Publicaciones de Mercado Libre → Listing / ListingVariation, vinculadas a Variant por SKU.

Stock y precio quedan como dato del canal: no alimentan el stock del sistema ni se escriben.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.catalog.linking import _sync_mirror, auto_link
from apps.catalog.models import Listing, ListingVariation, Variant
from apps.integrations.models import Channel

from .common import attr_value, dec, dt

logger = logging.getLogger(__name__)
CHANNEL = "mercadolibre"
CLOSED_MAX_AGE = timedelta(days=60)


def _variation_sku(item: dict, variation: dict | None) -> str:
    if variation is not None:
        sku = attr_value(variation.get("attributes"), "SELLER_SKU") or (
            variation.get("seller_custom_field") or ""
        )
        if sku.strip():
            return sku.strip()
    return attr_value(item.get("attributes"), "SELLER_SKU") or (item.get("seller_custom_field") or "").strip()


def _pictures(item: dict) -> dict[str, str]:
    return {p.get("id"): p.get("secure_url") or p.get("url") for p in item.get("pictures") or []}


@transaction.atomic
def upsert_item(item: dict) -> Listing:
    channel = Channel.objects.get(code=CHANNEL)
    shipping = item.get("shipping") or {}
    size_grid_id = attr_value(item.get("attributes"), "SIZE_GRID_ID")
    data = {
        "attributes": item.get("attributes") or [],
        "pictures": [p.get("secure_url") for p in item.get("pictures") or []],
        "family_name": item.get("family_name"),
        "shipping": shipping,
        "last_updated": item.get("last_updated"),
        # Salud de la publicación (M6): motivos de pausa, etiquetas de calidad/moderación y guía de talles.
        "sub_status": item.get("sub_status") or [],
        "tags": item.get("tags") or [],
        "warnings": item.get("warnings") or [],
        "size_grid_id": size_grid_id,
    }
    previous = (
        Listing.objects.filter(channel=channel, external_id=str(item["id"]))
        .values_list("data", flat=True)
        .first()
    )
    chart = (previous or {}).get("size_chart")
    if chart and size_grid_id and chart.get("grid_id") == size_grid_id:
        data["size_chart"] = chart  # la guía de talles cacheada sobrevive a la sincronización
    listing, _ = Listing.objects.update_or_create(
        channel=channel,
        external_id=str(item["id"]),
        defaults={
            "title": (item.get("title") or "")[:255],
            "status": item.get("status") or "",
            "listing_type": item.get("listing_type_id") or "",
            "category_id": item.get("category_id") or "",
            "permalink": item.get("permalink") or "",
            "logistic_type": shipping.get("logistic_type") or "",
            "price": dec(item.get("price")),
            "currency": item.get("currency_id") or "ARS",
            "available_quantity": item.get("available_quantity"),
            "sold_quantity": item.get("sold_quantity"),
            "health": dec(item.get("health")),
            "user_product_id": item.get("user_product_id") or "",
            "data": data,
            "last_synced_at": timezone.now(),
        },
    )
    pictures = _pictures(item)
    variations = item.get("variations") or []
    rows = variations or [None]
    notes, seen = [], []
    for variation in rows:
        ext_id = str(variation["id"]) if variation else ""
        sku = _variation_sku(item, variation)
        attributes = {
            c.get("name"): c.get("value_name")
            for c in (variation or {}).get("attribute_combinations") or []
            if c.get("name")
        }
        picture_ids = (variation or {}).get("picture_ids") or list(pictures)
        row, _ = ListingVariation.objects.update_or_create(
            listing=listing,
            external_id=ext_id,
            defaults={
                "sku": sku[:64],
                "attributes": attributes,
                "price": dec((variation or {}).get("price", item.get("price"))),
                "available_quantity": (variation or {}).get(
                    "available_quantity", item.get("available_quantity")
                ),
                "user_product_id": (variation or {}).get("user_product_id") or "",
                "picture_urls": [pictures[p] for p in picture_ids if p in pictures],
            },
        )
        seen.append(ext_id)
        linked = auto_link(row)  # respeta vínculos manuales (M3)
        if row.link_source == "manual" and not linked:
            pass  # desvinculado a propósito: no se marca para revisión
        elif not sku:
            notes.append(f"{ext_id or 'publicación'}: sin SKU")
        elif not linked:
            notes.append(f"{ext_id or 'publicación'}: SKU {sku} no está en el catálogo")
    gone = listing.variations.exclude(external_id__in=seen)
    for row in gone:  # datos del canal: se pueden borrar (con su vínculo espejo)
        row.variant = None
        _sync_mirror(row)
    gone.delete()
    listing.needs_review = bool(notes)
    listing.review_notes = "; ".join(notes)[:255]
    listing.save(update_fields=["needs_review", "review_notes", "updated_at"])
    return listing


def _too_old_closed(item: dict) -> bool:
    if item.get("status") != "closed":
        return False
    updated = dt(item.get("last_updated"))
    return bool(updated and timezone.now() - updated > CLOSED_MAX_AGE)


def import_all(client) -> dict:
    stats = {"listings": 0, "skipped_closed": 0, "errors": []}
    ids = list(client.scan_item_ids(client.user_id))
    seen = []
    for start in range(0, len(ids), 20):
        chunk = ids[start : start + 20]
        for entry in client.get("/items", params={"ids": ",".join(chunk)}):
            item = entry.get("body") or {}
            if entry.get("code") != 200 or not item.get("id"):
                stats["errors"].append({"id": item.get("id"), "error": f"multiget {entry.get('code')}"})
                continue
            if _too_old_closed(item):
                stats["skipped_closed"] += 1
                continue
            seen.append(str(item["id"]))
            try:
                upsert_item(item)
                stats["listings"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("Error importando la publicación ML %s", item.get("id"))
                stats["errors"].append({"id": item.get("id"), "error": f"{type(exc).__name__}: {exc}"[:300]})
    stats["closed"] = (
        Listing.objects.filter(channel__code=CHANNEL)
        .exclude(external_id__in=seen)
        .exclude(status="closed")
        .update(status="closed")
    )
    return stats


def refresh(client, item_id: str) -> Listing:
    return upsert_item(client.get(f"/items/{item_id}"))


def variant_for(item_id: str, variation_id) -> Variant | None:
    row = (
        ListingVariation.objects.filter(
            listing__channel__code=CHANNEL,
            listing__external_id=str(item_id),
            external_id=str(variation_id or ""),
        )
        .select_related("variant")
        .first()
    )
    return row.variant if row else None
