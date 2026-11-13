"""Fixtures for podiumd-tests' own zaaktypen in ZAC, their zaken and taken, and the test admin's signaleringen."""

from __future__ import annotations

import dataclasses
import functools

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import EMAIL_IOT
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import section
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.catalogi import ZAC_CATALOGUS_WRITES
from podiumd_tests.seed.catalogi import ZaaktypeTypes
from podiumd_tests.seed.catalogi import make_concept_besluittype
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.seed.zac_zaaktype import ZAC_TYPES
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.seed.zac_zaaktype import zac_catalogus
from podiumd_tests.zac import HEROPEND
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import save_zaakafhandelparameters
from podiumd_tests.zac_signaleringen import turn_signaleringen
from podiumd_tests.zac_taken import AANVULLENDE_INFORMATIE
from podiumd_tests.zac_taken import activate_human_tasks
from podiumd_tests.zac_taken import started_taak

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts

# Days a Goedkeuren taak of the taken zaaktype takes: more than any zaak of it has left.
GOEDKEUREN_DOORLOOPTIJD = 3650


@pytest.fixture(scope="session", name="zaaktype_registry")
def fixture_zaaktype_registry(request: pytest.FixtureRequest, run_tag: str) -> Iterator[ResourceRegistry]:
    """Cleanup at the end of the session, for the throwaway zaaktypen."""
    registry = ResourceRegistry(run_tag, keep=bool(request.config.getoption("--keep-data")))
    try:
        yield registry
    finally:
        registry.cleanup()


@pytest.fixture(scope="session", name="eigen_catalogus")
def fixture_eigen_catalogus(podiumd_env: Environment, openzaak: ApiClient) -> JsonObject:
    """ZAC's own catalogus in Open Zaak, where the profile allows tests to publish run-tagged zaaktypen."""
    if not podiumd_env.profile.is_allowed(ZAC_CATALOGUS_WRITES):
        pytest.skip(
            f"profile {podiumd_env.profile.name} keeps tests out of ZAC's catalogus: allow it with profile setting"
            f" {ZAC_CATALOGUS_WRITES}"
        )
    return zac_catalogus(podiumd_env, openzaak)


