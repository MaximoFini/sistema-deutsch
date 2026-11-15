"""M6 · Operación de Mercado Libre: preguntas, mensajes, reclamos, salud de publicaciones, avisos y permisos."""

import io
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import httpx
import pytest
import respx
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import ADMIN, DEPOSITO, VENDEDOR, VENTAS
from apps.alerts.models import Alert, AlertType
from apps.audit.models import AuditLog
from apps.catalog.models import Listing, Product, Variant
from apps.conversations import health, inbox, labels, tasks
from apps.conversations.models import Claim, Message, Question, SavedReply
from apps.integrations import credentials
from apps.integrations.adapters.mercadolibre import claims, listings, messages, orders, questions
from apps.integrations.adapters.mercadolibre.client import MLClient
from apps.integrations.models import Channel
from apps.inventory.models import StockLevel, Warehouse
from tests import ml_samples as S

pytestmark = pytest.mark.django_db
API = "https://api.mercadolibre.com"
GRID = "3947384"
CHART = {
    "id": GRID,
    "main_attribute": {"attributes": [{"site_id": "MLA", "id": "SIZE"}]},
    "rows": [
        {
            "id": f"{GRID}:1",
            "attributes": [
                {"id": "SIZE", "name": "Talle", "values": [{"name": "M"}]},
                {"id": "CHEST_CIRCUMFERENCE", "name": "Contorno de pecho", "values": [{"name": "100 cm"}]},
            ],
        },
        {
            "id": f"{GRID}:2",
            "attributes": [
                {"id": "SIZE", "name": "Talle", "values": [{"name": "L"}]},
                {"id": "CHEST_CIRCUMFERENCE", "name": "Contorno de pecho", "values": [{"name": "106 cm"}]},
            ],
        },
    ],
}


def save_cred():
    credentials.save(
        "mercadolibre",
        {
            "access_token": "ACCESS-1",
            "refresh_token": "REFRESH-1",
            "expires_at": (timezone.now() + timedelta(hours=5)).isoformat(),
            "user_id": S.SELLER,
        },
    )


@pytest.fixture
def connected(db):
    save_cred()


@pytest.fixture
def api(connected):
    with respx.mock(base_url=API, assert_all_called=False) as m:
        yield m


@pytest.fixture
def catalog_variants(db):
    p = Product.objects.create(name="Buzo")
    return [Variant.objects.create(product=p, sku=s) for s in ("BUZ-001-M-NEG", "BUZ-001-L-NEG", "GOR-010")]


def item_with_grid(**overrides):
    data = S.item(**overrides)
    data["attributes"].append({"id": "SIZE_GRID_ID", "value_name": GRID})
    return data


def make_question(qid=9001, hours_ago=1, status="UNANSWERED", item_id="MLA1001", answer=None):
    q = questions.upsert_question(S.question(qid=qid, status=status, item_id=item_id, answer=answer))
    q.asked_at = timezone.now() - timedelta(hours=hours_ago)
    q.save(update_fields=["asked_at"])
    return q


def client_for(django_client, users_by_role, role):
    django_client.force_login(users_by_role[role])
    return django_client


# ── T1 · modelos, permisos, alertas y settings ───────────────────────────


def test_roles_get_m6_permissions(users_by_role):
    vendedor, deposito, ventas = users_by_role[VENDEDOR], users_by_role[DEPOSITO], users_by_role[VENTAS]
    for perm in (
        "conversations.view_question",
        "conversations.answer_question",
        "conversations.view_message",
        "conversations.send_message",
    ):
        assert vendedor.has_perm(perm) and ventas.has_perm(perm) and not deposito.has_perm(perm)
    for perm in (
        "conversations.view_claim",
        "catalog.view_listing_health",
        "conversations.manage_saved_replies",
    ):
        assert ventas.has_perm(perm) and users_by_role[ADMIN].has_perm(perm)
        assert not vendedor.has_perm(perm) and not deposito.has_perm(perm)


def test_permission_labels_in_spanish():
    from apps.accounts.roles import PERMISSION_LABELS, ROLE_PERMISSIONS

    perms = {p for role in ROLE_PERMISSIONS.values() for p in role}
    assert perms <= set(PERMISSION_LABELS)


def test_alert_types_seeded():
    due = AlertType.objects.get(code="ml.claim_due")
    assert due.send_email and set(due.roles.values_list("name", flat=True)) == {ADMIN, VENTAS}
    old = AlertType.objects.get(code="ml.question_unanswered_long")
    assert set(old.roles.values_list("name", flat=True)) == {ADMIN, VENTAS}


