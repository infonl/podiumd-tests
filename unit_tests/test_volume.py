"""Unit tests for the volume seed: kinds, counts, corpus and report."""

import json

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest
import requests

from podiumd_tests.clients.api import ApiClient
from podiumd_tests.environment import Environment
from podiumd_tests.seed import volume
from podiumd_tests.seed.volume import KINDS
from podiumd_tests.seed.volume import SCALES
from podiumd_tests.seed.volume import VOLUME_ACTOR
from podiumd_tests.seed.volume import VOLUME_TAG
from podiumd_tests.seed.volume import Kind
from podiumd_tests.seed.volume import Seeded
from podiumd_tests.seed.volume import corpus
from podiumd_tests.seed.volume import counts
from podiumd_tests.seed.volume import faster
from podiumd_tests.seed.volume import format_seeded
from podiumd_tests.seed.volume import seed
from podiumd_tests.seed.volume import target
from podiumd_tests.seed.volume import unseed


def test_a_profile_setting_replaces_only_the_perf_count(profile_factory, fake_runner):
    env = Environment(profile_factory(settings={"seed_volume_zaken": "2000"}), fake_runner, environ={})
    assert target(env, "perf", "zaken") == 2000
    assert target(env, "smoke", "zaken") == SCALES["smoke"]["zaken"]
    assert target(env, "perf", "partijen") == SCALES["perf"]["partijen"]


def test_corpus_picks_wrap_around():
    names = corpus()
    assert names.persoon(len(names.personen)) == names.persoon(0)
    assert names.scenario(len(names.scenarios) + 1) == names.scenario(1)


def test_report_shows_counts_or_the_skip_reason():
    report = format_seeded([Seeded("zaken", 3, 50), Seeded("objecten", 0, 0, "skipped: no objecten")])
    assert report.splitlines() == ["zaken          3 -> 50", "objecten       skipped: no objecten"]


def test_zaken_in_zac_need_the_profile_setting(profile_factory, fake_runner):
    zaken_in_zac = next(k for k in KINDS if k.name == "zaken_in_zac")
    refused = Environment(profile_factory(), fake_runner, environ={})
    allowed = Environment(profile_factory(settings={"pabc_volume_zaaktype": "True"}), fake_runner, environ={})
    assert "pabc_volume_zaaktype" in str(zaken_in_zac.refused(refused))
    assert zaken_in_zac.refused(allowed) is None
    assert zaken_in_zac.target_kind == "zaken"


API = "https://api.example.test/v1"


def volume_env(profile, skipped=()) -> Environment:
    """An environment whose deployments are named after their component; `skipped` components are absent."""
    env = SimpleNamespace(
        profile=profile,
        kube="kube",
        deployment_for=lambda component: component,
        deployment_names=["openzaak", "openzaak-worker", "openklant"],
        capabilities=SimpleNamespace(skip_reason=lambda c: f"requires: {c}" if c in skipped else None),
        credentials=SimpleNamespace(get=lambda _key: "secret"),
    )
    return cast("Environment", env)


def kind(name: str) -> Kind:
    return next(k for k in KINDS if k.name == name)


def api() -> ApiClient:
    return ApiClient(requests.Session(), API, {})


@pytest.fixture
def snippets(monkeypatch):
    """Replaces run_snippet: install({name: answer(params)}) returns the list of (name, params) run."""
    ran = []

    def install(answers):
        def run(_kube, _deployment, name, params, _timeout=120):
            ran.append((name, params))
            return answers[name](params)

        monkeypatch.setattr(volume, "run_snippet", run)
        return ran

    return install


def posted(sent, path: str) -> list[dict[str, Any]]:
    return [json.loads(s.body) for s in sent if s.method == "POST" and s.url == f"{API}/{path}"]


def test_zaken_create_the_zaaktype_first_then_zaken_with_scenarios(monkeypatch, fake_http, snippets, profile_factory):
    ran = snippets({"openzaak_zaaktype": lambda params: {"present": False} if params["action"] == "status" else {}})
    monkeypatch.setattr(volume, "openzaak_client", lambda *_args: api())
    sent = fake_http(
        {
            "GET /v1/catalogi/api/v1/zaaktypen": (200, {"results": [{"url": "zt"}], "next": None}),
            "POST /v1/zaken/api/v1/zaken": (201, {"url": f"{API}/zaken/api/v1/zaken/z"}),
            "GET /v1/zaken/api/v1/zaken": (200, {"count": 2}),
        }
    )
    env = volume_env(profile_factory())
    kind("zaken").create(env, range(2), 1)
    assert [params["action"] for _, params in ran] == ["status", "apply"]
    zaken = posted(sent, "zaken/api/v1/zaken")
    assert [(z["zaaktype"], z["omschrijving"]) for z in zaken] == [("zt", corpus().scenario(i)[:80]) for i in range(2)]
    assert kind("zaken").count(env) == 2


