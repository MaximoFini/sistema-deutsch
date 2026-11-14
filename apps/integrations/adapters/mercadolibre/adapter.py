"""Adaptador de Mercado Libre para el framework de integraciones (M0)."""

import json
import logging

from django.conf import settings
from django.utils import timezone

from apps.integrations import credentials

from . import claims, listings, messages, orders, questions, shipments
from .client import CHANNEL, MLClient
from .common import last_segment

logger = logging.getLogger(__name__)
TOPICS = ["orders_v2", "shipments", "questions", "messages", "claims", "items"]


class MercadoLibreAdapter:
    code = CHANNEL
    own_schedule = True

    def __init__(self):
        self.handlers = {
            "orders_v2": self.handle_order,
            "shipments": self.handle_shipment,
            "questions": self.handle_question,
            "messages": self.handle_message,
            "claims": self.handle_claim,
            "items": self.handle_item,
        }

    def client(self) -> MLClient:
        return MLClient()

    # ── Notificaciones ──
    def verify_webhook(self, request) -> bool:
        """ML no firma: se aceptan solo las de nuestra app y nuestro vendedor. El dato real se lee
        siempre de la API con nuestro token, así que una notificación falsa no puede inyectar datos."""
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return False
        if str(payload.get("application_id")) != str(settings.ML_APP_ID):
            return False
        try:
            seller = credentials.get(CHANNEL)["user_id"]
        except credentials.CredentialsMissing:
            return False
        return str(payload.get("user_id")) == str(seller)

    def topic(self, payload: dict, headers: dict) -> str:
        return payload.get("topic", "unknown")

    def dedupe_key(self, payload: dict, headers: dict) -> str:
        minute = timezone.now().strftime("%Y%m%d%H%M")
        return f"{payload.get('topic')}:{payload.get('resource')}:{minute}"

    # ── Handlers: cada notificación = "volvé a leer el recurso" ──
    def handle_order(self, event):
        orders.refresh(self.client(), last_segment(event.payload["resource"]))

    def handle_shipment(self, event):
        shipments.refresh(self.client(), last_segment(event.payload["resource"]))

    def handle_question(self, event):
        questions.refresh(self.client(), last_segment(event.payload["resource"]))

    def handle_message(self, event):
        messages.refresh_message(self.client(), last_segment(event.payload["resource"]))

    def handle_claim(self, event):
        claims.refresh(self.client(), last_segment(event.payload["resource"]))

    def handle_item(self, event):
        listings.refresh(self.client(), last_segment(event.payload["resource"]))

    def reconcile(self, since):
        return orders.sync_orders(self.client(), updated_since=since)

    # ── Regla de oro: construida pero bloqueada ──
    def write_stock(self, item_id: str, variation_id: str | None, quantity: int):
        from apps.integrations.guard import ensure_write_allowed

        ensure_write_allowed(CHANNEL, "stock", {"item": item_id, "variation": variation_id})
        body = (
            {"variations": [{"id": int(variation_id), "available_quantity": quantity}]}
            if variation_id
            else {"available_quantity": quantity}
        )
        self.client().put(f"/items/{item_id}", json=body)

    def write_price(self, item_id: str, price):
        from apps.integrations.guard import ensure_write_allowed

        ensure_write_allowed(CHANNEL, "price", {"item": item_id})
        self.client().put(f"/items/{item_id}", json={"price": float(price)})
