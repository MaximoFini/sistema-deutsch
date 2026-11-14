"""Único punto de escritura de stock (principio ERP n.º 3): todo cambio deja un movimiento."""

from decimal import Decimal

from django.db import transaction

from .models import StockLevel, StockMovement, Warehouse


def default_warehouse() -> Warehouse:
    return Warehouse.objects.get(is_default=True)


@transaction.atomic
def apply_sync_level(variant, warehouse, quantity, source=StockMovement.Source.CONTABILIUM_SYNC, note=""):
    """Iguala el stock físico al valor informado por la fuente de verdad (hoy Contabilium).

    Registra un movimiento `sync_adjustment` por la diferencia. Si no hay diferencia, no hace nada.
    Devuelve el movimiento creado o None.
    """
    quantity = Decimal(quantity)
    level, _ = StockLevel.objects.select_for_update().get_or_create(variant=variant, warehouse=warehouse)
    delta = quantity - level.on_hand
    if delta == 0:
        return None
    movement = StockMovement.objects.create(
        variant=variant,
        warehouse=warehouse,
        kind=StockMovement.Kind.SYNC_ADJUSTMENT,
        quantity=delta,
        source=source,
        note=note,
    )
    level.on_hand = quantity
    level.save(update_fields=["on_hand", "updated_at"])
    return movement


@transaction.atomic
def change_reserved(variant, warehouse, delta, reference=None, user=None, note=""):
    """Reserva (delta > 0) o libera (delta < 0) stock, p. ej. pedidos mayoristas sin pagar (M8)."""
    delta = Decimal(delta)
    level, _ = StockLevel.objects.select_for_update().get_or_create(variant=variant, warehouse=warehouse)
    movement = StockMovement(
        variant=variant,
        warehouse=warehouse,
        kind=StockMovement.Kind.RESERVATION if delta > 0 else StockMovement.Kind.RELEASE,
        quantity=delta,
        affects="reserved",
        source=StockMovement.Source.SYSTEM,
        created_by=user,
        note=note,
    )
    if reference is not None:
        movement.reference = reference
    movement.save()
    level.reserved = max(Decimal(0), level.reserved + delta)
    level.save(update_fields=["reserved", "updated_at"])
    return movement
