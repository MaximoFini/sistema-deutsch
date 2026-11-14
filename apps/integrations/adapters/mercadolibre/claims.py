"""Reclamos y devoluciones de Mercado Libre."""

import logging

from apps.alerts import services as alerts
from apps.conversations.models import Claim
from apps.integrations.http import ChannelHTTPError
from apps.integrations.models import Channel

from . import orders
from .common import dt

logger = logging.getLogger(__name__)
CHANNEL = "mercadolibre"


def _due_and_action(claim: dict):
    dues = []
    for player in claim.get("players") or []:
        if player.get("role") in ("respondent", "seller") or player.get("type") == "seller":
            for action in player.get("available_actions") or []:
                dues.append(dt(action.get("due_date")))
    actions = [d for d in dues if d is not None]
    return (min(actions) if actions else None), bool(dues)


def _return(client, claim_id) -> tuple[str, dict]:
    try:
        data = client.get(f"/post-purchase/v2/claims/{claim_id}/returns")
    except ChannelHTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return "", {}
        raise
    shipping = (data.get("shipments") or [{}])[0] if data.get("shipments") else (data.get("shipping") or {})
    status = shipping.get("status") or data.get("status") or ""
    return status[:40], {"status": data.get("status"), "shipping": shipping}


def _reason_detail(c: dict) -> str:
    reason = c.get("reason")
    return (reason.get("detail") or "")[:255] if isinstance(reason, dict) else ""


def upsert_claim(client, c: dict) -> Claim:
    due, action_required = _due_and_action(c)
    order_id = str(c.get("resource_id") or "") if c.get("resource") in (None, "order") else ""
    return_status, return_data = ("", {})
    if "return" in (c.get("related_entities") or []):
        return_status, return_data = _return(client, c["id"])
    reason = c.get("reason_id") or ""
    claim, created = Claim.objects.update_or_create(
        channel=Channel.objects.get(code=CHANNEL),
        external_id=str(c["id"]),
        defaults={
            "document": orders.find_document(order_id) if order_id else None,
            "order_external_id": order_id,
            "claim_type": (c.get("type") or "")[:40],
            "stage": (c.get("stage") or "")[:40],
            "status": (c.get("status") or "")[:20],
            "reason": reason[:100],
            "reason_detail": _reason_detail(c),
            "action_required": action_required and c.get("status") == "opened",
            "due_date": due,
            "return_status": return_status,
            "return_data": return_data,
            "data": {"related_entities": c.get("related_entities"), "resolution": c.get("resolution")},
        },
    )
    if claim.action_required:
        alerts.emit(
            "ml.claim_opened",
            title=f"Reclamo de Mercado Libre en la venta {order_id or claim.external_id}",
            body=f"Motivo: {reason or 'sin detalle'}. Responder antes de {due:%d/%m %H:%M}."
            if due
            else f"Motivo: {reason or 'sin detalle'}.",
            link_url="/integraciones/",
            dedupe_key=f"claim:{claim.external_id}",
        )
    return claim


def refresh(client, claim_id) -> Claim:
    return upsert_claim(client, client.get(f"/post-purchase/v1/claims/{claim_id}"))


def sync_open(client) -> dict:
    stats = {"claims": 0, "errors": []}
    seen = set()
    for c in client.search_offset(
        "/post-purchase/v1/claims/search", {"status": "opened"}, results_key="data", limit=30
    ):
        try:
            upsert_claim(client, c)
            seen.add(str(c["id"]))
            stats["claims"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append({"id": c.get("id"), "error": f"{type(exc).__name__}: {exc}"[:300]})
    for claim in Claim.objects.filter(channel__code=CHANNEL, status="opened").exclude(external_id__in=seen):
        try:
            refresh(client, claim.external_id)
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append({"id": claim.external_id, "error": f"{type(exc).__name__}: {exc}"[:300]})
    return stats
