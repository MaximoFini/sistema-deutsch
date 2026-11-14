from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import Product, Variant
from apps.customers.models import Customer
from apps.integrations.models import Channel, ChannelWriteSwitch, ExternalRef
from apps.integrations.services import find_by_external, link_external
from apps.inventory import services as inventory
from apps.inventory.models import StockMovement, Warehouse
from apps.pricing import services as pricing
from apps.pricing.models import PriceList
from apps.sales.models import SalesDocument, SalesLine

pytestmark = pytest.mark.django_db


@pytest.fixture
def variant():
    product = Product.objects.create(name="Remera básica")
    return Variant.objects.create(
        product=product, sku="REM-001-M-NEG", attributes={"talle": "M", "color": "Negro"}
    )


def test_seeds_exist():
    assert Warehouse.objects.get(is_default=True).code == "LOCAL"
    assert set(PriceList.objects.values_list("code", flat=True)) == {"MINORISTA", "MAYORISTA"}
    assert not PriceList.objects.get(code="MAYORISTA").prices_include_vat
    assert Channel.objects.count() == 5
    assert ChannelWriteSwitch.objects.filter(enabled=True).count() == 0


def test_sync_level_creates_movement_for_difference(variant):
    wh = inventory.default_warehouse()
    m1 = inventory.apply_sync_level(variant, wh, 10)
    assert m1.quantity == 10 and m1.kind == StockMovement.Kind.SYNC_ADJUSTMENT
    m2 = inventory.apply_sync_level(variant, wh, 7)
    assert m2.quantity == -3
    level = variant.stock_levels.get(warehouse=wh)
    assert level.on_hand == 7
    assert sum(m.quantity for m in StockMovement.objects.filter(variant=variant)) == level.on_hand


def test_sync_level_without_change_creates_nothing(variant):
    wh = inventory.default_warehouse()
    inventory.apply_sync_level(variant, wh, 5)
    assert inventory.apply_sync_level(variant, wh, 5) is None
    assert StockMovement.objects.count() == 1


def test_reservation_changes_available(variant):
    wh = inventory.default_warehouse()
    inventory.apply_sync_level(variant, wh, 10)
    inventory.change_reserved(variant, wh, 3)
    level = variant.stock_levels.get(warehouse=wh)
    assert level.available == 7
    inventory.change_reserved(variant, wh, -3)
    level.refresh_from_db()
    assert level.available == 10


def test_price_by_validity(variant):
    plist = PriceList.objects.get(code="MINORISTA")
    now = timezone.now()
    pricing.set_price(plist, variant, Decimal("1000"), valid_from=now - timedelta(days=10))
    pricing.set_price(plist, variant, Decimal("1200"), valid_from=now - timedelta(days=1))
    assert pricing.current_price(plist, variant).price == Decimal("1200")
    assert pricing.current_price(plist, variant, at=now - timedelta(days=5)).price == Decimal("1000")


def test_set_price_skips_unchanged(variant):
    plist = PriceList.objects.get(code="MINORISTA")
    pricing.set_price(plist, variant, Decimal("1000"))
    assert pricing.set_price(plist, variant, Decimal("1000")) is None
    assert plist.items.count() == 1


def test_document_numbering_per_type():
    channel = Channel.objects.get(code="manual")
    now = timezone.now()
    o1 = SalesDocument.objects.create(channel=channel, issued_at=now)
    o2 = SalesDocument.objects.create(channel=channel, issued_at=now)
    r1 = SalesDocument.objects.create(channel=channel, issued_at=now, doc_type="return", related_document=o1)
    assert o2.number == o1.number + 1
    assert r1.related_document == o1
    assert o1.related_documents.get() == r1


def test_line_and_document_totals(variant):
    doc = SalesDocument.objects.create(channel=Channel.objects.get(code="manual"), issued_at=timezone.now())
    SalesLine.objects.create(
        document=doc,
        variant=variant,
        sku_snapshot=variant.sku,
        description_snapshot="Remera",
        quantity=Decimal("3"),
        unit_price=Decimal("1000.50"),
        discount=Decimal("1.50"),
    )
    doc.shipping_total = Decimal("500")
    doc.recalculate_totals()
    assert doc.subtotal == Decimal("3000.00")
    assert doc.total == Decimal("3500.00")


def test_external_ref_unique_per_channel_and_type(variant):
    link_external("tiendanube", variant.product, "123")
    other = Product.objects.create(name="Otro")
    with pytest.raises(IntegrityError), transaction.atomic():
        ExternalRef.objects.create(
            channel=Channel.objects.get(code="tiendanube"),
            content_type=ExternalRef.objects.first().content_type,
            object_id=other.pk,
            external_id="123",
        )


def test_product_with_ids_in_three_channels(variant):
    product = variant.product
    for code, ext in [("tiendanube", "tn-1"), ("mercadolibre", "MLA1"), ("contabilium", "cb-9")]:
        link_external(code, product, ext)
    assert find_by_external("mercadolibre", Product, "MLA1") == product
    assert ExternalRef.objects.filter(object_id=product.pk).count() == 3


def test_link_external_is_idempotent(variant):
    link_external("tiendanube", variant.product, "999")
    link_external("tiendanube", variant.product, "999")
    assert ExternalRef.objects.count() == 1


def test_customer_defaults():
    c = Customer.objects.create(legal_name="Juan Pérez")
    assert c.vat_condition == "CF" and not c.credit_enabled
