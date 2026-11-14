"""Adaptador de Tiendanube (M1). Al importarse se registra en el registry y carga sus tareas."""

from apps.integrations import registry

from .adapter import TiendanubeAdapter

adapter = registry.register(TiendanubeAdapter())

from . import fulfillment, tasks  # noqa: E402,F401  (registra las tareas en Procrastinate)
