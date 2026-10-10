"""The klantcontactmedewerker in KISS and ITA: a browser login and the KISS register header."""

from __future__ import annotations

import json
import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.browser import challenge_login
from podiumd_tests.json_data import entries
from podiumd_tests.kube import metadata_name
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# KISS proxies Open Klant's klantinteracties API under this path.
KISS_KLANTCONTACTEN = "/api/klantinteracties/api/v1/klantcontacten"
# URLs in KISS's search content that point nowhere.
KENNIS_URL = "https://example.invalid/"


def kcc_login(page: Page, env: Environment, component: str) -> requests.Session:
    """The KCC test user's session in KISS ("kiss") or ITA ("ita")."""
    return challenge_login(page, env, env.profile.urls[component], KCC.username, env.credentials.get(KCC.store_key))


def kiss_register(kiss: requests.Session, kiss_url: str) -> dict[str, str]:
    """The header that sends a KISS proxy call to its default register (KISS has one per systeem)."""
    systemen = entries(expect_status(kiss.get(kiss_url + "/api/environment/registers"), 200).json()["systemen"])
    default = next(s for s in systemen if s.get("isDefault"))
    return {"systemIdentifier": str(default["identifier"])}


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


# ITA 3.3.2's access guard takes Open Klant's deprecated toegewezenAanActor (a bare reference to the
# first assigned actor) over the expanded actor with the same uuid: a groep assigned first is not seen
# as a groep. Fixed in ITA 3.3.4 (Interne-Taak-Afhandeling/ITA#582).
ITA_GROUP_ACCESS = pytest.mark.xfail(
    strict=True,
    raises=UnexpectedStatusError,
    reason="ITA 3.3.2 refuses a groep member a contactverzoek assigned to the groep first (403: its guard reads"
    " the deprecated toegewezenAanActor reference); fixed in ITA 3.3.4 (ITA#582)",
)


def kiss_sync_cronjob(env: Environment, source: str) -> str:
    """The name of KISS's elastic-sync CronJob for a search source (vac, kennisbank), e.g. contact-vac-sync."""
    names = [metadata_name(c) for c in env.items("cronjobs")]
    return next(n for n in names if n.endswith(f"-{source}-sync"))


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
        "vertalingen": [{"taal": "nl", "datumWijziging": today(), "titel": titel, "tekst": tekst}],
        "beschikbareTalen": ["nl"],
    }
