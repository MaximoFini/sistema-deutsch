"""Adaptador de prueba: ejercita todo el framework sin tocar APIs reales. Solo para tests."""

from apps.catalog.models import Product


class FakeAdapter:
    code = "fake"

    def __init__(self):
        self.fail_times = 0  # cuántas veces fallar antes de procesar bien
        self.calls = 0
        self.reconcile_calls: list = []
        self.handlers = {"product.updated": self.handle_product}

    def verify_webhook(self, request) -> bool:
        return request.headers.get("X-Fake-Signature") == "ok"

    def dedupe_key(self, payload, headers) -> str:
        return f"{payload['id']}:{payload.get('updated_at', '')}"

    def topic(self, payload, headers) -> str:
        return payload.get("event", "unknown")

    def handle_product(self, event):
        from apps.integrations.services import find_by_external, link_external

        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("falla simulada")
        data = event.payload
        product = find_by_external("fake", Product, data["id"])
        if product is None:
            product = Product.objects.create(name=data["name"])
        else:
            product.name = data["name"]
            product.save(update_fields=["name", "updated_at"])
        link_external("fake", product, data["id"])

    def reconcile(self, since):
        self.reconcile_calls.append(since)
        return {"checked": 0}

    def write_stock(self, sku: str, quantity: int, http=None):
        from apps.integrations.guard import ensure_write_allowed

        ensure_write_allowed(self.code, "stock", {"sku": sku})
        if http is not None:
            http.put(f"/stock/{sku}", json={"quantity": quantity})
