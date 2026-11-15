"""Dominio propio para la tienda (etapa B): `WHOLESALE_HOST` sirve la tienda en la raíz."""

from django.conf import settings

HOST_URLCONF = "apps.wholesale.host_urls"


def is_store_host(request) -> bool:
    host = (settings.WHOLESALE_HOST or "").strip().lower()
    if not host:
        return False
    return request.get_host().split(":")[0].lower() == host


class WholesaleHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_store_host(request):
            request.urlconf = HOST_URLCONF
        return self.get_response(request)
