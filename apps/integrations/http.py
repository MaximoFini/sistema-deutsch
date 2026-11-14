"""Cliente HTTP común para las APIs de los canales: timeouts, reintentos ante 429/5xx,
límite de velocidad y logs sin secretos."""

import logging
import time

import httpx

from apps.core.logging import mask_text

from . import ratelimit

logger = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class ChannelHTTPError(Exception):
    def __init__(self, message, response: httpx.Response | None = None):
        super().__init__(message)
        self.response = response


class ChannelClient:
    def __init__(
        self,
        rate_key: str,
        base_url: str = "",
        headers: dict | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        sleep=time.sleep,
        transport: httpx.BaseTransport | None = None,
    ):
        self.rate_key = rate_key
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.sleep = sleep
        self._client = httpx.Client(
            base_url=base_url, headers=headers or {}, timeout=timeout, transport=transport
        )

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        attempt = 0
        while True:
            ratelimit.acquire(self.rate_key, sleep=self.sleep)
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise ChannelHTTPError(f"{method} {mask_text(url)}: {exc}") from exc
                self._wait(attempt, None)
                attempt += 1
                continue
            logger.info("%s %s -> %s", method, mask_text(str(response.request.url)), response.status_code)
            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                self._wait(attempt, response)
                attempt += 1
                continue
            if response.is_error:
                raise ChannelHTTPError(
                    f"{method} {mask_text(url)} respondió {response.status_code}", response=response
                )
            return response

    def _wait(self, attempt: int, response: httpx.Response | None):
        retry_after = response.headers.get("Retry-After") if response is not None else None
        try:
            wait = float(retry_after) if retry_after else self.backoff_base * (2**attempt)
        except ValueError:
            wait = self.backoff_base * (2**attempt)
        self.sleep(min(wait, 60.0))

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def close(self):
        self._client.close()
