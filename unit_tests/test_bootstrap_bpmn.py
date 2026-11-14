"""Unit tests for the BPMN process bootstrap step."""

import io
import json
import zipfile

from types import SimpleNamespace
from xml.etree import ElementTree as ET  # nosec B405  # parses the suite's own process

import pytest
import requests

from podiumd_tests.bootstrap import bpmn
from podiumd_tests.bootstrap.bpmn import PROCESS_KEY
from podiumd_tests.bootstrap.bpmn import ZacBpmnProcess
from podiumd_tests.bootstrap.bpmn import ZacBpmnProductaanvraag
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.names import BPMN_PRODUCTAANVRAAGTYPE
from podiumd_tests.bootstrap.names import ZAC_DOMAIN
from podiumd_tests.bootstrap.names import ZAC_FUNCTIONAL_ROLES
from podiumd_tests.bootstrap.runner import Context
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import STEPS
from podiumd_tests.bootstrap.zac import ZacCatalogusStep
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.credentials import env_var_name
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.seed.openzaak import published_zaaktype
from podiumd_tests.zac import HEROPEND

BPMN_MODEL = "http://www.omg.org/spec/BPMN/20100524/MODEL"
ZAAKTYPE = {
    "url": "https://oz/catalogi/api/v1/zaaktypen/zt-1/",
    "omschrijving": "ptest-bootstrap-bpmn",
    "concept": False,
}


class FakeOpenZaak:
    def __init__(self, zaaktypen):
        self.zaaktypen: list[dict[str, object]] = zaaktypen

    def list(self, _path, _params):
        return self.zaaktypen


class FakeResponse(SimpleNamespace):
    def json(self):
        return self.body


def test_published_zaaktype_skips_concepts_and_names_the_step():
    found = FakeOpenZaak([{**ZAAKTYPE, "concept": True}, ZAAKTYPE])
    assert published_zaaktype(found, "zt", "openzaak-zaaktype-bpmn") == ZAAKTYPE  # pyright: ignore[reportArgumentType]
    with pytest.raises(LookupError, match="openzaak-zaaktype-bpmn"):
        published_zaaktype(FakeOpenZaak([{**ZAAKTYPE, "concept": True}]), "zt", "openzaak-zaaktype-bpmn")  # pyright: ignore[reportArgumentType]
    assert uuid_of(ZAAKTYPE["url"]) == "zt-1"


def test_configuration_links_the_process_to_the_zaaktype(monkeypatch):
    monkeypatch.setattr(bpmn, "user_groups", lambda _http, _zac: ["beheerders"])
    body = ZacBpmnProcess(ADMIN).configuration(None, "https://zac", ZAAKTYPE)  # pyright: ignore[reportArgumentType]
    assert (body["zaaktypeUuid"], body["bpmnProcessDefinitionKey"], body["groepNaam"]) == (
        "zt-1",
        PROCESS_KEY,
        "beheerders",
    )
    # A link left for a deleted zaaktype must neither block the next one nor break ZAC's list of links.
    assert "productaanvraagtype" not in body
    assert "zaakNietOntvankelijkResultaattype" not in body


LINK = {"bpmnProcessDefinitionKey": PROCESS_KEY, "zaaktypeUuid": "zt-1"}


ALL = ("raadpleger", "behandelaar", "coordinator", "recordmanager", "beheerder", "brp_zoeken")
BASE = ALL[:-1]


def mapped(short=0, *, brp_zoeken=True):
    """A fake domain_mappings: each role's count of application roles minus `short`; 0 for the brp_zoeken role."""
    return lambda _pabc, _url, role: (
        0 if not brp_zoeken and role.endswith("brp-zoeken") else len(ZAC_FUNCTIONAL_ROLES[role]) - short
    )


