"""Unit tests for run ids and finding stale leftovers."""

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import requests

from podiumd_tests import sweep as sweep_module
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.results import new_run_id
from podiumd_tests.results import run_started
from podiumd_tests.sweep import is_stale
from podiumd_tests.sweep import parse_age
from podiumd_tests.sweep import with_productaanvraag

if TYPE_CHECKING:
    from podiumd_tests.json_data import JsonObject

API = "https://api.example.test"
NOW = datetime(2026, 10, 7, 12, 30, tzinfo=UTC)


def test_run_id_carries_its_start_minute():
    run_id = new_run_id(NOW)
    assert run_id.startswith("2610071230") and len(run_id) == 14
    assert run_started(run_id) == NOW
    assert run_started("a1b2c3") is None
    assert run_started("260000000000aa") is None  # month 00


def test_stale_by_the_tag_anywhere_in_the_object():
    old = {"omschrijving": f"ptest-{new_run_id(NOW - timedelta(days=2))}-zaak"}
    fresh = {"record": {"data": {"bron": {"kenmerk": f"ptest-{new_run_id(NOW)}-productaanvraag"}}}}
    cutoff = NOW - timedelta(hours=24)
    assert is_stale(old, cutoff)
    assert not is_stale(fresh, cutoff)


def test_legacy_tags_are_stale_and_bootstrap_objects_never():
    cutoff = NOW - timedelta(hours=24)
    assert is_stale({"naam": "ptest-4d4a3d-actor-12"}, cutoff)
    assert not is_stale({"naam": "ptest-bootstrap-kcc", "identificatie": "ptest-bootstrap-klacht"}, cutoff)
    assert not is_stale({"naam": "someone else's actor"}, cutoff)


@pytest.mark.parametrize(
    ("text", "age"), [("30m", timedelta(minutes=30)), ("24h", timedelta(hours=24)), ("7d", timedelta(days=7))]
)
def test_parse_age(text, age):
    assert parse_age(text) == age


def test_parse_age_refuses_other_units():
    with pytest.raises(ValueError, match="expected a number with m, h or d"):
        parse_age("1w")


def test_a_zaak_of_a_run_tagged_productaanvraag_is_stale(monkeypatch, fake_http, env_factory):
    tagged = {"url": "o/1", "record": {"data": {"aanvraaggegevens": f"ptest-{new_run_id(NOW)}-formulier"}}}
    zaken: list[JsonObject] = [
        {"url": "z/1", "toelichting": "kenmerk 'OF-1'"},
        {"url": "z/2", "toelichting": "kenmerk 'OF-2'"},
    ]
    fake_http(
        {
            "/objects": (200, [tagged, {"url": "o/2", "record": {}}]),
            "/zaken/api/v1/zaakobjecten": (200, [{"zaak": "z/1"}]),
        }
    )
    monkeypatch.setattr(sweep_module, "objecten_client", lambda _env: ApiClient(requests.Session(), API, {}))
    found = with_productaanvraag(env_factory(), ApiClient(requests.Session(), API, {}), zaken)
    assert [is_stale(z, NOW + timedelta(hours=1)) for z in found] == [True, False]
