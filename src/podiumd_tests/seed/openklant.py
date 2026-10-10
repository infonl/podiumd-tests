"""Open Klant test data; every factory registers its deleter (PLAN.md §4 B)."""

from __future__ import annotations

import random

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# BSNs of the BRP test set and KvK numbers of the KvK test set are shared by every team;
# generated numbers keep tests independent of what others left behind.
_rng = random.SystemRandom()


def random_bsn() -> str:
    """A random 9-digit number that passes the BSN eleven test (elfproef)."""
    while True:
        digits = [_rng.randint(0, 9) for _ in range(8)]
        total = sum(d * w for d, w in zip(digits, range(9, 1, -1), strict=True))
        last = total % 11
        if last < 10 and digits[0] != 0:  # the check digit is weighted -1
            return "".join(map(str, [*digits, last]))


def random_kvk_nummer() -> str:
    """A random 8-digit KvK number."""
    return str(_rng.randint(10_000_000, 99_999_999))


def random_nummer() -> str:
    """A random 10-digit nummer for a partij, klantcontact or internetaak.

    Open Klant 2.15 numbers new objects as highest + 1 without a lock: parallel creates
    then collide on the unique nummer and get 500. An explicit nummer avoids that race.
    """
    return str(_rng.randint(1_000_000_000, 9_999_999_999))


def _create(openklant: ApiClient, registry: ResourceRegistry, path: str, body: dict[str, object]) -> JsonObject:
    created = openklant.post(path, body)
    url = str(created["url"])
    registry.add(f"{path} {url}", lambda: openklant.delete(url))
    return created


def ref(obj: JsonObject) -> dict[str, str]:
    """The {"uuid": …} reference Open Klant uses between its objects."""
    return {"uuid": str(obj["uuid"])}


def make_partij(openklant: ApiClient, registry: ResourceRegistry, **fields: object) -> JsonObject:
    """A persoon-partij named after the run tag; fields override the defaults."""
    body: dict[str, object] = {
        "nummer": random_nummer(),
        "soortPartij": "persoon",
        "indicatieActief": True,
        "indicatieGeheimhouding": False,
        "voorkeurstaal": "nld",
        "partijIdentificatie": {"contactnaam": {"voornaam": "PodiumD", "achternaam": registry.tagged("partij")}},
        "digitaleAdressen": [],
        "rekeningnummers": [],
        "voorkeursDigitaalAdres": None,
        "voorkeursRekeningnummer": None,
        **fields,
    }
    return _create(openklant, registry, "partijen", body)


def make_organisatie(openklant: ApiClient, registry: ResourceRegistry) -> JsonObject:
    """An organisatie-partij named after the run tag."""
    return make_partij(
        openklant, registry, soortPartij="organisatie", partijIdentificatie={"naam": registry.tagged("bv")}
    )


def make_partij_identificator(
    openklant: ApiClient, registry: ResourceRegistry, partij: JsonObject, kind: str, number: str
) -> JsonObject:
    """A BSN ("bsn"), KvK ("kvk_nummer") or RSIN ("rsin") identificator of a partij."""
    objecttype = "natuurlijk_persoon" if kind == "bsn" else "niet_natuurlijk_persoon"
    register = "brp" if kind == "bsn" else "hr"
    body: dict[str, object] = {
        "identificeerdePartij": ref(partij),
        "anderePartijIdentificator": "",
        "partijIdentificator": {
            "codeObjecttype": objecttype,
            "codeSoortObjectId": kind,
            "objectId": number,
            "codeRegister": register,
        },
    }
    return _create(openklant, registry, "partij-identificatoren", body)


def make_digitaal_adres(
    openklant: ApiClient,
    registry: ResourceRegistry,
    partij: JsonObject | None,
    adres: str,
    betrokkene: JsonObject | None = None,
) -> JsonObject:
    """An e-mail address of a partij (its standard address), of a klantcontact's betrokkene, or of no one."""
    body: dict[str, object] = {
        "verstrektDoorBetrokkene": ref(betrokkene) if betrokkene else None,
        "verstrektDoorPartij": ref(partij) if partij else None,
        "adres": adres,
        "soortDigitaalAdres": "email",
        "omschrijving": registry.tagged("adres"),
        "isStandaardAdres": partij is not None,
    }
    return _create(openklant, registry, "digitaleadressen", body)


