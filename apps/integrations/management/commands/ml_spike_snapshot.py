import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations.adapters.mercadolibre.client import MLClient

FIELDS = [
    "title",
    "status",
    "attributes",
    "pictures",
    "variations",
    "price",
    "available_quantity",
    "last_updated",
]


class Command(BaseCommand):
    help = "Spike DDEV-23: guarda una foto de una publicación de ML para comparar antes/después de una sync de Contabilium."

    def add_arguments(self, parser):
        parser.add_argument("item_id")

    def handle(self, item_id, **options):
        client = MLClient()
        item = client.get(f"/items/{item_id}")
        try:
            description = client.get(f"/items/{item_id}/description")
        except Exception:  # noqa: BLE001
            description = {}
        snapshot = {k: item.get(k) for k in FIELDS}
        snapshot["description"] = description.get("plain_text")
        out_dir = Path(settings.BASE_DIR) / "local" / "spikes"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{item_id}-{timezone.now():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"Foto guardada en {path}")
