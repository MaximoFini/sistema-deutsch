"""Mensajes postventa de Mercado Libre: guardar, conciliar y enviar."""

import logging

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.conversations.models import Message
from apps.integrations.http import ChannelHTTPError
from apps.integrations.models import Channel, ExternalRef
from apps.sales.models import SalesDocument

from .common import dt, error_body, last_segment

logger = logging.getLogger(__name__)
CHANNEL = "mercadolibre"
MAX_LENGTH = 350
TAG = {"tag": "post_sale"}


class MessagingBlocked(Exception):
    pass


def _document_for(thread_id: str) -> SalesDocument | None:
    for key in (f"pack:{thread_id}", f"order:{thread_id}"):
        ref = ExternalRef.objects.filter(
            channel__code=CHANNEL, content_type__model="salesdocument", external_id=key
        ).first()
        if ref:
            return SalesDocument.objects.filter(pk=ref.object_id).first()
    return None


def _thread_id(m: dict) -> str:
    for res in m.get("message_resources") or []:
        if res.get("name") in ("packs", "orders"):
            return str(res.get("id"))
    return str(m.get("resource_id") or "")


def _text(m: dict) -> str:
    text = m.get("text")
    if isinstance(text, dict):
        return text.get("plain") or ""
    return text or ""


def upsert_message(m: dict, seller_id: str) -> Message:
    thread = _thread_id(m)
    sender = str((m.get("from") or {}).get("user_id") or "")
    dates = m.get("message_date") or {}
    message, _ = Message.objects.update_or_create(
        channel=Channel.objects.get(code=CHANNEL),
        external_id=str(m["id"]),
        defaults={
            "thread_key": thread,
            "document": _document_for(thread) if thread else None,
            "direction": Message.Direction.OUT if sender == str(seller_id) else Message.Direction.IN,
            "text": _text(m),
            "attachments": [
                {
                    "filename": a.get("filename"),
                    "original_filename": a.get("original_filename"),
                    "type": a.get("type"),
                }
                for a in m.get("message_attachments") or []
            ],
            "sent_at": dt(dates.get("created") or m.get("date_created")),
        },
    )
    return message


def refresh_message(client, message_id: str) -> list[Message]:
    data = client.get(f"/messages/{message_id}", params=TAG)
    items = data.get("messages", [data]) if isinstance(data, dict) else data
    return [upsert_message(m, client.user_id) for m in items if m.get("id")]


def sync_thread(client, pack_id: str) -> int:
    data = client.get(
        f"/messages/packs/{pack_id}/sellers/{client.user_id}", params={**TAG, "mark_as_read": "false"}
    )
    count = 0
    for m in data.get("messages") or []:
        upsert_message(m, client.user_id)
        count += 1
    return count


def sync_unread(client) -> dict:
    stats = {"threads": 0, "messages": 0, "errors": []}
    data = client.get("/messages/unread", params={"role": "seller", **TAG})
    for row in data.get("results") or []:
        resource = row.get("resource") or ""  # "/packs/{id}/sellers/{seller}"
        parts = [p for p in resource.split("/") if p]
        pack_id = parts[1] if len(parts) > 1 and parts[0] in ("packs", "orders") else last_segment(resource)
        try:
            stats["messages"] += sync_thread(client, pack_id)
            stats["threads"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append({"id": pack_id, "error": f"{type(exc).__name__}: {exc}"[:300]})
    return stats


def _thread_and_buyer(document: SalesDocument) -> tuple[str, str]:
    refs = ExternalRef.objects.filter(
        channel__code=CHANNEL, content_type__model="salesdocument", object_id=document.pk
    )
    pack = next((r.external_id.split(":", 1)[1] for r in refs if r.external_id.startswith("pack:")), None)
    order = next((r.external_id.split(":", 1)[1] for r in refs if r.external_id.startswith("order:")), None)
    buyer = (
        ExternalRef.objects.filter(
            channel__code=CHANNEL, content_type__model="customer", object_id=document.customer_id
        ).first()
        if document.customer_id
        else None
    )
    if not (pack or order) or buyer is None:
        raise MessagingBlocked("El pedido no tiene una conversación de Mercado Libre asociada.")
    return pack or order, buyer.external_id


def send(client, document: SalesDocument, text: str, *, user, attachments=()) -> Message:
    if not user.has_perm("conversations.send_message"):
        raise PermissionDenied
    text = (text or "").strip()
    if not text:
        raise MessagingBlocked("El mensaje está vacío.")
    if len(text) > MAX_LENGTH:
        raise MessagingBlocked(f"Mercado Libre permite hasta {MAX_LENGTH} caracteres (tiene {len(text)}).")
    thread, buyer_id = _thread_and_buyer(document)
    try:
        attachment_ids = []
        for filename, content in attachments:
            uploaded = client.post("/messages/attachments", params=TAG, files={"file": (filename, content)})
            attachment_ids.append(uploaded.get("id"))
        body = {"from": {"user_id": int(client.user_id)}, "to": {"user_id": int(buyer_id)}, "text": text}
        if attachment_ids:
            body["attachments"] = attachment_ids
        result = client.post(f"/messages/packs/{thread}/sellers/{client.user_id}", json=body, params=TAG)
    except ChannelHTTPError as exc:
        data = error_body(exc)
        reason = data.get("message") or data.get("error") or ""
        raise MessagingBlocked(
            f"Mercado Libre no permite enviar este mensaje{': ' + reason if reason else ''}."
        ) from exc
    with transaction.atomic():
        message = Message.objects.create(
            channel=Channel.objects.get(code=CHANNEL),
            external_id=str(result.get("id") or f"local-{timezone.now().timestamp()}"),
            document=document,
            thread_key=thread,
            direction=Message.Direction.OUT,
            text=text,
            attachments=[{"filename": f} for f, _ in attachments],
            sent_at=timezone.now(),
            sent_by=user,
        )
        audit.record(user, "ml.message_sent", document, after={"text": text, "attachments": len(attachments)})
    return message
