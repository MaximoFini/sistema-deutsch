"""Publicaciones de Mercado Libre → Listing / ListingVariation, vinculadas a Variant por SKU.

Stock y precio quedan como dato del canal: no alimentan el stock del sistema ni se escriben.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Listing, ListingVariation, Variant
from apps.integrations.models import Channel
from apps.integrations.services import link_external

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
            "data": {
                "attributes": item.get("attributes") or [],
                "pictures": [p.get("secure_url") for p in item.get("pictures") or []],
                "family_name": item.get("family_name"),
                "shipping": shipping,
                "last_updated": item.get("last_updated"),
            },
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
        variant = Variant.objects.filter(sku=sku).first() if sku else None
        if not sku:
            notes.append(f"{ext_id or 'publicación'}: sin SKU")
        elif variant is None:
            notes.append(f"{ext_id or 'publicación'}: SKU {sku} no está en el catálogo")
        attributes = {
            c.get("name"): c.get("value_name")
            for c in (variation or {}).get("attribute_combinations") or []
            if c.get("name")
        }
        picture_ids = (variation or {}).get("picture_ids") or list(pictures)
        ListingVariation.objects.update_or_create(
            listing=listing,
            external_id=ext_id,
            defaults={
                "variant": variant,
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
        if variant is not None:
            link_external(CHANNEL, variant, f"{item['id']}:{ext_id}", {"listing_id": listing.pk, "sku": sku})
    listing.variations.exclude(external_id__in=seen).delete()  # datos del canal: se pueden borrar
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
