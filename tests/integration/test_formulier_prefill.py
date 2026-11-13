"""Chain: Open Formulieren prefills a form from the BRP after a DigiD login and from KvK after an eHerkenning login.

Open Formulieren's haalcentraal plugin fills the form for any BSN the login gives; geheimhouding and overlijden
do not stop it. DigiD and eHerkenning are Keycloak's mock, with a run-tagged Keycloak user per identity.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.basisregistraties import BRP_GEHEIMHOUDING
from podiumd_tests.basisregistraties import BRP_OVERLEDEN
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KVK_RECHTSVORMEN
from podiumd_tests.bootstrap.steps import OF_PREFILL
from podiumd_tests.bootstrap.steps import ZGW_REGISTRATION
from podiumd_tests.json_data import entries
from podiumd_tests.openformulieren import forget_submission
from podiumd_tests.openformulieren import log_in
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openformulieren", "keycloak", "cluster"),
]


def prefilled(key: str, plugin: str, attribute: str, component_type: str = "textfield") -> JsonObject:
    """Return a Form.io component that Open Formulieren prefills with the plugin's attribute."""
    prefill = {"plugin": plugin, "attribute": attribute, "identifierRole": "main"}
    return {"type": component_type, "key": key, "label": key, "prefill": prefill}


BRP_FIELDS = [
    prefilled("voornamen", "haalcentraal", "naam.voornamen"),
    prefilled("geslachtsnaam", "haalcentraal", "naam.geslachtsnaam"),
    prefilled("geboortedatum", "haalcentraal", "geboorte.datum.datum", "date"),
    prefilled("straat", "haalcentraal", "verblijfplaats.verblijfadres.officieleStraatnaam"),
    prefilled("huisnummer", "haalcentraal", "verblijfplaats.verblijfadres.huisnummer"),
    prefilled("postcode", "haalcentraal", "verblijfplaats.verblijfadres.postcode"),
    prefilled("woonplaats", "haalcentraal", "verblijfplaats.verblijfadres.woonplaats"),
]
KVK_FIELDS = [
    prefilled("kvk_nummer", "kvk-kvknumber", "kvkNummer"),
    prefilled("naam", "kvk-kvknumber", "naam"),
    prefilled("rechtsvorm", "kvk-kvknumber", "_embedded.eigenaar.rechtsvorm"),
]
# What the BRP test set holds for each person.
INWONERS = {
    "inwoner": (EREBOS, ["Erebos", "Bultenaar", "2000-04-01", "Plataanlaan", "4", "3224TT", "Hellevoetsluis"]),
    "geheimhouding": (
        BRP_GEHEIMHOUDING,
        ["Jan", "Cuykelaer", "1977-12-10", "Thorbeckelaan", "731", "2564CJ", "'s-Gravenhage"],
    ),
    "overleden": (BRP_OVERLEDEN, ["Astrid", "Abels", "1974-12-16", "Turfmarkt", "39", "2511CA", "'s-Gravenhage"]),
}


@pytest.fixture(autouse=True)
def prefill_linked(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> None:
    """Skip where the profile does not let bootstrap link Open Formulieren's prefill services."""
    if not podiumd_env.profile.is_allowed(str(OF_PREFILL.opt_in)):
        pytest.skip(
            f"profile setting {OF_PREFILL.opt_in} is off on {podiumd_env.profile.name}: Open Formulieren's BRP and "
            f"KvK prefill are unlinked; set it and run bootstrap step {OF_PREFILL.name}"
        )
    need_bootstrap(OF_PREFILL.name, "openformulieren-oidc-mock")


def prefill_after_login(
    podiumd_env: Environment,
    registry: ResourceRegistry,
    name: str,
    fields: list[JsonObject],
    method: str,
    identity: Mapping[str, list[str]],
) -> JsonObject:
    """Log a new Keycloak user with the identity attributes in on a new form with fields; the step's prefilled data."""
    base = podiumd_env.profile.urls["openformulieren"]
    slug = registry.tagged(name)
    make_form(podiumd_env, registry, slug, fields, ZGW_REGISTRATION, (method,))
    admin = for_environment(podiumd_env)
    username, password = registry.tagged(f"{name}-login"), admin.new_password()
    user_id = admin.create_user(username, password, dict(identity))
    registry.add(f"keycloak user {username}", lambda: admin.delete_user(user_id))
    http = podiumd_env.session()
    log_in(http, base, slug, method, (username, password))
    submission, _ = start_submission(http, base, slug)
    forget_submission(podiumd_env, registry, str(submission["id"]))
    step = expect_status(http.get(str(entries(submission["steps"])[0]["url"])), HTTPStatus.OK).json()
    return dict(step["data"])


@pytest.mark.parametrize(("bsn", "expected"), INWONERS.values(), ids=INWONERS)
@pytest.mark.source("TA regression/11-of-brp-prefill.spec.ts", "Open Formulieren prefills a form from the BRP.")
@pytest.mark.scenario("""
    Given a form in Open Formulieren whose fields are prefilled from the BRP
    And a person of the BRP test set, also one with geheimhouding or one who died
    When that person logs in to the form with DigiD
    Then the form shows the person's naam, geboortedatum and adres from the BRP
""")
def test_digid_login_prefills_the_form_from_the_brp(
    podiumd_env: Environment, registry: ResourceRegistry, bsn: str, expected: list[str]
) -> None:
    """After a DigiD login the haalcentraal plugin fills naam, geboortedatum and adres from the BRP."""
    data = prefill_after_login(podiumd_env, registry, f"brp-{bsn}", BRP_FIELDS, "digid_oidc", {"bsn": [bsn]})
    assert [data.get(str(field["key"])) for field in BRP_FIELDS] == expected


@pytest.mark.parametrize("rechtsvorm", ["eenmanszaak", "stichting"])
@pytest.mark.source("TA regression/57-kvk-prefill.spec.ts", "Open Formulieren prefills a form from KvK.")
@pytest.mark.scenario("""
    Given a form in Open Formulieren whose fields are prefilled from KvK
    When a company of KvK's test set logs in to the form with eHerkenning
    Then the form shows the company's KvK-nummer, naam and rechtsvorm from its basisprofiel
""")
def test_eherkenning_login_prefills_the_form_from_kvk(
    podiumd_env: Environment, registry: ResourceRegistry, rechtsvorm: str
) -> None:
    """After an eHerkenning login the kvk-kvknumber plugin fills KvK-nummer, naam and rechtsvorm."""
    bedrijf = KVK_RECHTSVORMEN[rechtsvorm]
    identity = {"kvk": [bedrijf.kvk_nummer]}
    data = prefill_after_login(podiumd_env, registry, f"kvk-{rechtsvorm}", KVK_FIELDS, "eherkenning_oidc", identity)
    assert tuple(data.get(str(field["key"])) for field in KVK_FIELDS) == bedrijf
