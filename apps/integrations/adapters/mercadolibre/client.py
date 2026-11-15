"""Cliente de la API de Mercado Libre: token vigente, reintento único ante 401 y paginación."""

from apps.integrations.http import ChannelClient, ChannelHTTPError

from . import auth

API_BASE = "https://api.mercadolibre.com"
CHANNEL = auth.CHANNEL
MAX_PAGES = 400
QUICK_TIMEOUT = 4.0


class MLClient:
    def __init__(self, *, sleep=None, timeout: float | None = None, max_retries: int | None = None):
        """`timeout`/`max_retries` vacíos = los de ChannelClient (20 s y 3 reintentos)."""
        kwargs = {"sleep": sleep} if sleep is not None else {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        self.http = ChannelClient(
            CHANNEL, base_url=API_BASE, headers={"Accept": "application/json"}, **kwargs
        )
        self._user_id = None

    @classmethod
    def quick(cls, **kwargs) -> "MLClient":
        """Cliente para lecturas "de adorno" dentro de una pantalla: 4 s y sin reintentos."""
        return cls(timeout=QUICK_TIMEOUT, max_retries=0, **kwargs)

    @property
    def user_id(self) -> str:
        if self._user_id is None:
            self._user_id = auth.get_credentials()["user_id"]
        return self._user_id

    def request(self, method: str, path: str, **kwargs):
        token = auth.get_access_token()
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {token}"}
        try:
            return self.http.request(method, path, headers=headers, **kwargs)
        except ChannelHTTPError as exc:
            if exc.response is None or exc.response.status_code != 401:
                raise
        token = auth.force_refresh(token)  # una sola renovación y un solo reintento
        headers["Authorization"] = f"Bearer {token}"
        return self.http.request(method, path, headers=headers, **kwargs)

    def get(self, path: str, params: dict | None = None, headers: dict | None = None):
        return self.request("GET", path, params=params, headers=headers or {}).json()

    def get_raw(self, path: str, params: dict | None = None):
        return self.request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None, params: dict | None = None, files=None):
        kwargs = {"params": params}
        if files is not None:
            kwargs["files"] = files
        else:
            kwargs["json"] = json
        return self.request("POST", path, **kwargs).json()

    def put(self, path: str, json: dict):
        return self.request("PUT", path, json=json).json()

    def search_offset(
        self, path: str, params: dict | None = None, results_key: str = "results", limit: int = 50
    ):
        """Itera un listado paginado por offset/limit (paging.total)."""
        offset = 0
        for _ in range(MAX_PAGES):
            data = self.get(path, params={**(params or {}), "offset": offset, "limit": limit})
            items = data.get(results_key) or []
            yield from items
            total = (data.get("paging") or {}).get("total", 0)
            offset += len(items)
            if not items or offset >= total:
                return
        raise RuntimeError(f"Paginación de {path} superó {MAX_PAGES} páginas.")

    def scan_item_ids(self, seller_id: str):
        """IDs de todas las publicaciones con search_type=scan (sin el tope de 1000 del offset)."""
        params = {"search_type": "scan", "limit": 100}
        for _ in range(MAX_PAGES):
            data = self.get(f"/users/{seller_id}/items/search", params=params)
            ids = data.get("results") or []
            yield from ids
            scroll = data.get("scroll_id")
            if not ids or not scroll:
                return
            params = {"search_type": "scan", "limit": 100, "scroll_id": scroll}
        raise RuntimeError("Scan de publicaciones superó el máximo de páginas.")
