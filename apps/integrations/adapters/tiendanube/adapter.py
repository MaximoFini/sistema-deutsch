"""Adaptador de Tiendanube para el framework de integraciones (M0)."""

import base64
import hashlib
import hmac
import logging

from django.conf import settings
from django.utils import timezone

from . import catalog, orders
from .client import CHANNEL, TiendanubeClient

logger = logging.getLogger(__name__)

ORDER_EVENTS = [
    "order/created",
    "order/updated",
    "order/paid",
    "order/packed",
    "order/fulfilled",
    "order/cancelled",
    "order/edited",
    "order/voided",
]
PRODUCT_EVENTS = ["product/created", "product/updated", "product/deleted"]
WEBHOOK_EVENTS = [*ORDER_EVENTS, *PRODUCT_EVENTS, "app/uninstalled"]
HMAC_HEADER = "X-Linkedstore-Hmac-Sha256"


def compute_signatures(body: bytes) -> tuple[str, str]:
    digest = hmac.new(settings.TN_CLIENT_SECRET.encode(), body, hashlib.sha256).digest()
    return digest.hex(), base64.b64encode(digest).decode()


def signature_is_valid(body: bytes, signature: str | None) -> bool:
    """La doc muestra hex; aceptamos también base64 hasta confirmarlo con un webhook real."""
    if not signature or not settings.TN_CLIENT_SECRET:
        return False
    hex_sig, b64_sig = compute_signatures(body)
    return hmac.compare_digest(signature, hex_sig) or hmac.compare_digest(signature, b64_sig)


class TiendanubeAdapter:
    code = CHANNEL
    own_schedule = True  # tiene sus propias tareas periódicas (pedidos cada N min, catálogo diario)

    def __init__(self):
        self.handlers = {event: self.handle_order for event in ORDER_EVENTS}
        self.handlers.update(
            {
                "product/created": self.handle_product,
                "product/updated": self.handle_product,
                "product/deleted": self.handle_product_deleted,
                "app/uninstalled": self.handle_uninstalled,
            }
        )

    # ── Webhooks ──
    def verify_webhook(self, request) -> bool:
        return signature_is_valid(request.body, request.headers.get(HMAC_HEADER))

    def topic(self, payload: dict, headers: dict) -> str:
        return payload.get("event", "unknown")

    def dedupe_key(self, payload: dict, headers: dict) -> str:
        # El cuerpo solo trae {store_id, event, id}: dos cambios legítimos del mismo pedido son
        # idénticos. Agrupar por minuto colapsa reintentos y ráfagas sin perder cambios posteriores.
        minute = timezone.now().strftime("%Y%m%d%H%M")
        return f"{payload.get('event')}:{payload.get('id')}:{minute}"

    # ── Handlers (cada evento = "volvé a leer la entidad") ──
    def client(self) -> TiendanubeClient:
        return TiendanubeClient.from_credentials()

    def handle_order(self, event):
        orders.upsert_order(self.client().get_order(event.payload["id"]))

    def handle_product(self, event):
        from apps.integrations.http import ChannelHTTPError

        try:
            data = self.client().get_product(event.payload["id"])
        except ChannelHTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                catalog.deactivate_product(event.payload["id"])
                return
            raise
        catalog.upsert_product(data)

    def handle_product_deleted(self, event):
        catalog.deactivate_product(event.payload["id"])

    def handle_uninstalled(self, event):
        from .oauth import disconnect

        disconnect(reason="La app fue desinstalada desde Tiendanube.")

    # ── Conciliación por defecto (la que usa el framework): pedidos ──
    def reconcile(self, since):
        return orders.sync_orders(self.client(), updated_since=since)

    # ── Escritura de stock/precio: construida pero bloqueada (regla de oro) ──
    def write_stock(self, variant_external_id: str, product_external_id: str, quantity: int):
        from apps.integrations.guard import ensure_write_allowed

        ensure_write_allowed(CHANNEL, "stock", {"variant": variant_external_id})
        self.client().http.request(
            "PATCH",
            "/products/stock-price",
            json=[
                {
                    "id": int(product_external_id),
                    "variants": [{"id": int(variant_external_id), "inventory_levels": [{"stock": quantity}]}],
                }
            ],
        )

    def write_price(self, variant_external_id: str, product_external_id: str, price):
        from apps.integrations.guard import ensure_write_allowed

        ensure_write_allowed(CHANNEL, "price", {"variant": variant_external_id})
        self.client().http.request(
            "PATCH",
            "/products/stock-price",
            json=[
                {
                    "id": int(product_external_id),
                    "variants": [{"id": int(variant_external_id), "price": str(price)}],
                }
            ],
        )
