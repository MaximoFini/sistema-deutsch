"""Token bucket en Postgres, correcto con varios workers en paralelo."""

import time

from django.db import transaction
from django.utils import timezone

from .models import RateLimitBucket

DEFAULT_LIMITS = {
    # key: (capacidad, recarga por segundo). Ajustar según la documentación de cada API.
    "tiendanube": (40, 2.0),
    "mercadolibre": (50, 5.0),
    "contabilium": (10, 1.0),
}


def try_acquire(key: str, tokens: float = 1.0) -> float:
    """Intenta consumir `tokens`. Devuelve 0 si pudo, o los segundos a esperar si no."""
    capacity, refill = DEFAULT_LIMITS.get(key, (10, 1.0))
    now = timezone.now()
    with transaction.atomic():
        bucket, _ = RateLimitBucket.objects.select_for_update().get_or_create(
            key=key,
            defaults={
                "capacity": capacity,
                "refill_per_second": refill,
                "tokens": capacity,
                "updated_at": now,
            },
        )
        elapsed = max(0.0, (now - bucket.updated_at).total_seconds())
        bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_per_second)
        bucket.updated_at = now
        if bucket.tokens >= tokens:
            bucket.tokens -= tokens
            bucket.save(update_fields=["tokens", "updated_at"])
            return 0.0
        bucket.save(update_fields=["tokens", "updated_at"])
        return (tokens - bucket.tokens) / bucket.refill_per_second


def acquire(key: str, tokens: float = 1.0, sleep=time.sleep, max_wait: float = 60.0) -> None:
    waited = 0.0
    while (wait := try_acquire(key, tokens)) > 0:
        if waited + wait > max_wait:
            raise TimeoutError(f"Límite de velocidad de {key}: espera mayor a {max_wait}s")
        sleep(wait)
        waited += wait
