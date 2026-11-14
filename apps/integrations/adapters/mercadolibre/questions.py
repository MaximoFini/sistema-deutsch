"""Preguntas de Mercado Libre: guardar, conciliar y responder."""

import logging

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.catalog.models import Listing
from apps.conversations.models import Question
from apps.integrations.http import ChannelHTTPError
from apps.integrations.models import Channel

from .common import dt, error_body

logger = logging.getLogger(__name__)
CHANNEL = "mercadolibre"
STATUS = {
    "UNANSWERED": Question.Status.UNANSWERED,
    "ANSWERED": Question.Status.ANSWERED,
    "CLOSED_UNANSWERED": Question.Status.CLOSED,
    "UNDER_REVIEW": Question.Status.UNANSWERED,
    "BANNED": Question.Status.BANNED,
    "DELETED": Question.Status.DELETED,
    "DISABLED": Question.Status.CLOSED,
}


class AnswerRejected(Exception):
    def __init__(self, message: str, status: str):
        super().__init__(message)
        self.status = status


def upsert_question(q: dict) -> Question:
    channel = Channel.objects.get(code=CHANNEL)
    item_id = str(q.get("item_id") or "")
    answer = q.get("answer") or {}
    defaults = {
        "text": q.get("text") or "",
        "item_external_id": item_id,
        "listing": Listing.objects.filter(channel=channel, external_id=item_id).first() if item_id else None,
        "asker_nickname": ((q.get("from") or {}).get("nickname") or "")[:100],
        "asked_at": dt(q.get("date_created")),
        "status": STATUS.get(q.get("status"), Question.Status.UNANSWERED),
    }
    if answer.get("text"):
        defaults["answer_text"] = answer["text"]
        defaults["answered_at"] = dt(answer.get("date_created"))
    question, created = Question.objects.get_or_create(
        channel=channel, external_id=str(q["id"]), defaults=defaults
    )
    if not created:
        if question.status == Question.Status.ERROR and defaults["status"] == Question.Status.UNANSWERED:
            defaults.pop("status")  # conserva el error local hasta que alguien reintente
        for key, value in defaults.items():
            setattr(question, key, value)
        question.save()
    return question


def refresh(client, question_id) -> Question:
    return upsert_question(client.get(f"/questions/{question_id}", params={"api_version": 4}))


def sync_unanswered(client) -> dict:
    stats = {"questions": 0, "errors": []}
    seen = set()
    params = {"seller_id": client.user_id, "status": "UNANSWERED", "api_version": 4}
    for q in client.search_offset("/questions/search", params, results_key="questions"):
        try:
            upsert_question(q)
            seen.add(str(q["id"]))
            stats["questions"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append({"id": q.get("id"), "error": f"{type(exc).__name__}: {exc}"[:300]})
    # Las que teníamos sin responder y ya no aparecen: se respondieron o borraron en ML.
    stale = Question.objects.filter(channel__code=CHANNEL, status=Question.Status.UNANSWERED).exclude(
        external_id__in=seen
    )
    for question in stale:
        try:
            refresh(client, question.external_id)
        except ChannelHTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                question.status = Question.Status.DELETED
                question.save(update_fields=["status", "updated_at"])
    return stats


def _rejection(exc: ChannelHTTPError) -> tuple[str, str]:
    body = error_body(exc)
    text = f"{body.get('error', '')} {body.get('message', '')} {body.get('cause', '')}".lower()
    if (
        "deleted" in text
        or "not_found" in text
        or (exc.response is not None and exc.response.status_code == 404)
    ):
        return "La pregunta fue borrada.", Question.Status.DELETED
    if "banned" in text or "blocked" in text or "block" in text:
        return "El usuario está bloqueado.", Question.Status.BANNED
    if "already" in text or "answered" in text:
        return "La pregunta ya fue respondida.", Question.Status.ANSWERED
    return "El texto no es válido para Mercado Libre.", Question.Status.ERROR


def answer(client, question: Question, text: str, *, user) -> Question:
    if not user.has_perm("conversations.answer_question"):
        raise PermissionDenied
    text = (text or "").strip()
    question.draft_answer = text  # nunca se pierde lo escrito
    question.save(update_fields=["draft_answer", "updated_at"])
    if not text:
        raise AnswerRejected("La respuesta está vacía.", question.status)
    try:
        client.post("/answers", json={"question_id": int(question.external_id), "text": text})
    except ChannelHTTPError as exc:
        message, status = _rejection(exc)
        question.answer_error = message
        question.status = status
        question.save(update_fields=["answer_error", "status", "updated_at"])
        raise AnswerRejected(message, status) from exc
    with transaction.atomic():
        question.status = Question.Status.ANSWERED
        question.answer_text = text
        question.answered_at = timezone.now()
        question.answered_by = user
        question.answer_error = ""
        question.draft_answer = ""
        question.save()
        audit.record(user, "ml.question_answered", question, after={"answer": text})
    return question
