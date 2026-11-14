"""Inicialización de Sentry con enmascarado de datos sensibles (US-8)."""

from .logging import mask_mapping, mask_text


def scrub_event(event: dict, hint=None) -> dict:
    request = event.get("request")
    if request:
        for key in ("headers", "data", "cookies", "query_string"):
            value = request.get(key)
            if isinstance(value, dict | list):
                request[key] = mask_mapping(value)
            elif isinstance(value, str):
                request[key] = mask_text(value)
    for exc in (event.get("exception") or {}).get("values", []):
        if isinstance(exc.get("value"), str):
            exc["value"] = mask_text(exc["value"])
        for frame in (exc.get("stacktrace") or {}).get("frames", []):
            if isinstance(frame.get("vars"), dict):
                frame["vars"] = mask_mapping(frame["vars"])
    if "extra" in event:
        event["extra"] = mask_mapping(event["extra"])
    for crumb in (event.get("breadcrumbs") or {}).get("values", []):
        if isinstance(crumb.get("message"), str):
            crumb["message"] = mask_text(crumb["message"])
    return event


def init(dsn: str, environment: str) -> None:
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        send_default_pii=False,
        traces_sample_rate=0.0,
        before_send=scrub_event,
    )