def test_settings_defaults(settings):
    assert settings.ML_QUESTION_WARNING_HOURS == 12
    assert settings.ML_CLAIM_WARNING_HOURS == [24, 4]
    assert settings.ML_HEALTH_MIN_SCORE == 0.7
    assert "{id}" in settings.ML_LISTING_EDIT_URL and "{order_id}" in settings.ML_CLAIM_URL


# ── T2 · ajustes en M2 ───────────────────────────────────────────────────


def test_upsert_item_saves_health_fields(catalog_variants):
    listing = listings.upsert_item(
        item_with_grid(
            status="paused",
            sub_status=["out_of_stock"],
            tags=["poor_quality_picture"],
            warnings=[{"code": "item.attributes.missing_required", "message": "Falta GENDER"}],
        )
    )
    data = listing.data
    assert data["sub_status"] == ["out_of_stock"] and data["tags"] == ["poor_quality_picture"]
    assert data["warnings"][0]["code"] == "item.attributes.missing_required"
    assert data["size_grid_id"] == GRID


def test_upsert_item_keeps_cached_size_chart_only_for_same_grid(catalog_variants):
    listing = listings.upsert_item(item_with_grid())
    listing.data["size_chart"] = {"grid_id": GRID, "fetched_at": timezone.now().isoformat(), "rows": []}
    listing.save()
    assert "size_chart" in listings.upsert_item(item_with_grid()).data
    assert "size_chart" not in listings.upsert_item(S.item()).data  # sin guía (o guía nueva): se descarta


def test_claim_opened_alert_links_to_claim(api, catalog_variants):
    orders.upsert_order(S.order())
    claim = claims.upsert_claim(MLClient(sleep=lambda s: None), S.claim())
    alert = Alert.objects.get(alert_type__code="ml.claim_opened")
    assert alert.link_url == f"/ml/reclamos/{claim.pk}/"


# ── T3 · preguntas y contexto ────────────────────────────────────────────


def test_unanswered_oldest_first_and_answered_search(catalog_variants):
    listings.upsert_item(S.item())
    new = make_question(qid=1, hours_ago=1)
    old = make_question(qid=2, hours_ago=20)
    make_question(qid=3, status="ANSWERED", answer={"text": "Sí, hay talle L", "date_created": None})
    assert list(inbox.unanswered_questions()) == [old, new]
    assert inbox.answered_questions(q="talle L").count() == 1
    assert inbox.answered_questions(q="nada que ver").count() == 0
    assert inbox.answered_questions(item="Buzo Canguro").count() == 1
    assert inbox.answered_questions(item="MLA1001").count() == 1


def test_question_context_stock_and_previous(api, catalog_variants):
    listings.upsert_item(S.item())
    warehouse = Warehouse.objects.get(is_default=True)
    StockLevel.objects.create(variant=catalog_variants[0], warehouse=warehouse, on_hand=7, reserved=2)
    q = make_question(qid=1)
    for i in range(12):
        make_question(qid=100 + i, status="ANSWERED", answer={"text": f"r{i}", "date_created": None})
    ctx = inbox.question_context(q)
    rows = {r.sku: r for r in ctx.variations}
    assert rows["BUZ-001-M-NEG"].ml_stock == 10 and rows["BUZ-001-M-NEG"].catalog_stock == 5
    assert rows["BUZ-001-L-NEG"].ml_stock == 5 and rows["BUZ-001-L-NEG"].catalog_stock is None
    assert "M" in rows["BUZ-001-M-NEG"].label and "Negro" in rows["BUZ-001-M-NEG"].label
    assert len(ctx.previous) == 10 and q not in ctx.previous
    assert ctx.size_chart is None  # la publicación no tiene guía de talles


def test_size_chart_cached_with_ttl(api, catalog_variants, settings):
    listing = listings.upsert_item(item_with_grid())
    route = api.get(f"/catalog/charts/{GRID}").mock(return_value=httpx.Response(200, json=CHART))
    chart = health.size_chart(listing)
    assert chart["columns"] == ["Contorno de pecho"]
    assert [(r["size"], r["cells"]) for r in chart["rows"]] == [("M", ["100 cm"]), ("L", ["106 cm"])]
    listing.refresh_from_db()
    assert health.size_chart(listing)["grid_id"] == GRID and route.call_count == 1  # del caché
    settings.ML_SIZE_CHART_TTL_HOURS = 0
    health.size_chart(listing)
    assert route.call_count == 2  # caché vencido: se vuelve a pedir