def test_zaken_count_zero_without_the_zaaktype(monkeypatch, fake_http, profile_factory):
    monkeypatch.setattr(volume, "openzaak_client", lambda *_args: api())
    fake_http({"GET /v1/catalogi/api/v1/zaaktypen": (200, {"results": [], "next": None})})
    assert kind("zaken").count(volume_env(profile_factory())) == 0


@pytest.mark.parametrize(("settings", "reindexed"), [({"pabc_volume_zaaktype": "true"}, 1), ({}, 0)])
def test_deleting_zaken_reindexes_zac_when_allowed(monkeypatch, snippets, profile_factory, settings, reindexed):
    ran = snippets({"openzaak_zaaktype": lambda _params: {}})
    reindexes = []
    monkeypatch.setattr(volume, "reindex_zaken", reindexes.append)
    profile = profile_factory(urls={"zac": "https://zac.test"}, settings=settings)
    kind("zaken").delete_all(volume_env(profile))
    assert [params["action"] for _, params in ran] == ["remove"]
    assert len(reindexes) == reindexed


def test_partijen_mix_personen_and_organisaties(monkeypatch, fake_http, snippets, profile_factory):
    ran = snippets({"openklant_volume": lambda _params: {"count": 3}})
    monkeypatch.setattr(volume, "openklant_client", lambda _env: api())
    sent = fake_http({"POST /v1/partijen": (201, {"url": f"{API}/partijen/p"})})
    env = volume_env(profile_factory())
    kind("partijen").create(env, range(6, 8), 1)
    partijen = posted(sent, "partijen")
    assert [p["soortPartij"] for p in partijen] == ["persoon", "organisatie"]
    assert {p["interneNotitie"] for p in partijen} == {VOLUME_TAG}
    assert kind("partijen").count(env) == 3
    kind("partijen").delete_all(env)
    assert [params["action"] for _, params in ran] == ["count", "delete"]


def test_internetaken_are_assigned_to_a_created_volume_actor(monkeypatch, fake_http, profile_factory):
    monkeypatch.setattr(volume, "openklant_client", lambda _env: api())
    answers = {
        f"POST /v1/{p}": (201, {"url": f"{API}/{p}/x", "uuid": f"{p}-1"})
        for p in ("actoren", "klantcontacten", "internetaken")
    }
    sent = fake_http(answers | {"GET /v1/actoren": (200, {"results": [], "next": None})})
    kind("internetaken").create(volume_env(profile_factory()), range(1), 1)
    assert posted(sent, "actoren")[0]["naam"] == VOLUME_ACTOR
    assert posted(sent, "internetaken")[0]["toegewezenAanActoren"] == [{"uuid": "actoren-1"}]


class FakeAdmin:
    def __init__(self):
        self.created: list[str] = []
        self.joined: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def count_users(self, _tag):
        return len(self.created)

    def group_id(self, _name):
        return "g1"

    def new_password(self):
        return "pw"

    def create_user(self, username, _password, _attributes, _names):
        self.created.append(username)
        return username

    def join_group(self, user, group):
        self.joined.append((user, group))

    def users(self, _tag):
        return [{"id": u} for u in self.created]

    def delete_user(self, user):
        self.deleted.append(user)


def test_users_join_the_medewerkers_group(monkeypatch, profile_factory):
    admin = FakeAdmin()
    monkeypatch.setattr(volume, "for_environment", lambda _env: admin)
    env = volume_env(profile_factory())
    kind("users").create(env, range(2), 1)
    assert all(u.startswith(f"{VOLUME_TAG}-") and u == u.lower() for u in admin.created)
    assert admin.joined == [(u, "g1") for u in admin.created]
    assert kind("users").count(env) == 2
    kind("users").delete_all(env)
    assert admin.deleted == admin.created


def test_objecten_are_created_in_batches(snippets, profile_factory):
    ran = snippets(
        {"objecttypen_volume": lambda _params: {"uuid": "ot1"}, "objecten_volume": lambda _params: {"count": 5}}
    )
    env = volume_env(profile_factory())
    kind("objecten").create(env, range(450), 1)
    batches = [(p["start"], p["stop"], p["uuid"]) for name, p in ran if name == "objecten_volume"]
    assert batches == [(0, 200, "ot1"), (200, 400, "ot1"), (400, 450, "ot1")]
    assert kind("objecten").count(env) == 5
    del ran[:]
    kind("objecten").delete_all(env)
    assert [(name, p["action"]) for name, p in ran] == [
        ("objecttypen_volume", "status"),
        ("objecten_volume", "delete"),
        ("objecttypen_volume", "remove"),
    ]


