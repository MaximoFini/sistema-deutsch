"""Utilidades de base de datos."""

import logging

from django.db import connection

logger = logging.getLogger(__name__)

# Tablas que más cambian en una carga grande (catálogo, precios, stock, pedidos).
BULK_TABLES = (
    "catalog_product",
    "catalog_variant",
    "pricing_pricelistitem",
    "inventory_stocklevel",
    "inventory_stockmovement",
    "sales_salesdocument",
    "sales_salesline",
    "sales_shipment",
)


def refresh_statistics(tables=BULK_TABLES) -> None:
    """Actualiza las estadísticas de Postgres después de una carga grande.

    Sin esto, hasta que pase el autovacuum el planificador puede creer que las tablas siguen casi vacías y
    elegir planes que tardan minutos (se vio 208 s en el catálogo mayorista y 30–60 s en reportes).
    Nunca rompe la operación que lo llama.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE " + ", ".join(tables))
    except Exception:  # noqa: BLE001
        logger.warning("No se pudieron actualizar las estadísticas de la base", exc_info=True)