def test_size_chart_failure_returns_none(api, catalog_variants):
    listing = listings.upsert_item(item_with_grid())
    api.get(f"/catalog/charts/{GRID}").mock(return_value=httpx.Response(500))
    assert health.size_chart(listing, client=MLClient(sleep=lambda s: None)) is None


def test_size_chart_without_connection_returns_none(catalog_variants):
    listing = listings.upsert_item(item_with_grid())
    assert health.size_chart(listing) is None  # sin credenciales: no rompe


# ── T4 · conversaciones ──────────────────────────────────────────────────


@pytest.fixture
def two_threads(catalog_variants):
    doc1, _ = orders.upsert_order(S.order(order_id=2000001))
    doc2, _ = orders.upsert_order(S.order(order_id=2000002, shipping_id=40002))
    m1 = messages.upsert_message(S.message(mid="a1", order_id=2000001), S.SELLER)
    m2 = messages.upsert_message(
        S.message(mid="a2", order_id=2000001, from_seller=True, text="Mañana"), S.SELLER
    )
    m3 = messages.upsert_message(S.message(mid="b1", order_id=2000002, text="¿Factura A?"), S.SELLER)
    now = timezone.now()
    Message.objects.filter(pk=m1.pk).update(sent_at=now - timedelta(hours=1), read_at=now)
    Message.objects.filter(pk=m2.pk).update(sent_at=now - timedelta(minutes=30))
    Message.objects.filter(pk=m3.pk).update(sent_at=now - timedelta(hours=3))
    return doc1, doc2


def test_threads_grouped_unread_first(two_threads):
    doc1, doc2 = two_threads
    rows = inbox.threads()
    assert [r.thread_key for r in rows] == ["2000002", "2000001"]  # la que tiene no leídos va primero
    assert rows[0].unread == 1 and rows[0].document == doc2 and rows[0].last_text == "¿Factura A?"
    assert rows[1].unread == 0 and rows[1].total == 2 and rows[1].last_text == "Mañana"
    assert not rows[1].last_from_buyer
    assert [r.thread_key for r in inbox.threads(only_unread=True)] == ["2000002"]
    assert inbox.unread_threads_count() == 1


def test_thread_and_mark_read(two_threads):
    document, msgs = inbox.thread("2000001")
    assert document == two_threads[0] and [m.external_id for m in msgs] == ["a1", "a2"]
    assert inbox.mark_read("2000002") == 1
    assert inbox.mark_read("2000002") == 0
    assert inbox.unread_threads_count() == 0


# ── T5 · salud de publicaciones ──────────────────────────────────────────


def ml_listing(external_id="MLA1", **fields):
    defaults = {"title": "Pub", "status": "active", "data": {}}
    defaults.update(fields)
    return Listing.objects.create(
        channel=Channel.objects.get(code="mercadolibre"), external_id=external_id, **defaults
    )


@pytest.mark.parametrize(
    "fields,code,reason",
    [
        ({"status": "paused", "data": {"sub_status": ["out_of_stock"]}}, "paused", "sin stock"),
        ({"status": "paused"}, "paused", "sin motivo"),
        ({"status": "under_review"}, "under_review", "revisión"),
        ({"data": {"sub_status": ["forbidden"]}}, "under_review", "infracción"),
        ({"data": {"tags": ["moderation_penalty"]}}, "under_review", "moderación"),
        ({"data": {"tags": ["incomplete_technical_specs"]}}, "incomplete", "ficha técnica"),
        (
            {"data": {"warnings": [{"code": "item.attributes.missing_required", "message": "x"}]}},
            "incomplete",
            "atributos obligatorios",
        ),
        ({"health": Decimal("0.50")}, "low_quality", "50%"),
        ({"data": {"tags": ["poor_quality_thumbnail"]}}, "low_quality", "foto principal"),
        ({"needs_review": True, "review_notes": "111: sin SKU"}, "needs_review", "sin SKU"),
    ],
)
def test_problem_types(fields, code, reason):
    problems = health.problems_for(ml_listing(**fields))
    match = [p for p in problems if p.code == code]
    assert match and reason in match[0].reason


def test_healthy_listing_has_no_problems():
    assert (
        health.problems_for(ml_listing(health=Decimal("0.90"), data={"tags": ["good_quality_picture"]})) == []
    )


def test_unknown_codes_shown_as_is():
    problems = health.problems_for(ml_listing(status="paused", data={"sub_status": ["codigo_raro"]}))
    assert problems[0].reason == "codigo_raro"


