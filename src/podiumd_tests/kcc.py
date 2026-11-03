"""The klantcontactmedewerker in KISS and ITA: a browser login and the KISS register header."""

from __future__ import annotations

import json
import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest
import yaml

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.browser import challenge_login
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.responses import expect_status
from podiumd_tests.results import now_iso
from podiumd_tests.seed.openzaak import today
from podiumd_tests.workloads import component_versions

if TYPE_CHECKING:
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# KISS proxies Open Klant's klantinteracties API under this path.
KISS_KLANTCONTACTEN = "/api/klantinteracties/api/v1/klantcontacten"
# URLs in KISS's search content that point nowhere.
KENNIS_URL = "https://example.invalid/"


def kcc_login(page: Page, env: Environment, component: str, user: KeycloakUser = KCC) -> requests.Session:
    """A test user's session (default the KCC user) in KISS ("kiss") or ITA ("ita"), logged in in the browser.

    ITA starts a login only for a browser navigation; KISS also takes oidc.challenge_session.
    """
    return challenge_login(page, env, env.profile.urls[component], user.username, env.credentials.get(user.store_key))


def kiss_register(kiss: requests.Session, kiss_url: str) -> dict[str, str]:
    """The header that sends a KISS proxy call to its Open Klant 2 register, the default one first.

    Skips when KISS has none: its klantinteracties proxy answers 400 for an e-Suite register (OpenKlant1).
    """
    systemen = entries(expect_status(kiss.get(kiss_url + "/api/environment/registers"), 200).json()["systemen"])
    openklant2 = sorted(
        (s for s in systemen if s.get("registryVersion") == "OpenKlant2"), key=lambda s: not s.get("isDefault")
    )
    if not openklant2:
        pytest.skip("KISS has no Open Klant 2 register (REGISTERS__<n>__REGISTRY_VERSION=OpenKlant2), only e-Suite")
    return {"systemIdentifier": str(openklant2[0]["identifier"])}


def kiss_klantcontact(
    kiss: requests.Session, kiss_url: str, openklant: ApiClient, registry: ResourceRegistry, body: JsonObject
) -> JsonObject:
    """Register a klantcontact through KISS; Open Klant's copy of it.

    KISS does not delete klantcontacten (DELETE answers 405); cleanup goes to Open Klant.
    """
    response = kiss.post(kiss_url + KISS_KLANTCONTACTEN, json=body, headers=kiss_register(kiss, kiss_url))
    created = expect_status(response, HTTPStatus.CREATED).json()
    registry.add(f"klantcontact {created['url']}", lambda: openklant.delete(str(created["url"])))
    return openklant.get(f"klantcontacten/{created['uuid']}")


def ita_detail_text(ita: requests.Session, ita_url: str, taak: JsonObject) -> str:
    """ITA's detail of the contactverzoek, as JSON text: what the KCC user sees on its detail page.

    ITA shows it to members of the groep the taak is assigned to (ITA_GROEP for the KCC test user,
    bootstrap objecten-medewerker-kcc).
    """
    return json.dumps(expect_status(ita.get(f"{ita_url}/api/internetaken/{taak['nummer']}"), HTTPStatus.OK).json())


# ITA answers 409 with this when Objecten refuses its logboek POST.
LOGBOEK_FORBIDDEN = "403 (Forbidden)"
LOGBOEK_HINT = (
    "on a Traefik edge without request-body buffering for Objecten, uWSGI reads ITA's chunked .NET body as empty"
    " (NGINX Gateway Fabric always buffers): set bufferRequestBody on the objecten ingress"
)


def add_klantcontact(ita: requests.Session, ita_url: str, body: JsonObject) -> requests.Response:
    """ITA's answer to an internetaak; UnexpectedStatusError, with the edge cause for Objecten's 403, otherwise."""
    response = ita.post(f"{ita_url}/api/klantcontacten/add-klantcontact", json=body)
    try:
        return expect_status(response, HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.NO_CONTENT)
    except UnexpectedStatusError as error:
        if response.status_code == HTTPStatus.CONFLICT and LOGBOEK_FORBIDDEN in response.text:
            msg = f"{error}; {LOGBOEK_HINT}"
            raise UnexpectedStatusError(msg) from error
        raise


# ITA before 3.3.4 takes Open Klant's deprecated toegewezenAanActor (a bare reference to the first
# assigned actor) over the expanded actor with the same uuid: a groep assigned first is not seen as a
# groep (Interne-Taak-Afhandeling/ITA#582).
ITA_GROUP_ACCESS_FIXED = (3, 3, 4)


def expect_ita_group_access_bug(request: pytest.FixtureRequest, env: Environment) -> None:
    """Mark the test a strict xfail when the deployed ITA is older than 3.3.4."""
    version = component_versions(env, ["ita"]).get("ita")
    if version is not None and version < ITA_GROUP_ACCESS_FIXED:
        request.applymarker(
            pytest.mark.xfail(
                strict=True,
                raises=UnexpectedStatusError,
                reason="ITA before 3.3.4 refuses a groep member a contactverzoek assigned to the groep first"
                " (403: its guard reads the deprecated toegewezenAanActor reference; ITA#582)",
            )
        )


def kiss_sync_cronjob(env: Environment, source: str) -> str:
    """The name of KISS's elastic-sync CronJob for a search source (vac, kennisbank), e.g. contact-vac-sync."""
    names = [metadata_name(c) for c in env.items("cronjobs")]
    return next(n for n in names if n.endswith(f"-{source}-sync"))


def kiss_website_crawlers(env: Environment) -> dict[str, str]:
    """KISS's website crawler CronJobs (kiss.settings.syncJobs.website), each with the URL it crawls.

    The KISS chart names the Secret with the crawler's crawler.yml after its CronJob.
    """
    names = [n for n in (metadata_name(c) for c in env.items("cronjobs")) if "-crawler-website-" in n]
    return {
        n: str(entries(yaml.safe_load(env.kube.secret_value(n, "crawler.yml")).get("domains"))[0]["url"]) for n in names
    }


def kiss_search_hits(kiss: requests.Session, kiss_url: str, query: str) -> list[JsonObject]:
    """The hits of KISS's search for the query in all its sources."""
    response = kiss.post(kiss_url + "/api/search", json={"query": query, "page": 1, "filters": []})
    return entries(section(expect_status(response, HTTPStatus.OK).json(), "hits").get("hits"))


def vac_data(titel: str, antwoord: str = "Antwoord van podiumd-tests.") -> dict[str, object]:
    """A VAC (vraag-antwoordcombinatie) for Objecten with the title as its question."""
    return {"vraag": titel, "antwoord": antwoord, "doelgroep": "eu-burger", "status": "actief"}


def kennisartikel_data(titel: str, tekst: str = "Tekst van podiumd-tests.") -> dict[str, object]:
    """An SDG kennisartikel for Objecten with the title in its Dutch translation, at KENNIS_URL + title."""
    return {
        "url": KENNIS_URL + quote(titel),
        "uuid": str(uuid.uuid4()),
        "upnUri": KENNIS_URL + "upn",
        "publicatieDatum": today(),
        "productAanwezig": True,
        "productValtOnder": None,
        "verantwoordelijkeOrganisatie": {
            "url": KENNIS_URL + "organisatie",
            "owmsIdentifier": KENNIS_URL + "owms",
            "owmsEndDate": "2099-12-31T00:00:00Z",
        },
        "locaties": None,
        "doelgroep": "eu-burger",
        "vertalingen": [{"taal": "nl", "datumWijziging": now_iso(), "titel": titel, "tekst": tekst}],
        "beschikbareTalen": ["nl"],
    }
