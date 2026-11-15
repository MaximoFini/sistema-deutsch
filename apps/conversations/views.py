"""Pantallas de Operación de Mercado Libre (M6): preguntas, mensajes, reclamos y salud.

Las únicas escrituras en ML son `questions.answer` y `messages.send` (M2). Nada de stock ni precios.
"""

import logging
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.accounts.mixins import PanelLoginRequiredMixin, PanelPermissionRequiredMixin
from apps.audit import services as audit
from apps.integrations.errors import friendly

from . import health, inbox, labels
from .models import Claim, Message, Question, SavedReply

logger = logging.getLogger(__name__)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ALREADY_ANSWERED = (
    "Esta pregunta ya estaba respondida, así que no se volvió a enviar. La respuesta está arriba."
)
ALREADY_SENT = "Ese mensaje ya se envió hace un momento. No se volvió a mandar."
DUPLICATE_WINDOW = timedelta(minutes=2)
DISCONNECTED = "Mercado Libre está desconectado: las respuestas no se pueden enviar. Hay que reconectarlo desde Integraciones."
QUESTION_MAX = 2000
CLOSED_CLAIM_DAYS = 90


def _querystring(request) -> str:
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


def _ml_client():
    from apps.integrations.adapters.mercadolibre.client import MLClient

    return MLClient()


def _messaging_blocked_text(exc) -> str:
    """Motivo en castellano cuando ML bloquea un mensaje (auditoría M6, A5). El texto original de ML va
    al log. Los bloqueos propios de M2 (vacío, muy largo, sin conversación) ya están en castellano."""
    from apps.integrations.adapters.mercadolibre.common import error_body

    cause = exc.__cause__
    if cause is None:
        return str(exc)
    body = error_body(cause)
    logger.warning("ML bloqueó un mensaje: %s | %s", exc, body)
    return labels.message_block_reason(body)


def _rejection_message(exc) -> str:
    """M2 trata cualquier error del POST como «texto no válido». Si en realidad fue la red, el token o
    un límite de ML, se muestra ese motivo (el texto queda guardado igual)."""
    cause = exc.__cause__
    if exc.status == Question.Status.ERROR and cause is not None:
        response = getattr(cause, "response", None)
        status = getattr(response, "status_code", None)
        if status is None or status >= 500 or status in (401, 429):
            return f"No se pudo enviar la respuesta. {friendly(cause)} Lo que escribiste quedó guardado."
    return str(exc)


# ── Preguntas ────────────────────────────────────────────────────────────


class QuestionListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "conversations.view_question"
    template_name = "conversations/question_list.html"
    context_object_name = "questions"
    paginate_by = 50

    def get_queryset(self):
        return inbox.unanswered_questions()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            warn_before=inbox.warning_limit(),
            warn_hours=settings.ML_QUESTION_WARNING_HOURS,
            connected=inbox.ml_connected(),
            querystring="",
        )
        return ctx


class AnsweredQuestionListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "conversations.view_question"
    template_name = "conversations/question_answered.html"
    context_object_name = "questions"
    paginate_by = 30

    def get_queryset(self):
        return inbox.answered_questions(
            self.request.GET.get("q", ""), self.request.GET.get("publicacion", "")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            q=self.request.GET.get("q", ""),
            publicacion=self.request.GET.get("publicacion", ""),
            querystring=_querystring(self.request),
        )
        return ctx


