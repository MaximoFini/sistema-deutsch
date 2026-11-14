"""Registro de adaptadores de canal. Cada adaptador (M1 Tiendanube, M2 Mercado Libre,
M8 Contabilium) implementa `ChannelAdapter` y se registra con `register`."""

from collections.abc import Callable
from datetime import datetime
from importlib import import_module
from typing import Protocol

from django.http import HttpRequest

_ADAPTERS: dict[str, "ChannelAdapter"] = {}

ADAPTER_MODULES = [
    "apps.integrations.adapters.tiendanube",  # M1
    # "apps.integrations.adapters.mercadolibre", # M2
    # "apps.integrations.adapters.contabilium",  # M8
]


class ChannelAdapter(Protocol):
    code: str
    handlers: dict[str, Callable]  # topic -> handler(event)

    def verify_webhook(self, request: HttpRequest) -> bool: ...

    def dedupe_key(self, payload: dict, headers: dict) -> str: ...

    def topic(self, payload: dict, headers: dict) -> str: ...

    def reconcile(self, since: datetime | None) -> dict: ...


def register(adapter: "ChannelAdapter") -> "ChannelAdapter":
    _ADAPTERS[adapter.code] = adapter
    return adapter


def unregister(code: str) -> None:
    _ADAPTERS.pop(code, None)


def get(code: str) -> "ChannelAdapter | None":
    return _ADAPTERS.get(code)


def all_adapters() -> list["ChannelAdapter"]:
    return list(_ADAPTERS.values())


def autodiscover():
    for module in ADAPTER_MODULES:
        import_module(module)