@pytest.fixture(scope="session", name="zac_eigen_zaaktype")
def fixture_zac_eigen_zaaktype(
    podiumd_env: Environment,
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    zaaktype_registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> JsonObject:
    """ZAC's zaakafhandelparameters of a throwaway zaaktype in PABC domain ptest-bootstrap, its own deelzaaktype.

    Tests using it share xdist group zac-eigen-zaaktype, so a run makes one.
    """
    need_bootstrap("zac-bpmn-process")
    return make_zac_zaaktype(podiumd_env, openzaak, zaaktype_registry, test_zaaktype)


@pytest.fixture(scope="session", name="zac_taken_zaaktype")
def fixture_zac_taken_zaaktype(
    podiumd_env: Environment,
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    parts: ZaaktypeParts,
    zaaktype_registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> JsonObject:
    """ZAC's zaakafhandelparameters of a throwaway zaaktype as zac_eigen_zaaktype, with every human task on.

    Its documents are of the test informatieobjecttype or e-mail; Advies extern mails the adviseur, Goedkeuren takes
    GOEDKEUREN_DOORLOOPTIJD days. Tests using it share xdist group zac-taken-zaaktype, so a run makes one.
    """
    need_bootstrap("zac-bpmn-process")
    need_bootstrap("openzaak-iot-email")
    iots = openzaak.list(f"{CATALOGI}/informatieobjecttypen", {"catalogus": str(test_zaaktype["catalogus"])})
    email = next(str(iot["url"]) for iot in iots if iot.get("omschrijving") == EMAIL_IOT and not iot.get("concept"))
    parameters = make_zac_zaaktype(
        podiumd_env,
        openzaak,
        zaaktype_registry,
        test_zaaktype,
        informatieobjecttypen=(parts.informatieobjecttype, email),
    )
    return activate_human_tasks(
        zac_as_admin(podiumd_env),
        podiumd_env.profile.urls["zac"],
        str(section(parameters, "zaaktype")["uuid"]),
        ADVIES_EXTERN={"formulierDefinitieId": "EXTERN_ADVIES_MAIL"},
        GOEDKEUREN={"doorlooptijd": GOEDKEUREN_DOORLOOPTIJD},
    )


# A resultaattype per brondatum afleidingswijze ZAC handles, eigenschap peildatum for afleidingswijze eigenschap, and
# statustype Heropend, which heropenen needs.
ARCHIEF_TYPES = ZaaktypeTypes(
    ("Intake", "Wacht op aanvullende informatie", "In behandeling", HEROPEND, "Afgerond"),
    ZAC_TYPES.roltypen,
    ("peildatum",),
    ("eigenschap", "termijn", "ingangsdatum_besluit", "vervaldatum_besluit", "hoofdzaak"),
)
# The resultaattype the archief zaaktype's zaakbeeindigreden gives.
AFBREEK_RESULTAAT = "termijn"
# Reactietermijn and publicatietermijn of the archief zaaktype's besluittype.
BESLUIT_TERMIJN = "P14D"


@pytest.fixture(scope="session", name="zac_archief_zaaktype")
def fixture_zac_archief_zaaktype(
    podiumd_env: Environment,
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    zaaktype_registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> JsonObject:
    """ZAC's zaakafhandelparameters of a throwaway zaaktype with ARCHIEF_TYPES and a besluittype with publicatie.

    Its one zaakbeeindigreden gives resultaat AFBREEK_RESULTAAT. Tests using it share xdist group zac-archief-zaaktype.
    """
    need_bootstrap("zac-bpmn-process")
    besluittype = make_concept_besluittype(
        podiumd_env,
        openzaak,
        zaaktype_registry,
        str(test_zaaktype["catalogus"]),
        publicatieIndicatie=True,
        publicatietermijn=BESLUIT_TERMIJN,
        reactietermijn=BESLUIT_TERMIJN,
    )
    types = dataclasses.replace(ARCHIEF_TYPES, besluittypen=(str(besluittype["url"]),))
    parameters = make_zac_zaaktype(podiumd_env, openzaak, zaaktype_registry, test_zaaktype, types=types)
    zac, zac_url = zac_as_admin(podiumd_env), podiumd_env.profile.urls["zac"]
    uuid = str(section(parameters, "zaaktype")["uuid"])
    reden = get_entries(zac, f"{zac_url}/rest/zaakafhandelparameters/zaakbeeindigredenen")[0]
    resultaattypen = get_entries(zac, f"{zac_url}/rest/zaakafhandelparameters/resultaattypes/{uuid}")
    resultaat = next(item for item in resultaattypen if item.get("naam") == AFBREEK_RESULTAAT)
    beeindigen = [{"zaakbeeindigReden": reden, "resultaattype": resultaat}]
    return save_zaakafhandelparameters(zac, zac_url, {**parameters, "zaakbeeindigParameters": beeindigen})


def _zaak_starter(
    zac: requests.Session, urls: dict[str, str], parameters: JsonObject, openzaak: ApiClient, registry: ResourceRegistry
) -> Callable[[], JsonObject]:
    """Start a zaak of the zaakafhandelparameters' zaaktype in ZAC; cleanup deletes it and its documents."""

    def start() -> JsonObject:
        zaak = create_zaak(zac, urls["zac"], parameters, omschrijving=registry.tagged("zac-eigen"))
        clean_up_zaak(zac, urls["zac"], openzaak, registry, zaak)
        return zaak

    return start


@pytest.fixture(name="zac_eigen_zaak")
def fixture_zac_eigen_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaaktype: JsonObject,
    openzaak: ApiClient,
    registry: ResourceRegistry,
) -> Callable[[], JsonObject]:
    """Start a zaak of podiumd-tests' own zaaktype in ZAC; cleanup deletes it from Open Zaak."""
    return _zaak_starter(zac, urls, zac_eigen_zaaktype, openzaak, registry)


@pytest.fixture(name="zac_taken_zaak")
def fixture_zac_taken_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_taken_zaaktype: JsonObject,
    openzaak: ApiClient,
    registry: ResourceRegistry,
) -> Callable[[], JsonObject]:
    """Start a zaak of the taken zaaktype in ZAC; cleanup deletes it and its documents from Open Zaak."""
    return _zaak_starter(zac, urls, zac_taken_zaaktype, openzaak, registry)


@pytest.fixture(name="behandeling")
def fixture_behandeling(
    zac: requests.Session, urls: dict[str, str], zac_taken_zaak: Callable[[], JsonObject]
) -> JsonObject:
    """A zaak of the taken zaaktype after an ontvankelijk intake: in behandeling."""
    zaak = zac_taken_zaak()
    afronden_intake(zac, urls["zac"], zaak)
    return zaak


@pytest.fixture(name="start_taak")
def fixture_start_taak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_group: str,
) -> Callable[..., JsonObject]:
    """Start the task Aanvullende informatie on a zaak of the taken zaaktype for the test admin in its group, no mail.

    fields: more of ZAC's RESTHumanTaskData, e.g. taakdata zaakOpschorten with a fataledatum.
    """

    def start(zaak: JsonObject, **fields: object) -> JsonObject:
        return started_taak(zac, urls["zac"], zaak, AANVULLENDE_INFORMATIE, (zac_group, ADMIN.username), **fields)

    return start


@pytest.fixture(name="taak")
def fixture_taak(zac_taken_zaak: Callable[[], JsonObject], start_taak: Callable[..., JsonObject]) -> JsonObject:
    """The task Aanvullende informatie, started on a new zaak of the taken zaaktype."""
    return start_taak(zac_taken_zaak())


@pytest.fixture(name="zac_archief_zaak")
def fixture_zac_archief_zaak(
    zac_archief_zaaktype: JsonObject,
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
) -> Callable[[], JsonObject]:
    """Start a zaak of the archief zaaktype in ZAC; cleanup deletes it from Open Zaak.

    The zaaktype comes first: ZAC reads a user's zaaktypen at login.
    """
    return _zaak_starter(zac, urls, zac_archief_zaaktype, openzaak, registry)


@pytest.fixture(name="signaleringen")
def fixture_signaleringen(
    zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> Callable[..., None]:
    """Turn the test admin's signaleringen (turn_signaleringen); cleanup restores them.

    Tests using it share xdist group zac-signaleringen: the settings are the admin's.
    """
    return functools.partial(turn_signaleringen, zac, urls["zac"], registry)
