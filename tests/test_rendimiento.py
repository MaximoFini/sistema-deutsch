"""P3 (auditoría M0–M4): la cantidad de consultas de las pantallas principales no crece con el volumen.

Se cargan datos moderados con bulk_create (rápido) y cada pantalla tiene un presupuesto fijo de
consultas. Si alguien agrega un N+1, el número se dispara y el test falla.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Listing, ListingVariation, Product, Variant
from apps.customers.models import Customer
from apps.integrations.models import Channel, ExternalRef
from apps.pricing.models import PriceList, PriceListItem
from apps.sales import states
from apps.sales.models import Payment, SalesDocument, SalesLine, Shipment

pytestmark = pytest.mark.django_db

ORDERS = 300
VARIANTS = 500

# Presupuestos: conteo real medido + un margen chico (sesión, permisos, mensajes).
BUDGET = {
    "sales:list": 12,  # medido: 9
    "sales:detail": 17,  # medido: 15 (M5 suma la tanda del pedido)
    "catalog:list": 10,  # medido: 7
    "catalog:channel_stock": 12,  # medido: 9
    "catalog:quality": 14,  # medido: 11
    # M5 · preparación y despacho
    "sales:prepare": 11,  # medido: 8
    "sales:dispatch": 12,  # medido: 9
    "sales:batches": 10,  # medido: 7
    "sales:batch_detail": 14,  # medido: 11 (tanda de 30 pedidos)
}


@pytest.fixture
def volume(db):
    channels = {c.code: c for c in Channel.objects.filter(code__in=["tiendanube", "mercadolibre", "manual"])}
    now = timezone.now()

    products = Product.objects.bulk_create([Product(name=f"Producto {i}") for i in range(VARIANTS // 5)])
    variants = Variant.objects.bulk_create(
        [Variant(product=products[i // 5], sku=f"SKU-{i:04d}") for i in range(VARIANTS)]
    )
    retail = PriceList.objects.get(code="MINORISTA")
    PriceListItem.objects.bulk_create(
        [PriceListItem(price_list=retail, variant=v, price=Decimal("1000"), valid_from=now) for v in variants]
    )
    ct = ContentType.objects.get_for_model(Variant)
    ExternalRef.objects.bulk_create(
        [
            ExternalRef(
                channel=channels["tiendanube"],
                content_type=ct,
                object_id=v.pk,
                external_id=f"tn-{v.pk}",
                extra={"stock": 3, "price": "1000"},
            )
            for v in variants[::2]
        ]
    )
    listings = Listing.objects.bulk_create(
        [
            Listing(
                channel=channels["mercadolibre"], external_id=f"MLA{i}", title=f"Pub {i}", status="active"
            )
            for i in range(VARIANTS // 5)
        ]
    )
    ListingVariation.objects.bulk_create(
        [
            ListingVariation(listing=listings[i // 5], variant=v, external_id=str(i), available_quantity=2)
            for i, v in enumerate(variants)
        ]
    )

    customers = Customer.objects.bulk_create([Customer(legal_name=f"Cliente {i}") for i in range(50)])
    codes = list(channels)
    docs = SalesDocument.objects.bulk_create(
        [
            SalesDocument(
                doc_type=SalesDocument.DocType.ORDER,
                channel=channels[codes[i % 3]],
                number=900000 + i,
                customer=customers[i % 50],
                status=states.NEW if i % 2 else states.PREPARING,
                issued_at=now - timedelta(minutes=i),
                total=Decimal("2000"),
                channel_reference=f"Pedido {i}",
            )
            for i in range(ORDERS)
        ]
    )
    SalesLine.objects.bulk_create(
        [
            SalesLine(
                document=d,
                variant=variants[(i + k) % VARIANTS],
                sku_snapshot=variants[(i + k) % VARIANTS].sku,
                description_snapshot="Producto",
                quantity=1,
                unit_price=1000,
                line_total=1000,
            )
            for i, d in enumerate(docs)
            for k in range(2)
        ]
    )
    Payment.objects.bulk_create(
        [
            Payment(document=d, method="cash", amount=d.total, status=Payment.Status.CONFIRMED)
            for d in docs[::2]
        ]
    )
    Shipment.objects.bulk_create(
        [
            Shipment(
                document=d,
                method=Shipment.Method.ME_FLEX,
                dispatch_deadline=now + timedelta(hours=i % 24) if i % 3 == 0 else None,
            )
            for i, d in enumerate(docs)
        ]
    )
    return docs


def _batch_with_orders(docs, size=30):
    """Una tanda con `size` pedidos del volumen (para medir el detalle de tanda)."""
    from apps.accounts.models import User
    from apps.fulfillment.models import PickBatch, PickBatchOrder

    user = User.objects.create_user(email="tanda@test.local", full_name="Tanda", password="clave-de-test-123")
    batch = PickBatch.objects.create(number=1, created_by=user)
    PickBatchOrder.objects.bulk_create(
        [PickBatchOrder(batch=batch, document=d) for d in docs if d.status == states.PREPARING][:size]
    )
    return batch


def _url(name, docs):
    if name == "sales:detail":
        return reverse(name, args=[docs[0].pk])
    if name == "sales:batch_detail":
        return reverse(name, args=[_batch_with_orders(docs).number])
    return reverse(name)


@pytest.mark.parametrize("name", list(BUDGET))
def test_query_budget(admin_client, volume, django_assert_max_num_queries, name):
    url = _url(name, volume)
    assert admin_client.get(url).status_code == 200  # calienta sesión y permisos
    with django_assert_max_num_queries(BUDGET[name]):
        response = admin_client.get(url)
    assert response.status_code == 200
