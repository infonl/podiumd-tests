"""The klantcontactmedewerker in KISS and ITA: a browser login and the KISS register header."""

from __future__ import annotations

import json
import uuid

from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest
import yaml

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.browser import challenge_login
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_name
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.responses import expect_status
from podiumd_tests.results import now_iso
from podiumd_tests.seed.openklant import delete_klantcontact_tree
from podiumd_tests.seed.openklant import klantcontact_body
from podiumd_tests.seed.openzaak import today
from podiumd_tests.workloads import expect_defect

if TYPE_CHECKING:
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# KISS proxies Open Klant's klantinteracties API under this path.
KISS_KLANTINTERACTIES = "/api/klantinteracties/api/v1"
# KISS's own route for a new klantcontact: it links the logged-in medewerker as actor.
KISS_POST_KLANTCONTACTEN = "/api/postklantcontacten"
KISS_CONTACTMOMENTDETAILS = "/api/contactmomentdetails"
KISS_POST_INTERNETAAK = "/api/postinternetaak"
# The codeObjecttype KISS gives the actor of a contactverzoek (getActorConfig); ITA reads afd and grp.
KISS_ACTOR_CODES = {"afdeling": "afd", "groep": "grp", "medewerker": "mdw"}
# URLs in KISS's search content that point nowhere.
KENNIS_URL = "https://example.invalid/"


def kcc_login(page: Page, env: Environment, component: str, user: KeycloakUser = KCC) -> requests.Session:
    """Return a test user's session (default the KCC user) in KISS ("kiss") or ITA ("ita"), logged in in the browser.

    ITA starts a login only for a browser navigation; KISS also takes oidc.challenge_session.
    """
    return challenge_login(page, env, env.profile.urls[component], user.username, env.credentials.get(user.store_key))


def kiss_register(kiss: requests.Session, kiss_url: str) -> dict[str, str]:
    """Return the header that sends a KISS proxy call to its Open Klant 2 register, the default one first.

    Skips when KISS has none: its klantinteracties proxy answers 400 for an e-Suite register (OpenKlant1).
    """
    systemen = entries(expect_status(kiss.get(f"{kiss_url}/api/environment/registers"), 200).json()["systemen"])
    openklant2 = sorted(
        (systeem for systeem in systemen if systeem.get("registryVersion") == "OpenKlant2"),
        key=lambda systeem: not systeem.get("isDefault"),
    )
    if not openklant2:
        found = ", ".join(f"{systeem.get('identifier')} ({systeem.get('registryVersion')})" for systeem in systemen)
        pytest.skip(f"KISS has no Open Klant 2 register, only {found}: its klantcontacten go to the e-Suite")
    return {"systemIdentifier": str(openklant2[0]["identifier"])}


def kiss_klantcontact(
    kiss: requests.Session, kiss_url: str, openklant: ApiClient, registry: ResourceRegistry, body: JsonObject
) -> JsonObject:
    """Register a klantcontact as KISS's frontend does; Open Klant's copy of it.

    KISS links the logged-in medewerker as actor. KISS does not delete klantcontacten; cleanup goes to Open Klant.
    """
    response = kiss.post(kiss_url + KISS_POST_KLANTCONTACTEN, json=body, headers=kiss_register(kiss, kiss_url))
    created = expect_status(response, HTTPStatus.OK).json()
    url = str(created["url"])
    registry.add(f"klantcontact {url}", lambda: delete_klantcontact_tree(openklant, url))
    return openklant.get(f"klantcontacten/{created['uuid']}")