def test_kiss_content_is_synced_after_create_and_delete(monkeypatch, snippets, profile_factory):
    ran = snippets({"objecten_tagged": lambda params: {"count": len(params["items"])}})
    jobs = []
    monkeypatch.setattr(volume, "kiss_sync_cronjob", lambda _env, sync: f"cron-{sync}")
    monkeypatch.setattr(volume, "run_cronjob", lambda _kube, cronjob, job: jobs.append((cronjob, job)))
    env = volume_env(profile_factory())
    kind("vac").create(env, range(3), 1)
    kind("vac").delete_all(env)
    assert [(p["action"], len(p["items"])) for _, p in ran] == [("create", 3), ("delete", 0)]
    assert jobs == [("cron-vac", f"{VOLUME_TAG}-vac-sync")] * 2
    assert kind("vac").count(env) == 0


@pytest.mark.parametrize(("known", "added", "deleted"), [(None, [VOLUME_TAG], []), ("et", [], ["et"])])
def test_zaken_in_zac_manage_the_pabc_entity_type(monkeypatch, profile_factory, known, added, deleted):
    adds, deletes, reindexes = [], [], []
    monkeypatch.setattr(volume, "admin_session", lambda *_args: "pabc-session")
    monkeypatch.setattr(volume, "zaaktype_entity_type", lambda *_args: known)
    monkeypatch.setattr(volume, "add_zaaktype_entity_type", lambda _session, _url, name: adds.append(name))
    monkeypatch.setattr(volume, "delete_entity_type", lambda _session, _url, entity: deletes.append(entity))
    monkeypatch.setattr(volume, "reindex_zaken", reindexes.append)
    monkeypatch.setattr(volume, "zac_session", lambda *_args: "zac-session")
    monkeypatch.setattr(volume, "count_zaken_found", lambda _session, _url, _tag: 7)
    env = volume_env(profile_factory(urls={"pabc": "https://pabc.test", "zac": "https://zac.test"}))
    kind("zaken_in_zac").create(env, range(1), 1)
    kind("zaken_in_zac").delete_all(env)
    assert (adds, deletes, reindexes) == (added, deleted, [env])
    assert kind("zaken_in_zac").count(env) == 7


def fake_kinds(monkeypatch, stored: dict[str, int]) -> None:
    def make(name, component):
        def create(_env, missing, _parallel):
            stored[name] += len(missing)

        def count(_env):
            if name not in stored:
                raise LookupError(name)
            return stored[name]

        return Kind(name, component, count, create, lambda _env: stored.update({name: 0}))

    kinds = (make("zaken", "openzaak"), make("users", "keycloak"), make("partijen", "openklant"))
    monkeypatch.setattr(volume, "KINDS", kinds)


def test_seed_tops_up_and_unseed_deletes_present_kinds(monkeypatch, profile_factory):
    stored = {"zaken": 1, "users": 5, "partijen": 0}
    fake_kinds(monkeypatch, stored)
    env = volume_env(profile_factory(), skipped=("openklant",))
    assert seed(env, "smoke", parallel=1) == [
        Seeded("zaken", 1, 3),
        Seeded("users", 5, 5),
        Seeded("partijen", 0, 0, "skipped: requires: openklant"),
    ]
    assert unseed(env) == [
        Seeded("partijen", 0, 0, "skipped: requires: openklant"),
        Seeded("users", 5, 0),
        Seeded("zaken", 3, 0),
    ]


def test_counts_are_none_where_skipped_or_failing(monkeypatch, profile_factory):
    fake_kinds(monkeypatch, {"zaken": 4})
    env = volume_env(profile_factory(), skipped=("openklant",))
    assert counts(env) == {"zaken": 4, "users": None, "partijen": None}


@pytest.mark.parametrize(("replicas", "expected"), [(3, [("openzaak", 3), ("openzaak-worker", 3)]), (0, [])])
def test_faster_scales_present_components_and_their_workers(monkeypatch, profile_factory, replicas, expected):
    scaled_to = []

    @contextmanager
    def scaled(_kube, deployment, count):
        scaled_to.append((deployment, count))
        yield

    monkeypatch.setattr(volume, "scaled", scaled)
    with faster(volume_env(profile_factory(), skipped=("openklant",)), replicas):
        assert scaled_to == expected
