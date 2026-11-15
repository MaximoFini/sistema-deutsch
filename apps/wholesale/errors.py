"""Páginas de error con la marca de la tienda cuando el pedido es de la tienda (ruta o dominio propio)."""

from django.shortcuts import render
from django.views import defaults

from .lockout import is_store_request


def page_not_found(request, exception=None):
    if is_store_request(request):
        return render(request, "store/404.html", status=404)
    return defaults.page_not_found(request, exception)


def permission_denied(request, exception=None):
    if is_store_request(request):
        return render(request, "store/403.html", status=403)
    return defaults.permission_denied(request, exception)