class QuestionDetailView(PanelPermissionRequiredMixin, View):
    permission_required = "conversations.view_question"
    template_name = "conversations/question_detail.html"

    def _render(self, request, question, *, text=None, error="", status=200):
        context = inbox.question_context(question)
        can_answer = request.user.has_perm("conversations.answer_question")
        open_statuses = (Question.Status.UNANSWERED, Question.Status.ERROR)
        return render(
            request,
            self.template_name,
            {
                "question": question,
                "ctx": context,
                "text": question.draft_answer if text is None else text,
                "error": error,
                "connected": inbox.ml_connected(),
                "can_answer": can_answer and question.status in open_statuses,
                "saved_replies": SavedReply.objects.filter(is_active=True) if can_answer else [],
                "warn_before": inbox.warning_limit(),
                "max_length": QUESTION_MAX,
            },
            status=status,
        )

    def get(self, request, pk):
        question = get_object_or_404(Question.objects.select_related("listing", "answered_by"), pk=pk)
        return self._render(request, question)

    def post(self, request, pk):
        if not request.user.has_perm("conversations.answer_question"):
            raise PermissionDenied
        from apps.integrations.adapters.mercadolibre import questions as ml_questions

        question = get_object_or_404(Question.objects.select_related("listing", "answered_by"), pk=pk)
        text = (request.POST.get("text") or "").strip()
        if question.status == Question.Status.ANSWERED:
            # Doble clic o reenvío del formulario: ML rechazaría la segunda respuesta con un error confuso.
            return self._render(request, question, text=text, error=ALREADY_ANSWERED)
        if len(text) > QUESTION_MAX:
            return self._render(
                request,
                question,
                text=text,
                error=f"La respuesta es muy larga: Mercado Libre permite hasta {QUESTION_MAX} caracteres (tiene {len(text)}).",
            )
        if not inbox.ml_connected():
            question.draft_answer = text
            question.save(update_fields=["draft_answer", "updated_at"])
            return self._render(request, question, text=text, error=DISCONNECTED)
        client = _ml_client()
        try:
            ml_questions.answer(client, question, text, user=request.user)
        except ml_questions.AnswerRejected as exc:
            if exc.status == Question.Status.ANSWERED:
                try:  # trae la respuesta que se dio desde la app de ML
                    question = ml_questions.refresh(client, question.external_id)
                except Exception:  # noqa: BLE001
                    logger.warning("No se pudo refrescar la pregunta %s", question.pk, exc_info=True)
            question.refresh_from_db()
            return self._render(request, question, text=text, error=_rejection_message(exc))
        except PermissionDenied:
            raise
        except Exception as exc:  # noqa: BLE001 — token, red, etc.: mensaje claro, sin 500
            logger.exception("Error respondiendo la pregunta %s", question.pk)
            question.refresh_from_db()
            return self._render(request, question, text=text, error=friendly(exc))
        messages.success(request, "Respuesta enviada a Mercado Libre.")
        following = inbox.next_unanswered(after=question)
        if following is not None:
            return redirect("ml:question_detail", pk=following.pk)
        return redirect("ml:questions")


class QuestionSizeChartView(PanelPermissionRequiredMixin, View):
    """Fragmento HTMX con la guía de talles (auditoría M6, A4). Se pide a ML con un cliente rápido
    (4 s, sin reintentos): si ML no responde se muestra la del caché o nada, sin colgar la ficha."""

    permission_required = "conversations.view_question"

    def get(self, request, pk):
        from apps.integrations.adapters.mercadolibre.client import MLClient

        question = get_object_or_404(Question.objects.select_related("listing"), pk=pk)
        chart = health.size_chart(question.listing, client=MLClient.quick())
        return render(request, "conversations/_size_chart.html", {"chart": chart})


# ── Respuestas guardadas ─────────────────────────────────────────────────


class SavedReplyForm(forms.ModelForm):
    class Meta:
        model = SavedReply
        fields = ["title", "text"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "w-full rounded border border-stone-300 px-2 py-2"}),
            "text": forms.Textarea(
                attrs={"rows": 4, "class": "w-full rounded border border-stone-300 px-2 py-2"}
            ),
        }


class SavedReplyListView(PanelPermissionRequiredMixin, View):
    permission_required = "conversations.manage_saved_replies"
    template_name = "conversations/saved_replies.html"

    def _render(self, request, form, status=200):
        return render(
            request,
            self.template_name,
            {"replies": SavedReply.objects.select_related("created_by"), "form": form},
            status=status,
        )

    def get(self, request):
        return self._render(request, SavedReplyForm())

    def post(self, request):
        form = SavedReplyForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, status=400)
        reply = form.save(commit=False)
        reply.created_by = request.user
        reply.save()
        audit.record(
            request.user, "ml.saved_reply_changed", reply, after={"title": reply.title, "text": reply.text}
        )
        messages.success(request, f"Respuesta guardada «{reply.title}» creada.")
        return redirect("ml:saved_replies")


class SavedReplyEditView(PanelPermissionRequiredMixin, View):
    permission_required = "conversations.manage_saved_replies"
    template_name = "conversations/saved_reply_edit.html"

    def get(self, request, pk):
        reply = get_object_or_404(SavedReply, pk=pk)
        return render(request, self.template_name, {"reply": reply, "form": SavedReplyForm(instance=reply)})

    def post(self, request, pk):
        reply = get_object_or_404(SavedReply, pk=pk)
        before = {"title": reply.title, "text": reply.text, "is_active": reply.is_active}
        if "toggle" in request.POST:
            reply.is_active = not reply.is_active
            reply.save(update_fields=["is_active", "updated_at"])
            audit.record(
                request.user,
                "ml.saved_reply_changed",
                reply,
                before=before,
                after={"is_active": reply.is_active},
            )
            messages.success(request, f"«{reply.title}» {'activada' if reply.is_active else 'dada de baja'}.")
            return redirect("ml:saved_replies")
        form = SavedReplyForm(request.POST, instance=reply)
        if not form.is_valid():
            return render(request, self.template_name, {"reply": reply, "form": form}, status=400)
        form.save()
        audit.record(
            request.user,
            "ml.saved_reply_changed",
            reply,
            before=before,
            after={"title": reply.title, "text": reply.text},
        )
        messages.success(request, f"Respuesta guardada «{reply.title}» actualizada.")
        return redirect("ml:saved_replies")