def klantcontact_body(registry: ResourceRegistry, **fields: object) -> dict[str, object]:
    """A klantcontact by phone whose onderwerp carries the run tag; fields override the defaults."""
    return {
        "nummer": random_nummer(),
        "kanaal": "telefoon",
        "onderwerp": registry.tagged("klantcontact"),
        "inhoud": "podiumd-tests",
        "indicatieContactGelukt": True,
        "taal": "nld",
        "vertrouwelijk": False,
        "plaatsgevondenOp": datetime.now(tz=UTC).isoformat(),
        **fields,
    }


def make_klantcontact(openklant: ApiClient, registry: ResourceRegistry, **fields: object) -> JsonObject:
    """A klantcontact (klantcontact_body) in Open Klant."""
    return _create(openklant, registry, "klantcontacten", klantcontact_body(registry, **fields))


def make_betrokkene(
    openklant: ApiClient, registry: ResourceRegistry, klantcontact: JsonObject, partij: JsonObject | None
) -> JsonObject:
    """A klant betrokken at a klantcontact, for a partij or anonymous."""
    body: dict[str, object] = {
        "wasPartij": ref(partij) if partij else None,
        "hadKlantcontact": ref(klantcontact),
        "rol": "klant",
        "initiator": True,
        "organisatienaam": "",
        "contactnaam": {"voorletters": "", "voornaam": "PodiumD", "voorvoegselAchternaam": "", "achternaam": "test"},
    }
    return _create(openklant, registry, "betrokkenen", body)


def make_actor(
    openklant: ApiClient,
    registry: ResourceRegistry,
    soort: str = "medewerker",
    name: str | None = None,
    objecttype: str = "act",
) -> JsonObject:
    """An actor of a kind (medewerker, organisatorische_eenheid, geautomatiseerde_actor); default name: the run tag.

    objecttype: its actoridentificator's codeObjecttype; ITA reads "grp" and "afd" as groep and afdeling.
    """
    name = name or registry.tagged(f"actor-{_rng.randint(0, 999_999)}")
    body: dict[str, object] = {
        "naam": name,
        "soortActor": soort,
        "indicatieActief": True,
        "actoridentificator": {
            "objectId": name,
            "codeObjecttype": objecttype,
            "codeRegister": "obj",
            "codeSoortObjectId": "idf",
        },
    }
    return _create(openklant, registry, "actoren", body)


def make_internetaak(
    openklant: ApiClient, registry: ResourceRegistry, klantcontact: JsonObject, actoren: list[JsonObject]
) -> JsonObject:
    """An internetaak to handle, raised by a klantcontact and assigned to actors."""
    body: dict[str, object] = {
        "nummer": random_nummer(),
        "gevraagdeHandeling": "Terugbellen",
        "aanleidinggevendKlantcontact": ref(klantcontact),
        "toegewezenAanActoren": [ref(a) for a in actoren],
        "toelichting": registry.tagged("internetaak"),
        "status": "te_verwerken",
    }
    return _create(openklant, registry, "internetaken", body)


# (codeObjecttype, codeRegister, codeSoortObjectId) of what an onderwerpobject points at.
ZAAK = ("zaak", "openzaak", "zaak-uuid")
FORMULIERINZENDING = ("formulierinzending", "Open Formulieren", "public_registration_reference")


def make_onderwerpobject(
    openklant: ApiClient,
    registry: ResourceRegistry,
    klantcontact: JsonObject,
    object_id: str,
    codes: tuple[str, str, str] = ZAAK,
) -> JsonObject:
    """Links a klantcontact to what it is about: a zaak (as KISS records it) or a form submission."""
    objecttype, register, soort = codes
    body: dict[str, object] = {
        "klantcontact": ref(klantcontact),
        "onderwerpobjectidentificator": {
            "objectId": object_id,
            "codeObjecttype": objecttype,
            "codeRegister": register,
            "codeSoortObjectId": soort,
        },
    }
    return _create(openklant, registry, "onderwerpobjecten", body)


