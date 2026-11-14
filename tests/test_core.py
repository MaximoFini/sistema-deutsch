import logging

import pytest

from apps.core import sources
from apps.core.logging import MaskSecretsFilter, mask_mapping, mask_text
from apps.core.models import DataSource
from apps.core.sentry import scrub_event

pytestmark = pytest.mark.django_db


def test_health_ok(client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json()["db"] is True


def test_all_data_types_start_owned_by_contabilium():
    assert DataSource.objects.count() == 5
    for data_type in DataSource.DataType.values:
        assert sources.source_of(data_type) == "contabilium"
        assert not sources.is_owned_by_system(data_type)


def test_changing_source_is_reflected_and_guard_works():
    with pytest.raises(sources.SourceOfTruthViolation):
        sources.ensure_system_owned("stock")
    sources.set_source("stock", "system")
    assert sources.is_owned_by_system("stock")
    sources.ensure_system_owned("stock")  # no levanta


def test_unknown_data_type_defaults_to_contabilium():
    DataSource.objects.filter(data_type="price").delete()
    assert sources.source_of("price") == "contabilium"


def test_mask_text_hides_tokens():
    text = 'GET /x?access_token=abc123 {"refresh_token": "zzz"} Authorization: Bearer eyJhbGci.x.y'
    masked = mask_text(text)
    assert "abc123" not in masked and "zzz" not in masked and "eyJhbGci" not in masked


def test_mask_mapping_recursive():
    data = {"user": "x", "password": "p", "nested": [{"client_secret": "s", "ok": 1}]}
    assert mask_mapping(data) == {
        "user": "x",
        "password": "***",
        "nested": [{"client_secret": "***", "ok": 1}],
    }


def test_log_filter_masks_message(caplog):
    logger = logging.getLogger("test.mask")
    logger.addFilter(MaskSecretsFilter())
    with caplog.at_level(logging.INFO):
        logger.info("token=%s", "SUPERSECRETO")
    assert "SUPERSECRETO" not in caplog.text


def test_sentry_scrub():
    event = {
        "request": {"headers": {"Authorization": "Bearer abc", "Accept": "json"}, "data": {"password": "x"}},
        "exception": {"values": [{"value": "fallo con access_token=qwerty"}]},
    }
    scrubbed = scrub_event(event)
    assert scrubbed["request"]["headers"]["Authorization"] == "***"
    assert scrubbed["request"]["data"]["password"] == "***"
    assert "qwerty" not in scrubbed["exception"]["values"][0]["value"]
