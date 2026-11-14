from django.utils import timezone

from .models import PriceListItem


def current_price(price_list, variant, at=None) -> PriceListItem | None:
    """Precio vigente en un momento dado (por defecto, ahora)."""
    at = at or timezone.now()
    return (
        PriceListItem.objects.filter(price_list=price_list, variant=variant, valid_from__lte=at)
        .order_by("-valid_from")
        .first()
    )


def set_price(
    price_list, variant, price, vat_rate=21, valid_from=None, promotional_price=None
) -> PriceListItem | None:
    """Agrega un precio nuevo solo si cambió respecto del vigente (evita filas duplicadas)."""
    valid_from = valid_from or timezone.now()
    current = current_price(price_list, variant, at=valid_from)
    if (
        current
        and current.price == price
        and current.vat_rate == vat_rate
        and current.promotional_price == promotional_price
    ):
        return None
    return PriceListItem.objects.create(
        price_list=price_list,
        variant=variant,
        price=price,
        vat_rate=vat_rate,
        valid_from=valid_from,
        promotional_price=promotional_price,
    )
