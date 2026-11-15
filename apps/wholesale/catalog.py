"""Catálogo de la tienda: qué se vende, a qué precio neto y si hay disponible (US-3, §4).

- Se venden los productos activos con al menos una variante activa cuyo precio vigente en la lista
  MAYORISTA es mayor a $0.
- Precio neto (sin IVA): el de la lista; si viene con IVA (`CONTABILIUM_WHOLESALE_INCLUDES_VAT`) se
  divide por 1,21.
- Disponible = físico del depósito por defecto − reservado (incluye las reservas mayoristas) − margen
  de seguridad. La cantidad exacta nunca se muestra al cliente.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.db.models import (
    DecimalField,
    Exists,
    F,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog.attributes import ordered_values
from apps.catalog.models import Product, Variant
from apps.inventory.models import StockLevel
from apps.inventory.services import default_warehouse
from apps.pricing.models import PriceList, PriceListItem
from apps.pricing.services import current_price

from .models import StoreSettings

VAT_RATE = Decimal("21")
VAT_FACTOR = Decimal("1.21")
CENT = Decimal("0.01")
PAGE_SIZE = 24
MONEY = DecimalField(max_digits=14, decimal_places=2)
QTY = DecimalField(max_digits=12, decimal_places=3)
SIZE_KEYS = ("talle", "Talle", "TALLE")
COLOR_KEYS = ("color", "Color", "COLOR")
FILTER_OPTIONS_CACHE_SECONDS = 300


def quantize(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_net(list_price) -> Decimal | None:
    """Precio de lista MAYORISTA → neto sin IVA."""
    if list_price is None:
        return None
    price = Decimal(list_price)
    if settings.CONTABILIUM_WHOLESALE_INCLUDES_VAT:
        price = price / VAT_FACTOR
    return quantize(price)


def format_money(value) -> str:
    """$ 1.234,56 siempre en formato argentino (no depende del idioma del navegador)."""
    text = f"{Decimal(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"$ {text}"


def vat_of(net) -> Decimal:
    return quantize(Decimal(net) * VAT_RATE / 100)


def wholesale_list() -> PriceList:
    return PriceList.objects.get(code="MAYORISTA")


def price_subquery(price_list_id: int, at=None) -> Subquery:
    """Precio vigente de la variante (OuterRef "pk") en la lista dada."""
    at = at or timezone.now()
    return Subquery(
        PriceListItem.objects.filter(price_list_id=price_list_id, variant=OuterRef("pk"), valid_from__lte=at)
        .order_by("-valid_from")
        .values("price")[:1],
        output_field=MONEY,
    )


def stock_subquery(warehouse_id: int) -> Coalesce:
    """Físico − reservado en el depósito (0 si la variante no tiene fila de stock)."""
    sq = StockLevel.objects.filter(variant=OuterRef("pk"), warehouse_id=warehouse_id).annotate(
        free=F("on_hand") - F("reserved")
    )
    return Coalesce(Subquery(sq.values("free")[:1], output_field=QTY), Value(Decimal(0), output_field=QTY))


@dataclass
class Context:
    """Lo que se calcula una vez por pantalla (lista de precios, depósito y margen)."""

    price_list_id: int
    warehouse_id: int
    margin: int

    @classmethod
    def load(cls) -> "Context":
        return cls(
            price_list_id=wholesale_list().pk,
            warehouse_id=default_warehouse().pk,
            margin=StoreSettings.load().safety_margin_units,
        )


def sellable_variants(ctx: Context) -> QuerySet[Variant]:
    """Variantes activas de productos activos con precio MAYORISTA > 0, anotadas con
    `list_price` y `free` (físico − reservado)."""
    return (
        Variant.objects.filter(is_active=True, product__is_active=True)
        .annotate(list_price=price_subquery(ctx.price_list_id), free=stock_subquery(ctx.warehouse_id))
        .filter(list_price__gt=0)
    )


def available_from(free, margin: int) -> int:
    return max(0, int(Decimal(free or 0)) - int(margin or 0))


def available(variant: Variant, ctx: Context | None = None) -> int:
    """Unidades que se pueden vender por la tienda (nunca negativo)."""
    ctx = ctx or Context.load()
    free = getattr(variant, "free", None)
    if free is None:
        level = StockLevel.objects.filter(variant=variant, warehouse_id=ctx.warehouse_id).first()
        free = (level.on_hand - level.reserved) if level else 0
    return available_from(free, ctx.margin)


def net_price(variant: Variant, ctx: Context | None = None) -> Decimal | None:
    """Precio neto vigente (sin IVA), o None si no tiene precio MAYORISTA."""
    list_price = getattr(variant, "list_price", None)
    if list_price is None:
        item = current_price(wholesale_list(), variant)
        list_price = item.price if item else None
    return to_net(list_price)


@dataclass
class Filters:
    q: str = ""
    category: str = ""
    brand: str = ""
    size: str = ""

    @classmethod
    def from_request(cls, request) -> "Filters":
        get = request.GET
        return cls(
            q=get.get("q", "").strip()[:100],
            category=get.get("categoria", "").strip()[:150],
            brand=get.get("marca", "").strip()[:100],
            size=get.get("talle", "").strip()[:30],
        )

    @property
    def active(self) -> bool:
        return bool(self.q or self.category or self.brand or self.size)

    def querystring(self) -> str:
        pairs = {"q": self.q, "categoria": self.category, "marca": self.brand, "talle": self.size}
        return urlencode({k: v for k, v in pairs.items() if v})


def _size_q(size: str) -> Q:
    q = Q()
    for key in SIZE_KEYS:
        q |= Q(**{f"attributes__{key}": size})
    return q


def store_products(filters: Filters | None = None, ctx: Context | None = None) -> QuerySet[Product]:
    """Productos de la tienda con `has_available`, ordenados: disponibles primero, después por nombre.

    Las variantes (con `list_price` y `free`) se cargan con un prefetch de una sola consulta.
    """
    filters = filters or Filters()
    ctx = ctx or Context.load()
    variants = sellable_variants(ctx)
    variants_of_product = variants.filter(product=OuterRef("pk"))
    if filters.size:
        variants_of_product = variants_of_product.filter(_size_q(filters.size))
    with_stock = variants_of_product.filter(free__gt=ctx.margin)
    products = Product.objects.filter(is_active=True).filter(Exists(variants_of_product))
    if filters.q:
        sku_match = Variant.objects.filter(product=OuterRef("pk"), sku__icontains=filters.q)
        products = products.filter(Q(name__icontains=filters.q) | Exists(sku_match))
    if filters.category:
        products = products.filter(Q(categories__contains=[filters.category]) | Q(category=filters.category))
    if filters.brand:
        products = products.filter(brand=filters.brand)
    return (
        products.annotate(has_available=Exists(with_stock))
        .order_by("-has_available", "name", "pk")
        .prefetch_related(Prefetch("variants", queryset=variants.order_by("sku"), to_attr="store_variants"))
    )


def filter_options(ctx: Context | None = None) -> dict:
    """Categorías, marcas y talles que tienen algo a la venta (se guarda 5 minutos en caché)."""

    def build():
        c = ctx or Context.load()
        rows = sellable_variants(c).values_list(
            "product__categories", "product__category", "product__brand", "attributes"
        )
        categories, brands, sizes = set(), set(), set()
        for cats, cat, brand, attrs in rows:
            categories.update(x for x in (cats or []) if x)
            if cat:
                categories.add(cat)
            if brand:
                brands.add(brand)
            size = _attr(attrs, SIZE_KEYS)
            if size:
                sizes.add(size)
        return {
            "categories": sorted(categories, key=str.lower),
            "brands": sorted(brands, key=str.lower),
            "sizes": sort_sizes(sizes),
        }

    return cache.get_or_set("store:filter_options", build, FILTER_OPTIONS_CACHE_SECONDS)


SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "2XL", "3XL", "4XL", "5XL", "U", "ÚNICO"]


def _size_key(value: str):
    upper = str(value).upper()
    if upper in SIZE_ORDER:
        return (1, SIZE_ORDER.index(upper), "")
    try:
        return (0, float(str(value).replace(",", ".")), "")
    except ValueError:
        return (2, 0, upper)


def sort_sizes(values) -> list[str]:
    """Talles en orden natural: números de menor a mayor, después XS…XXL, después el resto."""
    return sorted(set(values), key=_size_key)


def _attr(attrs: dict | None, keys) -> str:
    for key in keys:
        value = (attrs or {}).get(key)
        if value:
            return str(value)
    return ""


# ── Ficha de producto y grilla talle × color ─────────────────────────────────


@dataclass
class Cell:
    variant: Variant
    net: Decimal
    available: int
    in_cart: int = 0

    @property
    def sold_out(self) -> bool:
        return self.available <= 0


@dataclass
class Grid:
    """Matriz talles (filas) × colores (columnas). Sin talle o sin color, una sola fila/columna."""

    sizes: list[str]
    colors: list[str]
    cells: dict = field(default_factory=dict)  # (talle, color) -> Cell
    others: list = field(default_factory=list)  # variantes con otros atributos (se listan aparte)

    def rows(self):
        for size in self.sizes:
            yield size, [self.cells.get((size, color)) for color in self.colors]

    @property
    def any_available(self) -> bool:
        return any(not c.sold_out for c in self.cells.values()) or any(not c.sold_out for c in self.others)

    @property
    def all_cells(self) -> list[Cell]:
        return list(self.cells.values()) + list(self.others)


def build_grid(variants, ctx: Context, cart_quantities: dict | None = None) -> Grid:
    """Arma la grilla con las variantes vendibles (anotadas con `list_price` y `free`)."""
    cart_quantities = cart_quantities or {}
    sizes, colors, cells, others = [], [], {}, []
    for v in variants:
        cell = Cell(
            variant=v,
            net=to_net(v.list_price),
            available=available_from(v.free, ctx.margin),
            in_cart=cart_quantities.get(v.pk, 0),
        )
        size = _attr(v.attributes, SIZE_KEYS)
        color = _attr(v.attributes, COLOR_KEYS)
        key = (size, color)
        if key in cells:  # dos variantes con el mismo talle y color (atributos extra): se listan aparte
            others.append(cell)
            continue
        cells[key] = cell
        if size not in sizes:
            sizes.append(size)
        if color not in colors:
            colors.append(color)
    return Grid(
        sizes=sort_sizes(sizes) if any(sizes) else sizes,
        colors=sorted(colors, key=str.lower),
        cells=cells,
        others=others,
    )


def variant_label(variant: Variant) -> str:
    return " / ".join(ordered_values(variant.attributes))


def main_image(product: Product) -> dict | None:
    images = sorted((product.images or []), key=lambda i: i.get("position") or 0)
    return images[0] if images and images[0].get("url") else None
