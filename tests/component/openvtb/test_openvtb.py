"""Open VTB: verzoeken, taken and berichten through its APIs with the suite's own token."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import differences
from podiumd_tests.json_data import section
from podiumd_tests.mock_server import Callback
from podiumd_tests.responses import invalid_names
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.opennotificaties import make_cloudevent_abonnement
from podiumd_tests.seed.openvtb import BERICHT_EVENTS
from podiumd_tests.seed.openvtb import PROFILE_FIELDS
from podiumd_tests.seed.openvtb import PUBLISH_TASK
from podiumd_tests.seed.openvtb import TAAK_DETAILS
from podiumd_tests.seed.openvtb import enabled_schedules
from podiumd_tests.seed.openvtb import make_bericht
from podiumd_tests.seed.openvtb import make_taak
from podiumd_tests.seed.openvtb import missing_celery
from podiumd_tests.seed.openvtb import publish_bericht
from podiumd_tests.seed.openvtb import taak_body
from podiumd_tests.seed.openvtb import without
from podiumd_tests.seed.openvtb import zaak_urn
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
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
    created = make_taak(openvtb_taken, registry, "urltaken")
    url = str(created["url"])
    assert openvtb_taken.get(url)["titel"] == created["titel"]
    openvtb_taken.delete(url)
    openvtb_taken.request("GET", url, 404)


MIJN_SERVICES = "external VNG-Realisatie/mijn-services-documentatie docs/mijn-services/"
TAKEN_PROFILE = f"{MIJN_SERVICES}aansluitprofielen/openvtb-taken-api/v0.1"


@pytest.mark.requires("openzaak")
@pytest.mark.source(
    f"{MIJN_SERVICES}scenarios/ontbrekende-informatie-aanleveren.md",
    "Scenario 'Ontbrekende informatie aanleveren' and the Open VTB Taken aansluitprofiel at API level: no PodiumD"
    " portal shows Open VTB taken yet.",
)
@pytest.mark.scenario("""
    Given a zaak of an inwoner in Open Zaak
    When the behandelaar asks the inwoner for missing information as a taak on that zaak
    Then Open VTB lists the taak as the zaak's open taak, with every field Mijn Taken shows
    When the inwoner has done the taak and the behandelaar has processed it
    Then the zaak has no open taak left and the taak reads back as verwerkt
""")
def test_taak_on_a_zaak_is_found_and_completed(
    openvtb_taken: ApiClient, openzaak: ApiClient, test_zaaktype: JsonObject, registry: ResourceRegistry
) -> None:
    """An externe taak related to a zaak's URN is listed by that URN while open, and moves to uitgevoerd and verwerkt."""
    urn = zaak_urn(make_zaak(openzaak, registry, str(test_zaaktype["url"])))
    created = make_taak(
        openvtb_taken,
        registry,
        "urltaken",
        isGerelateerdAan=[{"urn": urn}],
        isToegewezenAan=f"urn:nld:brp:bsn:{random_bsn()}",
        handelingsPerspectief="informatie_geven",
        toelichting="Lever het ontbrekende bewijsstuk aan.",
    )
    taak = f"externetaken/{created['uuid']}"

    def open_taken() -> list[object]:
        return [
            found["uuid"] for found in openvtb_taken.list("externetaken", {"isGerelateerdAan": urn, "status": "open"})
        ]

    read = openvtb_taken.get(taak)
    assert [field for field in PROFILE_FIELDS if field not in read] == []
    assert (read["taakSoort"], read["status"], read["isGerelateerdAan"]) == ("urltaak", "open", [{"urn": urn}])
    assert open_taken() == [created["uuid"]]
    openvtb_taken.patch(taak, {"status": "uitgevoerd"})
    assert open_taken() == []
    openvtb_taken.patch(taak, {"status": "verwerkt"})
    assert openvtb_taken.get(taak)["status"] == "verwerkt"


@pytest.mark.parametrize(("endpoint", "soort"), [("betaaltaken", "betaaltaak"), ("formuliertaken", "formuliertaak")])
@pytest.mark.source(TAKEN_PROFILE, "The aansluitprofiel reads every taak soort through externetaken, by taakSoort.")
@pytest.mark.scenario("""
    When the behandelaar creates a betaaltaak or a formuliertaak for an inwoner
    Then Open VTB returns it as an externe taak of that soort with the details given
""")
def test_taak_soort_reads_back_as_externe_taak(
    openvtb_taken: ApiClient, registry: ResourceRegistry, endpoint: str, soort: str
) -> None:
    """A betaaltaak or formuliertaak reads back through externetaken with its taakSoort and details."""
    created = make_taak(openvtb_taken, registry, endpoint)
    read = openvtb_taken.get(f"externetaken/{created['uuid']}")
    assert read["taakSoort"] == soort
    assert differences(TAAK_DETAILS[endpoint], read["details"]) == []


