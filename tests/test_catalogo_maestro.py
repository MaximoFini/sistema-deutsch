import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from apps.accounts.roles import ADMIN, DEPOSITO, VENTAS
from apps.audit.models import AuditLog
from apps.catalog import channel_view, linking, quality
from apps.catalog import contabilium_import as ci
from apps.catalog.models import ContabiliumImport, Listing, ListingVariation, Product, Variant
from apps.integrations.adapters.mercadolibre import listings as ml_listings
from apps.integrations.adapters.tiendanube import catalog as tn_catalog
from apps.integrations.models import Channel, ExternalRef
from apps.inventory.models import StockLevel
from apps.pricing import services as pricing
from apps.pricing.models import PriceList, PriceListItem
from tests import ml_samples, tn_samples

pytestmark = pytest.mark.django_db


@pytest.fixture
def tn_catalog_loaded(db):
    tn_catalog.upsert_product(tn_samples.product())  # BUZ-001-M-NEG y BUZ-001-L-NEG
    return Variant.objects.get(sku="BUZ-001-M-NEG"), Variant.objects.get(sku="BUZ-001-L-NEG")


def ml_row(item_id="MLA1001", variation_id="111"):
    return ListingVariation.objects.get(listing__external_id=item_id, external_id=variation_id)


def csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def xlsx_bytes(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Vinculación ──────────────────────────────────────────────────────────


def test_ml_auto_link_by_sku(tn_catalog_loaded):
    ml_listings.upsert_item(ml_samples.item())
    row = ml_row()
    assert row.variant.sku == "BUZ-001-M-NEG" and row.link_source == "auto"
    assert ExternalRef.objects.filter(channel__code="mercadolibre", external_id="MLA1001:111").exists()


def test_manual_link_survives_sync(tn_catalog_loaded, admin_user):
    m, l_ = tn_catalog_loaded
    ml_listings.upsert_item(ml_samples.item())
    linking.link_manual(ml_row(), l_, user=admin_user)
    ml_listings.upsert_item(ml_samples.item())  # nueva sync
    row = ml_row()
    assert row.variant == l_ and row.link_source == "manual"
    log = AuditLog.objects.get(action="catalog.link_changed")
    assert log.before["sku_variante"] == "BUZ-001-M-NEG" and log.after["sku_variante"] == "BUZ-001-L-NEG"
    assert ExternalRef.objects.get(channel__code="mercadolibre", external_id="MLA1001:111").object_id == l_.pk


def test_manual_unlink_is_respected(tn_catalog_loaded, admin_user):
    ml_listings.upsert_item(ml_samples.item())
    linking.unlink_manual(ml_row(), user=admin_user)
    ml_listings.upsert_item(ml_samples.item())
    row = ml_row()
    assert row.variant is None and row.link_source == "manual"
    assert not ExternalRef.objects.filter(channel__code="mercadolibre", external_id="MLA1001:111").exists()


def test_relink_when_variant_arrives_later(db):
    ml_listings.upsert_item(ml_samples.item())
    assert ml_row().variant is None
    tn_catalog.upsert_product(tn_samples.product())
    assert ml_row().variant.sku == "BUZ-001-M-NEG"


def test_contabilium_links_by_barcode(tn_catalog_loaded, admin_user):
    data = ci.parse_file("p.csv", csv_bytes("Código;Nombre;Código de barras\nX-999;Buzo;7790000000011\n"))
    imp = ContabiliumImport.objects.create(
        uploaded_by=admin_user, filename="p.csv", rows=data["rows"], summary={}
    )
    ci.apply_import(imp, user=admin_user)
    row = ListingVariation.objects.get(listing__channel__code="contabilium", listing__external_id="X-999")
    assert row.variant.sku == "BUZ-001-M-NEG"


# ── Lectura del archivo ──────────────────────────────────────────────────


def test_parse_csv_semicolon_and_argentine_numbers():
    content = "Código;Nombre;Stock;Precio;Precio Mayorista\nBUZ-001-M-NEG;Buzo M;12;$ 45.000,00;30.000,50\n"
    data = ci.parse_file("productos.csv", csv_bytes(content))
    row = data["rows"][0]
    assert row["code"] == "BUZ-001-M-NEG" and row["stock"] == "12"
    assert row["retail_price"] == "45000.00" and row["wholesale_price"] == "30000.50"


def test_parse_csv_comma():
    data = ci.parse_file("p.csv", csv_bytes("sku,descripcion,existencia\nA1,Uno,3\n"))
    assert data["rows"][0]["code"] == "A1" and data["rows"][0]["name"] == "Uno"


def test_parse_xlsx_with_header_in_row_3_and_numeric_codes():
    content = xlsx_bytes(
        [
            ["Listado de productos"],
            [],
            ["Codigo", "Descripción", "Cod. Barras", "Stock Actual", "PVP"],
            [123, "Gorra", 7790000000099.0, 4, 1500.5],
        ]
    )
    data = ci.parse_file("export.xlsx", content)
    row = data["rows"][0]
    assert row["code"] == "123" and row["barcode"] == "7790000000099" and row["retail_price"] == "1500.5"


def test_missing_code_column_lists_found_columns():
    with pytest.raises(ci.ImportFileError, match="Nombre, Precio"):
        ci.parse_file("p.csv", csv_bytes("Nombre;Precio\nBuzo;100\n"))


def test_duplicates_and_bad_rows():
    content = "Código;Stock;Precio\nA;1;10\nA;2;20\nB;dos;10\n"
    data = ci.parse_file("p.csv", csv_bytes(content))
    assert [r["code"] for r in data["rows"]] == ["A"]
    assert data["duplicates"][0]["code"] == "A" and data["errors"][0]["code"] == "B"


@override_settings(CONTABILIUM_MAX_FILE_MB=0)
def test_file_too_big():
    with pytest.raises(ci.ImportFileError, match="supera"):
        ci.parse_file("p.csv", b"x" * 10)


def test_unsupported_format():
    with pytest.raises(ci.ImportFileError, match="Formato"):
        ci.parse_file("p.pdf", b"%PDF")


# ── Vista previa y aplicar ───────────────────────────────────────────────


CSV = (
    "Código;Nombre;Stock;Precio;Precio Mayorista\n"
    "BUZ-001-M-NEG;Buzo M;12;45000;30000\n"
    "BUZ-001-L-NEG;Buzo L;3;45000;\n"
    "NUEVO-1;Producto nuevo;5;1000;800\n"
    "NUEVO-1;Repetido;5;1000;800\n"
)


def test_preview_writes_nothing(tn_catalog_loaded, admin_user):
    imp = ci.create_preview(filename="p.csv", content=csv_bytes(CSV), user=admin_user)
    s = imp.summary
    assert (s["total"], s["matched"], s["unmatched"], s["duplicates"], s["wholesale_changes"]) == (
        3,
        2,
        1,
        1,
        1,
    )
    assert not Listing.objects.filter(channel__code="contabilium").exists()
    assert not PriceListItem.objects.filter(price_list__code="MAYORISTA").exists()


def test_apply_links_loads_wholesale_and_keeps_stock(tn_catalog_loaded, admin_user):
    m, l_ = tn_catalog_loaded
    stock_before = StockLevel.objects.get(variant=m).on_hand
    imp = ci.create_preview(filename="p.csv", content=csv_bytes(CSV), user=admin_user)
    stats = ci.apply_import(imp, user=admin_user)
    assert stats == {"linked": 2, "unlinked": 1, "wholesale_updated": 1, "missing": 0}
    assert pricing.current_price(PriceList.objects.get(code="MAYORISTA"), m).price == Decimal("30000.00")
    assert StockLevel.objects.get(variant=m).on_hand == stock_before  # no toca el stock del sistema
    cb = ListingVariation.objects.get(
        listing__channel__code="contabilium", listing__external_id="BUZ-001-M-NEG"
    )
    assert cb.available_quantity == 12 and cb.variant == m
    imp.refresh_from_db()
    assert imp.status == "applied" and AuditLog.objects.filter(action="catalog.contabilium_imported").exists()


def test_apply_twice_is_rejected(tn_catalog_loaded, admin_user):
    imp = ci.create_preview(filename="p.csv", content=csv_bytes(CSV), user=admin_user)
    ci.apply_import(imp, user=admin_user)
    with pytest.raises(ci.ImportNotApplicable):
        ci.apply_import(imp, user=admin_user)


def test_wholesale_only_when_changed_and_missing_codes(tn_catalog_loaded, admin_user):
    ci.apply_import(
        ci.create_preview(filename="1.csv", content=csv_bytes(CSV), user=admin_user), user=admin_user
    )
    second = "Código;Precio Mayorista\nBUZ-001-M-NEG;30000\n"
    stats = ci.apply_import(
        ci.create_preview(filename="2.csv", content=csv_bytes(second), user=admin_user), user=admin_user
    )
    assert stats["wholesale_updated"] == 0 and stats["missing"] == 2
    assert Listing.objects.get(channel__code="contabilium", external_id="NUEVO-1").status == "missing"


@override_settings(CONTABILIUM_WHOLESALE_INCLUDES_VAT=True)
def test_wholesale_with_vat_is_divided(tn_catalog_loaded, admin_user):
    m, _ = tn_catalog_loaded
    content = "Código;Precio Mayorista\nBUZ-001-M-NEG;12100\n"
    ci.apply_import(
        ci.create_preview(filename="p.csv", content=csv_bytes(content), user=admin_user), user=admin_user
    )
    assert pricing.current_price(PriceList.objects.get(code="MAYORISTA"), m).price == Decimal("10000.00")


def test_apply_respects_manual_links(tn_catalog_loaded, admin_user):
    m, l_ = tn_catalog_loaded
    ci.apply_import(
        ci.create_preview(filename="1.csv", content=csv_bytes(CSV), user=admin_user), user=admin_user
    )
    row = ListingVariation.objects.get(listing__channel__code="contabilium", listing__external_id="NUEVO-1")
    linking.link_manual(row, l_, user=admin_user)
    ci.apply_import(
        ci.create_preview(filename="2.csv", content=csv_bytes(CSV), user=admin_user), user=admin_user
    )
    row.refresh_from_db()
    assert row.variant == l_ and row.link_source == "manual"


# ── Pantallas ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("q", ["BUZ-001-M", "canguro", "7790000000011"])
def test_catalog_search(admin_client, tn_catalog_loaded, q):
    content = admin_client.get(reverse("catalog:list"), {"q": q}).content.decode()
    assert "BUZ-001-M-NEG" in content


def test_catalog_filters(admin_client, tn_catalog_loaded):
    ml_listings.upsert_item(ml_samples.item())
    sin_ml = admin_client.get(reverse("catalog:list"), {"filtro": "sin_ml"}).context["variants"]
    assert list(sin_ml) == []
    sin_cb = admin_client.get(reverse("catalog:list"), {"filtro": "sin_contabilium"}).context["variants"]
    assert len(sin_cb) == 2


def test_detail_shows_all_channels(admin_client, tn_catalog_loaded, admin_user):
    m, _ = tn_catalog_loaded
    ml_listings.upsert_item(ml_samples.item())
    ci.apply_import(
        ci.create_preview(filename="p.csv", content=csv_bytes(CSV), user=admin_user), user=admin_user
    )
    content = admin_client.get(reverse("catalog:detail", args=[m.pk])).content.decode()
    assert "Variante 5001" in content and "MLA1001" in content and "Código BUZ-001-M-NEG" in content
    assert "30000" in content  # mayorista


def test_catalog_permissions(client, users_by_role, tn_catalog_loaded):
    expectations = {
        "catalog:list": {ADMIN, DEPOSITO, VENTAS, "Vendedor"},
        "catalog:unlinked": {ADMIN, VENTAS},
        "catalog:contabilium": {ADMIN},
        "catalog:channel_stock": {ADMIN, VENTAS},
        "catalog:quality": {ADMIN, VENTAS},
    }
    for url_name, allowed in expectations.items():
        for role, user in users_by_role.items():
            client.force_login(user)
            status = client.get(reverse(url_name)).status_code
            assert status == (200 if role in allowed else 403), f"{role} en {url_name}: {status}"


def test_unlinked_screen_search_and_link(client, users_by_role, tn_catalog_loaded):
    data = ml_samples.item()
    data["variations"][0]["attributes"] = [{"id": "SELLER_SKU", "value_name": "OTRO-SKU"}]
    ml_listings.upsert_item(data)
    client.force_login(users_by_role[VENTAS])
    page = client.get(reverse("catalog:unlinked")).content.decode()
    assert "OTRO-SKU" in page
    row = ml_row()
    results = client.get(
        reverse("catalog:variant_search"), {"q": "BUZ-001-M", "row": row.pk}
    ).content.decode()
    assert "BUZ-001-M-NEG" in results
    m, _ = tn_catalog_loaded
    client.post(reverse("catalog:link", args=[row.pk]), {"variant": m.pk})
    row.refresh_from_db()
    assert row.variant == m and row.link_source == "manual" and row.linked_by == users_by_role[VENTAS]


def test_replace_link_requires_confirmation(admin_client, tn_catalog_loaded):
    m, l_ = tn_catalog_loaded
    ml_listings.upsert_item(ml_samples.item())
    row = ml_row()
    admin_client.post(reverse("catalog:link", args=[row.pk]), {"variant": l_.pk})
    row.refresh_from_db()
    assert row.variant == m  # sin confirmar, no cambia
    admin_client.post(reverse("catalog:link", args=[row.pk]), {"variant": l_.pk, "confirm": "1"})
    row.refresh_from_db()
    assert row.variant == l_


def test_deposito_cannot_link(client, users_by_role, tn_catalog_loaded):
    ml_listings.upsert_item(ml_samples.item())
    client.force_login(users_by_role[DEPOSITO])
    assert client.post(reverse("catalog:link", args=[ml_row().pk]), {"action": "unlink"}).status_code == 403


def test_contabilium_upload_preview_confirm_discard(admin_client, tn_catalog_loaded):
    upload = SimpleUploadedFile("productos.csv", csv_bytes(CSV), content_type="text/csv")
    response = admin_client.post(reverse("catalog:contabilium"), {"archivo": upload})
    imp = ContabiliumImport.objects.get()
    assert response["Location"] == reverse("catalog:contabilium_preview", args=[imp.pk])
    page = admin_client.get(response["Location"]).content.decode()
    assert "Confirmar e importar" in page and "NUEVO-1" in page
    admin_client.post(reverse("catalog:contabilium_decide", args=[imp.pk]), {"action": "apply"})
    imp.refresh_from_db()
    assert imp.status == "applied"
    upload2 = SimpleUploadedFile("otro.csv", csv_bytes(CSV), content_type="text/csv")
    admin_client.post(reverse("catalog:contabilium"), {"archivo": upload2})
    second = ContabiliumImport.objects.first()
    admin_client.post(reverse("catalog:contabilium_decide", args=[second.pk]), {"action": "discard"})
    second.refresh_from_db()
    assert second.status == "discarded"


def test_contabilium_upload_bad_file_shows_error(admin_client):
    upload = SimpleUploadedFile("malo.csv", csv_bytes("Nombre\nX\n"), content_type="text/csv")
    response = admin_client.post(reverse("catalog:contabilium"), {"archivo": upload}, follow=True)
    assert "No encontré una columna de código" in response.content.decode()


# ── Stock y precio por canal ─────────────────────────────────────────────


@pytest.fixture
def three_channels(tn_catalog_loaded, admin_user):
    ml_listings.upsert_item(ml_samples.item())  # 111 → M (stock 10), 112 → L (stock 5)
    full = ml_samples.item(item_id="MLA-FULL", shipping={"logistic_type": "fulfillment"})
    full["variations"] = full["variations"][:1]
    full["variations"][0]["available_quantity"] = 7
    ml_listings.upsert_item(full)
    content = (
        "Código;Stock;Precio;Precio Mayorista\nBUZ-001-M-NEG;12;45000;30000\nBUZ-001-L-NEG;3;45000;30000\n"
    )
    ci.apply_import(
        ci.create_preview(filename="p.csv", content=csv_bytes(content), user=admin_user), user=admin_user
    )
    return tn_catalog_loaded


def test_channel_rows(three_channels):
    m, l_ = three_channels
    rows = {r.variant.sku: r for r in channel_view.build_rows(Variant.objects.all())}
    rm = rows["BUZ-001-M-NEG"]
    assert rm.stock == {"contabilium": 12, "tiendanube": 12, "ml_own": 10, "ml_full": 7, "mayorista": None}
    assert rm.stock_diff  # ML propio 10 ≠ 12
    assert rm.price["minorista"] == Decimal("45000.00") and rm.price["mayorista"] == Decimal("30000.00")
    assert rm.price["tiendanube"] == Decimal("39900.00")  # promo
    rl = rows["BUZ-001-L-NEG"]
    assert rl.stock["ml_own"] == 5 and rl.stock_diff  # 3 / 3 / 5


def test_channel_price_diff(three_channels):
    Listing.objects.filter(external_id="MLA1001").update(price=50000)
    ListingVariation.objects.filter(listing__external_id="MLA1001").update(price=50000)
    rows = {r.variant.sku: r for r in channel_view.build_rows(Variant.objects.all())}
    assert "mercadolibre" in rows["BUZ-001-M-NEG"].price_diff


def test_no_diff_when_equal(tn_catalog_loaded):
    rows = channel_view.build_rows(Variant.objects.all())
    assert not any(r.has_diff for r in rows)


def test_channel_view_screen_filter_and_excel(admin_client, three_channels):
    page = admin_client.get(reverse("catalog:channel_stock"), {"diferencias": "1"})
    assert len(page.context["rows"]) == 2
    response = admin_client.get(reverse("catalog:channel_stock"), {"formato": "xlsx"})
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    ws = load_workbook(io.BytesIO(response.content)).active
    assert ws["A1"].value == "SKU" and ws.max_row == 3


def test_channel_view_is_read_only(admin_client):
    assert admin_client.post(reverse("catalog:channel_stock")).status_code == 405


def test_channel_view_query_count(three_channels):
    with CaptureQueriesContext(connection) as ctx:
        channel_view.build_rows(Variant.objects.all())
    assert len(ctx.captured_queries) <= 6


# ── Calidad ──────────────────────────────────────────────────────────────


def codes_for(sku):
    return {i.code for i in quality.find_issues() if i.sku == sku}


def test_quality_detects_each_problem(three_channels, admin_user):
    m, l_ = three_channels
    p = Product.objects.create(name="Sin nada")
    bare = Variant.objects.create(
        product=p, sku="TN-9", needs_review=True, review_notes="Sin SKU en Tiendanube"
    )
    pricing.set_price(PriceList.objects.get(code="MINORISTA"), bare, Decimal("0"))
    issues = codes_for("TN-9")
    assert {"no_sku", "no_barcode", "no_photo", "price_zero", "no_weight", "no_dimensions"} <= issues
    assert "stock_diff" in codes_for("BUZ-001-M-NEG")
    assert "no_barcode" in codes_for("BUZ-001-L-NEG")


def test_quality_price_suspicious_and_missing_in_ml(tn_catalog_loaded):
    m, _ = tn_catalog_loaded
    pricing.set_price(PriceList.objects.get(code="MINORISTA"), m, Decimal("500"))
    issues = codes_for("BUZ-001-M-NEG")
    assert "price_suspicious" in issues and "missing_in_ml" in issues


def test_quality_unlinked_and_dup(tn_catalog_loaded, admin_user):
    data = ml_samples.item()
    data["variations"][0]["attributes"] = []  # sin SKU en ML
    data["variations"][1]["seller_custom_field"] = "NO-EXISTE"
    ml_listings.upsert_item(data)
    content = "Código;Stock\nBUZ-001-M-NEG;1\nBUZ-001-M-NEG;2\n"
    ci.apply_import(
        ci.create_preview(filename="p.csv", content=csv_bytes(content), user=admin_user), user=admin_user
    )
    all_issues = quality.find_issues()
    assert any(i.code == "no_sku" and "MLA1001:111" in i.detail for i in all_issues)
    assert any(i.code == "unlinked" and i.sku == "NO-EXISTE" for i in all_issues)
    assert "dup_sku" in codes_for("BUZ-001-M-NEG")


def test_quality_screen_filters_and_excel(admin_client, three_channels):
    page = admin_client.get(reverse("catalog:quality"), {"severidad": "critical"})
    assert all(i.severity == "critical" for i in page.context["issues"]) and page.context["issues"]
    page = admin_client.get(reverse("catalog:quality"), {"tipo": "no_barcode"})
    assert {i.code for i in page.context["issues"]} == {"no_barcode"}
    response = admin_client.get(reverse("catalog:quality"), {"formato": "xlsx"})
    ws = load_workbook(io.BytesIO(response.content)).active
    assert ws["A1"].value == "Severidad" and ws.max_row > 1


def test_quality_query_count(three_channels):
    with CaptureQueriesContext(connection) as ctx:
        quality.find_issues()
    assert len(ctx.captured_queries) <= 10


def test_channel_seed_has_contabilium():
    assert Channel.objects.filter(code="contabilium").exists()