@pytest.mark.parametrize(
    ("keys", "links", "mappings", "known", "present"),
    [
        ([PROCESS_KEY], [LINK], mapped(), ALL, True),
        ([PROCESS_KEY], [{**LINK, "zaaktypeUuid": "zt-old"}], mapped(), ALL, False),
        ([PROCESS_KEY], [{**LINK, "zaakNietOntvankelijkResultaattype": {"id": "rt-1"}}], mapped(), ALL, False),
        ([], [LINK], mapped(), ALL, False),
        ([PROCESS_KEY], [LINK], mapped(1), ALL, False),
        # PABC without brp_zoeken (podiumd chart 4.9): its role is not wanted.
        (
            [PROCESS_KEY],
            [LINK],
            mapped(brp_zoeken=False),
            BASE,
            True,
        ),
        (
            [PROCESS_KEY],
            [LINK],
            mapped(brp_zoeken=False),
            ALL,
            False,
        ),
    ],
)
@pytest.mark.parametrize(
    ("deployed", "as_deployed"),
    [(bpmn.process_files, True), (lambda: None, True), (lambda: {"other.bpmn": ""}, False)],
    ids=["same-files", "no-download", "changed-files"],
)
def test_present_needs_the_process_a_link_and_the_pabc_roles(
    monkeypatch, keys, links, mappings, known, present, deployed, as_deployed
):
    answers = {bpmn.DEFINITIONS: [{"key": k} for k in keys], bpmn.CONFIGURATION: links}
    http = SimpleNamespace(get=lambda url: FakeResponse(status_code=200, body=answers[url.removeprefix("https://zac")]))
    step = ZacBpmnProcess(ADMIN)
    monkeypatch.setattr(ZacBpmnProcess, "_zac", lambda _self, _ctx: (http, "https://zac"))
    monkeypatch.setattr(bpmn, "_openzaak", lambda _ctx: FakeOpenZaak([ZAAKTYPE]))
    monkeypatch.setattr(ZacBpmnProcess, "_pabc", lambda _self, _ctx: (None, "https://pabc"))
    monkeypatch.setattr(bpmn, "application_roles", lambda _pabc, _url, _app: [{"name": n} for n in known])
    monkeypatch.setattr(bpmn, "domain_mappings", mappings)
    monkeypatch.setattr(bpmn, "deployed_files", lambda _http, _zac, _key: deployed())
    assert step.is_present(None) is (present and as_deployed)  # pyright: ignore[reportArgumentType]


def test_present_is_false_without_the_zaaktype(monkeypatch):
    monkeypatch.setattr(bpmn, "_openzaak", lambda _ctx: FakeOpenZaak([]))
    assert ZacBpmnProcess(ADMIN).is_present(None) is False  # pyright: ignore[reportArgumentType]


class FakePabc:
    """Records the step's PABC calls; entity_type is PABC's entity type of the zaaktype, known its application roles."""

    def __init__(self, monkeypatch, *, entity_type=None, known=ALL):
        self.calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(bpmn, "find_entity_type", lambda _pabc, _url, _name: entity_type)
        monkeypatch.setattr(bpmn, "add_entity_type", self._record("add_entity_type", "et-new"))
        monkeypatch.setattr(bpmn, "delete_entity_type", self._record("delete_entity_type"))
        monkeypatch.setattr(bpmn, "ensure_domain", self._record("ensure_domain", "dom-1"))
        monkeypatch.setattr(bpmn, "ensure_functional_role", self._record("ensure_functional_role"))
        monkeypatch.setattr(bpmn, "delete_roles_and_domain", self._record("delete_roles_and_domain"))
        monkeypatch.setattr(bpmn, "application_roles", lambda _pabc, _url, _app: [{"name": n} for n in known])

    def named(self, name):
        return [call[1:] for call in self.calls if call[0] == name]

    def _record(self, name, answer=None):
        def call(_pabc, _url, *args):
            self.calls.append((name, *args))
            return answer

        return call


@pytest.fixture
def ctx(env_factory, profile_factory, monkeypatch):
    env = env_factory(
        profile_factory(urls={"zac": "https://zac.example.test", "pabc": "https://pabc.example.test"}),
        {env_var_name(ADMIN.store_key): "pw"},
    )
    monkeypatch.setattr(bpmn, "zac_session", lambda *_: requests.Session())
    monkeypatch.setattr(bpmn, "admin_session", lambda *_: requests.Session())
    monkeypatch.setattr(bpmn, "openzaak_client", lambda *_: FakeOpenZaak([ZAAKTYPE]))
    monkeypatch.setattr(bpmn, "user_groups", lambda _http, _zac: ["beheerders"])
    return Context(env, CredentialStore(env.kube))


FORMS = f"{bpmn.DEFINITIONS}/{PROCESS_KEY}/forms"
FORM_COUNT = len(list(bpmn.FILES.glob("*.json")))
DEPLOYED = {
    f"POST {bpmn.DEFINITIONS}": (201, {}),
    f"POST {FORMS}": (201, {}),
    f"POST {bpmn.CONFIGURATION}": (200, {}),
    # The zaaktype's link, with the productaanvraagtype of step zac-bpmn-productaanvraag.
    f"GET {bpmn.CONFIGURATION}": (200, [{**LINK, "id": 4, "productaanvraagtype": BPMN_PRODUCTAANVRAAGTYPE}]),
}


