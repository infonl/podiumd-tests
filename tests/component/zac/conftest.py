"""Fixtures for podiumd-tests' own zaaktype in ZAC."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.zac import create_zaak

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject


@pytest.fixture(scope="session", name="zac_eigen_zaaktype")
def fixture_zac_eigen_zaaktype(
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    run_tag: str,
    need_bootstrap: Callable[..., None],
) -> Iterator[JsonObject]:
    """ZAC's zaakafhandelparameters of a throwaway zaaktype in PABC domain ptest-bootstrap, its own deelzaaktype.

    Tests using it share xdist group zac-eigen-zaaktype, so a run makes one.
    """
    need_bootstrap("zac-bpmn-process")
    registry = ResourceRegistry(run_tag, keep=bool(request.config.getoption("--keep-data")))
    try:
        yield make_zac_zaaktype(podiumd_env, openzaak, registry, test_zaaktype)
    finally:
        registry.cleanup()


@pytest.fixture(name="zac_eigen_zaak")
def fixture_zac_eigen_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaaktype: JsonObject,
    openzaak: ApiClient,
    registry: ResourceRegistry,
) -> Callable[[], JsonObject]:
    """Start a zaak of podiumd-tests' own zaaktype in ZAC; cleanup deletes it from Open Zaak."""

    def start() -> JsonObject:
        zaak = create_zaak(zac, urls["zac"], zac_eigen_zaaktype, omschrijving=registry.tagged("zac-eigen"))
        url = f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}"
        registry.add(f"zaak {zaak['identificatie']}", lambda: delete_zaak(openzaak, url))
        return zaak

    return start
