"""Catálogo de Tiendanube → modelos núcleo (Product, Variant, precio, stock).

Nunca escribe en Tiendanube. Cada producto se procesa en su propia transacción.
"""

import logging

from django.conf import settings
from django.db import transaction

from apps.catalog.models import Product, Variant
from apps.integrations.models import ExternalRef
from apps.integrations.services import find_by_external, link_external
from apps.inventory import services as inventory
from apps.pricing import services as pricing
from apps.pricing.models import PriceList

from .client import CHANNEL
from .common import cm_to_mm, dec, kg_to_g, text

logger = logging.getLogger(__name__)


def _attributes(product: dict, variant: dict) -> dict:
    names = [text(a) for a in product.get("attributes") or []]
    values = [text(v) for v in variant.get("values") or []]
    return {
        (names[i] if i < len(names) and names[i] else f"Atributo {i + 1}"): value
        for i, value in enumerate(values)
        if value
    }


def _images(product: dict) -> list[dict]:
    images = sorted(product.get("images") or [], key=lambda i: i.get("position") or 0)
    return [{"url": i.get("src"), "position": i.get("position"), "alt": text(i.get("alt"))} for i in images]


def _categories(product: dict) -> list[str]:
    cats = []
    for c in product.get("categories") or []:
        name = text(c.get("name")) if isinstance(c, dict) else ""
        if name:
            cats.append(name)
    return cats


def _resolve_variant(product_obj: Product, tn_variant: dict) -> tuple[Variant | None, str, list[str]]:
    """Busca la variante por ID de TN, después por SKU. Devuelve (variante|None, sku a usar, notas)."""
    notes = []
    tn_id = str(tn_variant["id"])
    variant = find_by_external(CHANNEL, Variant, tn_id)
    sku = (tn_variant.get("sku") or "").strip()
    if not sku:
        sku = f"TN-{tn_id}"
        notes.append("Sin SKU en Tiendanube")
    if variant is None:
        same_sku = Variant.objects.filter(sku=sku).first()
        if same_sku is not None:
            already_linked = ExternalRef.objects.filter(
                channel__code=CHANNEL, content_type__model="variant", object_id=same_sku.pk
            ).exclude(external_id=tn_id)
            if already_linked.exists():
                notes.append(f"SKU {sku} repetido en otra variante de Tiendanube")
                sku = f"TN-{tn_id}"
            else:
                variant = same_sku
    elif variant.sku != sku and Variant.objects.filter(sku=sku).exclude(pk=variant.pk).exists():
        notes.append(f"SKU {sku} ya usado por otra variante")
        sku = variant.sku
    return variant, sku, notes


@transaction.atomic
def upsert_product(data: dict) -> Product:
    product = find_by_external(CHANNEL, Product, data["id"])
    fields = {
        "name": text(data.get("name"))[:255] or f"Producto TN {data['id']}",
        "description": text(data.get("description")),
        "brand": (data.get("brand") or "Deutsch")[:100],
        "categories": _categories(data),
        "images": _images(data),
        "is_active": data.get("visibility", "visible") != "hidden"
        if "visibility" in data
        else bool(data.get("published", True)),
    }
    fields["category"] = (fields["categories"][0] if fields["categories"] else "")[:150]
    if product is None:
        product = Product.objects.create(**fields)
    else:
        for key, value in fields.items():
            setattr(product, key, value)
        product.save()
    link_external(
        CHANNEL,
        product,
        data["id"],
        {
            "handle": text(data.get("handle")),
            "updated_at": data.get("updated_at"),
            "visibility": data.get("visibility"),
        },
    )

    minorista = PriceList.objects.get(code="MINORISTA")
    warehouse = inventory.default_warehouse()
    feeds_stock = settings.STOCK_FEED_CHANNEL == CHANNEL
    seen = set()
    for tn_variant in data.get("variants") or []:
        variant, sku, notes = _resolve_variant(product, tn_variant)
        barcode = (tn_variant.get("barcode") or "").strip() or None
        if (
            barcode
            and Variant.objects.filter(barcode=barcode).exclude(pk=getattr(variant, "pk", None)).exists()
        ):
            notes.append(f"Código de barras {barcode} repetido")
            barcode = None
        values = {
            "product": product,
            "sku": sku,
            "barcode": barcode,
            "attributes": _attributes(data, tn_variant),
            "weight_g": kg_to_g(tn_variant.get("weight")),
            "width_mm": cm_to_mm(tn_variant.get("width")),
            "height_mm": cm_to_mm(tn_variant.get("height")),
            "length_mm": cm_to_mm(tn_variant.get("depth")),
            "is_active": product.is_active,
            "needs_review": bool(notes),
            "review_notes": "; ".join(notes)[:255],
        }
        if variant is None:
            variant = Variant.objects.create(**values)
        else:
            for key, value in values.items():
                setattr(variant, key, value)
            variant.save()
        seen.add(variant.pk)

        price = dec(tn_variant.get("price"))
        promo = dec(tn_variant.get("promotional_price"))
        if price is not None:
            pricing.set_price(minorista, variant, price, promotional_price=promo)
        stock = tn_variant.get("stock")
        if feeds_stock and stock is not None:
            inventory.apply_sync_level(variant, warehouse, stock, note="vía Tiendanube")
        link_external(
            CHANNEL,
            variant,
            tn_variant["id"],
            {
                "product_id": data["id"],
                "stock": stock,
                "price": str(price) if price is not None else None,
                "promotional_price": str(promo) if promo is not None else None,
                "updated_at": tn_variant.get("updated_at"),
            },
        )
    # Variantes que ya no están en TN: inactivas (nunca se borran).
    product.variants.exclude(pk__in=seen).update(is_active=False)
    return product


@transaction.atomic
def deactivate_product(tn_product_id) -> bool:
    product = find_by_external(CHANNEL, Product, tn_product_id)
    if product is None:
        return False
    product.is_active = False
    product.save(update_fields=["is_active", "updated_at"])
    product.variants.update(is_active=False)
    return True


def import_all(client, updated_since=None) -> dict:
    """Importa todos los productos (o los cambiados desde `updated_since`).

    Un producto con error no frena al resto: queda en stats["errors"].
    """
    params = {}
    if updated_since:
        params["updated_at_min"] = updated_since.isoformat()
    stats = {"products": 0, "errors": []}
    seen_ids = []
    for data in client.get_all("/products", params):
        seen_ids.append(str(data["id"]))
        try:
            upsert_product(data)
            stats["products"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error importando el producto TN %s", data.get("id"))
            stats["errors"].append({"id": data.get("id"), "error": f"{type(exc).__name__}: {exc}"[:300]})
    if updated_since is None:
        stats["deactivated"] = deactivate_missing(seen_ids)
    return stats


def deactivate_missing(seen_ids: list[str]) -> int:
    """Recorrido completo: lo que ya no existe en TN queda inactivo (recupera borrados perdidos)."""
    refs = ExternalRef.objects.filter(channel__code=CHANNEL, content_type__model="product").exclude(
        external_id__in=seen_ids
    )
    count = 0
    for ref in refs:
        if deactivate_product(ref.external_id):
            count += 1
    return count
