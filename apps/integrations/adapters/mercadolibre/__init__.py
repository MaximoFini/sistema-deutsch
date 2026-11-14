"""Adaptador de Mercado Libre (M2). Al importarse se registra y carga sus tareas."""

from apps.integrations import registry

from .adapter import MercadoLibreAdapter

adapter = registry.register(MercadoLibreAdapter())

from . import tasks  # noqa: E402,F401  (registra las tareas en Procrastinate)
