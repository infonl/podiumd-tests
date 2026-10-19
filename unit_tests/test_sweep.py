"""Unit tests for run ids and finding stale leftovers."""

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import requests

from podiumd_tests import sweep as sweep_module
from podiumd_tests.bootstrap import Outcome
from podiumd_tests.capabilities import Capabilities
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.credentials import env_var_name
from podiumd_tests.results import new_run_id
from podiumd_tests.results import run_started
from podiumd_tests.sweep import FINDERS
from podiumd_tests.sweep import Swept
from podiumd_tests.sweep import format_swept
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


def test_format_swept():
    assert format_swept([Swept("zaak", "z/1", "deleted"), Swept("form", "", "skipped", "requires: cluster")]) == (
        "deleted  zaak                 z/1\nskipped  form                  requires: cluster"
    )
    assert format_swept([]) == "nothing to sweep"


OLD = f"ptest-{new_run_id(NOW - timedelta(days=2))}"
FRESH = f"ptest-{new_run_id(NOW)}"


@pytest.fixture
def swept_env(env_factory, profile_factory, monkeypatch):
    """Sweep with Mailpit and Open Formulieren present and only the openklant-token step in place."""

    def build(present):
        env = env_factory(profile_factory(urls={"mailpit": "https://mailpit.example.test"}))
        env.__dict__["capabilities"] = Capabilities(frozenset(present), {})
        monkeypatch.setattr(sweep_module, "check", lambda *_: [Outcome("openklant-token", "present")])
        return env

    return build


def test_sweep_deletes_stale_mails_and_forms_and_skips_what_it_cannot_reach(swept_env, fake_http, monkeypatch):
    messages = [{"ID": "m1", "Subject": f"{OLD}-mail"}, {"ID": "m2", "Subject": f"{FRESH}-mail"}]
    sent = fake_http({"GET /api/v1/search": (200, {"messages": messages}), "DELETE /api/v1/messages": (200, {})})
    removed = []
    monkeypatch.setattr(sweep_module, "tagged_forms", lambda _env: [f"{OLD}-form", f"{FRESH}-form"])
    monkeypatch.setattr(sweep_module, "remove_form", lambda _env, slug: removed.append(slug))
    swept = sweep_module.sweep(
        swept_env({"mailpit", "openformulieren", "cluster"}), NOW - timedelta(hours=24), dry_run=False
    )
    by_action = {(s.kind, s.action, s.name) for s in swept if s.action != "skipped"}
    assert by_action == {("mail", "deleted", f"{OLD}-mail"), ("form", "deleted", f"{OLD}-form")}
    assert removed == [f"{OLD}-form"]
    assert [s.method for s in sent].count("DELETE") == 2  # one per Mailpit finder
    skipped = {s.kind: s.detail for s in swept if s.action == "skipped"}
    assert skipped["zaak"].startswith("requires: openzaak")


def test_sweep_names_a_missing_bootstrap_step_and_a_missing_cluster(swept_env, fake_http):
    fake_http()
    swept = sweep_module.sweep(swept_env({"openzaak"}), NOW, dry_run=True)
    skipped = {s.kind: s.detail for s in swept if s.action == "skipped"}
    assert skipped["zaak"] == "bootstrap step openzaak-client missing"
    assert skipped["form"].startswith("requires: openformulieren")


@pytest.mark.parametrize(
    ("dry_run", "delete_status", "action"), [(True, 200, "found"), (False, 500, "failed")], ids=["dry-run", "failed"]
)
def test_sweep_dry_run_and_failed_deletes(swept_env, fake_http, dry_run, delete_status, action):
    messages = [{"ID": "m1", "Subject": f"{OLD}-mail"}]
    sent = fake_http(
        {"GET /api/v1/search": (200, {"messages": messages}), "DELETE /api/v1/messages": (delete_status, {})}
    )
    swept = sweep_module.sweep(swept_env({"mailpit"}), NOW - timedelta(hours=24), dry_run=dry_run)
    mails = [s for s in swept if s.kind == "mail"]
    assert {(s.action, s.name) for s in mails} == {(action, f"{OLD}-mail")}
    assert all(s.detail.startswith("UnexpectedStatusError: DELETE") for s in mails if s.action == "failed")
    assert any(s.method == "DELETE" for s in sent) is not dry_run


@pytest.mark.parametrize("kind", ["besluit", "productaanvraag zaak", "abonnement", "partij"])
def test_finders_list_and_delete_with_their_own_client(env_factory, profile_factory, fake_http, kind):
    finder = next(f for f in FINDERS if f.kind == kind)
    urls = dict.fromkeys(("openzaak", "opennotificaties", "openklant", "objecten"), API)
    keys = ("zgw_secret", "zgw_productaanvraag_secret", "nrc_secret", "openklant_token", "objecten_token")
    environ = {env_var_name(f"ptest_bootstrap_{k}"): "s3cret" for k in keys}
    item = {"url": f"{API}/item/1"}
    env = env_factory(profile_factory(urls=urls), environ)
    client = finder.client(env)
    listed = client.url(finder.path).removeprefix(API)
    sent = fake_http({"GET /api/v2/objects": (200, []), "DELETE /item/1": (204, None), f"GET {listed}": (200, [item])})
    assert finder.items(env, client) == [item]
    finder.delete(client)(item)
    assert sent[-1].method == "DELETE"