def test_listings_with_problems_filters_and_counts():
    ml_listing("MLA1", title="Buzo negro", status="paused")
    ml_listing("MLA2", title="Gorra", health=Decimal("0.3"))
    ml_listing("MLA3", title="Remera", health=Decimal("0.9"))
    ml_listing("MLA4", title="Vieja", status="closed", health=Decimal("0.1"))
    rows, counts = health.listings_with_problems()
    assert {r.listing.external_id for r in rows} == {"MLA1", "MLA2"}
    assert counts["paused"] == 1 and counts["low_quality"] == 1 and counts["incomplete"] == 0
    rows, _ = health.listings_with_problems(code="paused")
    assert [r.listing.external_id for r in rows] == ["MLA1"]
    rows, counts = health.listings_with_problems(q="gorra")
    assert [r.listing.external_id for r in rows] == ["MLA2"] and counts["paused"] == 0


def test_search_by_sku(catalog_variants):
    listings.upsert_item(S.item(status="paused"))
    rows, _ = health.listings_with_problems(q="BUZ-001-L")
    assert rows and rows[0].skus == ["BUZ-001-L-NEG", "BUZ-001-M-NEG"]


def test_health_export_xlsx():
    from openpyxl import load_workbook

    ml_listing("MLA1", title="Buzo", status="paused", data={"sub_status": ["out_of_stock"]})
    rows, _ = health.listings_with_problems()
    ws = load_workbook(io.BytesIO(health.export_xlsx(rows))).active
    values = [c.value for c in ws[2]]
    assert values[0] == "MLA1" and "Pausada" in values[4] and "sin stock" in values[5]
    assert values[6] == "https://www.mercadolibre.com.ar/publicaciones/MLA1/modificar"


def test_labels_fallback():
    assert labels.claim_reason("PDD9939").startswith("Producto distinto")
    assert labels.claim_reason("XYZ") == "XYZ"
    assert labels.claim_type("mediations") == "Reclamo" and labels.claim_type("raro") == "raro"


# ── T6 · tareas periódicas ───────────────────────────────────────────────


def test_question_alert_once(users_by_role, catalog_variants):
    old = make_question(qid=1, hours_ago=13)
    make_question(qid=2, hours_ago=2)
    assert tasks.check_questions() == 1
    assert tasks.check_questions() == 0
    alert = Alert.objects.get(alert_type__code="ml.question_unanswered_long")
    assert alert.link_url == f"/ml/preguntas/{old.pk}/" and "13 h" in alert.title
    assert alert.receipts.filter(user=users_by_role[VENTAS]).exists()
    assert not alert.receipts.filter(user=users_by_role[VENDEDOR]).exists()


def make_claim(cid="5001", hours=30, action=True, status="opened", document=None):
    return Claim.objects.create(
        channel=Channel.objects.get(code="mercadolibre"),
        external_id=cid,
        order_external_id="2000001",
        status=status,
        reason="PNR123",
        claim_type="mediations",
        action_required=action,
        due_date=timezone.now() + timedelta(hours=hours) if hours is not None else None,
        document=document,
    )


def test_claim_due_24h_then_4h_without_duplicates(users_by_role):
    claim = make_claim(hours=30)
    start = timezone.now()
    assert tasks.check_claims_due(now=start) == 0
    assert tasks.check_claims_due(now=start + timedelta(hours=7)) == 1  # quedan 23 h
    assert tasks.check_claims_due(now=start + timedelta(hours=8)) == 0  # mismo umbral: no repite
    assert tasks.check_claims_due(now=start + timedelta(hours=27)) == 1  # quedan 3 h
    assert tasks.check_claims_due(now=start + timedelta(hours=28)) == 0
    assert tasks.check_claims_due(now=start + timedelta(hours=31)) == 0  # ya venció
    keys = set(Alert.objects.filter(alert_type__code="ml.claim_due").values_list("dedupe_key", flat=True))
    assert keys == {f"claim-due:{claim.pk}:24h", f"claim-due:{claim.pk}:4h"}
    alert = Alert.objects.get(dedupe_key=f"claim-due:{claim.pk}:4h")
    assert alert.link_url == f"/ml/reclamos/{claim.pk}/" and "vence en 3 h" in alert.title


def test_claim_detected_late_only_smallest_threshold(users_by_role):
    claim = make_claim(hours=3)
    assert tasks.check_claims_due() == 1
    assert Alert.objects.get(alert_type__code="ml.claim_due").dedupe_key == f"claim-due:{claim.pk}:4h"


