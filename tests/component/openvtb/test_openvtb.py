"""Open VTB: a verzoektype round trip through its API with the suite's own token."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openvtb", "cluster")]


@pytest.mark.core
@pytest.mark.source(
    "podiumd-tests",
    "Open VTB's API authenticates with a per-user token; a verzoektype is created, read and deleted with the suite's token.",
)
def test_verzoektype_roundtrip(openvtb_verzoeken: ApiClient, registry: ResourceRegistry) -> None:
    """A verzoektype created with a token reads back by url and is gone after DELETE (204)."""
    naam = registry.tagged("verzoektype")
    created = openvtb_verzoeken.post("verzoektypen", {"naam": naam})
    url = str(created["url"])
    registry.add(f"openvtb verzoektype {naam}", lambda: openvtb_verzoeken.delete(url))
    assert openvtb_verzoeken.get(url)["naam"] == naam
    openvtb_verzoeken.delete(url)
    openvtb_verzoeken.request("GET", url, 404)


@pytest.mark.core
@pytest.mark.source("podiumd-tests", "Component coverage of Open VTB 4.10 taken: a url-taak round trip.")
def test_urltaak_roundtrip(openvtb_taken: ApiClient, registry: ResourceRegistry) -> None:
    """A url-taak created with a token reads back by url and is gone after DELETE (204)."""
    titel = registry.tagged("urltaak")
    created = openvtb_taken.post(
        "urltaken",
        {
            "titel": titel,
            "einddatumHandelingsTermijn": "2026-01-10",
            "details": {"uitvraagLink": "http://example.invalid/"},
        },
    )
    url = str(created["url"])
    registry.add(f"openvtb urltaak {titel}", lambda: openvtb_taken.delete(url))
    assert openvtb_taken.get(url)["titel"] == titel
    openvtb_taken.delete(url)
    openvtb_taken.request("GET", url, 404)


@pytest.mark.source(
    "podiumd-tests", "Component coverage of Open VTB 4.10 berichten: a bericht created against a berichttype."
)
def test_bericht_needs_a_berichttype(
    openvtb_berichten: ApiClient, podiumd_env: Environment, registry: ResourceRegistry
) -> None:
    """A bericht created against a berichttype reads back (Open VTB 0.2.0 berichten API)."""
    berichttype = openvtb_berichten.post(
        "berichttypen",
        {"verantwoordelijkeOrganisatie": "urn:ptest:org", "mijnOverheidBerichtenbox": False, "bijlageTypen": []},
    )
    bt_url = str(berichttype["url"])
    onderwerp = registry.tagged("bericht")
    created = openvtb_berichten.post(
        "berichten",
        {"onderwerp": onderwerp, "berichtTekst": "ptest", "ontvanger": "urn:ptest:ontvanger:1", "berichtType": bt_url},
    )
    # Cleanup runs last-added first: delete the berichttype after the bericht, which it PROTECTs. The bericht
    # answers 405 to DELETE, so it goes through the Django shell.
    registry.add(f"openvtb berichttype {bt_url}", lambda: openvtb_berichten.delete(bt_url))
    registry.add(
        f"openvtb bericht {created['uuid']}", lambda: _delete_openvtb_bericht(podiumd_env, str(created["uuid"]))
    )
    assert openvtb_berichten.get(str(created["url"]))["onderwerp"] == onderwerp


def _delete_openvtb_bericht(podiumd_env: Environment, uuid: str) -> None:
    """Delete a bericht (and so free its berichttype) through Open VTB's Django shell; the API refuses it (405)."""
    code = f"from openvtb.components.berichten.models import Bericht\nBericht.objects.filter(uuid='{uuid}').delete()"
    podiumd_env.kube.exec_django_shell(podiumd_env.deployment_for("openvtb"), code)
