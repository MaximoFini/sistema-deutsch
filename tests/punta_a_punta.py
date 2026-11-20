"""Ayudas de `tests/test_punta_a_punta.py` (M9 · DDEV-57): canales simulados, fixtures y control de avisos.

Todo es simulado: HTTP con respx (cualquier llamada que no esté declarada falla), email con locmem y la
cola de tareas en memoria. Ningún test de este módulo usa red real ni manda un email real.

Los fixtures que se importan desde acá (`malla`, `tn`, `ml`, `channel_calls`, `golden_rule`) llevan
`# noqa: F401` donde se importan: pytest los encuentra por nombre.
"""

import json
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import httpx
import pytest
import respx
from django.test import Client
from django.utils import timezone

from apps.alerts.models import Alert
from apps.catalog.models import Product, Variant
from apps.integrations import credentials
from apps.inventory.models import StockLevel
from apps.wholesale.models import OutboundEmail
from tests import ml_samples as S
from tests.test_mayorista import set_stock, set_wholesale

TN_API = "https://api.tiendanube.com/2025-03/8434848"
ML_API = "https://api.mercadolibre.com"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
# Cualquier ruta de escritura con estas palabras sería tocar productos, stock o precios en un canal.
CATALOG_WORDS = ("/products", "/variants", "/items", "/stock", "/price", "/prices")


def login(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


# ── Datos de catálogo ────────────────────────────────────────────────────────


@pytest.fixture
def malla(db):
    """Malla 2 talles × 2 colores: precio mayorista 10.000 neto y stock 5 por variante.

    Los SKU son los de las muestras de ML y Tiendanube (`BUZ-001-…`), así los pedidos simulados de los
    canales se vinculan a estas variantes.
    """
    product = Product.objects.create(
        name="Buzo Canguro Oversize",
        brand="Deutsch",
        categories=["Buzos"],
        images=[{"url": "https://cdn.test/buzo.jpg", "position": 1}],
    )
    variants = {}
    for size in ("M", "L"):
        v = Variant.objects.create(
            product=product, sku=f"BUZ-001-{size}-NEG", attributes={"Talle": size, "Color": "Negro"}
        )
        set_wholesale(v, Decimal("10000"))
        set_stock(v, 5)
        variants[size] = v
    other = Variant.objects.create(
        product=Product.objects.create(name="Gorra Silicona", categories=["Gorras"]),
        sku="GOR-010",
        attributes={"Talle": "Único"},
    )
    set_wholesale(other, Decimal("5000"))
    set_stock(other, 8)
    variants["GOR"] = other
    return product, variants


@pytest.fixture(autouse=True)
def clear_cache():
    """Las opciones de filtro del catálogo se guardan 5 minutos en caché: cada test arranca limpio."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def reserved(variant) -> Decimal:
    return StockLevel.objects.get(variant=variant).reserved


def on_hand(variant) -> Decimal:
    return StockLevel.objects.get(variant=variant).on_hand


# ── Control de avisos y emails ───────────────────────────────────────────────


def alert_codes() -> Counter:
    return Counter(Alert.objects.values_list("alert_type__code", flat=True))


def email_codes() -> Counter:
    return Counter(OutboundEmail.objects.values_list("template_code", flat=True))


def assert_only(*, alerts=None, emails=None):
    """Que los avisos y los emails de la cola sean EXACTAMENTE estos (por código). Atrapa los inesperados."""
    if alerts is not None:
        assert alert_codes() == Counter(alerts), f"avisos inesperados: {dict(alert_codes())}"
    if emails is not None:
        assert email_codes() == Counter(emails), f"emails inesperados: {dict(email_codes())}"


# ── Canales simulados ────────────────────────────────────────────────────────


@pytest.fixture
def golden_rule():
    """La regla de oro: si algo intenta escribir stock o precio en un canal, el test falla."""
    with mock.patch(
        "apps.integrations.guard.ensure_write_allowed", side_effect=AssertionError("escritura a un canal")
    ) as guard:
        yield guard
    assert not guard.called


@pytest.fixture
def tn(db):
    """Tiendanube conectado y simulado (respx). `tn.calls` trae todo lo que salió hacia Tiendanube."""
    credentials.save(
        "tiendanube",
        {
            "access_token": "TN-TOKEN-SECRETO",
            "store_id": "8434848",
            "scope": "read_products,write_orders,read_customers,write_fulfillment_orders",
        },
    )
    with respx.mock(base_url=TN_API, assert_all_called=False) as router:
        yield router


@pytest.fixture
def ml(db):
    """Mercado Libre conectado y simulado (respx)."""
    credentials.save(
        "mercadolibre",
        {
            "access_token": "ACCESS-1",
            "refresh_token": "REFRESH-1",
            "expires_at": (timezone.now() + timedelta(hours=5)).isoformat(),
            "user_id": S.SELLER,
            "scope": "offline_access read write",
        },
    )
    with respx.mock(base_url=ML_API, assert_all_called=False) as router:
        yield router


def stub_ml_order(router, *, logistic="self_service", order_id=2000001, shipment_id=40001, order=None):
    """Declara lo que ML contesta para un pedido y su envío."""
    router.get(f"/orders/{order_id}").mock(return_value=httpx.Response(200, json=order or S.order()))
    router.get(f"/shipments/{shipment_id}").mock(
        return_value=httpx.Response(200, json=S.shipment(shipment_id, order_id, logistic))
    )
    router.get(f"/shipments/{shipment_id}/sla").mock(
        return_value=httpx.Response(200, json={"expected_date": "2026-11-13T12:00:00.000-03:00"})
    )
    router.get(f"/orders/{order_id}/billing_info").mock(
        return_value=httpx.Response(200, json=S.billing("CF"))
    )


def ml_notify(client: Client, resource: str, topic: str = "orders_v2"):
    payload = {"resource": resource, "topic": topic, "application_id": 5555, "user_id": int(S.SELLER)}
    return client.post("/hooks/mercadolibre/", data=json.dumps(payload), content_type="application/json")


def run_pending_events(connector) -> int:
    """Corre los `process_event` que dejaron los webhooks (el worker, en memoria)."""
    from apps.integrations.tasks import process_event

    ran = 0
    for job in list(connector.jobs.values()):
        if job["task_name"].endswith("process_event") and job["status"] == "todo":
            job["status"] = "done"
            process_event(**job["args"])
            ran += 1
    return ran


def non_get_calls(router) -> list:
    """Todo lo que salió hacia un canal y no fue una lectura."""
    return [c for c in router.calls if c.request.method != "GET"]


def catalog_writes(router) -> list:
    """Escrituras hacia productos, stock o precios de un canal: tiene que ser siempre una lista vacía."""
    return [
        c
        for c in router.calls
        if c.request.method != "GET" and any(w in c.request.url.path for w in CATALOG_WORDS)
    ]