def test_claim_without_due_or_action_no_alert(users_by_role):
    make_claim("1", hours=None)
    make_claim("2", hours=2, action=False)
    make_claim("3", hours=2, status="closed")
    assert tasks.check_claims_due() == 0


@override_settings(ML_CLAIM_WARNING_HOURS=[48])
def test_claim_thresholds_configurable(users_by_role):
    make_claim(hours=40)
    assert tasks.check_claims_due() == 1


def test_watch_task_every_5_minutes():
    from procrastinate.contrib.django import app

    key = ("apps.conversations.tasks.ml_operation_watch", "")
    assert app.periodic_registry.periodic_tasks[key].cron == "*/5 * * * *"


# ── T7 · pantallas de preguntas ──────────────────────────────────────────


def test_question_inbox_red_when_old(client, users_by_role, catalog_variants, connected):
    listings.upsert_item(S.item())
    make_question(qid=1, hours_ago=13)
    make_question(qid=2, hours_ago=1)
    content = client_for(client, users_by_role, VENDEDOR).get(reverse("ml:questions")).content.decode()
    assert content.count("¿Tenés talle XL?") == 2 and "border-red-300" in content
    assert "Buzo Canguro Oversize Deutsch" in content and "desconectado" not in content


def test_question_detail_shows_context(client, users_by_role, catalog_variants, api):
    listings.upsert_item(item_with_grid())
    api.get(f"/catalog/charts/{GRID}").mock(return_value=httpx.Response(200, json=CHART))
    SavedReply.objects.create(title="Talles", text="Mirá la guía de talles", created_by=users_by_role[ADMIN])
    q = make_question()
    content = (
        client_for(client, users_by_role, VENTAS).get(reverse("ml:question_detail", args=[q.pk])).content
    )
    content = content.decode()
    assert "Stock por talle y color" in content and "BUZ-001-M-NEG" in content
    assert "Guía de talles" in content and "106 cm" in content
    assert "Mirá la guía de talles" in content  # respuesta guardada lista para insertar


def test_answer_ok_redirects_to_next(client, users_by_role, catalog_variants, api):
    first = make_question(qid=1, hours_ago=5)
    second = make_question(qid=2, hours_ago=1)
    route = api.post("/answers").mock(return_value=httpx.Response(200, json={}))
    response = client_for(client, users_by_role, VENDEDOR).post(
        reverse("ml:question_detail", args=[first.pk]), {"text": "Sí, hay XL"}
    )
    assert response.status_code == 302 and response.url == reverse("ml:question_detail", args=[second.pk])
    assert json.loads(route.calls[0].request.content)["text"] == "Sí, hay XL"
    first.refresh_from_db()
    assert first.status == Question.Status.ANSWERED and first.answered_by == users_by_role[VENDEDOR]
    assert AuditLog.objects.filter(action="ml.question_answered").count() == 1


def test_answer_rejected_keeps_text_and_shows_reason(client, users_by_role, catalog_variants, api):
    q = make_question()
    api.post("/answers").mock(return_value=httpx.Response(400, json={"error": "bad_request", "message": "x"}))
    response = client_for(client, users_by_role, VENTAS).post(
        reverse("ml:question_detail", args=[q.pk]), {"text": "Llamame al 11-5555"}
    )
    content = response.content.decode()
    assert response.status_code == 200 and "no es válido para Mercado Libre" in content
    assert "Llamame al 11-5555" in content
    q.refresh_from_db()
    assert q.draft_answer == "Llamame al 11-5555"


def test_answer_already_answered_shows_ml_answer(client, users_by_role, catalog_variants, api):
    q = make_question()
    api.post("/answers").mock(return_value=httpx.Response(400, json={"message": "Question already answered"}))
    api.get("/questions/9001").mock(
        return_value=httpx.Response(
            200,
            json=S.question(
                status="ANSWERED", answer={"text": "Respondida desde la app", "date_created": None}
            ),
        )
    )
    content = client_for(client, users_by_role, VENTAS).post(
        reverse("ml:question_detail", args=[q.pk]), {"text": "Mi texto"}
    )
    content = content.content.decode()
    assert "ya fue respondida" in content and "Respondida desde la app" in content and "Mi texto" in content


def test_answer_network_error_is_friendly(client, users_by_role, catalog_variants, api):
    q = make_question()
    api.post("/answers").mock(side_effect=httpx.ConnectError("boom"))
    with mock.patch("apps.conversations.views._ml_client", return_value=MLClient(sleep=lambda s: None)):
        response = client_for(client, users_by_role, VENTAS).post(
            reverse("ml:question_detail", args=[q.pk]), {"text": "Hola"}
        )
    content = response.content.decode()
    assert response.status_code == 200 and "no responde" in content and "boom" not in content
    assert "quedó guardado" in content
    q.refresh_from_db()
    assert q in inbox.unanswered_questions()  # sigue en la bandeja para reintentar


