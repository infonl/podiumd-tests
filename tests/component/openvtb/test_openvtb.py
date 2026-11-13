"""Open VTB: a verzoektype round trip through its API with the suite's own token."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openvtb import make_bericht

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
@pytest.mark.scenario("""
    When a client creates a verzoektype in Open VTB with the suite's token
    Then the verzoektype reads back with its naam
    When the client deletes the verzoektype
    Then Open VTB no longer finds it
""")
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
@pytest.mark.scenario("""
    When a client creates a url-taak in Open VTB with the suite's token
    Then the url-taak reads back with its titel
    When the client deletes the url-taak
    Then Open VTB no longer finds it
""")
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
@pytest.mark.scenario("""
    Given a berichttype in Open VTB
    When a client creates a bericht of that berichttype
    Then the bericht reads back with its onderwerp
""")
def test_bericht_needs_a_berichttype(
    openvtb_berichten: ApiClient, podiumd_env: Environment, registry: ResourceRegistry
) -> None:
    """A bericht created against a berichttype reads back (Open VTB 0.2.0 berichten API)."""
    created = make_bericht(podiumd_env, openvtb_berichten, registry, "urn:ptest:ontvanger:1")
    assert openvtb_berichten.get(str(created["url"]))["onderwerp"] == registry.tagged("bericht")