def kiss_betrokkene(
    kiss: requests.Session, kiss_url: str, klantcontact: JsonObject, partij: JsonObject | None
) -> JsonObject:
    """Add the klant to a klantcontact through KISS's proxy, as KISS's frontend does; cleanup is the klantcontact's."""
    body: dict[str, object] = {
        "wasPartij": {"uuid": partij["uuid"]} if partij else None,
        "hadKlantcontact": {"uuid": klantcontact["uuid"]},
        "rol": "klant",
        "initiator": True,
        "organisatienaam": "",
        "contactnaam": {"voorletters": "P", "voornaam": "PodiumD", "voorvoegselAchternaam": "", "achternaam": "test"},
    }
    url = f"{kiss_url}{KISS_KLANTINTERACTIES}/betrokkenen"
    return expect_status(kiss.post(url, json=body, headers=kiss_register(kiss, kiss_url)), HTTPStatus.CREATED).json()


def kiss_klantcontacten(kiss: requests.Session, kiss_url: str, **params: str) -> list[JsonObject]:
    """Return the klantcontacten KISS lists for a query, e.g. a partij's on its Contactmomenten tab."""
    response = kiss.get(
        f"{kiss_url}{KISS_KLANTINTERACTIES}/klantcontacten", params=params, headers=kiss_register(kiss, kiss_url)
    )
    return entries(expect_status(response, HTTPStatus.OK).json().get("results"))


def kiss_actor(  # noqa: PLR0913, PLR0917  # the KISS session, cleanup and the actor
    kiss: requests.Session, kiss_url: str, openklant: ApiClient, registry: ResourceRegistry, soort: str, naam: str
) -> JsonObject:
    """Create the actor (afdeling, groep or medewerker) for a contactverzoek as KISS's frontend does.

    KISS reuses an actor with the same identificator; each test creates its own, so a parallel test's cleanup
    cannot delete it. naam is also its identificatie.
    """
    body = {
        "naam": naam,
        "soortActor": "medewerker" if soort == "medewerker" else "organisatorische_eenheid",
        "indicatieActief": True,
        "actoridentificator": {
            "objectId": naam,
            "codeObjecttype": KISS_ACTOR_CODES[soort],
            "codeRegister": "obj",
            "codeSoortObjectId": "idf",
        },
    }
    response = kiss.post(f"{kiss_url}{KISS_KLANTINTERACTIES}/actoren", json=body, headers=kiss_register(kiss, kiss_url))
    actor = expect_status(response, HTTPStatus.CREATED).json()
    registry.add(f"actor {actor['url']}", lambda: openklant.delete(str(actor["url"])))
    return actor


def kiss_contactverzoek(  # noqa: PLR0913, PLR0917  # one flow
    kiss: requests.Session,
    kiss_url: str,
    openklant: ApiClient,
    registry: ResourceRegistry,
    actoren: list[JsonObject],
    adres: str,
    partij: JsonObject | None = None,
) -> JsonObject:
    """Register a contactverzoek as KISS's frontend does; its internetaak in Open Klant.

    The klant leaves a phone number, or an e-mail address when adres has an @. Cleanup is the klantcontact's.
    """
    onderwerp = registry.tagged("contactverzoek")
    body = klantcontact_body(registry, onderwerp=onderwerp, inhoud=f"Vraag {onderwerp}")
    klantcontact = kiss_klantcontact(kiss, kiss_url, openklant, registry, body)
    betrokkene = kiss_betrokkene(kiss, kiss_url, klantcontact, partij)
    register = kiss_register(kiss, kiss_url)
    digitaal_adres = {
        "verstrektDoorBetrokkene": {"uuid": betrokkene["uuid"]},
        "verstrektDoorPartij": None,
        "adres": adres,
        "soortDigitaalAdres": "email" if "@" in adres else "telefoonnummer",
        "omschrijving": "onbekend",
    }
    response = kiss.post(f"{kiss_url}{KISS_KLANTINTERACTIES}/digitaleadressen", json=digitaal_adres, headers=register)
    expect_status(response, HTTPStatus.CREATED)
    taak = {
        "nummer": "",
        "gevraagdeHandeling": "Contact opnemen met betrokkene",
        "aanleidinggevendKlantcontact": {"uuid": klantcontact["uuid"]},
        "toegewezenAanActoren": [{"uuid": actor["uuid"]} for actor in actoren],
        "toelichting": registry.tagged("toelichting"),
        "status": "te_verwerken",
    }
    created = expect_status(
        kiss.post(kiss_url + KISS_POST_INTERNETAAK, json=taak, headers=register), HTTPStatus.CREATED
    )
    return openklant.get(f"internetaken/{created.json()['uuid']}")


