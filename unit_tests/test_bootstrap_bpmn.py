"""Unit tests for the BPMN process bootstrap step."""

from types import SimpleNamespace

import pytest

from podiumd_tests.bootstrap import bpmn
from podiumd_tests.bootstrap.bpmn import PROCESS_KEY
from podiumd_tests.bootstrap.bpmn import ZacBpmnProcess
from podiumd_tests.bootstrap.bpmn import bpmn_zaaktype
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.names import ZAC_FUNCTIONAL_ROLES
from podiumd_tests.bootstrap.steps import ADMIN

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


def test_bpmn_zaaktype_is_the_published_version():
    assert bpmn_zaaktype(FakeOpenZaak([{**ZAAKTYPE, "concept": True}, ZAAKTYPE])) == ZAAKTYPE  # pyright: ignore[reportArgumentType]
    with pytest.raises(LookupError, match="openzaak-zaaktype-bpmn"):
        bpmn_zaaktype(FakeOpenZaak([{**ZAAKTYPE, "concept": True}]))  # pyright: ignore[reportArgumentType]
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
def test_present_needs_the_process_a_link_and_the_pabc_roles(monkeypatch, keys, links, mappings, known, present):
    answers = {bpmn.DEFINITIONS: [{"key": k} for k in keys], bpmn.CONFIGURATION: links}
    http = SimpleNamespace(get=lambda url: FakeResponse(status_code=200, body=answers[url.removeprefix("https://zac")]))
    step = ZacBpmnProcess(ADMIN)
    monkeypatch.setattr(ZacBpmnProcess, "_zac", lambda _self, _ctx: (http, "https://zac"))
    monkeypatch.setattr(bpmn, "_openzaak", lambda _ctx: FakeOpenZaak([ZAAKTYPE]))
    monkeypatch.setattr(ZacBpmnProcess, "_pabc", lambda _self, _ctx: (None, "https://pabc"))
    monkeypatch.setattr(bpmn, "application_roles", lambda _pabc, _url, _app: [{"name": n} for n in known])
    monkeypatch.setattr(bpmn, "domain_mappings", mappings)
    assert step.is_present(None) is present  # pyright: ignore[reportArgumentType]


def test_present_is_false_without_the_zaaktype(monkeypatch):
    monkeypatch.setattr(bpmn, "_openzaak", lambda _ctx: FakeOpenZaak([]))
    assert ZacBpmnProcess(ADMIN).is_present(None) is False  # pyright: ignore[reportArgumentType]