def delete_klantcontact_tree(openklant: ApiClient, url: str) -> None:
    """Delete a klantcontact with the interne taken, onderwerpobjecten, betrokkenen and their digitale adressen."""
    expand = "leiddeTotInterneTaken,gingOverOnderwerpobjecten,hadBetrokkenen"
    found = openklant.request("GET", url, HTTPStatus.OK, HTTPStatus.NOT_FOUND, params={"expand": expand})
    if found.status_code == HTTPStatus.NOT_FOUND:
        return
    inlined = section(cast("JsonObject", found.json()), "_expand")
    # Open Klant keeps a betrokkene's digitale adressen when the betrokkene goes.
    for betrokkene in entries(inlined.get("hadBetrokkenen")):
        for adres in entries(betrokkene.get("digitaleAdressen")):
            openklant.delete(str(adres["url"]))
    for key in expand.split(","):
        for item in entries(inlined.get(key)):
            openklant.delete(str(item["url"]))
    openklant.delete(url)


def partijen_of(openklant: ApiClient, object_id: str) -> list[str]:
    """URLs of the partijen identified by a BSN or KvK number."""
    identificatoren = openklant.list("partij-identificatoren", {"partijIdentificatorObjectId": object_id})
    return list(dict.fromkeys(str(section(i, "identificeerdePartij")["url"]) for i in identificatoren))


def expanded(openklant: ApiClient, url: str, key: str) -> list[JsonObject]:
    """The objects that `expand=key` inlines in the object at the URL."""
    return entries(section(openklant.get(url, {"expand": key}), "_expand").get(key))


def klantcontacten_about(openklant: ApiClient, onderwerp: str, inhoud: str | None = None) -> list[JsonObject]:
    """The klantcontacten with the onderwerp and, when given, the inhoud."""
    found = openklant.list("klantcontacten", {"onderwerp": onderwerp})
    return [k for k in found if inhoud is None or k.get("inhoud") == inhoud]


def clean_up_klantcontacten(
    openklant: ApiClient, registry: ResourceRegistry, onderwerp: str, inhoud: str | None = None
) -> None:
    """Delete, at cleanup, the klantcontacten `klantcontacten_about` finds, with their trees."""
    registry.add(
        f"klantcontacten {onderwerp} {inhoud or ''}".rstrip(),
        lambda: [
            delete_klantcontact_tree(openklant, str(k["url"]))
            for k in klantcontacten_about(openklant, onderwerp, inhoud)
        ],
    )


def delete_partij(openklant: ApiClient, partij: str) -> None:
    """Delete a partij with its digitale adressen and identificatoren."""
    for adres in openklant.list("digitaleadressen", {"verstrektDoorPartij__uuid": partij.rsplit("/", 1)[-1]}):
        openklant.delete(str(adres["url"]))
    identificatoren = [
        openklant.get(str(ref["url"])) for ref in entries(openklant.get(partij).get("partijIdentificatoren"))
    ]
    # A sub-identificator (a vestigingsnummer under its kvk_nummer) protects its parent.
    for identificator in sorted(identificatoren, key=lambda i: i.get("subIdentificatorVan") is None):
        openklant.delete(str(identificator["url"]))
    openklant.delete(partij)


def make_submission_contact(openklant: ApiClient, registry: ResourceRegistry, kenmerk: str, adres: str) -> None:
    """The e-mail address a form's submitter left, as Open Formulieren registers it in Open Klant.

    A klantcontact about the submission (onderwerpobject with its kenmerk) with a betrokkene and the
    address; ZAC finds it for the productaanvraag with that kenmerk. Cleanup deletes the whole tree,
    also the onderwerpobject ZAC adds for the zaak.
    """
    klantcontact = make_klantcontact(openklant, registry, onderwerp=kenmerk)
    betrokkene = make_betrokkene(openklant, registry, klantcontact, None)
    make_digitaal_adres(openklant, registry, None, adres, betrokkene)
    make_onderwerpobject(openklant, registry, klantcontact, kenmerk, FORMULIERINZENDING)
    clean_up_klantcontacten(openklant, registry, kenmerk)