def test_apply_deploys_the_process_its_forms_and_the_link(ctx, fake_http, monkeypatch):
    pabc = FakePabc(monkeypatch)
    sent = fake_http(DEPLOYED)
    assert ZacBpmnProcess(ADMIN).apply(ctx) == {}
    posts = [s.url.removeprefix("https://zac.example.test") for s in sent if s.method == "POST"]
    assert posts == [bpmn.DEFINITIONS, *(FORMS for _ in range(FORM_COUNT)), bpmn.CONFIGURATION]
    stored = json.loads(sent[-1].body)
    assert (stored["zaaktypeUuid"], stored["id"], stored["productaanvraagtype"]) == (
        "zt-1",
        4,
        BPMN_PRODUCTAANVRAAGTYPE,
    )
    assert pabc.named("add_entity_type") == [("ptest-bootstrap-bpmn",)]
    assert pabc.named("ensure_domain") == [(ZAC_DOMAIN, ["et-new"])]
    assert {call[0] for call in pabc.named("ensure_functional_role")} == set(ZAC_FUNCTIONAL_ROLES)
    assert ctx.notes == []


def test_apply_reuses_the_entity_type_and_notes_roles_pabc_lacks(ctx, fake_http, monkeypatch):
    pabc = FakePabc(monkeypatch, entity_type="et-1", known=BASE)
    fake_http(DEPLOYED)
    ZacBpmnProcess(ADMIN).apply(ctx)
    assert pabc.named("add_entity_type") == []
    assert pabc.named("ensure_domain") == [(ZAC_DOMAIN, ["et-1"])]
    assert ctx.notes == ["not mapped, PABC lacks their application roles: ptest-bootstrap-zac-brp-zoeken"]


def test_apply_fails_when_zac_refuses_the_process(ctx, fake_http, monkeypatch):
    FakePabc(monkeypatch)
    fake_http({f"POST {bpmn.DEFINITIONS}": (400, {"detail": "invalid"})})
    with pytest.raises(UnexpectedStatusError, match="400"):
        ZacBpmnProcess(ADMIN).apply(ctx)


CONFIGURATION = f"GET {bpmn.CONFIGURATION}"
STORE = f"POST {bpmn.CONFIGURATION}"


@pytest.mark.parametrize(
    ("links", "present"),
    [
        ([{**LINK, "productaanvraagtype": BPMN_PRODUCTAANVRAAGTYPE}], True),
        ([LINK], False),
        ([{**LINK, "zaaktypeUuid": "zt-old", "productaanvraagtype": BPMN_PRODUCTAANVRAAGTYPE}], False),
        ([], False),
    ],
)
def test_productaanvraag_present_needs_the_type_on_the_zaaktypes_link(ctx, fake_http, links, present):
    fake_http({CONFIGURATION: (200, links)})
    assert ZacBpmnProductaanvraag(ADMIN).is_present(ctx) is present


def test_productaanvraag_apply_sets_the_type_on_the_link(ctx, fake_http):
    sent = fake_http({CONFIGURATION: (200, [{**LINK, "groepNaam": "g"}]), STORE: (200, {})})
    assert ZacBpmnProductaanvraag(ADMIN).apply(ctx) == {}
    stored = json.loads(sent[-1].body)
    assert (stored["productaanvraagtype"], stored["groepNaam"]) == (BPMN_PRODUCTAANVRAAGTYPE, "g")


def test_productaanvraag_apply_needs_the_link(ctx, fake_http):
    fake_http({CONFIGURATION: (200, [])})
    with pytest.raises(LookupError, match="zac-bpmn-process"):
        ZacBpmnProductaanvraag(ADMIN).apply(ctx)


@pytest.mark.parametrize(("productaanvraagtype", "stores"), [(BPMN_PRODUCTAANVRAAGTYPE, 1), ("another", 0)])
def test_productaanvraag_remove_clears_only_its_own_type(ctx, fake_http, productaanvraagtype, stores):
    sent = fake_http({CONFIGURATION: (200, [{**LINK, "productaanvraagtype": productaanvraagtype}]), STORE: (200, {})})
    assert ZacBpmnProductaanvraag(ADMIN).remove(ctx) == ()
    posts = [json.loads(s.body) for s in sent if s.method == "POST"]
    assert len(posts) == stores
    assert all(post["productaanvraagtype"] is None for post in posts)


@pytest.mark.parametrize(
    ("status", "entity_type", "deleted", "notes"),
    [(204, "et-1", [("et-1",)], 1), (404, None, [], 1), (500, "et-1", [("et-1",)], 2)],
)
def test_remove_deletes_forms_process_and_pabc_objects(
    ctx, fake_http, monkeypatch, status, entity_type, deleted, notes
):
    pabc = FakePabc(monkeypatch, entity_type=entity_type)
    sent = fake_http({f"DELETE {bpmn.DEFINITIONS}/{PROCESS_KEY}": (status, {})})
    assert ZacBpmnProcess(ADMIN).remove(ctx) == ()
    assert len([s for s in sent if s.method == "DELETE"]) == FORM_COUNT + 1
    assert pabc.named("delete_roles_and_domain") == [(ZAC_FUNCTIONAL_ROLES, ZAC_DOMAIN)]
    assert pabc.named("delete_entity_type") == deleted
    # Only a refused delete of the process adds a note; the note on the zaaktype link stays last.
    assert len(ctx.notes) == notes
    assert ctx.notes[-1].startswith("zaaktype-bpmn-configuration")


