"""Vínculos entre publicaciones/códigos de los canales (ListingVariation) y el maestro (Variant).

- Automático: por SKU (y por código de barras para Contabilium).
- Manual: lo decide una persona; la sincronización nunca lo pisa (link_source="manual").
- Cada vínculo tiene un ExternalRef espejo (canal, Variant, "{listing}:{variación}") para que
  cualquier módulo encuentre todos los IDs de una variante por una sola vía.
"""

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.integrations.models import ExternalRef

from .models import ListingVariation, Variant

BARCODE_CHANNELS = {"contabilium"}


def mirror_key(row: ListingVariation) -> str:
    return f"{row.listing.external_id}:{row.external_id}"


def _sync_mirror(row: ListingVariation) -> None:
    ct = ContentType.objects.get_for_model(Variant)
    key = mirror_key(row)
    ExternalRef.objects.filter(channel=row.listing.channel, content_type=ct, external_id=key).delete()
    if row.variant_id:
        ExternalRef.objects.create(
            channel=row.listing.channel,
            content_type=ct,
            object_id=row.variant_id,
            external_id=key,
            extra={"listing_id": row.listing_id, "sku": row.sku, "link_source": row.link_source},
        )


def find_variant(row: ListingVariation, barcode: str = "") -> Variant | None:
    if row.sku:
        variant = Variant.objects.filter(sku=row.sku).first()
        if variant:
            return variant
    if barcode and row.listing.channel.code in BARCODE_CHANNELS:
        return Variant.objects.filter(barcode=barcode).first()
    return None


@transaction.atomic
def auto_link(row: ListingVariation, barcode: str = "") -> bool:
    """Vincula por SKU/código de barras. Respeta los vínculos manuales. Devuelve si quedó vinculado."""
    if row.link_source == "manual":
        return row.variant_id is not None
    variant = find_variant(row, barcode)
    changed = (variant.pk if variant else None) != row.variant_id or row.link_source != (
        "auto" if variant else ""
    )
    row.variant = variant
    row.link_source = "auto" if variant else ""
    if changed:
        row.linked_at = timezone.now() if variant else None
        row.linked_by = None
        row.save(update_fields=["variant", "link_source", "linked_at", "linked_by"])
    _sync_mirror(row)
    return variant is not None


def _snapshot(row: ListingVariation) -> dict:
    return {
        "channel": row.listing.channel.code,
        "listing": row.listing.external_id,
        "variation": row.external_id,
        "sku_variante": row.variant.sku if row.variant_id else None,
        "origen": row.link_source,
    }


@transaction.atomic
def link_manual(row: ListingVariation, variant: Variant, *, user, request=None) -> None:
    before = _snapshot(row)
    row.variant = variant
    row.link_source = "manual"
    row.linked_by = user
    row.linked_at = timezone.now()
    row.save(update_fields=["variant", "link_source", "linked_by", "linked_at"])
    _sync_mirror(row)
    audit.record(user, "catalog.link_changed", row, before=before, after=_snapshot(row), request=request)


@transaction.atomic
def unlink_manual(row: ListingVariation, *, user, request=None) -> None:
    """Desvincula a propósito: queda sin variante y la sincronización no lo vuelve a vincular."""
    before = _snapshot(row)
    row.variant = None
    row.link_source = "manual"
    row.linked_by = user
    row.linked_at = timezone.now()
    row.save(update_fields=["variant", "link_source", "linked_by", "linked_at"])
    _sync_mirror(row)
    audit.record(user, "catalog.link_changed", row, before=before, after=_snapshot(row), request=request)


def relink_for_variant(variant: Variant) -> int:
    """Filas sin vincular (no manuales) con el SKU de esta variante → se vinculan."""
    count = 0
    rows = ListingVariation.objects.filter(variant__isnull=True, sku=variant.sku).exclude(
        link_source="manual"
    )
    for row in rows.select_related("listing__channel"):
        if auto_link(row):
            count += 1
    return count