def test_disconnected_banner_and_no_send(client, users_by_role, catalog_variants):
    q = make_question()
    c = client_for(client, users_by_role, VENTAS)
    content = c.get(reverse("ml:question_detail", args=[q.pk])).content.decode()
    assert "Mercado Libre está desconectado" in content and "disabled" in content
    with respx.mock(base_url=API) as m:
        response = c.post(reverse("ml:question_detail", args=[q.pk]), {"text": "Hola"})
        assert not m.calls
    assert "desconectado" in response.content.decode()
    q.refresh_from_db()
    assert q.draft_answer == "Hola" and q.status == Question.Status.UNANSWERED


def test_answer_too_long(client, users_by_role, catalog_variants, connected):
    q = make_question()
    response = client_for(client, users_by_role, VENTAS).post(
        reverse("ml:question_detail", args=[q.pk]), {"text": "x" * 2001}
    )
    assert "muy larga" in response.content.decode()


def test_answered_list_shows_who_and_where(client, users_by_role, catalog_variants):
    make_question(qid=1, status="ANSWERED", answer={"text": "Desde ML", "date_created": None})
    q = make_question(qid=2, status="ANSWERED", answer={"text": "Desde acá", "date_created": None})
    q.answered_by = users_by_role[VENTAS]
    q.save()
    content = (
        client_for(client, users_by_role, VENDEDOR).get(reverse("ml:questions_answered")).content.decode()
    )
    assert "desde Mercado Libre" in content and "desde el sistema" in content
    content = client.get(reverse("ml:questions_answered") + "?q=Desde+ac%C3%A1").content.decode()
    assert "Desde acá" in content and "Desde ML" not in content


def test_saved_replies_crud(client, users_by_role):
    c = client_for(client, users_by_role, VENTAS)
    response = c.post(reverse("ml:saved_replies"), {"title": "Envíos", "text": "Enviamos a todo el país"})
    assert response.status_code == 302
    reply = SavedReply.objects.get()
    assert reply.created_by == users_by_role[VENTAS]
    c.post(reverse("ml:saved_reply_edit", args=[reply.pk]), {"title": "Envíos", "text": "Nuevo texto"})
    reply.refresh_from_db()
    assert reply.text == "Nuevo texto"
    c.post(reverse("ml:saved_reply_edit", args=[reply.pk]), {"toggle": "1"})
    reply.refresh_from_db()
    assert not reply.is_active
    assert AuditLog.objects.filter(action="ml.saved_reply_changed").count() == 3
    assert c.post(reverse("ml:saved_replies"), {"title": "", "text": ""}).status_code == 400


def test_saved_replies_forbidden_for_vendedor(client, users_by_role):
    c = client_for(client, users_by_role, VENDEDOR)
    assert c.get(reverse("ml:saved_replies")).status_code == 403
    assert c.post(reverse("ml:saved_replies"), {"title": "x", "text": "y"}).status_code == 403
    assert not SavedReply.objects.exists()


# ── T8 · mensajes ────────────────────────────────────────────────────────


def test_thread_list_and_detail_marks_read(client, users_by_role, two_threads, connected):
    c = client_for(client, users_by_role, VENDEDOR)
    content = c.get(reverse("ml:threads")).content.decode()
    assert content.index("¿Factura A?") < content.index("Mañana") and "1 sin leer" in content
    content = c.get(reverse("ml:thread", args=["2000002"])).content.decode()
    assert "¿Factura A?" in content and "Ver pedido" in content
    assert not Message.objects.filter(thread_key="2000002", read_at__isnull=True).exists()


def test_send_message_from_thread(client, users_by_role, two_threads, api):
    route = api.post(f"/messages/packs/2000002/sellers/{S.SELLER}").mock(
        return_value=httpx.Response(201, json={"id": "out-9"})
    )
    response = client_for(client, users_by_role, VENDEDOR).post(
        reverse("ml:thread", args=["2000002"]), {"text": "Sí, te hacemos factura A"}
    )
    assert response.status_code == 302 and route.called
    assert Message.objects.filter(external_id="out-9", sent_by=users_by_role[VENDEDOR]).exists()
    assert AuditLog.objects.filter(action="ml.message_sent").exists()