def internetaken_of(klantcontacten: list[JsonObject]) -> list[str]:
    """Return the uuids of the internetaken the klantcontacten (expanded with leiddeTotInterneTaken) led to."""
    return [
        str(taak.get("uuid"))
        for klantcontact in klantcontacten
        for taak in entries(section(klantcontact, "_expand").get("leiddeTotInterneTaken"))
    ]


def kiss_contactverzoeken_by_adres(kiss: requests.Session, kiss_url: str, adres: str) -> list[str]:
    """Return the uuids of the internetaken KISS's contactverzoek search finds by a phone number or e-mail address."""
    params = {"adres": adres, "expand": "verstrektDoorBetrokkene"}
    response = kiss.get(
        f"{kiss_url}{KISS_KLANTINTERACTIES}/digitaleadressen", params=params, headers=kiss_register(kiss, kiss_url)
    )
    betrokkenen = {
        str(section(section(found, "_expand"), "verstrektDoorBetrokkene").get("uuid"))
        for found in entries(expect_status(response, HTTPStatus.OK).json().get("results"))
    }
    return [
        uuid
        for betrokkene in sorted(betrokkenen)
        for uuid in internetaken_of(
            kiss_klantcontacten(kiss, kiss_url, hadBetrokkene__uuid=betrokkene, expand="leiddeTotInterneTaken")
        )
    ]


def kiss_medewerkers(kiss: requests.Session, kiss_url: str, search: str, groep: str) -> list[JsonObject]:
    """Return the smoelenboek entries KISS's contactverzoek form offers for a search within a groep."""
    body = {"search": search, "filterField": "Smoelenboek.groepen.groepsnaam", "filterValue": groep}
    response = kiss.post(f"{kiss_url}/api/search/medewerkers", json=body)
    hits = entries(section(expect_status(response, HTTPStatus.OK).json(), "hits").get("hits"))
    return [section(section(hit, "_source"), "Smoelenboek") for hit in hits]


def kiss_contactmomentdetails(
    kiss: requests.Session, kiss_url: str, klantcontact: JsonObject, **fields: object
) -> JsonObject:
    """Store KISS's own details of a contactmoment (gespreksresultaat, afdeling, bronnen) and read them back.

    KISS keeps them in its database by the klantcontact's URL and has no call to delete them.
    """
    body: dict[str, object] = {
        "id": klantcontact["url"],
        "startdatum": now_iso(),
        "einddatum": now_iso(),
        "bronnen": [],
    }
    body.update(fields)
    expect_status(kiss.put(kiss_url + KISS_CONTACTMOMENTDETAILS, json=body), HTTPStatus.OK)
    found = kiss.get(kiss_url + KISS_CONTACTMOMENTDETAILS, params={"id": str(klantcontact["url"])})
    return expect_status(found, HTTPStatus.OK).json()


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
    expect_defect(
        request,
        env,
        "ita",
        lambda version: version < ITA_GROUP_ACCESS_FIXED,
        raises=UnexpectedStatusError,
        reason="ITA before 3.3.4 refuses a groep member a contactverzoek assigned to the groep first"
        " (403: its guard reads the deprecated toegewezenAanActor reference; ITA#582)",
    )


SATURDAY = 5
# ITA's urgency in weekday hours where the environment does not set it (Urgentie__* of ITA after 3.4.0).
ITA_TERMIJN_HOURS = 48
ITA_BIJNA_VERLOPEN_HOURS = 6


