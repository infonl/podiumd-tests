"""ZAC's beheer of referentietabellen and mailtemplates, on run-tagged tables and templates of podiumd-tests.

The estate's tables and templates are only read; a system table only gets a request ZAC refuses.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.zac_beheer import MAILTEMPLATES
from podiumd_tests.zac_beheer import REFERENTIETABELLEN
from podiumd_tests.zac_beheer import VALUE_MAX_LENGTH
from podiumd_tests.zac_beheer import create_mailtemplate
from podiumd_tests.zac_beheer import create_referentietabel
from podiumd_tests.zac_beheer import delete_mailtemplate
from podiumd_tests.zac_beheer import delete_referentietabel
from podiumd_tests.zac_beheer import guard_referentietabel
from podiumd_tests.zac_beheer import has_same_values
from podiumd_tests.zac_beheer import mailtemplate
from podiumd_tests.zac_beheer import referentietabel
from podiumd_tests.zac_beheer import referentietabel_values
from podiumd_tests.zac_beheer import update_mailtemplate
from podiumd_tests.zac_beheer import update_referentietabel

if TYPE_CHECKING:
    import requests

    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "keycloak"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, beheer-zaps).",
    ),
]


@pytest.mark.scenario("""
    Given a new referentietabel with the values Een and Twee
    When the beheerder keeps Een, removes Twee and adds Drie
    Then the table holds Een and Drie
    When the beheerder deletes the table
    Then ZAC no longer lists it
""")
def test_referentietabel_is_created_edited_and_deleted(
    zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """A referentietabel's values are replaced by the saved list; a deleted table is gone."""
    zac_url = urls["zac"]
    tabel = referentietabel(zac, zac_url, str(create_referentietabel(zac, zac_url, registry, ["Een", "Twee"])["code"]))
    # ZAC ignores the saved order of values (zac-15).
    assert sorted(referentietabel_values(tabel)) == ["Een", "Twee"]

    een = next(value for value in entries(tabel["values"]) if value["name"] == "Een")
    expect_status(update_referentietabel(zac, zac_url, tabel, [een, {"name": "Drie"}]), HTTPStatus.OK)
    assert sorted(referentietabel_values(referentietabel(zac, zac_url, str(tabel["code"])))) == ["Drie", "Een"]

    expect_status(delete_referentietabel(zac, zac_url, tabel), HTTPStatus.NO_CONTENT)
    codes = [found.get("code") for found in get_entries(zac, zac_url + REFERENTIETABELLEN)]
    assert tabel["code"] not in codes


@pytest.mark.xfail(
    strict=True,
    reason="[zac-15] ZAC 5.9.1 keeps a referentietabel's values in creation order: it sorts on a sortOrder that its "
    "REST API never sets; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a new referentietabel with the values Een, Twee and Drie
    When the beheerder saves them in the order Drie, Een, Twee
    Then ZAC gives the values in that order
""")
def test_referentietabel_keeps_the_saved_order(
    zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """GET after a PUT with the values reordered returns them in the saved order."""
    zac_url = urls["zac"]
    code = str(create_referentietabel(zac, zac_url, registry, ["Een", "Twee", "Drie"])["code"])
    tabel = referentietabel(zac, zac_url, code)
    by_name = {str(value["name"]): value for value in entries(tabel["values"])}
    reordered = [by_name["Drie"], by_name["Een"], by_name["Twee"]]
    expect_status(update_referentietabel(zac, zac_url, tabel, reordered), HTTPStatus.OK)
    assert referentietabel_values(referentietabel(zac, zac_url, code)) == ["Drie", "Een", "Twee"]


@pytest.mark.scenario("""
    Given a new referentietabel
    When the beheerder saves a value of 1000 characters
    Then ZAC keeps it
    When the beheerder saves a value of 1001 characters
    Then ZAC refuses it and the table keeps the value of 1000 characters
""")
def test_referentietabel_value_holds_at_most_1000_characters(
    zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """ZAC refuses a referentietabel value longer than VALUE_MAX_LENGTH."""
    zac_url = urls["zac"]
    tabel = create_referentietabel(zac, zac_url, registry, [])
    longest = "x" * VALUE_MAX_LENGTH
    expect_status(update_referentietabel(zac, zac_url, tabel, [{"name": longest}]), HTTPStatus.OK)
    expect_status(update_referentietabel(zac, zac_url, tabel, [{"name": f"{longest}x"}]), HTTPStatus.BAD_REQUEST)
    assert referentietabel_values(referentietabel(zac, zac_url, str(tabel["code"]))) == [longest]


@pytest.mark.scenario("""
    Given ZAC's system referentietabel Communicatiekanaal with its system value E-formulier
    When the beheerder saves the table without its system values
    Then ZAC refuses it and the table keeps all its values
""")
def test_system_value_of_a_referentietabel_cannot_be_removed(
    zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """ZAC refuses a save of a referentietabel that drops a system value."""
    zac_url = urls["zac"]
    tabel = referentietabel(zac, zac_url, "COMMUNICATIEKANAAL")
    values = entries(tabel["values"])
    gewoon = [value for value in values if not value.get("systemValue")]
    if len(gewoon) == len(values):
        pytest.skip("ZAC's referentietabel COMMUNICATIEKANAAL has no system value")
    guard_referentietabel(zac, zac_url, registry, tabel)
    expect_status(update_referentietabel(zac, zac_url, tabel, gewoon), HTTPStatus.BAD_REQUEST)
    assert has_same_values(referentietabel(zac, zac_url, "COMMUNICATIEKANAAL"), tabel)


@pytest.mark.scenario("""
    Given a new mailtemplate for mail from a zaak
    When the beheerder changes its onderwerp and body
    Then ZAC shows the new onderwerp and body
    When the beheerder deletes it
    Then ZAC no longer has it
""")
def test_mailtemplate_is_created_edited_and_deleted(
    zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """A saved mailtemplate reads back as saved; a deleted one is gone."""
    zac_url = urls["zac"]
    template = create_mailtemplate(zac, zac_url, registry)
    assert template["id"] in [found.get("id") for found in get_entries(zac, zac_url + MAILTEMPLATES)]

    update_mailtemplate(zac, zac_url, template, onderwerp="Nieuw {ZAAK_NUMMER}", body="<p>Nieuwe tekst</p>")
    gelezen = expect_status(mailtemplate(zac, zac_url, template), HTTPStatus.OK).json()
    assert (gelezen["onderwerp"], gelezen["body"]) == ("Nieuw {ZAAK_NUMMER}", "<p>Nieuwe tekst</p>")

    delete_mailtemplate(zac, zac_url, template)
    assert mailtemplate(zac, zac_url, template).status_code == HTTPStatus.NOT_FOUND