def test_send_message_blocked_keeps_text(client, users_by_role, two_threads, api):
    api.post(f"/messages/packs/2000002/sellers/{S.SELLER}").mock(
        return_value=httpx.Response(403, json={"message": "conversación con mediación"})
    )
    response = client_for(client, users_by_role, VENTAS).post(
        reverse("ml:thread", args=["2000002"]), {"text": "Hola de nuevo"}
    )
    content = response.content.decode()
    assert response.status_code == 200 and "no permite enviar" in content and "Hola de nuevo" in content


def test_thread_without_order(client, users_by_role, connected):
    messages.upsert_message(S.message(mid="z1", order_id=777), S.SELLER)
    c = client_for(client, users_by_role, VENTAS)
    assert "Pedido no encontrado" in c.get(reverse("ml:thread", args=["777"])).content.decode()
    response = c.post(reverse("ml:thread", args=["777"]), {"text": "Hola"})
    assert "No se encontró el pedido" in response.content.decode()


def test_unknown_thread_404(client, users_by_role):
    assert (
        client_for(client, users_by_role, VENTAS).get(reverse("ml:thread", args=["nada"])).status_code == 404
    )


def test_attachment_download(client, users_by_role, catalog_variants, api):
    orders.upsert_order(S.order())
    msg = messages.upsert_message(S.message(), S.SELLER)
    msg.attachments = [{"filename": "123_foto.jpg", "original_filename": "foto.jpg"}]
    msg.save()
    api.get("/messages/attachments/123_foto.jpg").mock(
        return_value=httpx.Response(200, content=b"JPEG", headers={"content-type": "image/jpeg"})
    )
    c = client_for(client, users_by_role, VENTAS)
    assert "foto.jpg" in c.get(reverse("ml:thread", args=["2000001"])).content.decode()
    response = c.get(reverse("ml:attachment", args=["2000001", "123_foto.jpg"]))
    assert response.status_code == 200 and response.content == b"JPEG"
    assert c.get(reverse("ml:attachment", args=["2000001", "otro.jpg"])).status_code == 404


def test_order_detail_links_to_conversation(client, users_by_role, two_threads):
    doc2 = two_threads[1]
    content = client_for(client, users_by_role, VENTAS).get(reverse("sales:detail", args=[doc2.pk])).content
    content = content.decode()
    assert reverse("ml:thread", args=["2000002"]) in content and "Ver conversación (1 sin leer)" in content


# ── T9 · reclamos y salud ────────────────────────────────────────────────


def test_claim_list_order_and_tabs(client, users_by_role):
    late = make_claim("1", hours=50)
    urgent = make_claim("2", hours=5)
    no_action = make_claim("3", hours=None, action=False)
    closed = make_claim("4", status="closed", action=False)
    c = client_for(client, users_by_role, VENTAS)
    response = c.get(reverse("ml:claims"))
    assert list(response.context["claims"]) == [urgent, late, no_action]
    content = response.content.decode()
    assert (
        "vence en 5 h" in content and "Requiere tu respuesta" in content and "Producto no recibido" in content
    )
    assert list(c.get(reverse("ml:claims") + "?estado=cerrados").context["claims"]) == [closed]


def test_claim_detail(client, users_by_role, catalog_variants):
    doc, _ = orders.upsert_order(S.order())
    claim = make_claim(hours=10, document=doc)
    claim.return_status = "shipped"
    claim.save()
    content = (
        client_for(client, users_by_role, VENTAS).get(reverse("ml:claim_detail", args=[claim.pk])).content
    )
    content = content.decode()
    assert "https://www.mercadolibre.com.ar/ventas/2000001/detalle" in content
    assert "en camino" in content and reverse("sales:detail", args=[doc.pk]) in content


def test_health_page_and_export(client, users_by_role):
    ml_listing(
        "MLA1", title="Buzo", status="paused", data={"sub_status": ["out_of_stock"], "pictures": ["p.jpg"]}
    )
    ml_listing("MLA2", title="Gorra", health=Decimal("0.2"))
    c = client_for(client, users_by_role, VENTAS)
    content = c.get(reverse("ml:health")).content.decode()
    assert "Buzo" in content and "Gorra" in content and "sin stock" in content
    assert "publicaciones/MLA1/modificar" in content and "Pausada (1)" in content
    content = c.get(reverse("ml:health") + "?tipo=low_quality").content.decode()
    assert "Gorra" in content and "Buzo" not in content
    response = c.get(reverse("ml:health_xlsx") + "?tipo=paused")
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")


# ── T10 · menú, contadores y permisos ────────────────────────────────────