@pytest.mark.parametrize(
    ("endpoint", "field"),
    [
        ("urltaken", "titel"),
        ("urltaken", "einddatumHandelingsTermijn"),
        ("urltaken", "uitvraagLink"),
        ("betaaltaken", "bedrag"),
        ("betaaltaken", "transactieomschrijving"),
        ("betaaltaken", "doelrekening"),
        ("formuliertaken", "formulierDefinitie"),
    ],
)
@pytest.mark.source(TAKEN_PROFILE, "The aansluitprofiel's OpenAPI snapshot lists the required fields per taak soort.")
@pytest.mark.scenario("""
    When a client creates a taak without one of its required fields
    Then Open VTB refuses it as a bad request naming that field
""")
def test_taak_without_a_required_field_is_refused(
    openvtb_taken: ApiClient, registry: ResourceRegistry, endpoint: str, field: str
) -> None:
    """A taak missing a required field answers 400 naming the field, not 500."""
    body = without(taak_body(registry, endpoint), field)
    response = openvtb_taken.request("POST", endpoint, 400, json=body)
    assert any(name.endswith(field) for name in invalid_names(response)), response.text


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


# Open VTB's worker and Open Notificaties each hand the event on in a background task.
EVENT_TIMEOUT = 120
SOURCE_IN_3501 = (
    "Jira IN-3501",
    "Open VTB's Celery worker and beat send its bericht CloudEvents through Open Notificaties.",
)


def expect_celery(env: Environment) -> None:
    """Fail where Open VTB runs without its worker or beat: then no bericht event ever leaves Open VTB."""
    failure = missing_celery(env)
    if failure:
        pytest.fail(failure)


@pytest.mark.requires("opennotificaties")
@pytest.mark.source(*SOURCE_IN_3501)
@pytest.mark.scenario("""
    Given a subscriber in Open Notificaties to Open VTB's bericht events
    When a client creates a bericht in Open VTB
    Then the subscriber gets the event that the bericht was registered
    When Open VTB publishes the bericht
    Then the subscriber gets the event that the bericht was published
""")
def test_bericht_events_reach_open_notificaties_subscribers(  # the chain's clients
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    run_tag: str,
    openvtb_berichten: ApiClient,
    opennotificaties: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """Open VTB's worker sends bericht-geregistreerd and bericht-gepubliceerd to Open Notificaties as CloudEvents."""
    need_bootstrap("infra-mock-server")
    expect_celery(podiumd_env)
    callback = Callback.new(podiumd_env, run_tag)
    make_cloudevent_abonnement(opennotificaties, registry, callback.url, BERICHT_EVENTS)
    bericht = make_bericht(podiumd_env, openvtb_berichten, registry, f"urn:nld:brp:bsn:{random_bsn()}")
    uuid = str(bericht["uuid"])

    def event(kind: str) -> Callable[[JsonObject], bool]:
        def is_wanted(entry: JsonObject) -> bool:
            body = section(entry, "body")
            return body.get("type") == f"{BERICHT_EVENTS}{kind}" and body.get("subject") == uuid

        return is_wanted

    callback.wait_for(
        event("bericht-geregistreerd"), timeout=EVENT_TIMEOUT, description=f"bericht-geregistreerd {uuid}"
    )
    publish_bericht(podiumd_env, uuid)
    callback.wait_for(event("bericht-gepubliceerd"), timeout=EVENT_TIMEOUT, description=f"bericht-gepubliceerd {uuid}")


@pytest.mark.source(*SOURCE_IN_3501)
@pytest.mark.scenario("""
    Given Open VTB with its worker and beat
    When the beat looks at its schedule
    Then it publishes the berichten whose publicatiedatum has passed, on a schedule that is switched on
""")
def test_due_berichten_are_published_on_a_schedule(podiumd_env: Environment) -> None:
    """Open VTB's beat has an enabled periodic task send_berichten_events."""
    expect_celery(podiumd_env)
    assert enabled_schedules(podiumd_env, PUBLISH_TASK), "Open VTB has no enabled periodic task send_berichten_events"