def test_bpmn_zaaktype_has_heropend_before_its_eindstatus_and_clears_zacs_cache():
    step = next(step for step in STEPS if step.name == "openzaak-zaaktype-bpmn")
    assert isinstance(step, ZacCatalogusStep)
    statustypen = step.params["statustypen"]
    assert HEROPEND in statustypen[:-1]  # pyright: ignore[reportIndexIssue]


def test_process_files_are_the_process_and_its_forms_by_file_name():
    files = bpmn.process_files()
    assert f"{PROCESS_KEY}.bpmn" in files
    assert len([name for name in files if name.endswith(".json")]) == FORM_COUNT


def test_deploy_process_posts_the_model_before_its_forms(fake_http):
    sent = fake_http({f"POST {bpmn.DEFINITIONS}": (201, {}), f"POST {bpmn.DEFINITIONS}/k/forms": (201, {})})
    bpmn.deploy_process(requests.Session(), "https://zac", "k", {"f.json": "{}", "k.bpmn": "<x/>"})
    assert [json.loads(s.body)["filename"] for s in sent] == ["k.bpmn", "f.json"]


def test_deployed_files_reads_the_download_and_is_none_without_one(fake_http, monkeypatch):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("k.bpmn", "<x/>")
    fake_http({f"GET {bpmn.DEFINITIONS}/k/download": (200, {})})
    monkeypatch.setattr(requests.Response, "content", property(lambda _self: archive.getvalue()))
    assert bpmn.deployed_files(requests.Session(), "https://zac", "k") == {"k.bpmn": "<x/>"}
    fake_http({})
    assert bpmn.deployed_files(requests.Session(), "https://zac", "k") is None


def test_complete_intake_assigns_and_chooses_the_eindstatus(fake_http):
    intake = {"id": "t1", "naam": bpmn.INTAKE, "status": "TOEGEKEND", "taakdata": {}}
    sent = fake_http({"GET /rest/taken/zaak/z1": (200, [intake]), "PATCH /rest/taken/complete": (200, intake)})
    bpmn.complete_intake(requests.Session(), "https://zac", {"uuid": "z1"}, ("g1", "bob"), extra="x")
    assert json.loads(sent[-1].body)["taakdata"] == {
        "AM_TeamBehandelaar_Groep": "g1",
        "AM_TeamBehandelaar_Medewerker": "bob",
        "ZK_Status": bpmn.EINDSTATUS,
        "ZK_Result": bpmn.EINDSTATUS,
        "extra": "x",
    }


def test_complete_keuze_sends_the_actie_and_its_fields(fake_http):
    keuze = {"id": "t2", "naam": bpmn.KEUZE, "status": "TOEGEKEND", "taakdata": {"ptestActie": "status"}}
    sent = fake_http({"GET /rest/taken/zaak/z1": (200, [keuze]), "PATCH /rest/taken/complete": (200, keuze)})
    bpmn.complete_keuze(requests.Session(), "https://zac", {"uuid": "z1"}, "opschorten", ptestDagen=3)
    assert json.loads(sent[-1].body)["taakdata"] == {"ptestActie": "opschorten", "ptestDagen": 3}


def test_process_is_xml_with_the_named_tasks_and_the_keuze_route():
    model = bpmn.process_files()[f"{PROCESS_KEY}.bpmn"]
    process = ET.fromstring(model)  # noqa: S314  # nosec B314  # the suite's own file
    names = {task.get("name") for task in process.iter(f"{{{BPMN_MODEL}}}userTask")}
    wanted = {bpmn.INTAKE, bpmn.SELECT, bpmn.SIGN, bpmn.SUMMARY, bpmn.HARDCODED, bpmn.INHERITED}
    assert wanted | {bpmn.KEUZE, bpmn.TERMIJN, bpmn.VORIGE} <= names
    assert f"var:getOrDefault({bpmn.KEUZE_ROUTE}, false)" in model


def test_process_names_the_hardcoded_assignment():
    model = bpmn.process_files()[f"{PROCESS_KEY}.bpmn"]
    groep, behandelaar = bpmn.HARDCODED_TO
    assert f"flowable:assignee={json.dumps(behandelaar)}" in model
    assert f"flowable:candidateGroups={json.dumps(groep)}" in model