def test_counters_fragment(client, users_by_role, two_threads):
    make_question(qid=1)
    make_claim(hours=10)
    content = client_for(client, users_by_role, VENTAS).get(reverse("ml:counters")).content.decode()
    assert "Preguntas" in content and "Reclamos" in content and "Salud" in content
    assert content.count("bg-red-600") == 3
    content = client_for(client, users_by_role, VENDEDOR).get(reverse("ml:counters")).content.decode()
    assert "Preguntas" in content and "Mensajes" in content and "Reclamos" not in content
    content = client_for(client, users_by_role, DEPOSITO).get(reverse("ml:counters")).content.decode()
    assert "Preguntas" not in content


def test_menu_group_loads_counters_with_htmx(client, users_by_role):
    content = client_for(client, users_by_role, VENTAS).get(reverse("core:home")).content.decode()
    assert reverse("ml:counters") in content and 'hx-trigger="load, every 60s"' in content
    content = client_for(client, users_by_role, DEPOSITO).get(reverse("core:home")).content.decode()
    assert reverse("ml:counters") not in content


@pytest.fixture
def m6_objects(users_by_role, catalog_variants):
    q = make_question()
    messages.upsert_message(S.message(mid="m1", order_id=2000001), S.SELLER)
    claim = make_claim()
    reply = SavedReply.objects.create(title="T", text="x", created_by=users_by_role[ADMIN])
    return {"q": q, "claim": claim, "reply": reply}


def m6_urls(o):
    return {
        "questions": reverse("ml:questions"),
        "answered": reverse("ml:questions_answered"),
        "question": reverse("ml:question_detail", args=[o["q"].pk]),
        "saved": reverse("ml:saved_replies"),
        "saved_edit": reverse("ml:saved_reply_edit", args=[o["reply"].pk]),
        "threads": reverse("ml:threads"),
        "thread": reverse("ml:thread", args=["2000001"]),
        "claims": reverse("ml:claims"),
        "claim": reverse("ml:claim_detail", args=[o["claim"].pk]),
        "health": reverse("ml:health"),
        "health_xlsx": reverse("ml:health_xlsx"),
    }


ALLOWED = {
    ADMIN: set(
        "questions answered question saved saved_edit threads thread claims claim health health_xlsx".split()
    ),
    VENTAS: set(
        "questions answered question saved saved_edit threads thread claims claim health health_xlsx".split()
    ),
    VENDEDOR: {"questions", "answered", "question", "threads", "thread"},
    DEPOSITO: set(),
}


@pytest.mark.parametrize("role", [ADMIN, VENTAS, VENDEDOR, DEPOSITO])
def test_url_permissions_by_role(client, users_by_role, m6_objects, role):
    c = client_for(client, users_by_role, role)
    for name, url in m6_urls(m6_objects).items():
        expected = 200 if name in ALLOWED[role] else 403
        assert c.get(url).status_code == expected, (role, name)


def test_anonymous_redirected_to_login(client, m6_objects):
    for url in m6_urls(m6_objects).values():
        response = client.get(url)
        assert response.status_code == 302 and "/cuenta/" in response.url
    assert client.get(reverse("ml:counters")).status_code == 302


def test_post_requires_answer_and_send_permission(client, users_by_role, m6_objects, connected):
    c = client_for(client, users_by_role, DEPOSITO)
    assert c.post(reverse("ml:question_detail", args=[m6_objects["q"].pk]), {"text": "x"}).status_code == 403
    # Un usuario con permiso de ver pero sin el de responder (permiso puntual) tampoco puede enviar.
    from django.contrib.auth.models import Permission

    user = users_by_role[DEPOSITO]
    user.user_permissions.add(
        Permission.objects.get(codename="view_question"), Permission.objects.get(codename="view_message")
    )
    c.force_login(user)
    assert c.post(reverse("ml:question_detail", args=[m6_objects["q"].pk]), {"text": "x"}).status_code == 403
    assert c.post(reverse("ml:thread", args=["2000001"]), {"text": "x"}).status_code == 403
    assert Group.objects.filter(name=DEPOSITO).exists()


def test_only_answer_and_send_write_to_ml():
    """Regla de oro: M6 no agrega escrituras a ML (las únicas son las de M2: /answers y /messages)."""
    import inspect

    from apps.conversations import health as h
    from apps.conversations import inbox as i
    from apps.conversations import views as v

    for module in (h, i, v, tasks):
        source = inspect.getsource(module)
        assert ".post(" not in source.replace("def post(", "") and ".put(" not in source
