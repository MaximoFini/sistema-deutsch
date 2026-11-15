# ruff: noqa: F811 — las fixtures se importan de test_operacion_ml y pytest las inyecta por nombre
"""Auditoría M6 (docs/auditoria-m6.md): correcciones A1–A7 y R1."""

import logging
from datetime import timedelta

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import VENTAS
from apps.alerts.models import Alert
from apps.catalog.models import ListingVariation
from apps.conversations import inbox, labels, tasks
from apps.conversations.models import Message, Question
from apps.integrations.adapters.mercadolibre import listings, messages
from apps.integrations.adapters.mercadolibre.client import MLClient
from tests import ml_samples as S
from tests.test_operacion_ml import (  # noqa: F401 — fixtures
    CHART,
    GRID,
    api,
    catalog_variants,
    client_for,
    connected,
    item_with_grid,
    make_claim,
    make_question,
    two_threads,
)

pytestmark = pytest.mark.django_db
SUMMARY_SIZE = tasks.QUESTION_SUMMARY_OVER + 5


# ── A1 · envíos duplicados ───────────────────────────────────────────────


def test_answered_question_is_not_sent_again(client, users_by_role, catalog_variants, api):
    q = make_question()
    Question.objects.filter(pk=q.pk).update(status="answered", answer_text="Sí, hay XL")
    route = api.post("/answers").mock(return_value=httpx.Response(200, json={}))
    response = client_for(client, users_by_role, VENTAS).post(
        reverse("ml:question_detail", args=[q.pk]), {"text": "Sí, hay XL"}
    )
    content = response.content.decode()
    assert response.status_code == 200 and not route.called
    assert "ya estaba respondida" in content and "Sí, hay XL" in content


def test_same_message_twice_is_sent_once(client, users_by_role, two_threads, api):
    route = api.post(f"/messages/packs/2000002/sellers/{S.SELLER}").mock(
        side_effect=[httpx.Response(201, json={"id": "out-1"}), httpx.Response(201, json={"id": "out-2"})]
    )
    c = client_for(client, users_by_role, VENTAS)
    url = reverse("ml:thread", args=["2000002"])
    assert c.post(url, {"text": "Te lo mandamos hoy"}).status_code == 302
    response = c.post(url, {"text": "Te lo mandamos hoy"})  # doble clic / reenvío
    assert response.status_code == 200 and "ya se envió hace un momento" in response.content.decode()
    assert route.call_count == 1
    assert Message.objects.filter(thread_key="2000002", direction="out").count() == 1
    # Otro texto sí se manda; y el mismo texto, pasados 2 minutos, también.
    Message.objects.filter(external_id="out-1").update(sent_at=timezone.now() - timedelta(minutes=3))
    assert c.post(url, {"text": "Te lo mandamos hoy"}).status_code == 302 and route.call_count == 2


def test_reply_form_locks_button_on_submit(client, users_by_role, two_threads, connected):
    content = client_for(client, users_by_role, VENTAS).get(reverse("ml:thread", args=["2000002"]))
    content = content.content.decode()
    assert 'data-busy="Enviando…"' in content and "button.disabled = true" in content
    assert 'addEventListener("pageshow"' in content


# ── A2 / A3 · avisos de preguntas y reclamos ────────────────────────────


def test_alert_max_age_setting_default(settings):
    assert settings.ML_QUESTION_ALERT_MAX_AGE_DAYS == 3


def test_old_questions_do_not_alert(users_by_role, catalog_variants, settings):
    make_question(qid=1, hours_ago=24 * 5)  # importada de hace 5 días
    assert tasks.check_questions() == 0
    settings.ML_QUESTION_ALERT_MAX_AGE_DAYS = 7
    assert tasks.check_questions() == 1


