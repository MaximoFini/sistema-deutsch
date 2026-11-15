"""P3 (auditoría M0–M4): la cantidad de consultas de las pantallas principales no crece con el volumen.

Se cargan datos moderados con bulk_create (rápido) y cada pantalla tiene un presupuesto fijo de
consultas. Si alguien agrega un N+1, el número se dispara y el test falla.
"""

import io
import random
import time
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
    "ml:threads": 14,  # medido: 12 (100 conversaciones; R1: último mensaje, pedidos y «Ver más viejas»)
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


# ── Auditoría M6 · R2 ────────────────────────────────────────────────────

THREADS = 1500  # 4 mensajes cada una; la mitad sin actividad en los últimos 60 días


def _many_threads(now):
    from apps.conversations.models import Message

    ml = Channel.objects.get(code="mercadolibre")
    docs = SalesDocument.objects.bulk_create(
        [
            SalesDocument(
                doc_type=SalesDocument.DocType.ORDER, channel=ml, number=700000 + i, total=1, issued_at=now
            )
            for i in range(THREADS)
        ]
    )
    Message.objects.bulk_create(
        [
            Message(
                channel=ml,
                external_id=f"t{i}-{k}",
                document=d,
                thread_key=f"th{i}",
                direction="in" if k % 2 == 0 else "out",
                text=f"Mensaje {k} de {i}",
                sent_at=now - timedelta(days=(i % 120), minutes=k),
                read_at=None if (i % 50 == 0 and k == 0) else now,
            )
            for i, d in enumerate(docs)
            for k in range(4)
        ]
    )


@pytest.mark.parametrize("query", ["", "?viejas=1", "?sin_leer=1", "?page=3"])
def test_threads_many_conversations(admin_client, django_assert_max_num_queries, query):
    """La lista de mensajes calcula el último texto solo para la página (no para las 1.500)."""
    _many_threads(timezone.now())
    url = reverse("ml:threads") + query
    assert admin_client.get(url).status_code == 200
    with django_assert_max_num_queries(14):  # medido: 12 por defecto, 11 con «viejas» o «sin leer»
        response = admin_client.get(url)
    assert response.status_code == 200 and len(response.context["threads"]) <= 50
    if not query:
        assert response.context["older_exist"]


def test_alert_task_second_run_is_cheap(db, django_assert_max_num_queries):
    """La tarea de avisos (cada 5 min) no recorre otra vez lo ya avisado ni las preguntas viejas."""
    from apps.conversations import tasks
    from apps.conversations.models import Claim, Question

    ml = Channel.objects.get(code="mercadolibre")
    now = timezone.now()
    Question.objects.bulk_create(
        [
            Question(
                channel=ml,
                external_id=f"aq{i}",
                text=f"Pregunta {i}",
                asked_at=now - timedelta(hours=13 + i % 200),  # la mitad de hace más de 3 días
                status="unanswered",
            )
            for i in range(1000)
        ]
    )
    Claim.objects.bulk_create(
        [
            Claim(
                channel=ml,
                external_id=f"ac{i}",
                status="opened",
                action_required=True,
                due_date=now + timedelta(hours=1 + i % 30),
            )
            for i in range(40)
        ]
    )
    assert tasks.check_questions(now=now) == 1  # un solo resumen, no cientos de avisos
    tasks.check_claims_due(now=now)
    with django_assert_max_num_queries(2):
        assert tasks.check_questions(now=now + timedelta(minutes=5)) == 0
        assert tasks.check_claims_due(now=now + timedelta(minutes=5)) == 0


# ── M7 · Reportes: 12 meses de datos (~10.000 pedidos) ────────────────────