def _ita_hours(env: Environment, variable: str, default: int) -> int:
    try:
        return int(env.kube.exec(env.deployment_for("ita"), "printenv", variable, timeout=30).strip())
    except (KubeError, ValueError):
        return default


def ita_afhandeltermijn_hours(env: Environment) -> int:
    """ITA's afhandeltermijn in weekday hours, after which a contactverzoek is overdue."""
    return _ita_hours(env, "Urgentie__AfhandeltermijnUren", ITA_TERMIJN_HOURS)


def ita_bijna_verlopen_hours(env: Environment) -> int:
    """Return the weekday hours before the afhandeltermijn ends in which ITA marks a contactverzoek almost overdue."""
    return _ita_hours(env, "Urgentie__BijnaVerlopenDrempelUren", ITA_BIJNA_VERLOPEN_HOURS)


def weekday_hours_before(moment: datetime, hours: float) -> datetime:
    """Return the moment `hours` weekday hours (Mon-Fri, UTC) before `moment`, as ITA counts its afhandeltermijn."""
    left = timedelta(hours=hours)
    end, day = moment, moment.replace(hour=0, minute=0, second=0, microsecond=0)
    while True:
        if day.weekday() < SATURDAY:
            if left <= end - day:
                return end - left
            left -= end - day
        end, day = day, day - timedelta(days=1)


def kiss_sync_cronjob(env: Environment, source: str) -> str:
    """Return the name of KISS's elastic-sync CronJob for a search source (vac, kennisbank), e.g. contact-vac-sync."""
    names = [metadata_name(cronjob) for cronjob in env.items("cronjobs")]
    return next(name for name in names if name.endswith(f"-{source}-sync"))


def kiss_website_crawlers(env: Environment) -> dict[str, str]:
    """KISS's website crawler CronJobs (kiss.settings.syncJobs.website), each with the URL it crawls.

    The KISS chart names the Secret with the crawler's crawler.yml after its CronJob.
    """
    cronjobs = [metadata_name(cronjob) for cronjob in env.items("cronjobs")]
    crawlers: dict[str, str] = {}
    for name in cronjobs:
        if "-crawler-website-" in name:
            crawler = yaml.safe_load(env.kube.secret_value(name, "crawler.yml"))
            crawlers[name] = str(entries(crawler.get("domains"))[0]["url"])
    return crawlers


def kiss_search_hits(kiss: requests.Session, kiss_url: str, query: str) -> list[JsonObject]:
    """Return the hits of KISS's search for the query in all its sources."""
    response = kiss.post(f"{kiss_url}/api/search", json={"query": query, "page": 1, "filters": []})
    return entries(section(expect_status(response, HTTPStatus.OK).json(), "hits").get("hits"))


def vac_data(titel: str, antwoord: str = "Antwoord van podiumd-tests.") -> dict[str, object]:
    """Return a VAC (vraag-antwoordcombinatie) for Objecten with the title as its question."""
    return {"vraag": titel, "antwoord": antwoord, "doelgroep": "eu-burger", "status": "actief"}


def kennisartikel_data(titel: str, tekst: str = "Tekst van podiumd-tests.") -> dict[str, object]:
    """Return an SDG kennisartikel for Objecten with the title in its Dutch translation, at KENNIS_URL + title."""
    return {
        "url": f"{KENNIS_URL}{quote(titel)}",
        "uuid": str(uuid.uuid4()),
        "upnUri": f"{KENNIS_URL}upn",
        "publicatieDatum": today(),
        "productAanwezig": True,
        "productValtOnder": None,
        "verantwoordelijkeOrganisatie": {
            "url": f"{KENNIS_URL}organisatie",
            "owmsIdentifier": f"{KENNIS_URL}owms",
            "owmsEndDate": "2099-12-31T00:00:00Z",
        },
        "locaties": None,
        "doelgroep": "eu-burger",
        "vertalingen": [{"taal": "nl", "datumWijziging": now_iso(), "titel": titel, "tekst": tekst}],
        "beschikbareTalen": ["nl"],
    }