def test_many_questions_send_one_summary_and_never_repeat(users_by_role, catalog_variants):
    for i in range(SUMMARY_SIZE):
        make_question(qid=100 + i, hours_ago=13 + i)
    assert tasks.check_questions() == 1
    alert = Alert.objects.get(alert_type__code="ml.question_unanswered_long")
    assert alert.title == f"Hay {SUMMARY_SIZE} preguntas sin responder hace más de 12 h"
    assert alert.link_url == "/ml/preguntas/" and alert.receipts.exists()
    assert not Question.objects.filter(alerted_at__isnull=True).exists()
    assert tasks.check_questions() == 0  # ni resumen nuevo ni avisos sueltos de las ya resumidas
    new = make_question(qid=999, hours_ago=13)
    assert tasks.check_questions() == 1
    assert Alert.objects.filter(dedupe_key=f"question-long:{new.pk}").exists()
    assert Alert.objects.count() == 2


def test_few_questions_alert_one_by_one(users_by_role, catalog_variants):
    for i in range(tasks.QUESTION_SUMMARY_OVER):
        make_question(qid=100 + i, hours_ago=13)
    assert tasks.check_questions() == tasks.QUESTION_SUMMARY_OVER


def test_second_run_skips_alerted_in_the_query(
    users_by_role, catalog_variants, django_assert_max_num_queries
):
    for i in range(30):
        make_question(qid=100 + i, hours_ago=13)
    for i in range(20):
        make_claim(cid=str(i), hours=3)
    tasks.check_questions()
    assert tasks.check_claims_due() == 20
    with django_assert_max_num_queries(2):  # una consulta por chequeo, sin recorrer nada
        assert tasks.check_questions() == 0
        assert tasks.check_claims_due() == 0


def test_claim_already_alerted_for_threshold_is_not_loaded(users_by_role):
    claim = make_claim(hours=20)
    start = timezone.now()
    assert tasks.check_claims_due(now=start) == 1
    assert tasks.check_claims_due(now=start + timedelta(hours=1)) == 0
    assert tasks.check_claims_due(now=start + timedelta(hours=17)) == 1  # quedan 3 h: umbral de 4 h
    keys = set(Alert.objects.values_list("dedupe_key", flat=True))
    assert keys == {f"claim-due:{claim.pk}:24h", f"claim-due:{claim.pk}:4h"}


# ── A4 · guía de talles sin colgar la ficha ─────────────────────────────


def test_quick_client_settings_without_changing_default():
    default, quick = MLClient(), MLClient.quick()
    assert default.http.max_retries == 3 and default.http._client.timeout.read == 20.0
    assert quick.http.max_retries == 0 and quick.http._client.timeout.read == 4.0


def test_question_page_does_not_call_ml_for_size_chart(client, users_by_role, catalog_variants, api):
    listings.upsert_item(item_with_grid())
    route = api.get(f"/catalog/charts/{GRID}").mock(return_value=httpx.Response(200, json=CHART))
    q = make_question()
    content = client_for(client, users_by_role, VENTAS).get(reverse("ml:question_detail", args=[q.pk]))
    assert "Cargando guía de talles…" in content.content.decode() and not route.called


def test_size_chart_fragment_fails_fast_and_uses_cache(
    client, users_by_role, catalog_variants, api, settings
):
    listing = listings.upsert_item(item_with_grid())
    stale = {"grid_id": GRID, "fetched_at": "2020-01-01T00:00:00+00:00", "columns": ["Largo"]}
    stale["rows"] = [{"size": "M", "measures": {"Largo": "70 cm"}, "cells": ["70 cm"]}]
    listing.data["size_chart"] = stale
    listing.save()
    route = api.get(f"/catalog/charts/{GRID}").mock(return_value=httpx.Response(503))
    q = make_question()
    content = client_for(client, users_by_role, VENTAS).get(reverse("ml:question_size_chart", args=[q.pk]))
    assert "70 cm" in content.content.decode()  # la del caché, aunque esté vencida
    assert route.call_count == 1  # sin reintentos


def test_size_chart_fragment_without_chart_is_empty(client, users_by_role, catalog_variants, connected):
    listings.upsert_item(S.item())
    q = make_question()
    response = client_for(client, users_by_role, VENTAS).get(reverse("ml:question_size_chart", args=[q.pk]))
    assert response.status_code == 200 and "Guía de talles" not in response.content.decode()


def test_size_chart_fragment_requires_permission(client, users_by_role, catalog_variants):
    from apps.accounts.roles import DEPOSITO

    q = make_question()
    c = client_for(client, users_by_role, DEPOSITO)
    assert c.get(reverse("ml:question_size_chart", args=[q.pk])).status_code == 403


