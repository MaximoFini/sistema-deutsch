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
    # M6 · operación de Mercado Libre
    "ml:questions": 11,  # medido: 8 (200 preguntas)
    "ml:question_detail": 14,  # medido: 11 (variaciones, stock y anteriores)
    "ml:threads": 12,  # medido: 9 (100 conversaciones)
    "ml:claims": 10,  # medido: 7
    "ml:health": 10,  # medido: 7 (100 publicaciones con problemas)
    "ml:counters": 11,  # medido: 8 (3 contadores)
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


def _ml_volume(docs):
    """Preguntas, conversaciones y reclamos de ML sobre el volumen (para medir las pantallas de M6)."""
    from apps.conversations.models import Claim, Message, Question

    ml = Channel.objects.get(code="mercadolibre")
    now = timezone.now()
    listings = list(Listing.objects.filter(channel=ml))
    for i, listing in enumerate(listings):  # problemas de salud variados
        listing.status = "paused" if i % 3 == 0 else "active"
        listing.health = Decimal("0.5") if i % 2 else Decimal("0.9")
        listing.data = {
            "sub_status": ["out_of_stock"],
            "tags": ["poor_quality_picture"],
            "pictures": ["p.jpg"],
        }
    Listing.objects.bulk_update(listings, ["status", "health", "data"])
    questions = Question.objects.bulk_create(
        [
            Question(
                channel=ml,
                external_id=f"q{i}",
                listing=listings[i % len(listings)],
                item_external_id=listings[i % len(listings)].external_id,
                text=f"Pregunta {i}",
                asked_at=now - timedelta(hours=i % 30),
                status="unanswered" if i % 2 else "answered",
                answer_text="" if i % 2 else "Respuesta",
                answered_at=None if i % 2 else now,
            )
            for i in range(200)
        ]
    )
    Message.objects.bulk_create(
        [
            Message(
                channel=ml,
                external_id=f"m{i}",
                document=docs[i % 100],
                thread_key=str(docs[i % 100].pk),
                direction="in" if i % 3 else "out",
                text=f"Mensaje {i}",
                sent_at=now - timedelta(minutes=i),
            )
            for i in range(400)
        ]
    )
    Claim.objects.bulk_create(
        [
            Claim(
                channel=ml,
                external_id=f"c{i}",
                document=docs[i],
                order_external_id=str(i),
                status="opened" if i % 4 else "closed",
                reason="PNR1",
                action_required=bool(i % 2),
                due_date=now + timedelta(hours=i),
            )
            for i in range(60)
        ]
    )
    return next(q for q in questions if q.status == "unanswered")


def _url(name, docs):
    if name.startswith("ml:"):
        question = _ml_volume(docs)
        if name == "ml:question_detail":
            return reverse(name, args=[question.pk])
        return reverse(name)
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