# ── Mensajes ─────────────────────────────────────────────────────────────


class ThreadListView(PanelPermissionRequiredMixin, TemplateView):
    permission_required = "conversations.view_message"
    template_name = "conversations/thread_list.html"
    paginate_by = 50

    def get_context_data(self, **kwargs):
        only_unread = bool(self.request.GET.get("sin_leer"))
        show_old = bool(self.request.GET.get("viejas"))
        since = None if show_old else inbox.recent_threads_since()
        page = Paginator(
            inbox.threads_queryset(only_unread=only_unread, since=since), self.paginate_by
        ).get_page(self.request.GET.get("page"))
        return {
            "show_old": show_old,
            "recent_days": inbox.RECENT_THREAD_DAYS,
            "older_exist": since is not None and not only_unread and inbox.older_threads_exist(since),
            "threads": inbox.thread_rows(page.object_list),
            "page_obj": page,
            "paginator": page.paginator,
            "is_paginated": page.paginator.num_pages > 1,
            "querystring": _querystring(self.request),
            "only_unread": only_unread,
            "connected": inbox.ml_connected(),
        }


class ThreadDetailView(PanelPermissionRequiredMixin, View):
    permission_required = "conversations.view_message"
    template_name = "conversations/thread_detail.html"

    def _render(self, request, thread_key, document, msgs, *, text="", error="", status=200):
        from apps.integrations.adapters.mercadolibre.messages import MAX_LENGTH
        from apps.sales import states

        return render(
            request,
            self.template_name,
            {
                "thread_key": thread_key,
                "document": document,
                "status_label": states.label(document.status) if document else "",
                "messages_list": msgs,
                "text": text,
                "error": error,
                "connected": inbox.ml_connected(),
                "can_send": request.user.has_perm("conversations.send_message"),
                "saved_replies": SavedReply.objects.filter(is_active=True)
                if request.user.has_perm("conversations.send_message")
                else [],
                "max_length": MAX_LENGTH,
            },
            status=status,
        )

    @staticmethod
    def _just_sent(thread_key, text) -> bool:
        return Message.objects.filter(
            thread_key=thread_key,
            direction=Message.Direction.OUT,
            text=text,
            sent_at__gte=timezone.now() - DUPLICATE_WINDOW,
        ).exists()

    def _load(self, thread_key):
        document, msgs = inbox.thread(thread_key)
        if not msgs:
            from django.http import Http404

            raise Http404("Conversación inexistente")
        return document, msgs

    def get(self, request, thread_key):
        document, msgs = self._load(thread_key)
        inbox.mark_read(thread_key, request.user)
        return self._render(request, thread_key, document, msgs)

    def post(self, request, thread_key):
        if not request.user.has_perm("conversations.send_message"):
            raise PermissionDenied
        from apps.integrations.adapters.mercadolibre import messages as ml_messages

        document, msgs = self._load(thread_key)
        text = (request.POST.get("text") or "").strip()
        if document is None:
            error = (
                "No se encontró el pedido de esta conversación en el sistema, así que no se puede responder "
                "desde acá. Respondé desde Mercado Libre."
            )
            return self._render(request, thread_key, document, msgs, text=text, error=error)
        if not inbox.ml_connected():
            return self._render(request, thread_key, document, msgs, text=text, error=DISCONNECTED)
        if text and self._just_sent(thread_key, text):
            # Doble clic o reenvío del formulario: ML no lo frena y el comprador recibiría dos mensajes.
            return self._render(request, thread_key, document, msgs, error=ALREADY_SENT)
        try:
            ml_messages.send(_ml_client(), document, text, user=request.user)
        except ml_messages.MessagingBlocked as exc:
            error = _messaging_blocked_text(exc)
            return self._render(request, thread_key, document, msgs, text=text, error=error)
        except PermissionDenied:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error enviando mensaje en la conversación %s", thread_key)
            return self._render(request, thread_key, document, msgs, text=text, error=friendly(exc))
        messages.success(request, "Mensaje enviado a Mercado Libre.")
        return redirect("ml:thread", thread_key=thread_key)


