"""Pantalla de bloqueo por intentos fallidos (django-axes): el mismo bloqueo para el panel y la
tienda, cada uno con su plantilla en castellano."""

from django.conf import settings
from django.shortcuts import render

from .middleware import is_store_host


def is_store_request(request) -> bool:
    if is_store_host(request):
        return True
    prefix = "/" + settings.WHOLESALE_PATH.strip("/") + "/"
    return request.path.startswith(prefix)


def lockout_response(request, original_response=None, credentials=None):
    template = "store/lockout.html" if is_store_request(request) else settings.AXES_LOCKOUT_TEMPLATE
    status = getattr(settings, "AXES_HTTP_RESPONSE_CODE", 429)
    return render(request, template, {"failure_limit": settings.AXES_FAILURE_LIMIT}, status=status)
