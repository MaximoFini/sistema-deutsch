"""Cliente de la API de Tiendanube (versión 2025-03) sobre el ChannelClient de M0."""

from django.conf import settings

from apps.integrations import credentials
from apps.integrations.http import ChannelClient, ChannelHTTPError

CHANNEL = "tiendanube"
API_BASE = "https://api.tiendanube.com"
MAX_PAGES = 500  # 500 × 200 = 100.000 ítems; TN limita los listados de pedidos a 10.000


def parse_next_link(link_header: str | None) -> str | None:
    """Devuelve la URL rel="next" del header Link, o None."""
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.split(";")
        if len(section) < 2:
            continue
        url = section[0].strip().strip("<>")
        if any(s.strip() == 'rel="next"' for s in section[1:]):
            return url
    return None


class TiendanubeClient:
    def __init__(self, access_token: str, store_id: str, *, sleep=None, transport=None):
        self.store_id = str(store_id)
        kwargs = {"transport": transport}
        if sleep is not None:
            kwargs["sleep"] = sleep
        self.http = ChannelClient(
            CHANNEL,
            base_url=f"{API_BASE}/{settings.TN_API_VERSION}/{self.store_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": settings.TN_USER_AGENT,
                "Content-Type": "application/json; charset=utf-8",
            },
            **kwargs,
        )

    @classmethod
    def from_credentials(cls, **kwargs) -> "TiendanubeClient":
        data = credentials.get(CHANNEL)
        return cls(data["access_token"], data["store_id"], **kwargs)

    def get(self, path: str, params: dict | None = None):
        return self.http.get(path, params=params).json()

    def get_all(self, path: str, params: dict | None = None):
        """Itera todos los resultados de un listado, siguiendo el header Link."""
        params = {"per_page": 200, **(params or {})}
        try:
            response = self.http.get(path, params=params)
        except ChannelHTTPError as exc:
            # Tiendanube responde 404 "Last page is 0" cuando el listado no tiene resultados: es una lista vacía.
            if (
                exc.response is not None
                and exc.response.status_code == 404
                and "Last page" in exc.response.text
            ):
                return
            raise
        for _ in range(MAX_PAGES):
            yield from response.json()
            next_url = parse_next_link(response.headers.get("Link"))
            if not next_url:
                return
            response = self.http.get(next_url)
        raise RuntimeError(f"Paginación de {path} superó {MAX_PAGES} páginas: se corta para evitar un bucle.")

    def post(self, path: str, json: dict):
        return self.http.post(path, json=json).json()

    def patch(self, path: str, json: dict):
        return self.http.request("PATCH", path, json=json).json()

    # Endpoints usados
    def get_product(self, product_id):
        return self.get(f"/products/{product_id}")

    def get_order(self, order_id):
        return self.get(f"/orders/{order_id}")

    def get_store(self):
        return self.get("/store")