REPORT_ORDERS = 10_000
REPORT_VARIANTS = 400
# (pantalla, parámetros extra): presupuesto de consultas (medido + margen chico).
REPORT_SCREENS = {
    ("reports:summary", ""): 14,  # medido: 11 (0,32 s)
    ("reports:sales", ""): 11,  # medido: 8 (0,24 s)
    ("reports:sales", "&agrupar=variante&orden=-unidades"): 10,  # medido: 7 (0,35 s)
    ("reports:sales", "&agrupar=talle"): 10,  # medido: 7 (0,24 s)
    ("reports:sales", "&agrupar=dia"): 11,  # medido: 8 (0,22 s)
    ("reports:products", ""): 21,  # medido: 18 (0,82 s: top 50 ×2, stock y "se agotan")
    ("reports:operations", ""): 17,  # medido: 14 (0,87 s)
    ("reports:summary_excel", ""): 14,  # medido: 11 (0,25 s)
    ("reports:sales_excel", "&agrupar=variante"): 10,  # medido: 7 (0,34 s)
    ("reports:products_excel", ""): 21,  # medido: 18 (0,75 s)
    ("reports:operations_excel", ""): 16,  # medido: 13 (0,58 s)
}


def _report_volume():
    """10.000 pedidos y 20.000 líneas repartidos en 12 meses, con envíos, preguntas y 20.000 movimientos de stock."""
    from django.db import connection

    from apps.conversations.models import Question
    from apps.inventory.models import StockLevel, StockMovement, Warehouse

    rnd = random.Random(7)
    channels = list(
        Channel.objects.filter(code__in=["tiendanube", "mercadolibre", "manual"]).order_by("code")
    )
    now = timezone.now()
    products = Product.objects.bulk_create(
        [Product(name=f"Producto R{i}") for i in range(REPORT_VARIANTS // 4)]
    )
    sizes, colors = ["S", "M", "L", "XL"], ["Negro", "Blanco", "Gris"]
    variants = Variant.objects.bulk_create(
        [
            Variant(
                product=products[i // 4],
                sku=f"R-{i:04d}",
                attributes={"Talle": sizes[i % 4], "Color": colors[i % 3]},
            )
            for i in range(REPORT_VARIANTS)
        ]
    )
    statuses = [states.DELIVERED] * 6 + [states.DISPATCHED, states.NEW, states.CANCELLED, states.READY]
    docs = []
    for i in range(REPORT_ORDERS):
        issued = now - timedelta(minutes=rnd.randint(0, 364 * 24 * 60))
        status = statuses[i % len(statuses)]
        out = issued + timedelta(hours=rnd.randint(1, 72))
        channel = channels[i % 3]
        docs.append(
            SalesDocument(
                doc_type=SalesDocument.DocType.ORDER,
                channel=channel,
                number=500000 + i,
                status=status,
                issued_at=issued,
                ready_at=issued,
                dispatched_at=out if status in (states.DELIVERED, states.DISPATCHED) and out < now else None,
                total=Decimal(rnd.randint(5, 80) * 1000),
                channel_reference=f"R{i}",
                net_pending=channel.code == "mercadolibre" and i % 20 == 0,
                invoiced_in_contabilium=i % 7 != 0,
            )
        )
    docs = SalesDocument.objects.bulk_create(docs, batch_size=2000)
    SalesLine.objects.bulk_create(
        [
            SalesLine(
                document=d,
                variant=None if (i + k) % 97 == 0 else variants[(i * 3 + k) % REPORT_VARIANTS],
                sku_snapshot=f"R-{(i * 3 + k) % REPORT_VARIANTS:04d}",
                description_snapshot="Producto",
                quantity=1 + k,
                unit_price=Decimal(5000),
                line_total=Decimal(5000 * (1 + k)),
                channel_fee=Decimal(600) if d.channel.code == "mercadolibre" else None,
            )
            for i, d in enumerate(docs)
            for k in range(2)
        ],
        batch_size=5000,
    )
    methods = [Shipment.Method.ME_FLEX, Shipment.Method.ME_COLECTA, Shipment.Method.ME_FULL]
    Shipment.objects.bulk_create(
        [
            Shipment(
                document=d,
                method=methods[i % 3] if d.channel.code == "mercadolibre" else Shipment.Method.CARRIER,
                dispatch_deadline=d.issued_at + timedelta(hours=24)
                if d.channel.code == "mercadolibre"
                else None,
                seller_cost=Decimal(1500) if d.channel.code == "mercadolibre" else None,
            )
            for i, d in enumerate(docs)
        ],
        batch_size=5000,
    )
    Payment.objects.bulk_create(
        [
            Payment(document=d, method="cash", amount=d.total, status=Payment.Status.CONFIRMED)
            for d in docs
            if d.channel.code == "manual" and d.number % 5
        ],
        batch_size=5000,
    )
    ml = next(c for c in channels if c.code == "mercadolibre")
    Question.objects.bulk_create(
        [
            Question(
                channel=ml,
                external_id=f"rq{i}",
                text="?",
                asked_at=now - timedelta(hours=i % 8000 + 5),
                answered_at=now - timedelta(hours=i % 8000) if i % 10 else None,
                status="answered" if i % 10 else "unanswered",
            )
            for i in range(3000)
        ]
    )
    warehouse = Warehouse.objects.get(is_default=True)
    movements = []
    for v in variants:
        level = 5
        for k in range(50):  # sube y baja; cada tanto queda en 0
            new = 0 if k % 9 == 4 else rnd.randint(1, 10)
            movements.append(
                StockMovement(
                    variant=v,
                    warehouse=warehouse,
                    kind=StockMovement.Kind.SYNC_ADJUSTMENT,
                    quantity=new - level,
                    source=StockMovement.Source.CONTABILIUM_SYNC,
                    on_hand_after=new,
                )
            )
            level = new
    created = StockMovement.objects.bulk_create(movements, batch_size=5000)
    with connection.cursor() as cursor:  # created_at es auto_now_add: se reparte en el año
        cursor.execute(
            "UPDATE inventory_stockmovement SET created_at = %s - (%s - id) * interval '26 minutes'",
            [now, created[-1].pk],
        )
    StockLevel.objects.bulk_create([StockLevel(variant=v, warehouse=warehouse, on_hand=3) for v in variants])


def test_reports_volume_under_two_seconds(admin_client):
    """M7 · T9: con 12 meses (~10.000 pedidos y 20.000 líneas) cada pantalla y Excel tarda menos de 2 s."""
    _report_volume()
    today = timezone.localdate()
    year = f"?periodo=rango&desde={today - timedelta(days=364)}&hasta={today}"
    admin_client.get(reverse("core:home"))  # calienta sesión y permisos
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    timings = {}
    for (name, extra), budget in REPORT_SCREENS.items():
        url = reverse(name) + year + extra
        start = time.perf_counter()
        with CaptureQueriesContext(connection) as ctx:
            response = admin_client.get(url)
        elapsed = time.perf_counter() - start
        timings[f"{name}{extra}"] = f"{elapsed:.2f} s / {len(ctx)} consultas"
        assert response.status_code == 200
        assert elapsed < 2.0, f"{name}{extra} tardó {elapsed:.2f} s"
        assert len(ctx) <= budget, f"{name}{extra}: {len(ctx)} consultas (presupuesto {budget})"
    kpis = admin_client.get(reverse("reports:summary") + year).context["kpis"]["by_key"]
    assert kpis["orders"]["value"] == REPORT_ORDERS - REPORT_ORDERS // 10  # sin los cancelados
    print("\nTiempos M7: " + "; ".join(f"{k} {v}" for k, v in timings.items()))


def test_reports_excel_50000_rows_under_ten_seconds():
    """M7 · T9: un Excel de 50.000 filas (con formato de pesos) se genera en menos de 10 s."""
    from openpyxl import load_workbook

    from apps.reports.excel import Sheet, build

    money = [Decimal("12345.67"), Decimal("11000.10"), Decimal("4500.00")]
    rows = [
        [f"SKU-{i:05d}", "Producto de prueba", "M", "Negro", i % 7 + 1, i % 5 + 1, *money]
        for i in range(50_000)
    ]
    start = time.perf_counter()
    content = build(
        [
            Sheet(
                "Ventas",
                ["SKU", "Producto", "Talle", "Color", "Unidades", "Pedidos", "Bruto", "Neto", "Precio"],
                rows,
                totals=["Total", "", "", "", 0, 0, *money],
                money_columns={6, 7, 8},
                note="Prueba de volumen",
            )
        ]
    )
    elapsed = time.perf_counter() - start
    print(f"\nExcel 50.000 filas: {elapsed:.2f} s, {len(content) / 1e6:.1f} MB")
    assert elapsed < 10.0
    ws = load_workbook(io.BytesIO(content), read_only=True)["Ventas"]
    assert ws.max_row == 50_003  # nota + encabezados + filas + totales