# ── A5 · motivos de bloqueo en castellano ────────────────────────────────


@pytest.mark.parametrize(
    "body, expected",
    [
        ({"message": "The message could not be sent because there is a mediation"}, "mediación en curso"),
        ({"error": "blocked_by_mediation"}, "mediación en curso"),
        ({"message": "Message limit exceeded"}, "límite de mensajes"),
        ({"cause": [{"code": "conversation_closed", "message": "closed"}]}, "está cerrada"),
        ({"message": "The buyer is blocked"}, "está bloqueado"),
        ({"message": "Something else"}, "Probá respondiendo desde Mercado Libre"),
        ({}, "Probá respondiendo desde Mercado Libre"),
    ],
)
def test_message_block_reasons(body, expected):
    assert expected in labels.message_block_reason(body)


def test_blocked_message_shows_spanish_and_logs_original(client, users_by_role, two_threads, api, caplog):
    api.post(f"/messages/packs/2000002/sellers/{S.SELLER}").mock(
        return_value=httpx.Response(403, json={"message": "The message could not be sent because xyz"})
    )
    with caplog.at_level(logging.WARNING, logger="apps.conversations.views"):
        response = client_for(client, users_by_role, VENTAS).post(
            reverse("ml:thread", args=["2000002"]), {"text": "Hola"}
        )
    content = response.content.decode()
    assert "Probá respondiendo desde Mercado Libre" in content and "could not be sent" not in content
    assert "could not be sent" in caplog.text


# ── A6 · orden de los atributos ──────────────────────────────────────────


def test_question_variations_size_first(catalog_variants):
    listing = listings.upsert_item(S.item())
    ListingVariation.objects.filter(listing=listing).update(attributes={"Color": "Negro", "Talle": "M"})
    ctx = inbox.question_context(make_question())
    assert {r.label for r in ctx.variations} == {"M / Negro"}


def test_shared_attribute_helper_keeps_fulfillment_imports():
    from apps.catalog.attributes import attributes_text
    from apps.fulfillment.batches import ATTRIBUTE_ORDER, variant_description  # noqa: F401

    assert ATTRIBUTE_ORDER == ("talle", "color")
    assert attributes_text({"Color": "Rojo", "Estampa": "Lisa", "Talle": "L", "x": ""}) == "L / Rojo / Lisa"


# ── A7 · respondida desde ML sin texto ───────────────────────────────────


def test_answered_without_text_explains(client, users_by_role, catalog_variants):
    q = make_question()
    Question.objects.filter(pk=q.pk).update(status="answered", answer_text="")
    c = client_for(client, users_by_role, VENTAS)
    expected = "Respondida desde Mercado Libre (el texto llega en la próxima sincronización)"
    assert expected in c.get(reverse("ml:questions_answered")).content.decode()
    assert expected in c.get(reverse("ml:question_detail", args=[q.pk])).content.decode()


# ── R1 · lista de mensajes ───────────────────────────────────────────────


def test_thread_list_hides_old_read_threads(client, users_by_role, two_threads, connected):
    old = timezone.now() - timedelta(days=90)
    Message.objects.filter(thread_key="2000001").update(sent_at=old, read_at=old)  # vieja y leída
    messages.upsert_message(S.message(mid="z1", order_id=3000003, text="¿Siguen?"), S.SELLER)
    Message.objects.filter(external_id="z1").update(sent_at=old)  # vieja pero sin leer
    c = client_for(client, users_by_role, VENTAS)
    content = c.get(reverse("ml:threads")).content.decode()
    assert "¿Factura A?" in content and "¿Siguen?" in content and "Mañana" not in content
    assert "Ver más viejas" in content
    content = c.get(reverse("ml:threads") + "?viejas=1").content.decode()
    assert "Mañana" in content and "Ver más viejas" not in content


def test_thread_rows_last_text_and_document(two_threads):
    rows = inbox.threads(since=inbox.recent_threads_since())
    assert [(r.thread_key, r.last_text, r.document) for r in rows] == [
        ("2000002", "¿Factura A?", two_threads[1]),
        ("2000001", "Mañana", two_threads[0]),
    ]
