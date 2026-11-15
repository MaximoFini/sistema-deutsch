"""Carrito persistente (uno por cliente), grilla y mínimo de compra (US-4, §5)."""

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.catalog.models import Variant

from . import catalog
from .models import Cart, CartItem, CustomerBalance, StoreSettings


@dataclass
class CartLine:
    item: CartItem
    variant: Variant
    quantity: int
    net: Decimal | None  # None = ya no tiene precio mayorista
    available: int

    @property
    def sellable(self) -> bool:
        return (
            self.net is not None
            and self.net > 0
            and self.variant.is_active
            and self.variant.product.is_active
        )

    @property
    def total(self) -> Decimal:
        return catalog.quantize((self.net or 0) * self.quantity)

    @property
    def over_stock(self) -> bool:
        return self.quantity > self.available

    @property
    def label(self) -> str:
        return catalog.variant_label(self.variant)


@dataclass
class Summary:
    lines: list[CartLine] = field(default_factory=list)
    subtotal: Decimal = Decimal(0)  # neto
    vat: Decimal = Decimal(0)
    gross: Decimal = Decimal(0)  # neto + IVA
    balance_available: Decimal = Decimal(0)
    balance_applied: Decimal = Decimal(0)
    total: Decimal = Decimal(0)  # a pagar
    units: int = 0
    min_amount: Decimal = Decimal(0)
    min_includes_vat: bool = False
    min_applies: bool = True

    @property
    def min_base(self) -> Decimal:
        return self.gross if self.min_includes_vat else self.subtotal

    @property
    def missing_for_min(self) -> Decimal:
        if not self.min_applies:
            return Decimal(0)
        return max(Decimal(0), self.min_amount - self.min_base)

    @property
    def reaches_min(self) -> bool:
        return self.missing_for_min <= 0

    @property
    def has_problems(self) -> bool:
        return any(not line.sellable or line.over_stock for line in self.lines)

    @property
    def can_checkout(self) -> bool:
        return bool(self.lines) and self.reaches_min and not self.has_problems

    def snapshot(self) -> list[list]:
        """Lo que el cliente ve: [variante, cantidad, precio neto] por línea (para detectar cambios)."""
        return [[line.variant.pk, line.quantity, str(line.net)] for line in self.lines]

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True).encode()).hexdigest()


def summarize(cart: Cart, *, apply_min: bool = True, ctx: catalog.Context | None = None) -> Summary:
    """Calcula el carrito con precios y disponible actuales (no modifica nada)."""
    ctx = ctx or catalog.Context.load()
    items = list(cart.items.order_by("pk"))
    variant_ids = [i.variant_id for i in items]
    variants = {
        v.pk: v
        for v in Variant.objects.filter(pk__in=variant_ids)
        .select_related("product")
        .annotate(
            list_price=catalog.price_subquery(ctx.price_list_id),
            free=catalog.stock_subquery(ctx.warehouse_id),
        )
    }
    settings_row = StoreSettings.load()
    summary = Summary(
        min_amount=settings_row.min_order_amount,
        min_includes_vat=settings_row.min_order_includes_vat,
        min_applies=apply_min,
    )
    for item in items:
        variant = variants[item.variant_id]
        net = catalog.to_net(variant.list_price)
        if net is not None and net <= 0:
            net = None
        line = CartLine(
            item=item,
            variant=variant,
            quantity=item.quantity,
            net=net,
            available=catalog.available_from(variant.free, ctx.margin),
        )
        summary.lines.append(line)
    summary.lines.sort(key=lambda line: (line.variant.product.name, line.variant.sku))
    priced = [line for line in summary.lines if line.sellable]
    summary.subtotal = sum((line.total for line in priced), start=Decimal(0))
    summary.vat = sum((catalog.vat_of(line.total) for line in priced), start=Decimal(0))
    summary.gross = summary.subtotal + summary.vat
    summary.units = sum(line.quantity for line in summary.lines)
    if cart.customer_id:
        summary.balance_available = CustomerBalance.balance_for(cart.customer)
    summary.balance_applied = min(summary.balance_available, summary.gross)
    summary.total = summary.gross - summary.balance_applied
    return summary


class QuantityError(Exception):
    pass


def parse_quantity(raw) -> int:
    raw = str(raw if raw is not None else "").strip()
    if raw == "":
        return 0
    try:
        value = int(raw)
    except ValueError as exc:
        raise QuantityError("Las cantidades tienen que ser números enteros (unidades sueltas).") from exc
    if value < 0:
        raise QuantityError("Las cantidades no pueden ser negativas.")
    return value


@transaction.atomic
def set_quantities(cart: Cart, quantities: dict[int, int], ctx: catalog.Context | None = None) -> list[str]:
    """Fija las cantidades pedidas por variante (0 = quitar). Limita al disponible.

    Devuelve los avisos para mostrar ("Solo podés pedir hasta N…").
    """
    ctx = ctx or catalog.Context.load()
    warnings = []
    variants = {
        v.pk: v
        for v in catalog.sellable_variants(ctx).filter(pk__in=list(quantities)).select_related("product")
    }
    existing = {i.variant_id: i for i in CartItem.objects.select_for_update().filter(cart=cart)}
    for variant_id, wanted in quantities.items():
        variant = variants.get(variant_id)
        item = existing.get(variant_id)
        if wanted <= 0:
            if item is not None:
                item.delete()
            continue
        if variant is None:
            warnings.append("Uno de los productos ya no está a la venta y no lo agregamos.")
            if item is not None:
                item.delete()
            continue
        limit = catalog.available_from(variant.free, ctx.margin)
        label = f"{variant.product.name} {catalog.variant_label(variant)}".strip()
        if limit <= 0:
            warnings.append(f"{label} se agotó y no lo pudimos agregar.")
            if item is not None:
                item.delete()
            continue
        if wanted > limit:
            warnings.append(f"Solo podés pedir hasta {limit} de {label}.")
            wanted = limit
        if item is None:
            CartItem.objects.create(cart=cart, variant=variant, quantity=wanted)
        elif item.quantity != wanted:
            item.quantity = wanted
            item.save(update_fields=["quantity"])
    return warnings


def quantities_in_cart(cart: Cart) -> dict[int, int]:
    return dict(cart.items.values_list("variant_id", "quantity"))


def remove(cart: Cart, variant_id: int) -> None:
    CartItem.objects.filter(cart=cart, variant_id=variant_id).delete()


def clear(cart: Cart) -> None:
    cart.items.all().delete()