class AttachmentView(PanelPermissionRequiredMixin, View):
    """Descarga un adjunto de la conversación desde ML (lectura). Solo adjuntos de esa conversación."""

    permission_required = "conversations.view_message"

    def get(self, request, thread_key, filename):
        from django.http import Http404

        from apps.conversations.models import Message

        owned = any(
            (a or {}).get("filename") == filename
            for m in Message.objects.filter(thread_key=thread_key).only("attachments")
            for a in (m.attachments or [])
        )
        if not owned:
            raise Http404("Adjunto inexistente")
        if not inbox.ml_connected():
            messages.error(
                request,
                DISCONNECTED.replace("las respuestas no se pueden enviar", "no se pueden ver los adjuntos"),
            )
            return redirect("ml:thread", thread_key=thread_key)
        try:
            response = _ml_client().get_raw(
                f"/messages/attachments/{filename}", params={"tag": "post_sale", "site_id": settings.ML_SITE}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo bajar el adjunto %s", filename, exc_info=True)
            messages.error(request, f"No se pudo abrir el adjunto. {friendly(exc)}")
            return redirect("ml:thread", thread_key=thread_key)
        out = HttpResponse(
            response.content, content_type=response.headers.get("content-type", "application/octet-stream")
        )
        out["Content-Disposition"] = 'inline; filename="{}"'.format(filename.replace('"', ""))
        return out


# ── Reclamos ─────────────────────────────────────────────────────────────


class ClaimListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "conversations.view_claim"
    template_name = "conversations/claim_list.html"
    context_object_name = "claims"
    paginate_by = 50

    def closed_tab(self) -> bool:
        return self.request.GET.get("estado") == "cerrados"

    def get_queryset(self):
        qs = Claim.objects.select_related("document__customer")
        if self.closed_tab():
            since = timezone.now() - timedelta(days=CLOSED_CLAIM_DAYS)
            return qs.exclude(status="opened").filter(updated_at__gte=since).order_by("-updated_at", "-pk")
        return qs.filter(status="opened").order_by(
            "-action_required", F("due_date").asc(nulls_last=True), "-created_at"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            closed=self.closed_tab(),
            now=timezone.now(),
            soon=timezone.now() + timedelta(hours=24),
            querystring=_querystring(self.request),
        )
        return ctx


class ClaimDetailView(PanelPermissionRequiredMixin, DetailView):
    permission_required = "conversations.view_claim"
    template_name = "conversations/claim_detail.html"
    context_object_name = "claim"

    def get_queryset(self):
        return Claim.objects.select_related("document__customer", "channel")

    def get_context_data(self, **kwargs):
        from apps.sales.models import ReturnInfo

        ctx = super().get_context_data(**kwargs)
        claim = self.object
        order_id = claim.order_external_id or claim.external_id
        ctx.update(
            returns=ReturnInfo.objects.filter(claim=claim).select_related("document"),
            ml_url=settings.ML_CLAIM_URL.format(order_id=order_id, id=claim.external_id),
            now=timezone.now(),
            soon=timezone.now() + timedelta(hours=24),
            resolution=(claim.data or {}).get("resolution") or {},
            related=(claim.data or {}).get("related_entities") or [],
        )
        return ctx


# ── Salud de publicaciones ───────────────────────────────────────────────


class HealthView(PanelPermissionRequiredMixin, TemplateView):
    permission_required = "catalog.view_listing_health"
    template_name = "conversations/health.html"
    paginate_by = 100

    def rows(self):
        return health.listings_with_problems(self.request.GET.get("q", ""), self.request.GET.get("tipo", ""))

    def get_context_data(self, **kwargs):
        rows, counts = self.rows()
        page = Paginator(rows, self.paginate_by).get_page(self.request.GET.get("page"))
        return {
            "rows": page.object_list,
            "page_obj": page,
            "paginator": page.paginator,
            "is_paginated": page.paginator.num_pages > 1,
            "querystring": _querystring(self.request),
            "counts": [(code, health.PROBLEMS[code], n) for code, n in counts.items()],
            "total": len(rows),
            "tipo": self.request.GET.get("tipo", ""),
            "q": self.request.GET.get("q", ""),
        }


class HealthExportView(HealthView):
    def get(self, request, *args, **kwargs):
        rows, _ = self.rows()
        response = HttpResponse(health.export_xlsx(rows), content_type=XLSX)
        response["Content-Disposition"] = (
            f'attachment; filename="salud-publicaciones-{timezone.localdate():%Y%m%d}.xlsx"'
        )
        return response


# ── Contadores del menú ──────────────────────────────────────────────────


class CountersView(PanelLoginRequiredMixin, TemplateView):
    """Fragmento HTMX del grupo Mercado Libre del menú con sus contadores (cada 60 s, como la campana).

    Cada contador se calcula solo si el usuario tiene el permiso de esa pantalla.
    """

    template_name = "conversations/_menu_links.html"

    def get_context_data(self, **kwargs):
        user = self.request.user
        counts = {}
        if user.has_perm("conversations.view_question"):
            counts["questions"] = Question.objects.filter(status__in=inbox.OPEN_STATUSES).count()
        if user.has_perm("conversations.view_message"):
            counts["threads"] = inbox.unread_threads_count()
        if user.has_perm("conversations.view_claim"):
            counts["claims"] = Claim.objects.filter(status="opened", action_required=True).count()
        return {"counts": counts}
