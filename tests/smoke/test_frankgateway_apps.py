"""The Frank!Gateway outway in the api-proxy's place: each app reaches the base registrations under its own prefix.

Runs once the outway routes per app (/<app>/<register>/), as migrate-apiproxy-to-frankgateway.py configures it.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import BAG_DAM
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.basisregistraties import bag_adres
from podiumd_tests.basisregistraties import brp_persoon
from podiumd_tests.basisregistraties import kvk_basisprofiel
from podiumd_tests.basisregistraties import outway_registers
from podiumd_tests.gateway import APP_PREFIXES
from podiumd_tests.gateway import APP_REGISTERS
from podiumd_tests.gateway import REGISTER_SETTINGS
from podiumd_tests.gateway import brp_routes_problems
from podiumd_tests.gateway import config_data
from podiumd_tests.gateway import has_app_routes
from podiumd_tests.gateway import is_no_route
from podiumd_tests.gateway import kiss_brp_headers
from podiumd_tests.gateway import outway_admin_routes
from podiumd_tests.gateway import register_settings
from podiumd_tests.gateway import route_name
from podiumd_tests.gateway import wiring_problems
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.capabilities import Capabilities
    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.requires("frankgateway"),
    pytest.mark.source(
        "podiumd-tests",
        "Checks the apiproxy to Frank!Gateway migration: every app reaches BRP, BAG and KvK through its own outway route.",
    ),
]

ADMIN_KEY = "frankgateway_admin_key"


@pytest.fixture(scope="module", name="outway")
def fixture_outway(http: requests.Session, urls: dict[str, str]) -> str:
    """The outway URL; skips unless the outway routes per app."""
    if not has_app_routes(http, urls["frankgateway"]):
        pytest.skip("the outway has no per-app routes (/zac/brp/): migrate-apiproxy-to-frankgateway.py not applied")
    return urls["frankgateway"]


@pytest.mark.parametrize(
    ("app", "register"),
    [
        requiring(app, app, register, test_id=route_name(app, register))
        for app, all_ in APP_REGISTERS.items()
        for register in all_
    ],
)
@pytest.mark.scenario("""
    Given an app reaches a base registration through its own route of the Frank!Gateway outway
    When that route is called as the app calls it
    Then the registration answers with its test data
    And so accepts the API key the outway adds
""")
def test_app_route_reaches_its_register(http: requests.Session, outway: str, app: str, register: str) -> None:
    """The app's route answers like its register: BRP finds Erebos, BAG Dam 1, KvK Test BV Donald, PDOK no 5xx."""
    if is_no_route(http.get(f"{outway}/{APP_PREFIXES[app]}/{register}/")):
        if app not in REGISTER_SETTINGS:
            pytest.skip(f"no route {route_name(app, register)}: {app} has no {register} Service")
        pytest.fail(f"no route {route_name(app, register)} in the outway")
    registers = outway_registers(outway, app)
    if register == "brp":
        brp_persoon(http, registers, EREBOS, ["naam.volledigeNaam"])
    elif register == "bag":
        expect_status(bag_adres(http, registers, BAG_DAM), HTTPStatus.OK)
    elif register == "kvk":
        expect_status(kvk_basisprofiel(http, registers, KVK_TEST_NUMMER), HTTPStatus.OK)
    else:
        response = http.get(f"{outway}/forms/pdok/bzk/locatieserver/search/v3_1/free", params={"q": "Dam 1 Amsterdam"})
        assert response.status_code < HTTPStatus.INTERNAL_SERVER_ERROR, (
            f"PDOK through forms-pdok: {response.status_code}"
        )


@pytest.mark.requires("cluster")
@pytest.mark.usefixtures("outway")
@pytest.mark.parametrize("app", [requiring(app, app) for app in APP_PREFIXES])
@pytest.mark.scenario("""
    Given the apps reach the base registrations through the Frank!Gateway outway
    When the app's register settings are read
    Then none of them points at the api-proxy
    And each one that points at the outway uses the app's own route
""")
def test_app_reaches_its_registers_through_its_own_prefix(podiumd_env: Environment, app: str) -> None:
    """ZAC's and KISS's register settings are all on their outway prefix; no Service of a Django app is on api-proxy."""
    settings = register_settings(podiumd_env, app)
    problems = wiring_problems(
        app, settings, podiumd_env.profile.urls["frankgateway"], registers_only=app in REGISTER_SETTINGS
    )
    assert not problems, "; ".join(problems)


@pytest.mark.requires("cluster")
@pytest.mark.usefixtures("outway")
@pytest.mark.scenario("""
    Given the apps reach the BRP through their own route of the Frank!Gateway outway
    When the outway's BRP routes are read
    Then each sets the BRP API key
    And the routes of Open Formulieren and Open Inwoner set KISS's protocollering headers under their own application
""")
def test_brp_routes_set_the_key_and_protocollering(
    podiumd_env: Environment, http: requests.Session, credentials: SecretResolver, caps: Capabilities
) -> None:
    """Every BRP route sets x-api-key; forms-brp and oip-brp also KISS's fixed headers, named after their app."""
    key = credentials.optional(ADMIN_KEY)
    if key is None:
        pytest.skip(f"no secret {ADMIN_KEY} in the profile: the outway's Admin API viewer key")
    routes: dict[str, JsonObject] = outway_admin_routes(podiumd_env, http, key)
    kiss = kiss_brp_headers(config_data(podiumd_env, "kiss")) if "kiss" in caps.present else {}
    problems = brp_routes_problems(routes, kiss)
    assert not problems, "; ".join(problems)
