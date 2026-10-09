"""The test admin's ZAC session and ZAC zaken, for the ZAC component tests."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import zaakafhandelparameters
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


@pytest.fixture(name="zac")
def fixture_zac(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """The test admin's session on ZAC's REST API."""
    need_bootstrap(ADMIN.name)
    return zac_session(podiumd_env, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))


@pytest.fixture(name="zac_parameters")
def fixture_zac_parameters(zac: requests.Session, urls: dict[str, str], podiumd_env: Environment) -> JsonObject:
    """ZAC's zaakafhandelparameters of the zaaktype ZAC starts zaken of (profile setting productaanvraag_zaaktype)."""
    identificatie = podiumd_env.profile.settings.get("productaanvraag_zaaktype")
    if not identificatie:
        pytest.skip(f"profile {podiumd_env.profile.name} has no settings.productaanvraag_zaaktype")
    found = zaakafhandelparameters(zac, urls["zac"], identificatie)
    if not found:
        pytest.skip(f"ZAC has no zaakafhandelparameters for {identificatie}")
    return found[0]


@pytest.fixture(name="zac_zaak")
def fixture_zac_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_parameters: JsonObject,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
) -> Callable[..., JsonObject]:
    """Start a zaak in ZAC with a run-tagged omschrijving; cleanup deletes it from Open Zaak."""

    def start(**fields: object) -> JsonObject:
        # ZAC's UI always sends a startdatum; without one ZAC answers 500.
        defaults = {"startdatum": date.today().isoformat(), "communicatiekanaal": "E-mail"}  # noqa: DTZ011  # a local date
        body = {"omschrijving": registry.tagged("zac-zaak"), **defaults, **fields}
        zaak = create_zaak(zac, urls["zac"], zac_parameters, **body)
        url = f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}"
        registry.add(f"zaak {zaak['identificatie']}", lambda: delete_zaak(openzaak_productaanvraag, url))
        return zaak

    return start
